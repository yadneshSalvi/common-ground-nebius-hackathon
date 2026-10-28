from __future__ import annotations
import hashlib
import uuid
from shared.protocol import digest, expires_in, utc_now
from shared.schema import TASKS
from broker.engine import BrokerError
from broker.models import new_receipt
from broker.solver import solve
from broker.checker import verify_assignments


def begin_plan(engine, mode, expected_revision):
    if mode not in ("live", "local"):
        raise BrokerError("Choose live Fireworks or the explicit local structured workflow.", 422)
    with engine.store.transaction() as (state, db):
        if state["revision"] != expected_revision:
            raise BrokerError("Shared information changed. Refresh before requesting a proposal.")
        if state["planning"]["status"] == "RUNNING":
            raise BrokerError("A proposal is already being prepared.")
        if state["proposal"] is not None:
            raise BrokerError("Close the current agreement round before requesting another proposal. Its signed actions and recovery state must stay inspectable.")
        if any(a.get("status") in ("VERIFIED", "AMBIGUOUS", "PAUSED", "NEEDS_ATTENTION", "APPLYING") for a in state["actions"].values()):
            raise BrokerError("Reconcile or cancel existing calendar effects before starting a new proposal.")
        engine.validate_current_grants(state, inference=mode == "live")
        state["planning"] = {"status": "RUNNING", "phase": "Checking released offers", "error": None, "mode": mode}
        engine.store.event(state, "PLANNING_REQUESTED", "Fireworks planning requested." if mode == "live" else "Local structured planning requested; no inference will run.")
    return {"accepted": True, "mode": mode}


