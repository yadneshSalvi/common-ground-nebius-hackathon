"""Durable at-least-once coordinator; owner services hold final dispatch authority."""
from shared.protocol import utc_now, parse_time, digest
from broker.engine import BrokerError
from broker.checker import verify_assignments


def validate_ready(engine, state, proposal_id, expected_version=None):
    if state["planning"]["status"] == "RUNNING":
        raise BrokerError("Planning is still in progress. Wait for its immutable proposal before dispatch.")
    proposal = state["proposal"]
    if not proposal or proposal["proposal_id"] != proposal_id or (expected_version is not None and proposal["version"] != expected_version):
        raise BrokerError("The proposal changed. Review the current version first.")
    if state["cancel_requested"]:
        raise BrokerError("Consent changed. Reconcile or cancel this agreement before replanning.")
    if parse_time(proposal["expires_at"]) <= parse_time(utc_now()):
        raise BrokerError("The proposal expired. A new proposal and approvals are required.")
    engine.validate_current_grants(state)
    offers = [m["body"]["payload"]["offer"] for m in state["offers"].values()]
    if not verify_assignments(proposal["tasks"], offers, proposal["assignments"])["valid"]:
        raise BrokerError("Independent assignment verification failed.")
    for owner in {a["owner_id"] for a in proposal["actions"]}:
        approval = state["approvals"].get(owner)
        if not approval:
            raise BrokerError("Every affected owner must approve this exact proposal first.")
        body = engine.verify_signed(state, approval, "Approval")
        if body["consent_revision"] != state["consent_revisions"].get(owner) or parse_time(body["payload"]["execution_not_after"]) <= parse_time(utc_now()):
            raise BrokerError("An approval is stale or expired.")
        if body["payload"]["proposal_digest"] != digest(proposal) or body["payload"]["manifest_digest"] != digest(proposal["actions"]):
            raise BrokerError("An approval no longer matches the action manifest.")
    return proposal


def execute(engine, proposal_id, expected_version=None, reconcile=False):
    if not engine.execution_lock.acquire(blocking=False):
        raise BrokerError("This agreement is already being applied or reconciled.")
    try:
        state = engine.store.read()
        if state["cancel_requested"]:
            return compensate_locked(engine, proposal_id)
        proposal = validate_ready(engine, state, proposal_id, expected_version)
        required = sorted({a["owner_id"] for a in proposal["actions"]})
        reservations = state["reservations"].copy()
        for owner in required:
            if owner not in reservations or parse_time(reservations[owner]["lease_expires_at"]) <= parse_time(utc_now()):
                try:
                    reservations[owner] = engine.owner_call(owner, "/coordination/prepare", {"proposal": proposal, "approval": state["approvals"][owner]})
                    with engine.store.transaction() as (current, db):
                        current["reservations"][owner] = reservations[owner]
                except BrokerError as error:
                    with engine.store.transaction() as (current, db):
                        current["state"] = "NEEDS_ATTENTION"
                        engine.store.event(current, "PREPARATION_REFUSED", "An owner could not reserve this commitment: " + str(error))
                    raise
        with engine.store.transaction() as (current, db):
            validate_ready(engine, current, proposal_id, expected_version)
            if not current["outbox"]:
                current["outbox"] = {a["action_id"]: {"owner_id": a["owner_id"], "status": "PENDING", "attempts": 0} for a in proposal["actions"]}
                current["actions"] = {a["action_id"]: {**a, "status": "PENDING"} for a in proposal["actions"]}
                engine.store.event(current, "OUTBOX_COMMITTED", "All owners reserved their commitments. Durable calendar dispatch is ready.")
            current["state"] = "APPLYING"
        for action in proposal["actions"]:
            state = engine.store.read()
            if state["cancel_requested"]:
                return compensate_locked(engine, proposal_id)
            if state["actions"][action["action_id"]]["status"] == "VERIFIED" and not reconcile:
                continue
            validate_ready(engine, state, proposal_id, expected_version)
            reservation = reservations[action["owner_id"]]
            request = {"proposal_id": proposal_id, "action_id": action["action_id"], "reservation_id": reservation["reservation_id"], "fence": reservation["fence"]}
            with engine.store.transaction() as (current, db):
                current["outbox"][action["action_id"]]["attempts"] += 1
                current["outbox"][action["action_id"]]["status"] = "SENDING"
                current["actions"][action["action_id"]]["status"] = "APPLYING"
            try:
                path = "/coordination/reconcile" if reconcile or state["outbox"][action["action_id"]]["attempts"] else "/coordination/dispatch"
                receipt = engine.owner_call(action["owner_id"], path, request)
            except BrokerError as error:
                receipt = {"action_id": action["action_id"], "status": "AMBIGUOUS" if error.status >= 500 else "FAILED", "error": str(error), "event_id": action["event_id"]}
            with engine.store.transaction() as (current, db):
                current["actions"][action["action_id"]] = {**action, **receipt}
                current.setdefault("action_receipts", []).append({"proposal_id": proposal_id, "observed_at": utc_now(), "source": "owner-dispatch", "receipt": receipt})
                current["outbox"][action["action_id"]]["status"] = receipt["status"]
                engine.store.event(current, "CALENDAR_" + receipt["status"], action["label"] + ": " + receipt["status"].lower().replace("_", " ") + ".", {"action_id": action["action_id"], "adapter": "local-calendar"})
                if receipt["status"] != "VERIFIED":
                    current["state"] = "NEEDS_ATTENTION" if receipt["status"] == "NEEDS_ATTENTION" else "RECOVERING"
            if receipt["status"] != "VERIFIED":
                return engine.public_state()
        observed = {}
        for owner in required:
            response = engine.owner_call(owner, "/coordination/events?proposal_id=" + proposal_id)
            for receipt in response["events"]:
                observed[receipt["action_id"]] = receipt
        with engine.store.transaction() as (current, db):
            if current["cancel_requested"]:
                current["state"] = "RECOVERING"
            else:
                for action in proposal["actions"]:
                    receipt = observed.get(action["action_id"], {"status": "NEEDS_ATTENTION", "error": "Owner verification receipt missing."})
                    current["actions"][action["action_id"]] = {**action, **receipt}
                    current.setdefault("action_receipts", []).append({"proposal_id": proposal_id, "observed_at": utc_now(), "source": "owner-calendar-observation", "receipt": receipt})
                complete = all(a["status"] == "VERIFIED" for a in current["actions"].values())
                current["state"] = "ACTIVE" if complete else "NEEDS_ATTENTION"
                engine.store.event(current, "AGREEMENT_ACTIVE" if complete else "VERIFICATION_INCOMPLETE", "All five local calendar entries are verified." if complete else "Some local calendar effects need review.")
        if engine.store.read()["cancel_requested"]:
            return compensate_locked(engine, proposal_id)
        return engine.public_state()
    finally:
        engine.execution_lock.release()


