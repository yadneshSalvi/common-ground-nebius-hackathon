from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import HTTPException

from shared.protocol import digest, envelope, expires_in, new_identity, parse_time, sign_message, utc_now, verify_message
from owner_agent.calendar import CalendarStore, event_id_for
from owner_agent.storage import Vault
from shared.schema import OWNER_INFO, TASKS, validate_payload

BROKER = "common-ground-broker"
HUMANS = ["asha", "ravi", "leena"]
RETENTION = "Released facts remain in this local agreement audit; withdrawal stops future use."
FIELDS = ["owner_id", "capabilities", "task_ids", "start", "end", "capacity", "preference_cost", "constraint_revision"]
CAPABILITIES = {"prepare": "preparation", "outbound": "driving", "accompany": "accompaniment", "return": "driving", "handoff": "handoff"}
PROFILES = {
    "asha": {"name": "Asha", "role": "Dev's daughter", "initials": "AS", "accent": "clay", "start": 720, "end": 990, "tasks": ["prepare", "handoff"], "conflict": (780, 945)},
    "ravi": {"name": "Ravi", "role": "Dev's son", "initials": "RA", "accent": "ochre", "start": 780, "end": 975, "tasks": ["outbound", "return"], "conflict": (835, 915)},
    "leena": {"name": "Leena", "role": "Dev's neighbor", "initials": "LE", "accent": "slate", "start": 820, "end": 1005, "tasks": ["accompany", "return", "handoff"], "conflict": (1005, 1035)},
}
FAULTS = {"none": "No injected fault", "timeout_after_write": "Injected: timeout after the local calendar writes", "fail_before_write": "Injected: adapter failure before writing", "pause_before_send": "Injected: pause after durable authorization, before sending", "conflict_before_write": "Injected: conflicting user calendar entry before writing"}


def require(condition, message: str, status: int = 409):
    if not condition:
        raise HTTPException(status_code=status, detail=message)