def run_plan(engine, mode):
    with engine.planning_lock:
        snapshot = engine.store.read()
        grants = list(snapshot["offers"].values())
        offers = [g["body"]["payload"]["offer"] for g in grants]
        input_fingerprint = digest(snapshot["offers"])
        receipt = None
        def validate_fresh():
            current = engine.store.read()
            engine.validate_current_grants(current, inference=mode == "live")
            if digest(current["offers"]) != input_fingerprint:
                raise BrokerError("Released offers changed during planning. Request a fresh proposal.")
            for owner, grant in current["offers"].items():
                status = engine.owner_call(owner, "/coordination/status")
                if status["consent_revision"] != grant["body"]["consent_revision"] or status["constraint_revision"] != grant["body"]["payload"]["offer"]["constraint_revision"] or grant["body"]["key_id"] in status["revoked_keys"]:
                    raise BrokerError("An owner changed consent, constraints or its key. Refresh the released offer.")
                if not status["release"] or status["release"]["signature"] != grant["signature"]:
                    raise BrokerError("An owner no longer authorizes this release.")
            return current

        def on_receipt(value):
            with engine.store.transaction() as (state, db):
                prior = next((i for i, r in enumerate(state["model_runs"]) if r["receipt_id"] == value["receipt_id"]), None)
                new_transmission = value.get("transmitted_at") and (prior is None or not state["model_runs"][prior].get("transmitted_at"))
                # JSON copy so later mutation cannot silently change a persisted attempt.
                import json
                copied = json.loads(json.dumps(value))
                if prior is None:
                    state["model_runs"].append(copied)
                else:
                    state["model_runs"][prior] = copied
                if new_transmission:
                    for grant in grants:
                        body = grant["body"]
                        state["disclosures"].append({"receipt_id": value["receipt_id"] + ":" + body["issuer"], "owner_id": body["issuer"], "recipients": {"inference": ["fireworks"]}, "fields": body["payload"]["fields"], "purpose": "coordinate-appointment", "time": value["transmitted_at"], "kind": "inference", "delivery": "attempted; provider HTTP result is in the model receipt", "payload_digest": value["input_digest"]})

        try:
            validate_fresh()
            if mode == "live":
                packet = engine.provider.make_input(snapshot["goal"], grants)
                receipt = new_receipt()
                with engine.store.transaction() as (state, db):
                    state["planning"]["phase"] = "Nemotron is comparing the released options"
                plan = engine.provider.run(packet, validate_fresh, on_receipt, receipt)
                tasks = plan["tasks"]
                explanation = plan["explanation"]
                suggestions = [item for item in plan["suggested_assignments"] if item["owner_id"] is not None]
                tradeoffs = plan["tradeoffs"]
            else:
                tasks = TASKS
                explanation = "The confirmed responsibilities were solved locally against released offers. No model was used for this proposal. Each owner must still check their private current state and approve."
                suggestions, tradeoffs = [], []
            validate_fresh()
            with engine.store.transaction() as (state, db):
                state["planning"]["phase"] = "Checking intervals, capacity, travel and handoffs"
            prior = snapshot["proposal"]["assignments"] if snapshot["proposal"] else snapshot.get("previous_assignments", [])
            result = solve(tasks, offers, previous=prior, suggestions=suggestions)
            if result["status"] not in ("OPTIMAL", "FEASIBLE"):
                with engine.store.transaction() as (state, db):
                    state["solver_result"] = result
                    state["planning"] = {"status": "NO_PLAN", "phase": "No confirmed plan", "error": result["reason"], "mode": mode}
                    state["state"] = "COLLECTING"
                    state["proposal"] = None
                    state["approvals"] = {}
                    engine.store.event(state, "SOLVER_" + result["status"], result["reason"], {"solver_status": result["status"]})
                return
            checked = verify_assignments(tasks, offers, result["assignments"])
            if not checked["valid"]:
                raise BrokerError("Independent verification rejected the candidate; it cannot be approved.")
            validate_fresh()
            with engine.store.transaction() as (state, db):
                if digest(state["offers"]) != input_fingerprint:
                    raise BrokerError("Released offers changed before proposal publication.")
                state["version"] += 1
                proposal_id = "proposal-" + uuid.uuid4().hex
                task_labels = {t["task_id"]: t["label"] for t in tasks}
                actions = []
                for assignment in result["assignments"]:
                    action_id = f"{proposal_id}:{assignment['task_id']}:{assignment['owner_id']}"
                    actions.append({"action_id": action_id, "owner_id": assignment["owner_id"], "task_id": assignment["task_id"], "label": task_labels[assignment["task_id"]], "start": assignment["start"], "end": assignment["end"], "date": state["goal"]["date"], "timezone": state["goal"]["timezone"], "adapter": "local-calendar", "event_id": "cg-" + hashlib.sha256(action_id.encode()).hexdigest()[:40], "expected_absent": True})
                proposal = {"proposal_id": proposal_id, "version": state["version"], "goal_id": state["goal"]["goal_id"], "goal_revision": state["goal"]["revision"], "date": state["goal"]["date"], "timezone": state["goal"]["timezone"], "created_at": utc_now(), "expires_at": min([expires_in(14400)] + [g["body"]["expires_at"] for g in grants]), "tasks": tasks, "assignments": result["assignments"], "actions": actions, "offer_refs": [{"owner_id": g["body"]["issuer"], "offer_id": g["body"]["payload"]["offer"]["offer_id"], "revision": g["body"]["payload"]["offer"]["revision"], "consent_revision": g["body"]["consent_revision"], "constraint_revision": g["body"]["payload"]["offer"]["constraint_revision"]} for g in grants], "solver": {key: value for key, value in result.items() if key != "assignments"}, "checker": checked, "model_receipt_id": receipt["receipt_id"] if receipt else None, "explanation": explanation, "tradeoffs": tradeoffs, "model_suggestions": suggestions}
                state["proposal"] = proposal
                state["archive"][proposal_id] = proposal
                state["approvals"], state["actions"], state["outbox"], state["reservations"] = {}, {}, {}, {}
                state["cancel_requested"] = False
                state["state"] = "AWAITING_APPROVAL"
                state["planning"] = {"status": "SUCCEEDED", "phase": "Ready for individual review", "error": None, "mode": mode}
                state["solver_result"] = result
                engine.store.event(state, "PROPOSAL_ISSUED", f"Proposal v{proposal['version']} passed independent released-offer checks. Owner approval is still required.", {"proposal_id": proposal_id, "proposal_digest": digest(proposal)})
        except Exception as error:
            with engine.store.transaction() as (state, db):
                message = str(error)[:500]
                try:
                    engine.provider.assert_clean(message)
                except ValueError:
                    message = "A private marker or credential was blocked. No proposal was issued."
                state["planning"] = {"status": "FAILED", "phase": "Planning needs attention", "error": message, "mode": mode}
                engine.store.event(state, "PLANNING_FAILED", message)