def compensate_locked(engine, proposal_id):
    state = engine.store.read()
    proposal = state["archive"].get(proposal_id)
    if not proposal or not state["proposal"] or state["proposal"]["proposal_id"] != proposal_id:
        raise BrokerError("Only the current agreement can be cancelled here.")
    with engine.store.transaction() as (current, db):
        current["cancel_requested"] = True
        current["state"] = "RECOVERING"
        for item in current["outbox"].values():
            if item["status"] == "PENDING":
                item["status"] = "CANCELLED"
    receipts = {}
    for owner in sorted({a["owner_id"] for a in proposal["actions"]}):
        try:
            result = engine.owner_call(owner, "/coordination/cancel", {"proposal_id": proposal_id})
            for receipt in result["actions"]:
                receipts[receipt["action_id"]] = receipt
        except BrokerError as error:
            # Unknown unapproved/unreserved proposals have no authorized effects.
            known = owner in state["reservations"] or any(a["owner_id"] == owner for a in state["actions"].values())
            if error.status == 404 and not known:
                continue
            for action in proposal["actions"]:
                if action["owner_id"] == owner:
                    receipts[action["action_id"]] = {"action_id": action["action_id"], "status": "NEEDS_ATTENTION", "error": "Owner cancellation is unconfirmed: " + str(error)}
    with engine.store.transaction() as (current, db):
        for action in proposal["actions"]:
            receipt = receipts.get(action["action_id"], {"action_id": action["action_id"], "status": "CANCELLED", "error": "No dispatch authorization or event exists for this action."})
            current["actions"][action["action_id"]] = {**action, **receipt}
            current.setdefault("action_receipts", []).append({"proposal_id": proposal_id, "observed_at": utc_now(), "source": "conditional-compensation", "receipt": receipt})
        complete = all(a["status"] == "CANCELLED" for a in current["actions"].values())
        current["state"] = "COMPENSATED" if complete else "NEEDS_ATTENTION"
        engine.store.event(current, "COMPENSATION_COMPLETE" if complete else "COMPENSATION_NEEDS_ATTENTION", "Unchanged app-created events were cancelled; absence was confirmed." if complete else "Some effects remain. User-edited events are preserved for owner review.")
    return engine.public_state()


def compensate(engine, proposal_id):
    if not engine.execution_lock.acquire(blocking=False):
        raise BrokerError("Wait for the current dispatch/reconciliation to report before cancelling.")
    try:
        return compensate_locked(engine, proposal_id)
    finally:
        engine.execution_lock.release()


def new_round(engine, expected_revision):
    if not engine.execution_lock.acquire(blocking=False):
        raise BrokerError("An agreement operation is still running.")
    try:
        state = engine.store.read()
        if state["revision"] != expected_revision:
            raise BrokerError("The agreement changed. Review its latest state first.")
        if state["planning"]["status"] == "RUNNING":
            raise BrokerError("Wait for the current planning attempt to finish.")
        if state["proposal"]:
            compensate_locked(engine, state["proposal"]["proposal_id"])
            if engine.store.read()["state"] != "COMPENSATED":
                raise BrokerError("Remaining calendar effects need owner review before a new round.")
        with engine.store.transaction() as (current, db):
            if current["proposal"]:
                current.setdefault("rounds", []).append({"proposal_id": current["proposal"]["proposal_id"], "closed_at": utc_now(), "state": current["state"], "approvals": list(current["approvals"].values()), "actions": list(current["actions"].values()), "outbox": current["outbox"], "reservations": current["reservations"]})
            current["previous_assignments"] = current["proposal"]["assignments"] if current["proposal"] else []
            current["proposal"] = None
            current["approvals"], current["actions"], current["outbox"], current["reservations"] = {}, {}, {}, {}
            current["cancel_requested"] = False
            current["state"] = "COLLECTING"
            current["planning"] = {"status": "IDLE", "phase": None, "error": None}
            engine.store.event(current, "NEW_ROUND", "A new agreement round is ready. Previous evidence remains in the history.")
        return engine.public_state()
    finally:
        engine.execution_lock.release()
