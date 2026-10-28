from __future__ import annotations
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import uuid
from pathlib import Path
import httpx
from pydantic import ValidationError
from shared.protocol import digest, utc_now, expires_in, parse_time, verify_message
from shared.schema import BROKER_ID, CIRCLE_ID, OWNER_IDS, OWNER_INFO, TASKS, validate_payload
from broker.store import Store
from broker.models import Provider
from broker.checker import verify_assignments


class BrokerError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class Engine:
    def __init__(self, config):
        self.config = json.loads(Path(config).read_text()) if isinstance(config, (str, Path)) else config
        self.store = Store(Path(self.config["data_dir"]) / "broker.sqlite")
        self.provider = Provider(self.config.get("env_path"), self.config.get("provider_transport"))
        self.execution_lock = threading.Lock()
        self.planning_lock = threading.Lock()
        # An interrupted model request is not a successful run. Dispatch outbox stays durable.
        with self.store.transaction() as (state, db):
            if state["cancel_requested"] and state["proposal"]:
                self.invalidate_observations(state)
            if state["planning"]["status"] == "RUNNING":
                state["planning"] = {"status": "FAILED", "phase": "Interrupted", "error": "The process stopped during planning. Retry explicitly; provider outcome may be unknown."}
                for receipt in state["model_runs"]:
                    if receipt["status"] == "RUNNING":
                        receipt.update(status="FAILED", error="Interrupted process; completion/usage unknown.", finished_at=utc_now())

    def bootstrap_members(self):
        existing = {o["id"]: o for o in self.store.read()["owners"]}
        owners = []
        for peer in self.config["owners"]:
            with httpx.Client(timeout=5, transport=self.config.get("owner_transport"), trust_env=False) as client:
                response = client.get(peer["url"] + "/meta")
                response.raise_for_status()
                meta = response.json()
            owner_id = peer["id"]
            if meta["owner_id"] != owner_id or meta.get("revoked"):
                raise BrokerError("Owner membership identity is invalid.")
            if owner_id in existing and existing[owner_id]["public_key"] != meta["public_key"]:
                raise BrokerError("Owner key changed; a fresh explicit local pairing is required.")
            info = OWNER_INFO.get(owner_id, {"id": owner_id, "name": meta["name"], "initials": meta["name"][:2].upper(), "role": "Registered care-circle owner", "accent": "slate"})
            owners.append({**{k: v for k, v in info.items() if k != "port"}, "url": peer.get("browser_url", peer["url"]), "key_id": meta["key_id"], "public_key": meta["public_key"]})
        with self.store.transaction() as (state, db):
            state["owners"] = owners

    def peer(self, owner_id):
        try:
            return next(peer for peer in self.config["owners"] if peer["id"] == owner_id)
        except StopIteration as error:
            raise BrokerError("Unknown owner.", 403) from error

    def owner_call(self, owner_id, path, body=None):
        peer = self.peer(owner_id)
        try:
            with httpx.Client(timeout=20, transport=self.config.get("owner_transport"), trust_env=False) as client:
                response = client.request("GET" if body is None else "POST", peer["url"] + path, headers={"Authorization": "Bearer " + peer["service_token"]}, json=body)
            if response.status_code >= 400:
                detail = response.json().get("detail", "Owner request was rejected.")
                self.provider.assert_clean(detail)
                raise BrokerError(str(detail)[:400], response.status_code)
            result = response.json()
            self.provider.assert_clean(result)
            return result
        except (httpx.HTTPError, json.JSONDecodeError) as error:
            raise BrokerError("An owner agent is offline or its response is uncertain. Reconcile before retrying.", 503) from error

    def pair(self, pair_code):
        if not isinstance(pair_code, str) or not hmac.compare_digest(pair_code, self.config["pair_code"]):
            raise BrokerError("The local pairing code is not valid.", 403)
        token, expiry = secrets.token_urlsafe(32), expires_in(3600)
        with self.store.connect() as db:
            db.execute("INSERT INTO sessions VALUES(?,?)", (hashlib.sha256(token.encode()).hexdigest(), expiry))
        return {"token": token, "expires_at": expiry, "role": "sample-coordinator"}

    def authenticate(self, token):
        if not token:
            raise BrokerError("Pair this local sample session first.", 403)
        with self.store.connect() as db:
            row = db.execute("SELECT expires_at FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row or parse_time(row[0]) <= parse_time(utc_now()):
            raise BrokerError("This sample session is missing or expired. Pair again using your local launch link.", 403)
        return {"expires_at": row[0], "role": "sample-coordinator"}

    def wrapper(self, proposal):
        return {"proposal": proposal, "proposal_digest": digest(proposal) if proposal else None, "manifest_digest": digest(proposal["actions"]) if proposal else None}

    def current(self, proposal_id=None):
        state = self.store.read()
        proposal = state["proposal"] if proposal_id is None else state["archive"].get(proposal_id)
        if proposal_id and not proposal:
            raise BrokerError("That proposal was not found.", 404)
        return self.wrapper(proposal)

    def public_state(self):
        self.refresh_active_effects()
        state = self.store.read()
        public = {"sample": True, **{k: state[k] for k in ("goal", "owners", "state", "model_runs", "disclosures", "history", "revision", "planning")}, **self.wrapper(state["proposal"]), "offers": list(state["offers"].values()), "approvals": list(state["approvals"].values()), "actions": list(state["actions"].values()), "provider": self.provider.public_config()}
        if "solver_result" in state:
            public["solver_result"] = state["solver_result"]
        self.provider.assert_clean(public)
        return public

    def refresh_active_effects(self):
        snapshot = self.store.read()
        proposal = snapshot["proposal"]
        if snapshot["state"] != "ACTIVE" or not proposal:
            return
        observed = {}
        for owner in {a["owner_id"] for a in proposal["actions"]}:
            try:
                result = self.owner_call(owner, "/coordination/events?proposal_id=" + proposal["proposal_id"])
                observed.update({r["action_id"]: r for r in result["events"]})
            except BrokerError:
                for action in proposal["actions"]:
                    if action["owner_id"] == owner:
                        observed[action["action_id"]] = {"action_id": action["action_id"], "status": "UNCONFIRMED", "error": "Owner unavailable; current event state needs reconciliation."}
        with self.store.transaction() as (state, db):
            if state["state"] != "ACTIVE" or state["cancel_requested"] or state["proposal"]["proposal_id"] != proposal["proposal_id"]:
                return
            changed = False
            for action in proposal["actions"]:
                receipt = observed.get(action["action_id"], {"action_id": action["action_id"], "status": "NEEDS_ATTENTION", "error": "Owner observation is missing."})
                if receipt["status"] != "VERIFIED":
                    state["actions"][action["action_id"]] = {**action, **receipt}
                    state.setdefault("action_receipts", []).append({"proposal_id": proposal["proposal_id"], "observed_at": utc_now(), "source": "active-calendar-observation", "receipt": receipt})
                    changed = True
            if changed:
                state["state"] = "NEEDS_ATTENTION"
                self.store.event(state, "CALENDAR_CHANGED", "A previously verified local event changed or could not be confirmed. Reconcile the current effects.")

    def verify_signed(self, state, message, kind):
        try:
            issuer = message["body"]["issuer"]
            owner = next(o for o in state["owners"] if o["id"] == issuer)
            if message["body"]["key_id"] != owner["key_id"] or owner["key_id"] in state["revoked_keys"]:
                raise ValueError("Key is unknown or revoked")
            body = verify_message(message, owner["public_key"], audience=BROKER_ID, message_type=kind)
            if body["circle_id"] != CIRCLE_ID:
                raise ValueError("Message belongs to a different circle")
            payload = validate_payload(kind, body["payload"])
            self.provider.assert_clean(payload)
            if kind == "ReleaseGrant":
                expected_audience = set(payload["recipients"]["humans"]) | {BROKER_ID} | set(payload["recipients"]["inference"])
                if set(body["audience"]) != expected_audience or payload["offer"]["owner_id"] != issuer:
                    raise ValueError("Release recipient/issuer binding mismatch")
            return body
        except (ValueError, KeyError, StopIteration, TypeError) as error:
            reason = "strict payload schema violation" if isinstance(error, ValidationError) else str(error)[:220]
            raise BrokerError("Signed message rejected: " + reason, 403) from error

    @staticmethod
    def redelivery(db, message):
        try:
            body = message["body"]
            row = db.execute("SELECT * FROM deliveries WHERE message_id=? OR (issuer=? AND nonce=?)", (body["message_id"], body["issuer"], body["nonce"])).fetchone()
            if row:
                if row["message_id"] == body["message_id"] and row["message_digest"] == digest(message):
                    return json.loads(row["result"])
                raise BrokerError("Message ID or nonce was reused with different signed bytes.")
        except (KeyError, TypeError) as error:
            raise BrokerError("Malformed signed envelope.", 422) from error
        return None

    @staticmethod
    def accept_nonce(db, body, message, result=None):
        try:
            db.execute("INSERT INTO nonces VALUES(?,?)", (body["issuer"], body["nonce"]))
            db.execute("INSERT INTO deliveries VALUES(?,?,?,?,?)", (body["message_id"], body["issuer"], body["nonce"], digest(message), json.dumps(result or {"accepted": True})))
        except sqlite3.IntegrityError as error:
            raise BrokerError("This signed message nonce has already been used.", 409) from error

    def ingest_release(self, message):
        with self.store.transaction() as (state, db):
            delivered = self.redelivery(db, message)
            if delivered is not None:
                return delivered
            body = self.verify_signed(state, message, "ReleaseGrant")
            owner, revision = body["issuer"], body["consent_revision"]
            payload, offer = body["payload"], body["payload"]["offer"]
            if payload["goal_revision"] != state["goal"]["revision"] or revision <= state["consent_revisions"].get(owner, 0):
                raise BrokerError("Release has a stale goal or consent revision.")
            previous = state["offers"].get(owner)
            if previous and offer["revision"] <= previous["body"]["payload"]["offer"]["revision"]:
                raise BrokerError("A release must have a newer offer revision.")
            self.accept_nonce(db, body, message)
            state.setdefault("protocol_messages", []).append(message)
            state["consent_revisions"][owner] = revision
            state["offers"][owner] = message
            self.clear_obsolete_planning(state)
            state["approvals"] = {}
            if state["proposal"]:
                state["state"] = "REPLAN_REQUIRED"
                state["cancel_requested"] = True
                self.invalidate_observations(state)
            else:
                state["state"] = "COLLECTING"
            state["disclosures"].append({"receipt_id": "release-" + body["message_id"], "owner_id": owner, "recipients": payload["recipients"], "fields": payload["fields"], "purpose": payload["purpose"], "time": utc_now(), "kind": "release", "payload_digest": digest(offer)})
            self.store.event(state, "OFFER_RELEASED", OWNER_INFO[owner]["name"] + " released a bounded offer.", {"offer_id": offer["offer_id"], "revision": offer["revision"]})
        return {"accepted": True}

    def validate_current_grants(self, state, inference=False):
        if not state["offers"]:
            raise BrokerError("Release at least one owner offer before planning.")
        for owner, message in state["offers"].items():
            body = self.verify_signed(state, message, "ReleaseGrant")
            if body["consent_revision"] != state["consent_revisions"].get(owner):
                raise BrokerError("A released offer has been withdrawn or superseded.")
            if inference and "fireworks" not in body["payload"]["recipients"]["inference"]:
                raise BrokerError(OWNER_INFO[owner]["name"] + " has released this offer to the circle only. Fireworks needs a separate named release.", 403)

    def ingest_approval(self, message):
        with self.store.transaction() as (state, db):
            delivered = self.redelivery(db, message)
            if delivered is not None:
                return delivered
            body = self.verify_signed(state, message, "Approval")
            self.validate_current_grants(state)
            proposal, payload = state["proposal"], body["payload"]
            if not proposal or state["cancel_requested"] or parse_time(proposal["expires_at"]) <= parse_time(utc_now()):
                raise BrokerError("There is no current approvable proposal.")
            owner = body["issuer"]
            reference = next((r for r in proposal["offer_refs"] if r["owner_id"] == owner), None)
            own_actions = [a["action_id"] for a in proposal["actions"] if a["owner_id"] == owner]
            if not reference or not own_actions or sorted(payload["action_ids"]) != sorted(own_actions):
                raise BrokerError("Approval does not match this owner's exact action set.")
            if payload["proposal_id"] != proposal["proposal_id"] or payload["version"] != proposal["version"] or payload["proposal_digest"] != digest(proposal) or payload["manifest_digest"] != digest(proposal["actions"]):
                raise BrokerError("Approval binds a different proposal or action manifest.")
            if body["consent_revision"] != reference["consent_revision"] or body["consent_revision"] != state["consent_revisions"].get(owner) or payload["constraint_revision"] != reference["constraint_revision"]:
                raise BrokerError("Approval consent or private-constraint revision is stale.")
            if parse_time(payload["execution_not_after"]) > parse_time(proposal["expires_at"]) or parse_time(payload["execution_not_after"]) <= parse_time(utc_now()):
                raise BrokerError("Approval execution window is invalid.")
            self.accept_nonce(db, body, message)
            state.setdefault("protocol_messages", []).append(message)
            state["approvals"][owner] = message
            required = {a["owner_id"] for a in proposal["actions"]}
            state["state"] = "PREPARED" if required <= set(state["approvals"]) else "AWAITING_APPROVAL"
            self.store.event(state, "EXACT_APPROVAL", OWNER_INFO[owner]["name"] + f" approved proposal v{proposal['version']} and its exact calendar actions.", {"proposal_digest": digest(proposal)})
        return {"accepted": True}

    def ingest_withdrawal(self, message):
        with self.store.transaction() as (state, db):
            delivered = self.redelivery(db, message)
            if delivered is not None:
                return delivered
            body = self.verify_signed(state, message, "Withdrawal")
            owner, revision = body["issuer"], body["consent_revision"]
            if revision <= state["consent_revisions"].get(owner, 0):
                raise BrokerError("Withdrawal must advance consent revision.")
            current = state["offers"].get(owner)
            if current and body["payload"]["offer_id"] != current["body"]["payload"]["offer"]["offer_id"]:
                raise BrokerError("Withdrawal references a different offer.")
            self.accept_nonce(db, body, message, {"accepted": True, "reconciliation_required": bool(state["actions"])})
            state.setdefault("protocol_messages", []).append(message)
            state["consent_revisions"][owner] = revision
            state["offers"].pop(owner, None)
            self.clear_obsolete_planning(state)
            state["approvals"] = {}
            state["cancel_requested"] = True
            state["state"] = "REPLAN_REQUIRED" if state["proposal"] else "COLLECTING"
            self.invalidate_observations(state)
            for item in state["outbox"].values():
                if item["status"] == "PENDING":
                    item["status"] = "CANCELLED"
            self.store.event(state, "WITHDRAWAL", OWNER_INFO[owner]["name"] + " stopped future use of their offer. Existing effects need reconciliation.", {"consent_revision": revision})
        return {"accepted": True, "reconciliation_required": bool(self.store.read()["actions"])}

    @staticmethod
    def clear_obsolete_planning(state):
        if state["planning"]["status"] != "RUNNING":
            state["planning"] = {"status": "IDLE", "phase": "Released offers changed", "error": None}
            state.pop("solver_result", None)

    @staticmethod
    def invalidate_observations(state):
        for action in state["actions"].values():
            if action.get("status") not in ("CANCELLED", "UNCONFIRMED"):
                state.setdefault("action_receipts", []).append({"proposal_id": state["proposal"]["proposal_id"], "observed_at": utc_now(), "source": "historical-cache-invalidated-by-consent-change", "receipt": dict(action)})
                action["previous_status"] = action["status"]
                action["status"] = "UNCONFIRMED"
                action["error"] = "Consent changed. Previous verification is historical; reconcile current calendar effects."