def overlaps(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


class OwnerEngine:
    def __init__(self, config: dict):
        self.config = config
        self.owner_id = config["owner_id"]
        if self.owner_id not in PROFILES:
            profile = config.get("owner_profile")
            if not isinstance(profile, dict) or not isinstance(profile.get("name"), str) or not profile["name"] or not isinstance(profile.get("capabilities"), list) or not profile["capabilities"]:
                raise ValueError("A registered v2 owner requires an explicit name and capabilities in owner_profile")
            if not set(profile["capabilities"]) <= {"preparation", "driving", "accompaniment", "handoff", "meal", "visit"}:
                raise ValueError("Unknown configured owner capability")
            registered = config.get("registered_owners", [])
            if not isinstance(registered, list) or not 2 <= len(registered) <= 6 or len(set(registered)) != len(registered) or self.owner_id not in registered:
                raise ValueError("A v2 owner requires its exact registered circle of two to six owners")
        self.profile = config.get("owner_profile") or PROFILES[self.owner_id]
        for key in ("pair_code", "service_token", "broker_ingest_token"):
            if not isinstance(config.get(key), str) or len(config[key]) < 20:
                raise ValueError(f"{key} must be a random capability of at least 20 characters")
        if len({config["pair_code"], config["service_token"], config["broker_ingest_token"]}) != 3:
            raise ValueError("Pairing and service capabilities must be distinct")
        self.lock = threading.RLock()
        self.vault = Vault(config["data_dir"])
        self.identity = new_identity(self.vault.directory / "identity.json", self.owner_id)
        self.calendar = CalendarStore(self.vault.directory / "calendar.sqlite3")
        with self.vault.transaction() as db:
            if self.vault.read(db) is None:
                self.vault.write(db, self.seed())

    def seed(self):
        if self.owner_id not in PROFILES:
            # Generic v2 owners start without invented private facts. V1 remains
            # the fixed authored legacy fixture and never authorizes this owner.
            return {"consent_revision": 0, "constraint_revision": 1, "offer_revision": 0, "fence": 0,
                    "release": None, "approvals": [], "fault": "none", "legacy_protocol": False,
                    "preferences": {"availability_start": 0, "availability_end": 1440, "task_ids": [],
                                    "ask_before_driving": True, "private_note": "", "revision": 1},
                    "private_calendar": [], "skills": [], "corrections": [], "calendar_resolutions": []}
        profile = PROFILES[self.owner_id]
        return {"consent_revision": 0, "constraint_revision": 1, "offer_revision": 0, "fence": 0, "release": None, "approvals": [], "fault": "none", "preferences": {"availability_start": profile["start"], "availability_end": profile["end"], "task_ids": profile["tasks"], "ask_before_driving": self.owner_id == "ravi", "private_note": f"CG_PRIVATE_{self.owner_id.upper()}_NOTE_7D18: an authored personal reason that stays here.", "revision": 1, "preference_cost": 1 if self.owner_id == "ravi" else 0, "provenance": "Owner-confirmed fictional sample preference", "confidence": 1.0, "owner_confirmed": True, "scope": "appointment transport", "expires_at": None}, "private_calendar": [{"source_id": f"local-private-{self.owner_id}", "title": f"CG_PRIVATE_{self.owner_id.upper()}_CALENDAR_2E93", "start": profile["conflict"][0], "end": profile["conflict"][1], "date": "2026-11-02", "timezone": "Asia/Kolkata"}], "skills": [{"skill_id": "appointment-with-handoff", "name": "Appointment transport with a confirmed handoff", "version": 1, "scope": "Administrative appointment coordination only", "allowed_tools": ["local-calendar"], "required_approvals": ["exact proposal and calendar action manifest"], "completion_checks": ["Each calendar effect independently read and verified", "Handoff has an assigned owner"], "owner_confirmed": True, "provenance": "Authored sample skill, confirmed in this private owner vault", "confidence": 1.0, "expires_at": None}], "corrections": [], "calendar_resolutions": []}

    @property
    def living(self):
        # Keep the legacy protocol and calendar independent of the v2 runtime.
        if not hasattr(self, "_living"):
            with self.lock:
                if not hasattr(self, "_living"):
                    from owner_agent.living import LivingOwner
                    self._living = LivingOwner(self)
        return self._living

    @property
    def origin(self):
        return self.config.get("origin", f"http://127.0.0.1:{self.config['port']}")

    def owner(self):
        info = OWNER_INFO.get(self.owner_id, {"id": self.owner_id, "name": self.profile["name"], "initials": self.profile.get("initials", self.profile["name"][:2].upper()), "role": self.profile.get("role", "Registered owner"), "accent": self.profile.get("accent", "slate")})
        return {**info, "owner_id": self.owner_id, "port": self.config["port"], "url": self.origin, "key_id": self.identity["key_id"], "public_key": self.identity["public_key"]}

    def meta(self):
        return {"owner_id": self.owner_id, "name": self.profile["name"], "port": self.config["port"], "public_key": self.identity["public_key"], "key_id": self.identity["key_id"], "revoked": self.identity["key_id"] in self.config.get("revoked_keys", [])}

    def broker(self, method: str, route: str, payload=None):
        try:
            with httpx.Client(timeout=8, transport=self.config.get("broker_transport"), trust_env=False) as client:
                response = client.request(method, self.config["broker_url"].rstrip("/") + route, headers={"Authorization": "Bearer " + self.config["broker_ingest_token"]}, json=payload)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, "Shared coordinator unavailable; your private state is saved locally.") from exc

    def queue(self, db, route: str, message: dict):
        db.execute("INSERT INTO outbox(message_id,route,payload) VALUES(?,?,?)", (message["body"]["message_id"], route, json.dumps({"message": message})))

    def flush(self):
        # Never hold a vault transaction open over network I/O. Ordering is durable.
        with self.lock:
            with self.vault.connect() as db:
                pending = db.execute("SELECT * FROM outbox WHERE delivered=0 ORDER BY rowid").fetchall()
            for row in pending:
                self.broker("POST", row["route"], json.loads(row["payload"]))
                with self.vault.transaction() as db:
                    db.execute("UPDATE outbox SET delivered=1 WHERE message_id=?", (row["message_id"],))

    def signed(self, kind: str, payload: dict, revision: int, allow_inference=False, ttl=14400):
        require(self.owner_id in PROFILES, "The authored legacy appointment protocol is unavailable for this v2 owner.", 404)
        validate_payload(kind, payload)
        audience = [BROKER, *HUMANS] + (["fireworks"] if allow_inference else [])
        return sign_message(self.identity["private_key"], envelope(self.owner_id, self.identity["key_id"], kind, payload, revision, audience, ttl))

    def preview(self, allow_inference: bool, state=None):
        require(self.owner_id in PROFILES, "The authored legacy appointment protocol is unavailable for this v2 owner.", 404)
        state = state or self.vault.read()
        p = state["preferences"]
        current = state["release"]
        if current and current["body"]["payload"]["recipients"]["inference"] == (["fireworks"] if allow_inference else []):
            try:
                verify_message(current, self.identity["public_key"], BROKER, "ReleaseGrant")
                if current["body"]["payload"]["offer"]["constraint_revision"] == state["constraint_revision"]:
                    return json.loads(json.dumps(current["body"]["payload"]))
            except ValueError:
                pass
        offer = {"offer_id": f"offer-{self.owner_id}-r{state['offer_revision'] + 1}", "owner_id": self.owner_id, "revision": state["offer_revision"] + 1, "constraint_revision": state["constraint_revision"], "capabilities": sorted({CAPABILITIES[t] for t in p["task_ids"]}), "task_ids": p["task_ids"], "start": p["availability_start"], "end": p["availability_end"], "capacity": 1, "preference_cost": p.get("preference_cost", 1 if self.owner_id == "ravi" else 0)}
        return {"goal_id": "dev-appointment", "goal_revision": 1, "purpose": "coordinate-appointment", "retention": RETENTION, "recipients": {"humans": HUMANS, "broker": BROKER, "inference": ["fireworks"] if allow_inference else []}, "fields": FIELDS, "offer": offer}

    def release(self, expected_revision: int, allow_inference: bool, preview_digest: str | None = None):
        with self.lock:
            with self.vault.transaction() as db:
                state = self.vault.read(db)
                require(expected_revision == state["constraint_revision"], "Your preferences changed. Review the disclosure again.")
                payload = self.preview(allow_inference, state)
                if preview_digest is not None:
                    require(preview_digest == digest(payload), "The exact release preview changed. Review its recipients and facts again.")
                unchanged = state["release"] is not None and state["release"]["body"]["payload"] == payload
                if not unchanged:
                    # New disclosure scope obtains a fresh consent revision. Existing
                    # untransmitted work is cancelled, applied effects safely recovered.
                    state["consent_revision"] += 1
                    self.invalidate(db, state)
                    state["offer_revision"] += 1
                    state["release"] = self.signed("ReleaseGrant", payload, state["consent_revision"], allow_inference)
                    self.queue(db, "/v1/releases", state["release"])
                    self.vault.write(db, state)
                result = state["release"]
            if not unchanged:
                self.compensate_changed()
        self.flush()
        return {"release": result, "consent_revision": result["body"]["consent_revision"]}

    def invalidate(self, db, state):
        state["approvals"] = []
        db.execute("UPDATE reservations SET status='CANCELLED' WHERE status='ACTIVE'")
        db.execute("UPDATE actions SET status='CANCELLED',error='Owner consent or constraints changed before transmission' WHERE transmitted_at IS NULL AND status IN ('INTENT','PAUSED','FAILED')")

    def withdrawal_message(self, db, state, reason):
        release = state["release"]
        if release:
            payload = {"goal_id": "dev-appointment", "offer_id": release["body"]["payload"]["offer"]["offer_id"], "reason_code": reason}
            message = self.signed("Withdrawal", payload, state["consent_revision"])
            self.queue(db, "/v1/withdrawals", message)
        state["release"] = None

    def preferences(self, payload):
        with self.lock:
            with self.vault.transaction() as db:
                state = self.vault.read(db)
                require(payload["expected_revision"] == state["constraint_revision"], "Preferences changed in another window. Reload before saving.")
                state["consent_revision"] += 1
                state["constraint_revision"] += 1
                previous = state["preferences"]
                changes = {key: payload[key] for key in ("availability_start", "availability_end", "task_ids", "ask_before_driving")}
                if payload.get("preference_cost") is not None:
                    changes["preference_cost"] = payload["preference_cost"]
                if payload.get("private_note") is not None:
                    changes["private_note"] = payload["private_note"]
                changed = [k for k, v in changes.items() if previous.get(k) != v]
                previous.update(changes)
                previous["revision"] = state["constraint_revision"]
                state["corrections"].append({"correction_id": str(uuid.uuid4()), "at": utc_now(), "from_revision": state["constraint_revision"] - 1, "to_revision": state["constraint_revision"], "changed_fields": changed, "source": "owner-confirmed structured form"})
                self.invalidate(db, state)
                self.withdrawal_message(db, state, "preference_corrected")
                self.vault.write(db, state)
            self.compensate_changed()
        self.flush()
        return {"constraint_revision": state["constraint_revision"], "consent_revision": state["consent_revision"], "preferences": state["preferences"]}

    def withdraw(self, expected_revision):
        with self.lock:
            with self.vault.transaction() as db:
                state = self.vault.read(db)
                require(expected_revision == state["consent_revision"], "Consent changed. Reload before withdrawing.")
                state["consent_revision"] += 1
                self.invalidate(db, state)
                self.withdrawal_message(db, state, "owner_withdrew")
                self.vault.write(db, state)
            effects = self.compensate_changed()
        self.flush()
        return {"consent_revision": state["consent_revision"], "release": None, "effects": effects}

    def fetch_proposal(self, proposal_id=None):
        route = "/v1/proposals/" + proposal_id if proposal_id else "/v1/current"
        wrapper = self.broker("GET", route)
        if not wrapper.get("proposal"):
            return None
        require(wrapper.get("proposal_digest") == digest(wrapper["proposal"]), "Coordinator supplied an inconsistent proposal digest.")
        require(wrapper.get("manifest_digest") == digest(wrapper["proposal"]["actions"]), "Coordinator supplied an inconsistent action manifest.")
        return wrapper

    def validate_proposal(self, proposal: dict, state: dict):
        """Independent fail-closed owner checks; no broker validity claim is trusted."""
        try:
            require(self.identity["key_id"] not in state.get("revoked_keys", []) + self.config.get("revoked_keys", []), "Owner signing key is revoked.")
            require(proposal["goal_id"] == "dev-appointment" and proposal["goal_revision"] == 1, "Wrong goal.")
            require(proposal["date"] == "2026-11-02" and proposal["timezone"] == "Asia/Kolkata", "Wrong date or timezone.")
            require(type(proposal["version"]) is int and proposal["version"] >= 1, "Invalid proposal version.")
            require(parse_time(proposal["expires_at"]) > datetime.now(timezone.utc), "Proposal expired.")
            release = state["release"]
            require(release is not None, "Release an offer before approving.")
            verify_message(release, self.identity["public_key"], BROKER, "ReleaseGrant")
            require(release["body"]["consent_revision"] == state["consent_revision"], "Release is stale.")
            offer = release["body"]["payload"]["offer"]
            refs = [r for r in proposal["offer_refs"] if r["owner_id"] == self.owner_id]
            require(len(refs) == 1, "Proposal must reference exactly one current owner offer.")
            ref = refs[0]
            require(ref == {"owner_id": self.owner_id, "offer_id": offer["offer_id"], "revision": offer["revision"], "consent_revision": state["consent_revision"], "constraint_revision": state["constraint_revision"]}, "Proposal references stale consent or constraints.")
            tasks = {t["task_id"]: t for t in proposal["tasks"]}
            require(len(tasks) == len(proposal["tasks"]), "Duplicate task IDs.")
            require(set(tasks) == {t["task_id"] for t in TASKS}, "Confirmed appointment task catalog changed.")
            for reference in TASKS:
                task = tasks[reference["task_id"]]
                for field in ("capability", "duration", "earliest", "latest", "location", "predecessors"):
                    require(task[field] == reference[field], "A confirmed task constraint changed.")
            assignments = proposal["assignments"]
            require(len({a["task_id"] for a in assignments}) == len(assignments), "Duplicate task assignments.")
            require({a["task_id"] for a in assignments} == set(tasks), "Every task needs exactly one assignment.")
            # Check the entire chain, rather than accepting the coordinator checker flag.
            by_task = {a["task_id"]: a for a in assignments}
            for assignment in assignments:
                task = tasks[assignment["task_id"]]
                require(type(assignment["start"]) is int and type(assignment["end"]) is int, "Intervals must be integer minutes.")
                require(assignment["end"] - assignment["start"] == task["duration"] and assignment["start"] >= task["earliest"] and assignment["end"] <= task["latest"], "Task duration or window changed.")
                for predecessor in task["predecessors"]:
                    require(predecessor in by_task and by_task[predecessor]["end"] <= assignment["start"], "Precedence conflict.")
            own = [a for a in assignments if a["owner_id"] == self.owner_id]
            require(bool(own), "This proposal has no commitment for this owner.")
            own_actions = [a for a in proposal["actions"] if a["owner_id"] == self.owner_id]
            require(len(own_actions) == len(own) and {a["task_id"] for a in own_actions} == {a["task_id"] for a in own}, "Calendar actions do not match assignments.")
            require(len({a["action_id"] for a in proposal["actions"]}) == len(proposal["actions"]), "Duplicate action IDs.")
            require(len({a["event_id"] for a in proposal["actions"]}) == len(proposal["actions"]), "Duplicate event IDs.")
            p = state["preferences"]
            for assignment in own:
                require(assignment["task_id"] in p["task_ids"] and assignment["task_id"] in offer["task_ids"], "Task is outside your private allowlist.")
                require(assignment["offer_id"] == offer["offer_id"] and assignment["offer_revision"] == offer["revision"], "Assignment references an old offer.")
                require(assignment["start"] >= p["availability_start"] and assignment["end"] <= p["availability_end"], "A private availability constraint has changed.")
                require(assignment["start"] >= offer["start"] and assignment["end"] <= offer["end"], "Assignment exceeds released availability.")
                require(not any(overlaps(assignment, source) for source in state["private_calendar"] if source["date"] == proposal["date"]), "A private calendar conflict prevents this commitment.")
                require(not any(overlaps(assignment, other) for other in own if other is not assignment), "Owner capacity exceeded.")
                action = next(a for a in own_actions if a["task_id"] == assignment["task_id"])
                require(action["start"] == assignment["start"] and action["end"] == assignment["end"] and action["date"] == proposal["date"] and action["timezone"] == proposal["timezone"], "Calendar interval differs from commitment.")
                require(action["adapter"] == "local-calendar" and action["expected_absent"] is True and action["event_id"] == event_id_for(action["action_id"]), "Invalid calendar action or idempotency key.")
                require(action["label"] == tasks[action["task_id"]]["label"], "Calendar label differs from the task you reviewed.")
                require(CAPABILITIES.get(assignment["task_id"]) == tasks[assignment["task_id"]]["capability"], "Task capability mismatch.")
            # A person's next task must be physically reachable. Driving tasks
            # already include their own travel; only gaps between tasks need this.
            def endpoints(task):
                location = task["location"]
                return tuple(location.split("→")) if "→" in location else (location, location)
            ordered = sorted(own, key=lambda a: (a["start"], a["end"]))
            for before, after in zip(ordered, ordered[1:]):
                end_location = endpoints(tasks[before["task_id"]])[1]
                start_location = endpoints(tasks[after["task_id"]])[0]
                travel = 0 if end_location == start_location else 40
                require(before["end"] + travel <= after["start"], "Travel time between commitments is insufficient.")
            return own_actions
        except HTTPException:
            raise
        except (KeyError, TypeError, ValueError, StopIteration) as exc:
            raise HTTPException(409, "The proposed agreement is malformed or no longer valid.") from exc

    def approve(self, proposal_id, expected_version):
        wrapper = self.fetch_proposal(proposal_id)
        require(wrapper is not None, "No proposal is available.")
        proposal = wrapper["proposal"]
        with self.lock, self.vault.transaction() as db:
            state = self.vault.read(db)
            require(proposal["proposal_id"] == proposal_id and proposal["version"] == expected_version, "Proposal changed. Review its current version.")
            own_actions = self.validate_proposal(proposal, state)
            payload = {"proposal_id": proposal_id, "version": expected_version, "proposal_digest": wrapper["proposal_digest"], "manifest_digest": wrapper["manifest_digest"], "action_ids": [a["action_id"] for a in own_actions], "constraint_revision": state["constraint_revision"], "execution_not_after": min(proposal["expires_at"], state["release"]["body"]["expires_at"]), "compensation_policy": "delete-only-unchanged-created-events"}
            previous = next((a for a in state["approvals"] if a["body"]["payload"] == payload), None)
            message = previous or self.signed("Approval", payload, state["consent_revision"])
            if previous is None:
                state["approvals"].append(message)
                self.queue(db, "/v1/approvals", message)
                self.vault.write(db, state)
        self.flush()
        return {"approval": message}

    def prepare(self, proposal, approval):
        with self.lock, self.vault.transaction() as db:
            state = self.vault.read(db)
            try:
                body = verify_message(approval, self.identity["public_key"], BROKER, "Approval")
            except ValueError as exc:
                raise HTTPException(409, "Invalid or expired owner approval.") from exc
            require(body["issuer"] == self.owner_id and body["key_id"] == self.identity["key_id"], "Approval identity mismatch.")
            require(approval in state["approvals"], "This owner did not approve that exact manifest.")
            payload = body["payload"]
            require(body["consent_revision"] == state["consent_revision"] and payload["constraint_revision"] == state["constraint_revision"], "Approval is stale.")
            require(payload["proposal_id"] == proposal.get("proposal_id") and payload["version"] == proposal.get("version") and payload["proposal_digest"] == digest(proposal) and payload["manifest_digest"] == digest(proposal.get("actions")), "Approval does not bind this exact agreement.")
            # Authenticate the exact local approval before consulting private
            # constraints. A scoped coordinator cannot use forged prepares as a
            # calendar conflict oracle.
            own_actions = self.validate_proposal(proposal, state)
            require(payload["action_ids"] == [a["action_id"] for a in own_actions], "Approval action allowlist mismatch.")
            require(parse_time(payload["execution_not_after"]) > datetime.now(timezone.utc), "Approval execution window expired.")
            old = db.execute("SELECT * FROM reservations WHERE proposal_id=?", (proposal["proposal_id"],)).fetchone()
            if old and old["status"] == "ACTIVE" and parse_time(old["lease_expires_at"]) > datetime.now(timezone.utc):
                require(json.loads(old["payload"])["proposal"] == proposal, "Immutable proposal changed.")
                return self.reservation_result(old)
            for row in db.execute("SELECT * FROM reservations WHERE status='ACTIVE'").fetchall():
                if parse_time(row["lease_expires_at"]) <= datetime.now(timezone.utc):
                    db.execute("UPDATE reservations SET status='EXPIRED' WHERE reservation_id=?", (row["reservation_id"],))
                    continue
                other_actions = [a for a in json.loads(row["payload"])["proposal"]["actions"] if a["owner_id"] == self.owner_id]
                require(not any(overlaps(a, b) for a in own_actions for b in other_actions), "Another agreement already reserves this owner's time.")
            for action in own_actions:
                existing = self.calendar.get(action["event_id"])
                require(existing is None or (existing == {**CalendarStore.intended(action, proposal["proposal_id"]), "etag": existing["etag"], "user_edited": False}), "Calendar precondition conflict.")
                require(not any(overlaps(action, event) and event["date"] == action["date"] and event["action_id"] != action["action_id"] for event in self.calendar.list()), "Existing local calendar entry conflicts with this commitment.")
            used = db.execute("SELECT * FROM used_nonces WHERE nonce=?", (body["nonce"],)).fetchone()
            require(used is None or (used["message_id"] == body["message_id"] and used["proposal_id"] == proposal["proposal_id"]), "Approval nonce replayed for another agreement.")
            db.execute("INSERT OR IGNORE INTO used_nonces(nonce,message_id,proposal_id) VALUES(?,?,?)", (body["nonce"], body["message_id"], proposal["proposal_id"]))
            state["fence"] += 1
            reservation_id = "reservation-" + secrets.token_urlsafe(18)
            lease = min(expires_in(300), payload["execution_not_after"], proposal["expires_at"])
            db.execute("DELETE FROM reservations WHERE proposal_id=?", (proposal["proposal_id"],))
            db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?,?)", (reservation_id, proposal["proposal_id"], state["fence"], lease, state["consent_revision"], state["constraint_revision"], json.dumps({"proposal": proposal, "approval": approval}), "ACTIVE"))
            self.vault.write(db, state)
            return {"reservation_id": reservation_id, "fence": state["fence"], "lease_expires_at": lease, "consent_revision": state["consent_revision"], "constraint_revision": state["constraint_revision"]}

    @staticmethod
    def reservation_result(row):
        return {key: row[key] for key in ("reservation_id", "fence", "lease_expires_at", "consent_revision", "constraint_revision")}

    def remove_calendar_event(self, event_id, expected_etag):
        """Record an explicit owner's decision before conditionally removing a file-local effect."""
        with self.lock:
            event = self.calendar.get(event_id)
            require(event is not None, "Local calendar entry not found.", 404)
            require(event["etag"] == expected_etag, "The local calendar entry changed. Review it again before removing.")
            resolution_id = "resolution-" + secrets.token_urlsafe(18)
            audit = {"resolution_id": resolution_id, "at": utc_now(), "owner_id": self.owner_id, "event_id": event_id, "action_id": event["action_id"], "proposal_id": event["proposal_id"], "expected_etag": expected_etag, "decision": "remove-this-local-event", "status": "AUTHORIZED", "provenance": "Explicit authenticated owner confirmation on the private local surface"}
            with self.vault.transaction() as db:
                state = self.vault.read(db)
                state.setdefault("calendar_resolutions", []).append(audit)
                self.vault.write(db, state)
            try:
                self.calendar.remove_by_owner(event_id, expected_etag)
            except (KeyError, ValueError) as exc:
                with self.vault.transaction() as db:
                    state = self.vault.read(db)
                    record = next(r for r in state["calendar_resolutions"] if r["resolution_id"] == resolution_id)
                    record.update(status="REFUSED_CHANGED_OR_MISSING", completed_at=utc_now())
                    self.vault.write(db, state)
                raise HTTPException(409, "The local calendar entry changed. Review it again before removing.") from exc
            with self.vault.transaction() as db:
                state = self.vault.read(db)
                record = next(r for r in state["calendar_resolutions"] if r["resolution_id"] == resolution_id)
                record.update(status="REMOVED", completed_at=utc_now(), verified_absent_at=utc_now())
                self.vault.write(db, state)
                db.execute("UPDATE actions SET status='CANCELLED',error='Owner explicitly removed this local calendar entry.' WHERE event_id=?", (event_id,))
            return {"event_id": event_id, "status": "REMOVED", "removed": True, "resolution_id": resolution_id}

    def receipt(self, row):
        result = {"action_id": row["action_id"], "status": row["status"], "event_id": row["event_id"], "etag": row["etag"], "verified_at": row["verified_at"], "intent": {"authorization_id": "intent-" + digest({"action_id": row["action_id"], "reservation_id": row["reservation_id"], "fence": row["fence"]})[:32], "fence": row["fence"], "authorized_at": row["authorized_at"], "transmitted_at": row["transmitted_at"]}}
        if row["error"]:
            result["error"] = row["error"]
        if row["status"] == "NEEDS_ATTENTION":
            event = self.calendar.get(row["event_id"])
            if event:
                # User-edited text is private. The coordinator sees remaining-effect metadata only.
                result["remaining_effect"] = {k: event[k] for k in ("event_id", "action_id", "proposal_id", "start", "end", "date", "timezone", "user_edited")}
        resolutions = self.vault.read().get("calendar_resolutions", [])
        resolved = next((r for r in reversed(resolutions) if r["event_id"] == row["event_id"] and r["status"] in ("REMOVED", "ABSENCE_CONFIRMED")), None)
        if resolved:
            result["resolution"] = {"resolution_id": resolved["resolution_id"], "kind": "owner-confirmed-removal", "at": resolved["at"], "verified_absent_at": resolved.get("verified_absent_at")}
        return result

    def _active(self, db, request):
        state = self.vault.read(db)
        row = db.execute("SELECT * FROM reservations WHERE reservation_id=?", (request["reservation_id"],)).fetchone()
        require(row is not None and row["proposal_id"] == request["proposal_id"] and row["fence"] == request["fence"], "Stale or unknown dispatch fence.")
        require(row["status"] == "ACTIVE", "Reservation was cancelled.")
        require(parse_time(row["lease_expires_at"]) > datetime.now(timezone.utc), "Reservation lease expired.")
        require(row["consent_revision"] == state["consent_revision"] and row["constraint_revision"] == state["constraint_revision"], "Consent or constraints changed before transmission.")
        saved = json.loads(row["payload"])
        own_actions = self.validate_proposal(saved["proposal"], state)
        try:
            approved = verify_message(saved["approval"], self.identity["public_key"], BROKER, "Approval")
            require(self.identity["key_id"] not in state.get("revoked_keys", []) and self.identity["key_id"] not in self.config.get("revoked_keys", []), "Owner signing key was revoked.")
            require(parse_time(approved["payload"]["execution_not_after"]) > datetime.now(timezone.utc), "Approval execution window expired.")
            require(saved["approval"] in state["approvals"], "Approval is no longer current.")
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, "Approval expired or became invalid before transmission.") from exc
        action = next((a for a in own_actions if a["action_id"] == request["action_id"]), None)
        require(action is not None, "Action is not authorized for this owner.")
        return state, action

    def dispatch(self, request, reconcile=False):
        with self.lock:
            # Reconciliation always reads a deterministic external ID first, even
            # after withdrawal, expiry or restart; it cannot silently authorize a send.
            with self.vault.connect() as db:
                previous = db.execute("SELECT * FROM actions WHERE action_id=?", (request["action_id"],)).fetchone()
                reservation = db.execute("SELECT * FROM reservations WHERE reservation_id=?", (request["reservation_id"],)).fetchone()
                require(reservation is not None and reservation["proposal_id"] == request["proposal_id"] and reservation["fence"] == request["fence"], "Stale or unknown dispatch fence.")
                if previous:
                    require(previous["proposal_id"] == request["proposal_id"], "Action ID belongs to another proposal.")
                    if previous["status"] in ("CANCELLED", "NEEDS_ATTENTION"):
                        return self.receipt(previous)
                    action = json.loads(previous["payload"])
                    actual = self.calendar.get(action["event_id"])
                    if actual:
                        match = {k: actual[k] for k in CalendarStore.intended(action, request["proposal_id"])} == CalendarStore.intended(action, request["proposal_id"]) and not actual["user_edited"]
                        with self.vault.transaction() as update:
                            update.execute("UPDATE actions SET status=?,etag=?,verified_at=?,error=? WHERE action_id=?", ("VERIFIED" if match else "NEEDS_ATTENTION", actual["etag"] if match else previous["etag"], utc_now() if match else None, None if match else "Calendar entry changed; owner review is required.", action["action_id"]))
                        with self.vault.connect() as reread:
                            current = reread.execute("SELECT * FROM actions WHERE action_id=?", (action["action_id"],)).fetchone()
                            return self.receipt(current)
                    if previous["status"] == "VERIFIED":
                        with self.vault.transaction() as update:
                            update.execute("UPDATE actions SET status='NEEDS_ATTENTION',error='Previously verified event is now missing.' WHERE action_id=?", (previous["action_id"],))
                        with self.vault.connect() as reread:
                            return self.receipt(reread.execute("SELECT * FROM actions WHERE action_id=?", (previous["action_id"],)).fetchone())
            with self.vault.transaction() as db:
                state, action = self._active(db, request)
                # Durable authorization linearization point: state, lease, approval,
                # calendar preconditions and fence are checked in this transaction.
                require(self.calendar.get(action["event_id"]) is None, "Calendar precondition changed before dispatch.")
                require(not any(e["date"] == action["date"] and overlaps(action, e) for e in self.calendar.list()), "Local calendar now conflicts with this action.")
                if previous is None:
                    db.execute("INSERT INTO actions(action_id,proposal_id,reservation_id,fence,payload,status,event_id,authorized_at) VALUES(?,?,?,?,?,'INTENT',?,?)", (action["action_id"], request["proposal_id"], request["reservation_id"], request["fence"], json.dumps(action), action["event_id"], utc_now()))
                else:
                    db.execute("UPDATE actions SET reservation_id=?,fence=?,status='INTENT',authorized_at=?,error=NULL WHERE action_id=?", (request["reservation_id"], request["fence"], previous["authorized_at"] if previous["fence"] == request["fence"] else utc_now(), action["action_id"]))
                mode = state["fault"]
                if mode == "pause_before_send":
                    db.execute("UPDATE actions SET status='PAUSED',error='Injected pause before calendar transmission.' WHERE action_id=?", (action["action_id"],))
            if mode == "pause_before_send":
                with self.vault.connect() as db:
                    return self.receipt(db.execute("SELECT * FROM actions WHERE action_id=?", (action["action_id"],)).fetchone())
            # Withdrawal and send scheduling share this lock. A resumed or expired
            # worker must revalidate authority immediately before transport.
            with self.vault.transaction() as db:
                self._active(db, request)
                current = db.execute("SELECT * FROM actions WHERE action_id=?", (action["action_id"],)).fetchone()
                require(current["fence"] == request["fence"] and current["status"] == "INTENT", "Dispatch intent was fenced or cancelled.")
                if mode == "fail_before_write":
                    db.execute("UPDATE actions SET status='FAILED',error='Injected adapter failure before write.' WHERE action_id=?", (action["action_id"],))
                else:
                    db.execute("UPDATE actions SET transmitted_at=? WHERE action_id=?", (utc_now(), action["action_id"]))
            if mode != "fail_before_write":
                try:
                    if mode == "conflict_before_write":
                        self.calendar.insert(action, request["proposal_id"])
                        self.calendar.edit(action["event_id"], "Injected local user calendar conflict")
                        raise ValueError("Injected calendar precondition conflict")
                    actual = self.calendar.insert(action, request["proposal_id"])
                    if mode == "timeout_after_write":
                        with self.vault.transaction() as db:
                            db.execute("UPDATE actions SET status='AMBIGUOUS',error='Injected timeout after write; read the deterministic event before retrying.' WHERE action_id=?", (action["action_id"],))
                    else:
                        verified = self.calendar.get(action["event_id"])
                        require(verified is not None and verified["etag"] == actual["etag"], "Calendar verification changed.")
                        with self.vault.transaction() as db:
                            db.execute("UPDATE actions SET status='VERIFIED',etag=?,verified_at=?,error=NULL WHERE action_id=?", (actual["etag"], utc_now(), action["action_id"]))
                except ValueError:
                    with self.vault.transaction() as db:
                        db.execute("UPDATE actions SET status='NEEDS_ATTENTION',error='Calendar precondition conflict; existing entry preserved.' WHERE action_id=?", (action["action_id"],))
            with self.vault.connect() as db:
                return self.receipt(db.execute("SELECT * FROM actions WHERE action_id=?", (action["action_id"],)).fetchone())

    def compensate(self, action_id):
        with self.lock:
            with self.vault.connect() as db:
                row = db.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()
            require(row is not None, "No owner-authorized action exists.", 404)
            with self.vault.connect() as db:
                reservation = db.execute("SELECT payload FROM reservations WHERE proposal_id=?", (row["proposal_id"],)).fetchone()
            require(reservation is not None and json.loads(reservation["payload"])["approval"]["body"]["payload"].get("compensation_policy") == "delete-only-unchanged-created-events", "This action has no signed compensation authorization.")
            action = json.loads(row["payload"])
            etag = row["etag"]
            existing = self.calendar.get(row["event_id"])
            # A transport timeout may have left no local ETag. Verify the exact
            # created payload before acquiring its ETag for conditional deletion.
            if etag is None and existing and not existing["user_edited"]:
                expected = CalendarStore.intended(action, row["proposal_id"])
                if {k: existing[k] for k in expected} == expected:
                    etag = existing["etag"]
            deleted, _ = self.calendar.delete_if_unchanged(row["event_id"], etag)
            with self.vault.transaction() as db:
                db.execute("UPDATE actions SET status=?,error=? WHERE action_id=?", ("CANCELLED" if deleted else "NEEDS_ATTENTION", "Created calendar entry removed or confirmed absent." if deleted else "User-edited calendar entry preserved; manual review is required.", action_id))
                row = db.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()
                return self.receipt(row)

    def cancel(self, proposal_id):
        """Cancel only locally approved work; conditionally recover existing effects."""
        with self.lock:
            with self.vault.transaction() as db:
                state = self.vault.read(db)
                reservation = db.execute("SELECT * FROM reservations WHERE proposal_id=?", (proposal_id,)).fetchone()
                rows = db.execute("SELECT * FROM actions WHERE proposal_id=?", (proposal_id,)).fetchall()
                approved = [m for m in state["approvals"] if m["body"]["payload"]["proposal_id"] == proposal_id]
                require(reservation is not None or bool(rows) or bool(approved), "No locally approved proposal exists to cancel.", 404)
                if reservation:
                    policy = json.loads(reservation["payload"])["approval"]["body"]["payload"].get("compensation_policy")
                    require(policy == "delete-only-unchanged-created-events", "This proposal has no signed compensation authorization.")
                else:
                    require(all(m["body"]["payload"].get("compensation_policy") == "delete-only-unchanged-created-events" for m in approved), "Missing signed compensation authorization.")
                db.execute("UPDATE reservations SET status='CANCELLED' WHERE proposal_id=?", (proposal_id,))
                db.execute("UPDATE actions SET status='CANCELLED',error='Agreement cancelled before transmission.' WHERE proposal_id=? AND transmitted_at IS NULL", (proposal_id,))
                state["approvals"] = [m for m in state["approvals"] if m["body"]["payload"]["proposal_id"] != proposal_id]
                self.vault.write(db, state)
            for row in rows:
                if row["transmitted_at"] is not None:
                    self.compensate(row["action_id"])
            return {"actions": self.events(proposal_id), "reservation_cancelled": True}

    def compensate_changed(self):
        with self.vault.connect() as db:
            rows = db.execute("SELECT action_id FROM actions WHERE transmitted_at IS NOT NULL AND status NOT IN ('CANCELLED')").fetchall()
        return [self.compensate(row["action_id"]) for row in rows]

    def events(self, proposal_id=None):
        """Observe actual adapter storage; this endpoint never resends or deletes."""
        with self.lock, self.vault.transaction() as db:
            rows = db.execute("SELECT * FROM actions" + (" WHERE proposal_id=?" if proposal_id else "") + " ORDER BY rowid", (proposal_id,) if proposal_id else ()).fetchall()
            private_state = self.vault.read(db)
            audit_changed = False
            for row in rows:
                action = json.loads(row["payload"])
                actual = self.calendar.get(row["event_id"])
                status, etag, error, verified = row["status"], row["etag"], row["error"], row["verified_at"]
                if actual is not None:
                    expected = CalendarStore.intended(action, row["proposal_id"])
                    matches = {key: actual[key] for key in expected} == expected and not actual["user_edited"]
                    matches = matches and (etag is None or etag == actual["etag"])
                    if matches and status != "CANCELLED":
                        status, etag, error, verified = "VERIFIED", actual["etag"], None, utc_now()
                    else:
                        status, error, verified = "NEEDS_ATTENTION", "Calendar entry changed or remains after cancellation; owner review is required.", None
                elif any(r["event_id"] == row["event_id"] and r["status"] in ("AUTHORIZED", "REMOVED", "ABSENCE_CONFIRMED") for r in private_state.get("calendar_resolutions", [])):
                    # A restart may land after the independent calendar deleted
                    # the event but before the private audit's acknowledgement.
                    # Actual absence plus the durable owner decision closes it.
                    resolution = next(r for r in reversed(private_state["calendar_resolutions"]) if r["event_id"] == row["event_id"] and r["status"] in ("AUTHORIZED", "REMOVED", "ABSENCE_CONFIRMED"))
                    if resolution["status"] == "AUTHORIZED":
                        resolution.update(status="ABSENCE_CONFIRMED", verified_absent_at=utc_now())
                        audit_changed = True
                    status, error = "CANCELLED", "Owner-confirmed removal; calendar absence verified."
                elif status == "VERIFIED":
                    status, error, verified = "NEEDS_ATTENTION", "Previously verified calendar entry is now missing.", None
                elif status == "INTENT":
                    status = "AMBIGUOUS" if row["transmitted_at"] else "PAUSED"
                    error = "Recovered durable dispatch intent; no calendar effect observed. Reconcile before retrying."
                db.execute("UPDATE actions SET status=?,etag=?,error=?,verified_at=? WHERE action_id=?", (status, etag, error, verified, row["action_id"]))
            if audit_changed:
                self.vault.write(db, private_state)
            current = db.execute("SELECT * FROM actions" + (" WHERE proposal_id=?" if proposal_id else "") + " ORDER BY rowid", (proposal_id,) if proposal_id else ()).fetchall()
            return [self.receipt(row) for row in current]

    def status(self):
        state = self.vault.read()
        return {"owner_id": self.owner_id, "consent_revision": state["consent_revision"], "constraint_revision": state["constraint_revision"], "release": state["release"], "revoked_keys": sorted(set(state.get("revoked_keys", []) + self.config.get("revoked_keys", [])))}

    def state(self):
        delivery_ok = True
        try:
            self.flush()
        except HTTPException:
            delivery_ok = False
        with self.lock:
            state = self.vault.read()
            result = {"owner": self.owner(), **{key: state[key] for key in ("preferences", "private_calendar", "release", "consent_revision", "constraint_revision", "approvals", "skills", "corrections")}, "calendar_events": self.calendar.list(), "calendar_resolutions": state.get("calendar_resolutions", []), "fault": {"mode": state["fault"], "label": FAULTS[state["fault"]]}, "proposals": [], "coordinator_available": delivery_ok}
        with self.vault.connect() as db:
            result["coordination_pending"] = db.execute("SELECT COUNT(*) FROM outbox WHERE delivered=0").fetchone()[0]
        try:
            current = self.fetch_proposal()
            if current:
                result["proposals"] = [current]
        except HTTPException:
            result["coordinator_available"] = False
        return result

    def set_fault(self, mode):
        with self.lock, self.vault.transaction() as db:
            state = self.vault.read(db)
            state["fault"] = mode
            self.vault.write(db, state)
        return {"mode": mode, "label": FAULTS[mode]}
