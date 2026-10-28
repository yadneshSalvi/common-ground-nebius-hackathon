"""Owner-local living agreements. No coordinator capability can create consent.

The encrypted vault owns decisions. Separate durable tables own transmission
intents, so restart and readback cannot accidentally become fresh authority.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import secrets
import uuid

from fastapi import HTTPException

from owner_agent.engine import BROKER, require
from shared.protocol import digest, envelope, expires_in, parse_time, sign_message, utc_now, verify_message
from shared.living import (agreement_digest, commitment_digest, consent_payload,
                           dependency_digest, goal_digest, validate_agreement,
                           validate_consent, validate_goal, validate_release)

MEMORY_TYPES = {"excluded_capability", "weekly_capacity", "request_category", "handoff_deadline", "require_receiver"}
PROVIDERS = {"none", "fireworks", "nebius"}


def future(value):
    return parse_time(value) > datetime.now(timezone.utc)


def normalized(validator, value):
    try:
        result = validator(value)
        return result.model_dump() if hasattr(result, "model_dump") else result
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, "The reviewed living agreement data is invalid.") from exc


def intersects(a, b):
    return a["date"] == b["date"] and a["start"] < b["end"] and b["start"] < a["end"]


def authored_sample_goal(raw):
    """Recognize the one fixed bootstrap fixture independently of the broker.

    The service capability may select this authored rehearsal, never relabel an
    arbitrary source or an amendment as a sample decision.
    """
    goal = normalized(validate_goal, raw)
    require(goal["confirmed_by"] == "authored-fictional-sample" and goal["revision"] == 1 and goal["participants"] == ["asha", "ravi", "leena"], "This is not the registered authored fictional setup.")
    day = goal["tasks"][0]["date"]
    source = (f"Fictional reviewed request for {day}, Asia/Kolkata. Asha, Ravi and Leena are the participating owners. Dev is the care recipient. "
              "Prepare Dev at home from 12:20 to 12:40 (20 minutes). Ravi can drive pickup and return. "
              "Drive Dev from home to clinic from 13:10 to 13:50 (40 minutes). Stay with Dev at the clinic from 13:50 to 15:20 (90 minutes). "
              "Drive Dev from clinic to home from 15:20 to 16:00 (40 minutes). Receive Dev at home from 16:00 to 16:15 (15 minutes). "
              "These five responsibilities form that required sequence. The explicitly confirmed travel time is 40 minutes in each direction between home and clinic. "
              "Asha prepares and receives Dev, Ravi initially drives both ways, and Leena accompanies him. All people, dates and decisions in this rehearsal are fictional.")
    facts = [("prepare", "Get ready at home", "preparation", 740, 760, "home", "home", []),
             ("outbound", "Take Dev to the appointment", "driving", 790, 830, "home", "clinic", ["prepare"]),
             ("accompany", "Stay with Dev at the appointment", "accompaniment", 830, 920, "clinic", "clinic", ["outbound"]),
             ("return", "Bring Dev home", "driving", 920, 960, "clinic", "home", ["accompany"]),
             ("handoff", "Receive Dev at home", "handoff", 960, 975, "home", "home", ["return"])]
    tasks = [{"task_id": tid, "label": label, "capability": capability, "date": day, "duration": end-start,
              "earliest": start, "latest": end, "start_location": origin, "end_location": destination,
              "predecessors": prior, "required": True, "subject": "Dev", "source_quote": source}
             for tid, label, capability, start, end, origin, destination, prior in facts]
    routes = [{"from_location": origin, "to_location": destination, "duration": 40,
               "source_quote": "The explicitly confirmed travel time is 40 minutes in each direction between home and clinic."}
              for origin, destination in [("home", "clinic"), ("clinic", "home")]]
    require(goal["title"] == "Dev’s afternoon appointment" and goal["description"] == "A fictional care arrangement that can be repaired without asking Asha to drive."
            and goal["timezone"] == "Asia/Kolkata" and goal["subject"] == "Dev" and goal["source_text"] == source
            and goal["tasks"] == tasks and goal["routes"] == routes, "This is not the registered authored fictional setup.")
    return goal


class LivingOwner:
    def __init__(self, engine):
        self.engine = engine
        self.vault = engine.vault
        self.lock = engine.lock
        self.owner_id = engine.owner_id
        self.config = engine.config
        self._calendar = self.config.get("living_calendar")
        with self.lock, self.vault.transaction() as db:
            state = self.vault.read(db)
            if "living" not in state:
                state["living"] = {
                    "revision": 1, "consent_revision": 0, "constraint_revision": 1,
                    "fence": 0, "goals": {}, "offers": {}, "approvals": {}, "prepared_revisions": {},
                    "reviewed_agreements": {}, "memories": [], "deletions": [], "release_history": [],
                    "requests": [], "refusals": {}, "withdrawn": {},
                    "excluded_tasks": {}, "task_choices": {}, "goal_constraint_revisions": {},
                    "policy": {"enabled": False, "revision": 0, "expires_at": None},
                    "sample_setups": [], "history": [],
                }
                self.vault.write(db, state)

    @property
    def calendar(self):
        if self._calendar is None:
            from owner_agent.living_calendar import LivingCalendarStore
            self._calendar = LivingCalendarStore(self.vault.directory / "living-calendar.sqlite3")
        return self._calendar

    def read(self, db=None):
        return self.vault.read(db)["living"]

    def write(self, db, state):
        private = self.vault.read(db)
        private["living"] = state
        self.vault.write(db, private)

    def constraint_revision(self, state, goal_id):
        return state["goal_constraint_revisions"].get(goal_id, state["constraint_revision"])

    def check_revision(self, state, expected):
        require(type(expected) is int and expected == state["revision"], "Your private workspace changed. Reload before saving.")

    def bump(self, state):
        state["revision"] += 1

    def key_active(self):
        private = self.vault.read()
        require(self.engine.identity["key_id"] not in private.get("revoked_keys", []) + self.config.get("revoked_keys", []), "Owner signing key is revoked.")

    def signed(self, kind, payload, state, recipients=None):
        self.key_active()
        audience = [BROKER, *sorted(state["goals"][payload["goal_id"]]["participants"])] if "goal_id" in payload else [BROKER, self.owner_id]
        for recipient in (recipients or []):
            if recipient not in audience:
                audience.append(recipient)
        return sign_message(self.engine.identity["private_key"], envelope(
            self.owner_id, self.engine.identity["key_id"], kind, payload,
            state["consent_revision"], audience, ttl=self.config.get("living_ttl", 14400), schema_version=2))

    def public_message(self, message, kind):
        try:
            body = verify_message(message, self.engine.identity["public_key"], BROKER, kind)
            require(body["schema_version"] == 2 and body["issuer"] == self.owner_id and body["key_id"] == self.engine.identity["key_id"] and body["circle_id"] == "dev-circle", "Invalid owner authority.")
            self.key_active()
            return body
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(409, "Invalid or expired owner authority.") from exc

    def flush(self):
        self.engine.flush()

    def _queue(self, db, route, message):
        self.engine.queue(db, route, message)

    def remember_goal(self, raw):
        goal = normalized(validate_goal, raw)
        require(self.owner_id in goal["participants"], "This reviewed goal does not include this owner.")
        require(set(goal["participants"]) <= set(self.config.get("registered_owners", ["asha", "ravi", "leena"])), "Goal participants must be registered owners.")
        require(bool(goal.get("confirmed_at")) and bool(goal.get("confirmed_by")), "A goal must first be explicitly reviewed.")
        with self.lock, self.vault.transaction() as db:
            state = self.read(db)
            previous = state["goals"].get(goal["goal_id"])
            if previous == goal:
                return {"accepted": True, "goal_id": goal["goal_id"], "revision": goal["revision"]}
            require(previous is None or goal["revision"] > previous["revision"], "A reviewed goal revision cannot be replaced or reversed.")
            if previous:
                self.invalidate(db, state, {goal["goal_id"]})
            state["goals"][goal["goal_id"]] = goal
            state["goal_constraint_revisions"][goal["goal_id"]] = state["constraint_revision"]
            self.bump(state)
            self.write(db, state)
        return {"accepted": True, "goal_id": goal["goal_id"], "revision": goal["revision"]}

    def active_memories(self, state, goal):
        return [memory for memory in state["memories"] if memory.get("owner_confirmed") is True
                and (not memory.get("expires_at") or future(memory["expires_at"]))
                and (not memory["scope"].get("goal_id") or memory["scope"]["goal_id"] == goal["goal_id"])]

    def memory_applies(self, memory, task):
        value = memory["value"]
        return (not value.get("task_id") or value["task_id"] == task["task_id"]) and (not value.get("capability") or value["capability"] == task["capability"])

    def _memory(self, raw, previous=None):
        require(isinstance(raw, dict), "A structured memory is required.", 422)
        allowed = {"memory_id", "type", "value", "scope", "provenance", "expires_at", "private_note", "owner_confirmed"}
        require(not set(raw) - allowed, "Unsupported memory fields.", 422)
        require(raw.get("type") in MEMORY_TYPES and isinstance(raw.get("value"), dict), "Choose a supported structured memory type.", 422)
        require(raw.get("owner_confirmed") is True, "Confirm the memory before it can affect decisions.", 422)
        require(isinstance(raw.get("provenance"), str) and 1 <= len(raw["provenance"]) <= 1000, "Memory provenance is required.", 422)
        scope = raw.get("scope", {})
        require(isinstance(scope, dict) and not set(scope) - {"goal_id"}, "Memory scope must name a goal or apply to all goals.", 422)
        if scope.get("goal_id") is not None:
            require(isinstance(scope["goal_id"], str) and len(scope["goal_id"]) <= 200, "Invalid memory goal scope.", 422)
        if raw.get("expires_at"):
            try:
                require(future(raw["expires_at"]), "Memory expiry must be in the future.", 422)
            except (ValueError, TypeError) as exc:
                raise HTTPException(422, "Invalid memory expiry.") from exc
        value = deepcopy(raw["value"])
        kind = raw["type"]
        allowed_values = {
            "excluded_capability": {"capability", "task_id"},
            "weekly_capacity": {"minutes"},
            "request_category": {"category", "allowed"},
            "handoff_deadline": {"capability", "task_id", "by"},
            "require_receiver": {"capability", "task_id", "receiver_id", "receiver_task_id", "by"},
        }
        require(not set(value) - allowed_values[kind], "Unsupported memory value fields.", 422)
        if "capability" in value:
            require(value["capability"] in {"preparation", "driving", "accompaniment", "handoff", "meal", "visit"}, "Invalid capability.", 422)
        if kind == "excluded_capability":
            require(bool(value.get("capability")), "An excluded capability is required.", 422)
        if kind == "weekly_capacity":
            require(type(value.get("minutes")) is int and 0 <= value["minutes"] <= 10080, "Capacity must be integer weekly minutes.", 422)
        if kind == "request_category":
            require(isinstance(value.get("category"), str) and 1 <= len(value["category"]) <= 100 and type(value.get("allowed")) is bool, "A category and explicit permission are required.", 422)
        if kind in {"require_receiver", "handoff_deadline"}:
            require(type(value.get("by")) is int and 1 <= value["by"] <= 1440, "A local-minute handoff deadline is required.", 422)
        if kind == "require_receiver":
            require(value.get("receiver_id") in self.config.get("registered_owners", ["asha", "ravi", "leena"]) and isinstance(value.get("receiver_task_id"), str) and value["receiver_task_id"], "A registered receiver and exact receiver task are required.", 422)
        if raw.get("private_note") is not None:
            require(isinstance(raw["private_note"], str) and len(raw["private_note"]) <= 2000, "Private note is too long.", 422)
        return {"memory_id": previous["memory_id"] if previous else raw.get("memory_id") or "memory-" + str(uuid.uuid4()),
                "type": kind, "value": value, "scope": deepcopy(scope), "provenance": raw["provenance"],
                "revision": previous["revision"] + 1 if previous else 1,
                "created_at": previous["created_at"] if previous else utc_now(), "updated_at": utc_now(),
                "expires_at": raw.get("expires_at"), "private_note": raw.get("private_note"), "owner_confirmed": True}

    def affected_goals(self, state, memories):
        affected = set()
        for goal_id, goal in state["goals"].items():
            for memory in memories:
                if memory["scope"].get("goal_id") not in (None, goal_id):
                    continue
                if memory["type"] in {"weekly_capacity", "request_category"} or any(self.memory_applies(memory, task) for task in goal["tasks"]):
                    affected.add(goal_id)
        return affected

    def invalidate(self, db, state, goal_ids, commitment_ids=None):
        """Fence affected future work; never globally compensate calendar effects."""
        for key, approval in list(state["approvals"].items()):
            agreement = state["reviewed_agreements"].get(key)
            if agreement and agreement["goal"]["goal_id"] in goal_ids:
                if commitment_ids is None:
                    state["approvals"].pop(key, None)
        for row in db.execute("SELECT * FROM living_reservations WHERE status='ACTIVE'").fetchall():
            agreement = json.loads(row["payload"])["agreement"]
            if agreement["goal"]["goal_id"] not in goal_ids:
                continue
            if commitment_ids is None:
                db.execute("UPDATE living_reservations SET status='CANCELLED' WHERE reservation_id=?", (row["reservation_id"],))
            for mutation in agreement["delta"]["calendar_mutations"]:
                if commitment_ids is None or mutation["commitment_id"] in commitment_ids:
                    db.execute("UPDATE living_mutations SET status='CANCELLED',error='Owner authority changed before transmission.' WHERE mutation_id=? AND transmitted_at IS NULL", (mutation["mutation_id"],))
        if commitment_ids is None:
            for goal_id in goal_ids:
                state["offers"].pop(goal_id, None)
                state["goal_constraint_revisions"][goal_id] = state["constraint_revision"]

    def save_memory(self, expected_revision, raw):
        with self.lock, self.vault.transaction() as db:
            state = self.read(db)
            self.check_revision(state, expected_revision)
            previous = next((m for m in state["memories"] if m["memory_id"] == raw.get("memory_id")), None)
            memory = self._memory(raw, previous)
            state["memories"] = [m for m in state["memories"] if m["memory_id"] != memory["memory_id"]] + [memory]
            state["constraint_revision"] += 1
            state["consent_revision"] += 1
            self.invalidate(db, state, self.affected_goals(state, [memory] + ([previous] if previous else [])))
            self.bump(state)
            self.write(db, state)
        return {"memory": memory, "revision": state["revision"], "constraint_revision": state["constraint_revision"]}

    def delete_memory(self, memory_id, expected_revision):
        with self.lock, self.vault.transaction() as db:
            state = self.read(db)
            self.check_revision(state, expected_revision)
            memory = next((m for m in state["memories"] if m["memory_id"] == memory_id), None)
            require(memory is not None, "Memory not found.", 404)
            affected = self.affected_goals(state, [memory])
            state["memories"] = [m for m in state["memories"] if m["memory_id"] != memory_id]
            # The receipt deliberately retains no content, type, provenance or hash.
            receipt = {"memory_id": memory_id, "deleted_at": utc_now(), "revision": memory["revision"] + 1}
            state["deletions"].append(receipt)
            state["constraint_revision"] += 1
            state["consent_revision"] += 1
            self.invalidate(db, state, affected)
            self.bump(state)
            self.write(db, state)
        return {"deleted": receipt, "revision": state["revision"]}

    def set_policy(self, expected_revision, enabled, expires_at):
        require(type(enabled) is bool, "Policy choice must be explicit.", 422)
        if enabled:
            try:
                require(bool(expires_at) and future(expires_at), "An enabled standing policy needs a future expiry.", 422)
            except (ValueError, TypeError) as exc:
                raise HTTPException(422, "Invalid policy expiry.") from exc
        with self.lock, self.vault.transaction() as db:
            state = self.read(db)
            self.check_revision(state, expected_revision)
            state["policy"] = {"enabled": enabled, "revision": state["policy"]["revision"] + 1, "expires_at": expires_at if enabled else None,
                               "provenance": "Explicit owner-reviewed standing policy", "updated_at": utc_now()}
            # Revoking a policy cancels only attestations that used that policy.
            for key, message in list(state["approvals"].items()):
                if message["body"]["payload"]["basis"] == "standing-policy":
                    state["approvals"].pop(key)
                    agreement = state["reviewed_agreements"][key]
                    db.execute("UPDATE living_reservations SET status='CANCELLED' WHERE agreement_id=? AND revision=?", (agreement["agreement_id"], agreement["revision"]))
                    db.execute("UPDATE living_mutations SET status='CANCELLED',error='Standing policy changed before transmission.' WHERE agreement_id=? AND revision=? AND transmitted_at IS NULL", (agreement["agreement_id"], agreement["revision"]))
            self.bump(state)
            self.write(db, state)
        return {"policy": state["policy"], "revision": state["revision"]}

    def preview(self, goal_id, provider="none", state=None):
        require(provider in PROVIDERS, "Choose an exact inference recipient.", 422)
        state = state or self.read()
        goal = state["goals"].get(goal_id)
        require(goal is not None, "Review a confirmed goal before releasing an offer.")
        memories = self.active_memories(state, goal)
        excluded = set(state["excluded_tasks"].get(goal_id, []))
        choices = state.get("task_choices", {}).get(goal_id)
        configured_capabilities = self.config.get("owner_profile", {}).get("capabilities")
        configured_requests = self.config.get("owner_profile", {}).get("request_categories", configured_capabilities)
        refused = {q["task_id"] for q in state["requests"] if q["goal_id"] == goal_id and f"{goal_id}:{q['task_id']}" in state["refusals"]}
        tasks = [task for task in goal["tasks"] if (choices is None or task["task_id"] in choices) and (configured_capabilities is None or task["capability"] in configured_capabilities) and task["task_id"] not in excluded | refused and not any(m["type"] == "excluded_capability" and self.memory_applies(m, task) for m in memories)]
        conditions = []
        for task in tasks:
            for memory in memories:
                if memory["type"] == "require_receiver" and self.memory_applies(memory, task):
                    value = memory["value"]
                    conditions.append({"task_id": task["task_id"], "receiver_id": value["receiver_id"], "receiver_task_id": value["receiver_task_id"], "by": value["by"]})
        windows = []
        for task in tasks:
            window = {"date": task["date"], "start": task["earliest"], "end": task["latest"]}
            for memory in memories:
                if memory["type"] == "handoff_deadline" and self.memory_applies(memory, task):
                    window["end"] = min(window["end"], memory["value"]["by"])
            if window not in windows:
                windows.append(window)
        previous = state["offers"].get(goal_id, {}).get(provider)
        previous_payload = previous["body"]["payload"] if previous else None
        # Invalidation removes current grants, but never rewinds their sequence.
        # Historical signatures supply only the counter, never current authority.
        goal_messages = [*state.get("release_history", []), *state["offers"].get(goal_id, {}).values()]
        revision = max((m["body"]["payload"]["offer_revision"] for m in goal_messages if m["body"]["payload"]["goal_id"] == goal_id), default=0) + 1
        expiry = expires_in(self.config.get("living_ttl", 14400))
        # Preview/release uses a deterministic persisted clock anchor, then checks
        # its exact digest. A rerender cannot silently alter the reviewed payload.
        preview_key = f"{goal_id}:{provider}"
        cache = getattr(self, "_previews", {})
        cached = cache.get(preview_key)
        signature = digest({"revision": state["revision"], "goal": goal, "provider": provider})
        if cached and cached["signature"] == signature and future(cached["release"]["expires_at"]):
            payload = deepcopy(cached["release"])
        else:
            payload = {"goal_id": goal_id, "goal_revision": goal["revision"], "goal_digest": goal_digest(goal),
                       "offer_id": f"offer-{self.owner_id}-{uuid.uuid4()}", "offer_revision": revision,
                       "owner_id": self.owner_id, "constraint_revision": self.constraint_revision(state, goal_id),
                       "task_ids": [task["task_id"] for task in tasks], "windows": windows, "conditions": conditions,
                       "recipients": {"humans": sorted(goal["participants"]), "broker": BROKER, "inference": [] if provider == "none" else [provider]},
                       "request_categories": sorted(set(configured_requests if configured_requests is not None else {"preparation", "driving", "accompaniment", "handoff", "meal", "visit"}) - {m["value"]["category"] for m in memories if m["type"] == "request_category" and not m["value"]["allowed"]}),
                       "expires_at": expiry}
            if previous_payload:
                comparable = lambda p: {k: v for k, v in p.items() if k not in {"offer_id", "offer_revision", "expires_at"}}
                if comparable(previous_payload) == comparable(payload):
                    try:
                        self.public_message(previous, "LivingRelease")
                        payload = deepcopy(previous_payload)
                    except HTTPException:
                        pass
            payload = normalized(validate_release, payload)
            cache[preview_key] = {"signature": signature, "release": deepcopy(payload)}
            self._previews = cache
        return {"release": payload, "preview_digest": digest(payload),
                "private_explanation": [{"memory_id": m["memory_id"], "type": m["type"], "provenance": m["provenance"], "revision": m["revision"]} for m in memories]}

    def release(self, goal_id, provider, preview_digest, expected_revision, sample_setup_digest=None):
        with self.lock, self.vault.transaction() as db:
            state = self.read(db)
            self.check_revision(state, expected_revision)
            preview = self.preview(goal_id, provider, state)
            require(preview_digest == preview["preview_digest"], "The reviewed release changed. Review its exact recipients and conditions again.")
            previous = state["offers"].get(goal_id, {}).get(provider)
            if previous and previous["body"]["payload"] == preview["release"]:
                message = previous
            else:
                state["consent_revision"] += 1
                message = self.signed("LivingRelease", preview["release"], state, preview["release"]["recipients"]["inference"])
                state["offers"].setdefault(goal_id, {})[provider] = message
                state.setdefault("release_history", []).append(message)
                self._queue(db, "/v2/releases", message)
                self.bump(state)
                self.write(db, state)
            if sample_setup_digest is not None:
                record = next((r for r in state["sample_setups"] if r["goal_id"] == goal_id and r.get("goal_digest") == sample_setup_digest), None)
                require(record is not None and record.get("provider") == provider, "The exact initial sample disclosure choice is unavailable.")
                record["setup_release"] = deepcopy(message)
                self.write(db, state)
        self.flush()
        return {"release": message, "revision": state["revision"], "consent_revision": state["consent_revision"]}

    @staticmethod
    def agreement_key(agreement):
        return f"{agreement['agreement_id']}:{agreement['revision']}"

    def current(self):
        return self.engine.broker("GET", "/v2/current")

    def fetch_agreement(self, agreement_id, revision):
        wrapper = self.engine.broker("GET", f"/v2/agreements/{agreement_id}/{revision}")
        raw = wrapper.get("agreement", wrapper)
        require(isinstance(raw, dict) and raw.get("agreement_id") == agreement_id and raw.get("revision") == revision, "The exact agreement revision is unavailable.")
        return raw

    def own_mutations(self, agreement):
        return [m for m in agreement["delta"]["calendar_mutations"] if m.get("owner_id") == self.owner_id]

    def check_agreement(self, raw, state, *, private=True, retained_authority=False):
        agreement = normalized(validate_agreement, raw)
        self.key_active()
        goal = agreement["goal"]
        require(state["goals"].get(goal["goal_id"]) == goal and agreement["goal_digest"] == goal_digest(goal), "The agreement differs from the locally reviewed goal.")
        require(future(agreement["expires_at"]), "Agreement expired.")
        tasks = {t["task_id"]: t for t in goal["tasks"]}
        commits = agreement["commitments"]
        by_task = {c["task_id"]: c for c in commits}
        require(len(by_task) == len(commits) and all(t["task_id"] in by_task for t in goal["tasks"] if t["required"]), "Complete required coverage is required for consent.")
        own = [c for c in commits if c["owner_id"] == self.owner_id]
        mutations = self.own_mutations(agreement)
        require(bool(own) or bool(mutations), "No commitment or scoped calendar effect belongs to this owner.")
        key = self.agreement_key(agreement)
        same_revision = state["reviewed_agreements"].get(key)
        require(same_revision is None or same_revision == agreement, "This owner already reviewed another document at that exact revision.")
        previous = state["reviewed_agreements"].get(f"{agreement['agreement_id']}:{agreement['base_revision']}")
        if agreement["base_revision"]:
            require(previous is not None, "The amendment has no locally reviewed exact base revision.")
        # Independently re-evaluate intervals, subject, graph and directional routes.
        routes = {(r["from_location"], r["to_location"]): r["duration"] for r in goal["routes"]}
        for commitment in commits:
            task = tasks[commitment["task_id"]]
            require(commitment["owner_id"] in goal["participants"] and commitment["date"] == task["date"] and commitment["timezone"] == goal["timezone"], "Commitment identity, date or timezone changed.")
            require(commitment["capability"] == task["capability"] and commitment["subject"] == task["subject"] and commitment["start_location"] == task["start_location"] and commitment["end_location"] == task["end_location"], "Commitment no longer matches the reviewed task.")
            require(type(commitment["start"]) is int and type(commitment["end"]) is int and commitment["end"] - commitment["start"] == task["duration"] and commitment["start"] >= task["earliest"] and commitment["end"] <= task["latest"], "Commitment violates the reviewed interval.")
            for predecessor in task["predecessors"]:
                prior = by_task.get(predecessor)
                require(prior is not None and (prior["date"], prior["end"]) <= (commitment["date"], commitment["start"]), "Required predecessor is absent or too late.")
                if prior["date"] == commitment["date"]:
                    travel = 0 if prior["end_location"] == commitment["start_location"] else routes.get((prior["end_location"], commitment["start_location"]))
                    require(travel is not None and prior["end"] + travel <= commitment["start"], "Reviewed transfer route is unknown or unreachable.")
        for owner in goal["participants"]:
            ordered = sorted((c for c in commits if c["owner_id"] == owner), key=lambda c: (c["date"], c["start"]))
            for first, second in zip(ordered, ordered[1:]):
                travel = 0 if first["end_location"] == second["start_location"] else routes.get((first["end_location"], second["start_location"]))
                elapsed = (datetime.fromisoformat(second["date"]) - datetime.fromisoformat(first["date"])).days * 1440 + second["start"] - first["end"]
                require(travel is not None and travel <= elapsed, "Owner capacity or confirmed travel time is violated.")
        subjects = {(c["subject"], c["date"]) for c in commits}
        for subject, day in subjects:
            sequence = sorted((c for c in commits if c["subject"] == subject and c["date"] == day), key=lambda c: (c["start"], c["end"]))
            for first, second in zip(sequence, sequence[1:]):
                require(first["end"] <= second["start"] and first["end_location"] == second["start_location"], "The care recipient overlaps responsibilities or lacks an explicit reviewed journey.")
        if not private:
            return agreement
        memories = self.active_memories(state, goal)
        releases = state["offers"].get(goal["goal_id"], {})
        valid_releases = []
        for message in releases.values():
            try:
                self.public_message(message, "LivingRelease")
                payload = message["body"]["payload"]
                if payload["constraint_revision"] == self.constraint_revision(state, goal["goal_id"]) and payload["goal_digest"] == goal_digest(goal) and future(payload["expires_at"]):
                    valid_releases.append(payload)
            except HTTPException:
                continue
        private_calendar = self.vault.read().get("private_calendar", [])
        try:
            current_calendar = self.calendar.list()
        except Exception as exc:
            raise HTTPException(503, "The owner's calendar cannot currently be checked; no new mutation is authorized.") from exc
        for commitment in own:
            if retained_authority and commitment["commitment_id"] in state["withdrawn"].get(agreement["agreement_id"], []):
                continue
            require(commitment["commitment_id"] not in state["withdrawn"].get(agreement["agreement_id"], []), "This scoped commitment was withdrawn.")
            matching = [p for p in valid_releases if p["offer_id"] == commitment["offer_id"] and p["offer_revision"] == commitment["offer_revision"]]
            require(bool(matching), "Commitment has no exact current per-goal release.")
            offer = matching[0]
            require(commitment["task_id"] in offer["task_ids"] and any(w["date"] == commitment["date"] and w["start"] <= commitment["start"] and w["end"] >= commitment["end"] for w in offer["windows"]), "Commitment exceeds the reviewed release.")
            capabilities = self.config.get("owner_profile", {}).get("capabilities")
            require(capabilities is None or commitment["capability"] in capabilities, "Commitment exceeds this owner's configured capabilities.")
            require(not any(m["type"] == "excluded_capability" and self.memory_applies(m, commitment) for m in memories), "A private capability constraint prevents this commitment.")
            require(not any(intersects(commitment, source) for source in private_calendar), "A private calendar conflict prevents this commitment.")
            require(not any(intersects(commitment, event) and event.get("commitment_id") != commitment["commitment_id"] for event in current_calendar), "An existing owner calendar effect conflicts with this commitment.")
            for condition in offer["conditions"]:
                if condition["task_id"] == commitment["task_id"]:
                    receiver = by_task.get(condition["receiver_task_id"])
                    require(receiver is not None and receiver["owner_id"] == condition["receiver_id"] and receiver["date"] == commitment["date"] and receiver["end"] <= condition["by"], "The reviewed receiver condition is not satisfied.")
                    require(condition in commitment["conditions"], "The exact reviewed condition must remain public and bound.")
            for memory in memories:
                if memory["type"] == "handoff_deadline" and self.memory_applies(memory, commitment):
                    require(commitment["end"] <= memory["value"]["by"], "A private handoff deadline prevents this commitment.")
        for memory in memories:
            if memory["type"] == "weekly_capacity":
                totals = {}
                for commitment in own:
                    if retained_authority and commitment["commitment_id"] in state["withdrawn"].get(agreement["agreement_id"], []):
                        continue
                    week = datetime.fromisoformat(commitment["date"]).isocalendar()[:2]
                    totals[week] = totals.get(week, 0) + commitment["end"] - commitment["start"]
                # Global limits include other real effects in this owner's store.
                # The amended agreement is replaced as a whole, so it is counted
                # exactly once. Goal-local limits apply only to their named goal.
                if not memory["scope"].get("goal_id"):
                    counted = {c["commitment_id"] for c in own}
                    # Editing/deleting a calendar event is not a withdrawal or a
                    # human completion. A pending shorter revision cannot free
                    # prior responsibility: retain its largest authorized load
                    # per stable commitment/week until explicitly withdrawn.
                    other_loads = {}
                    for reviewed in state["reviewed_agreements"].values():
                        if reviewed["agreement_id"] == agreement["agreement_id"]:
                            continue
                        withdrawn_ids = set(state["withdrawn"].get(reviewed["agreement_id"], []))
                        for other in reviewed["commitments"]:
                            if other["owner_id"] != self.owner_id or other["commitment_id"] in withdrawn_ids:
                                continue
                            week = datetime.fromisoformat(other["date"]).isocalendar()[:2]
                            key = (other["commitment_id"], week)
                            other_loads[key] = max(other_loads.get(key, 0), other["end"] - other["start"])
                    for (cid, week), minutes in other_loads.items():
                        if week in totals:
                            totals[week] += minutes
                            counted.add(cid)
                    for event in current_calendar:
                        if event.get("creation", {}).get("agreement_id") == agreement["agreement_id"]:
                            continue
                        baseline = self.known_effect(event["event_id"])
                        public_event = baseline["intent"] if baseline else event
                        if public_event["commitment_id"] in counted:
                            continue
                        week = datetime.fromisoformat(public_event["date"]).isocalendar()[:2]
                        if week in totals:
                            totals[week] += public_event["end"] - public_event["start"]
                            counted.add(public_event["commitment_id"])
                    with self.vault.connect() as conn:
                        reservations = conn.execute("SELECT * FROM living_reservations WHERE status='ACTIVE' AND agreement_id!=?", (agreement["agreement_id"],)).fetchall()
                    for reservation in reservations:
                        if not future(reservation["lease_expires_at"]):
                            continue
                        reserved_agreement = json.loads(reservation["payload"])["agreement"]
                        withdrawn_ids = set(state["withdrawn"].get(reserved_agreement["agreement_id"], []))
                        for other in reserved_agreement["commitments"]:
                            if other["owner_id"] != self.owner_id or other["commitment_id"] in counted | withdrawn_ids:
                                continue
                            week = datetime.fromisoformat(other["date"]).isocalendar()[:2]
                            if week in totals:
                                totals[week] += other["end"] - other["start"]
                                counted.add(other["commitment_id"])
                require(all(minutes <= memory["value"]["minutes"] for minutes in totals.values()), "A private weekly capacity constraint prevents this agreement.")
        # Calendar intent data is exact public content. Historical creation is
        # immutable, even when its interval changes under a fresh review.
        for mutation in mutations:
            intent = mutation.get("intent")
            if mutation["kind"] != "delete":
                commitment = next((c for c in own if c["commitment_id"] == mutation["commitment_id"]), None)
                require(commitment is not None and intent is not None, "Mutation has no owner commitment.")
                for key in ("commitment_id", "owner_id", "task_id", "date", "timezone", "start", "end", "label"):
                    require(intent.get(key) == commitment.get(key), "Calendar intent differs from the reviewed commitment.")
                require(intent["location"] == {"start": commitment["start_location"], "end": commitment["end_location"]}, "Calendar intent locations changed.")
            known = self.known_effect(mutation["event_id"])
            if mutation["kind"] in {"update", "delete"}:
                require(known is not None and mutation.get("expected_etag") == known["etag"], "Calendar mutation must bind the owner's last observed version.")
                require(all(known["intent"][k] == mutation[k] for k in ("owner_id", "commitment_id", "action_id", "event_id")), "A calendar mutation cannot substitute another commitment's event.")
                if intent:
                    require(intent["creation"] == known["intent"]["creation"], "Calendar creation provenance must remain unchanged.")
            if mutation["kind"] == "delete":
                require(mutation["commitment_id"] in agreement["delta"]["withdrawn"] and mutation["commitment_id"] not in {c["commitment_id"] for c in commits}, "Delete is outside the exact removed commitment scope.")
                require(previous is not None and any(c["commitment_id"] == mutation["commitment_id"] and c["owner_id"] == self.owner_id for c in previous["commitments"]), "Delete has no prior owner commitment.")
            elif mutation["kind"] == "insert":
                require(mutation["commitment_id"] in agreement["delta"]["new"], "Insert is outside the exact new commitment scope.")
            else:
                require(mutation["commitment_id"] in agreement["delta"]["changed"], "Update is outside the exact changed commitment scope.")
        for commitment in own:
            intent = next(i for i in agreement["intents"] if i["commitment_id"] == commitment["commitment_id"])
            actual_mutations = [m for m in mutations if m["commitment_id"] == commitment["commitment_id"]]
            known = self.known_effect(intent["event_id"])
            if known:
                require(intent["creation"] == known["intent"]["creation"], "Calendar creation provenance must remain immutable.")
                needs_write = self.calendar.intended(intent) != self.calendar.intended(known["intent"])
                require(not needs_write or len(actual_mutations) == 1 and actual_mutations[0]["kind"] == "update", "Changed calendar content has no exact conditional update.")
            else:
                require(len(actual_mutations) == 1 and actual_mutations[0]["kind"] == "insert", "A new owner effect needs exactly one authorized insert.")
        return agreement

    def known_effect(self, event_id):
        with self.vault.connect() as db:
            rows = db.execute("SELECT * FROM living_mutations WHERE event_id=? AND etag IS NOT NULL ORDER BY rowid DESC", (event_id,)).fetchall()
        for row in rows:
            mutation = json.loads(row["payload"])
            if mutation.get("intent"):
                # The old ETag is persisted before a conditional update sends.
                # Its proposed content becomes a baseline only after readback.
                if mutation["kind"] == "update" and row["etag"] == mutation.get("expected_etag") and row["status"] != "VERIFIED" and row["verified_at"] is None:
                    continue
                return {"etag": row["etag"], "intent": mutation["intent"], "mutation": mutation}
        return None

    def _approve(self, raw, expected_digest, basis="exact-review", sample_bootstrap=False):
        with self.lock, self.vault.transaction() as db:
            state = self.read(db)
            bootstrap_record = self.sample_approval_record(raw, state) if sample_bootstrap else None
            agreement = self.check_agreement(raw, state)
            require(expected_digest == agreement_digest(agreement), "Review the exact agreement digest before approving.")
            key = self.agreement_key(agreement)
            previous = state["approvals"].get(key)
            if previous:
                self.authenticate(agreement, previous, state)
                message = previous
                if bootstrap_record is not None and not bootstrap_record.get("approval_digest"):
                    bootstrap_record["approval_digest"] = expected_digest
                    bootstrap_record["approved_at"] = utc_now()
                    bootstrap_record["approval"] = deepcopy(message)
                    self.write(db, state)
            else:
                state["consent_revision"] += 1
                payload = consent_payload(agreement, self.owner_id, state["consent_revision"], self.constraint_revision(state, agreement["goal"]["goal_id"]), basis=basis,
                                          policy_revision=state["policy"]["revision"] if basis == "standing-policy" else None)
                payload = normalized(validate_consent, payload)
                message = self.signed("LivingConsent", payload, state, agreement["goal"]["participants"])
                state["approvals"][key] = message
                state["reviewed_agreements"][key] = agreement
                self._queue(db, "/v2/consents", message)
                self.bump(state)
                if bootstrap_record is not None:
                    bootstrap_record["approval_digest"] = expected_digest
                    bootstrap_record["approved_at"] = utc_now()
                    bootstrap_record["approval"] = deepcopy(message)
                self.write(db, state)
        self.flush()
        return {"consent": message, "revision": state["revision"]}

    def approve(self, agreement_id, revision, expected_digest):
        raw = self.fetch_agreement(agreement_id, revision)
        return self._approve(raw, expected_digest)

    def authenticate(self, agreement, consent, state):
        # Do this before any private constraint/calendar lookup. The coordinator
        # must possess an exact approval already recorded by this owner.
        try:
            body = self.public_message(consent, "LivingConsent")
            key = self.agreement_key(agreement)
            require(state["approvals"].get(key) == consent, "Invalid or expired owner consent.")
            payload = body["payload"]
            goal_id = agreement["goal"]["goal_id"]
            expected = consent_payload(agreement, self.owner_id, payload["consent_revision"], self.constraint_revision(state, goal_id), basis=payload["basis"], policy_revision=payload["policy_revision"])
            require(payload == expected and body["consent_revision"] == payload["consent_revision"] and future(payload["execution_not_after"]), "Invalid or expired owner consent.")
            if payload["basis"] == "standing-policy":
                require(state["policy"]["enabled"] and state["policy"]["revision"] == payload["policy_revision"] and future(state["policy"]["expires_at"]), "Invalid or expired owner consent.")
            return body
        except (HTTPException, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(409, "Invalid or expired owner consent.") from exc

    def attest(self, raw):
        # A valid public shape alone cannot authorize a standing attestation.
        agreement = normalized(validate_agreement, raw)
        with self.lock:
            state = self.read()
            policy = state["policy"]
            if not policy["enabled"] or not policy.get("expires_at") or not future(policy["expires_at"]):
                return {"status": "needs_review"}
            previous = next((a for a in state["reviewed_agreements"].values() if a["agreement_id"] == agreement["agreement_id"] and a["revision"] == agreement["base_revision"]), None)
            if previous is None or self.agreement_key(previous) not in state["approvals"]:
                return {"status": "needs_review"}
            own = lambda a: {c["commitment_id"]: (commitment_digest(c), dependency_digest(c)) for c in a["commitments"] if c["owner_id"] == self.owner_id}
            withdrawn = set(state["withdrawn"].get(agreement["agreement_id"], []))
            previous_own = {cid: content for cid, content in own(previous).items() if cid not in withdrawn}
            mutations = self.own_mutations(agreement)
            allowed_deletions = all(m["kind"] == "delete" and m["commitment_id"] in withdrawn for m in mutations)
            # This binds direct handoff counterparts even when own event is retained.
            if previous_own != own(agreement) or not allowed_deletions:
                return {"status": "needs_review"}
            if previous["goal_digest"] != agreement["goal_digest"]:
                return {"status": "needs_review"}
            releases = {m["body"]["payload"]["offer_id"]: m["body"]["payload"] for m in [*state.get("release_history", []), *state["offers"].get(agreement["goal"]["goal_id"], {}).values()]}
            prior_by_id = {c["commitment_id"]: c for c in previous["commitments"]}
            for commitment in agreement["commitments"]:
                if commitment["owner_id"] != self.owner_id:
                    continue
                prior = prior_by_id[commitment["commitment_id"]]
                before = releases.get(prior["offer_id"])
                after = releases.get(commitment["offer_id"])
                if before is None or after is None or before["recipients"] != after["recipients"]:
                    return {"status": "needs_review"}
            try:
                self.check_agreement(agreement, state)
            except HTTPException:
                return {"status": "needs_review"}
            # Keep eligibility and fresh signing under the same owner lock.
            # Policy or memory revocation cannot slip between those decisions.
            result = self._approve(agreement, agreement_digest(agreement), basis="standing-policy")
            return {"status": "attested", **result}

    def prepare(self, raw, consent):
        with self.lock, self.vault.transaction() as db:
            state = self.read(db)
            body = self.authenticate(raw, consent, state)
            agreement = self.check_agreement(raw, state)
            require(agreement["revision"] >= state.get("prepared_revisions", {}).get(agreement["agreement_id"], 0), "A newer agreement revision already owns the local execution fence.")
            own = self.own_mutations(agreement)
            own_commitments = [c for c in agreement["commitments"] if c["owner_id"] == self.owner_id]
            for other in db.execute("SELECT * FROM living_reservations WHERE status='ACTIVE' AND agreement_id!=?", (agreement["agreement_id"],)).fetchall():
                if not future(other["lease_expires_at"]):
                    continue
                other_agreement = json.loads(other["payload"])["agreement"]
                other_commitments = [c for c in other_agreement["commitments"] if c["owner_id"] == self.owner_id]
                require(not any(intersects(a, b) for a in own_commitments for b in other_commitments), "Another agreement already reserves this owner's time.")
            # Exact authenticated authority precedes private adapter preconditions.
            for mutation in own:
                current = self.calendar.get(mutation["event_id"])
                if mutation["kind"] == "insert":
                    require(current is None or self.matches(current, mutation["intent"]), "Calendar precondition conflict.")
                elif current is not None:
                    require(current.get("etag") == mutation["expected_etag"] and not current.get("user_edited"), "Calendar precondition conflict.")
            used = db.execute("SELECT * FROM living_nonces WHERE nonce=?", (body["nonce"],)).fetchone()
            require(used is None or (used["message_id"] == body["message_id"] and used["agreement_id"] == agreement["agreement_id"] and used["revision"] == agreement["revision"]), "Consent nonce replayed for another agreement.")
            old = db.execute("SELECT * FROM living_reservations WHERE agreement_id=? AND revision=?", (agreement["agreement_id"], agreement["revision"])).fetchone()
            if old and old["status"] == "ACTIVE" and future(old["lease_expires_at"]):
                require(json.loads(old["payload"])["agreement"] == agreement, "An immutable agreement changed.")
                return {k: old[k] for k in ("reservation_id", "fence", "lease_expires_at")}
            # Fences supersede earlier reservations for the same agreement only.
            db.execute("UPDATE living_reservations SET status='SUPERSEDED' WHERE agreement_id=? AND status='ACTIVE'", (agreement["agreement_id"],))
            state["fence"] += 1
            state.setdefault("prepared_revisions", {})[agreement["agreement_id"]] = agreement["revision"]
            reservation = "living-reservation-" + secrets.token_urlsafe(18)
            lease = min(expires_in(300), agreement["expires_at"], body["payload"]["execution_not_after"], body["expires_at"])
            db.execute("INSERT OR IGNORE INTO living_nonces VALUES(?,?,?,?)", (body["nonce"], body["message_id"], agreement["agreement_id"], agreement["revision"]))
            db.execute("DELETE FROM living_reservations WHERE agreement_id=? AND revision=?", (agreement["agreement_id"], agreement["revision"]))
            db.execute("INSERT INTO living_reservations VALUES(?,?,?,?,?,?,?)", (reservation, agreement["agreement_id"], agreement["revision"], state["fence"], lease, json.dumps({"agreement": agreement, "consent": consent}), "ACTIVE"))
            self.write(db, state)
            return {"reservation_id": reservation, "fence": state["fence"], "lease_expires_at": lease}

    def matches(self, actual, intent):
        expected = self.calendar.intended(intent)
        return actual is not None and not actual.get("user_edited") and {k: actual.get(k) for k in expected} == expected

    def active(self, db, request):
        reservation = db.execute("SELECT * FROM living_reservations WHERE reservation_id=?", (request.get("reservation_id"),)).fetchone()
        require(reservation is not None and reservation["agreement_id"] == request.get("agreement_id") and reservation["revision"] == request.get("revision") and reservation["fence"] == request.get("fence"), "Stale or unknown living dispatch fence.")
        require(reservation["status"] == "ACTIVE" and future(reservation["lease_expires_at"]), "Living reservation expired or was cancelled.")
        saved = json.loads(reservation["payload"])
        state = self.read(db)
        require(state.get("prepared_revisions", {}).get(request["agreement_id"], request["revision"]) == request["revision"], "A newer revision fenced this dispatch.")
        self.authenticate(saved["agreement"], saved["consent"], state)
        agreement = self.check_agreement(saved["agreement"], state, retained_authority=True)
        mutation = next((m for m in self.own_mutations(agreement) if m["mutation_id"] == request.get("mutation_id")), None)
        require(mutation is not None, "The requested mutation is outside this owner's consent.")
        require(mutation["kind"] == "delete" or mutation["commitment_id"] not in state["withdrawn"].get(agreement["agreement_id"], []), "The commitment was withdrawn before transmission.")
        return reservation, mutation

    def receipt(self, row, actual=None):
        mutation = json.loads(row["payload"])
        result = {"mutation_id": row["mutation_id"], "commitment_id": mutation["commitment_id"], "action_id": mutation["action_id"],
                  "event_id": row["event_id"], "status": row["status"], "etag": row["etag"], "verified_at": row["verified_at"],
                  "intent_id": "intent-" + digest({"mutation_id": row["mutation_id"], "fence": row["fence"]})[:32],
                  "fence": row["fence"], "transmitted_at": row["transmitted_at"]}
        if row["error"]:
            result["error"] = row["error"]
        if row["status"] == "NEEDS_ATTENTION" and actual:
            # Manual rescheduling/location edits are private. Report only the
            # originally authorized public identities, never edited content.
            result["remaining_effect"] = {k: mutation[k] for k in ("event_id", "action_id", "commitment_id")}
        return result

    def observe(self, row):
        mutation = json.loads(row["payload"])
        try:
            actual = self.calendar.get(row["event_id"])
        except Exception:
            status, etag, verified, error, actual = "UNCONFIRMED", row["etag"], None, "Calendar observation is unavailable.", None
        else:
            etag, verified, error = row["etag"], None, row["error"]
            if mutation["kind"] == "delete" and actual is None:
                status, error, verified = "CANCELLED", None, utc_now()
            elif mutation["kind"] != "delete" and self.matches(actual, mutation["intent"]):
                if row["status"] == "CANCELLED":
                    status, error = "NEEDS_ATTENTION", "An effect remains after cancellation; owner review is required."
                else:
                    status, etag, verified, error = "VERIFIED", actual["etag"], utc_now(), None
            elif actual is not None:
                # A not-yet-sent update should see the previous exact app version.
                if row["transmitted_at"] is None and mutation["kind"] in {"update", "delete"} and actual.get("etag") == mutation.get("expected_etag") and not actual.get("user_edited"):
                    status = row["status"]
                else:
                    status, error = "NEEDS_ATTENTION", "Calendar content changed; the observed entry was preserved."
            elif row["status"] == "VERIFIED":
                status, error = "NEEDS_ATTENTION", "A previously verified calendar effect is missing."
            elif row["transmitted_at"]:
                status, error = "AMBIGUOUS", "No effect observed after transmission; fresh authority is required before retry."
            else:
                status = "CANCELLED" if row["status"] == "CANCELLED" else "PAUSED"
        with self.vault.transaction() as db:
            db.execute("UPDATE living_mutations SET status=?,etag=?,verified_at=?,error=? WHERE mutation_id=?", (status, etag, verified, error, row["mutation_id"]))
            updated = db.execute("SELECT * FROM living_mutations WHERE mutation_id=?", (row["mutation_id"],)).fetchone()
        return self.receipt(updated, actual)

    def dispatch(self, request, reconcile=False):
        with self.lock:
            with self.vault.connect() as db:
                reservation = db.execute("SELECT * FROM living_reservations WHERE reservation_id=?", (request.get("reservation_id"),)).fetchone()
                require(reservation is not None and reservation["agreement_id"] == request.get("agreement_id") and reservation["revision"] == request.get("revision") and reservation["fence"] == request.get("fence"), "Stale or unknown living dispatch fence.")
                previous = db.execute("SELECT * FROM living_mutations WHERE mutation_id=?", (request.get("mutation_id"),)).fetchone()
            if previous:
                require(previous["agreement_id"] == request["agreement_id"] and previous["revision"] == request["revision"], "Mutation belongs to another agreement revision.")
                saved = json.loads(reservation["payload"])["agreement"]
                selected = next((m for m in self.own_mutations(saved) if m["mutation_id"] == request["mutation_id"]), None)
                require(selected == json.loads(previous["payload"]), "Mutation content differs from the durable authority.")
                observed = self.observe(previous)
                if reconcile or previous["transmitted_at"] or observed["status"] in {"VERIFIED", "CANCELLED", "NEEDS_ATTENTION", "UNCONFIRMED"}:
                    return observed
            elif reconcile:
                raise HTTPException(404, "No durable mutation intent exists to reconcile.")
            with self.vault.transaction() as db:
                _, mutation = self.active(db, request)
                if previous is None:
                    db.execute("INSERT INTO living_mutations(mutation_id,agreement_id,revision,reservation_id,fence,payload,status,event_id,etag,authorized_at) VALUES(?,?,?,?,?,?,'INTENT',?,?,?)", (mutation["mutation_id"], request["agreement_id"], request["revision"], request["reservation_id"], request["fence"], json.dumps(mutation), mutation["event_id"], mutation.get("expected_etag"), utc_now()))
                else:
                    db.execute("UPDATE living_mutations SET status='INTENT',reservation_id=?,fence=?,error=NULL WHERE mutation_id=?", (request["reservation_id"], request["fence"], mutation["mutation_id"]))
                mode = self.vault.read(db)["fault"]
                if mode == "pause_before_send":
                    db.execute("UPDATE living_mutations SET status='PAUSED',error='Paused after durable authorization and before calendar transmission.' WHERE mutation_id=?", (mutation["mutation_id"],))
            if mode == "pause_before_send":
                with self.vault.connect() as db:
                    return self.receipt(db.execute("SELECT * FROM living_mutations WHERE mutation_id=?", (mutation["mutation_id"],)).fetchone())
            # This lock is shared with owner withdrawal/memory/policy writes. The
            # final persisted fence/authority check immediately precedes transport.
            with self.vault.transaction() as db:
                self.active(db, request)
                current = db.execute("SELECT * FROM living_mutations WHERE mutation_id=?", (mutation["mutation_id"],)).fetchone()
                require(current["status"] == "INTENT" and current["fence"] == request["fence"], "The durable transmission intent was cancelled or fenced.")
                if mode == "fail_before_write":
                    db.execute("UPDATE living_mutations SET status='FAILED',error='Adapter failed before transmission.' WHERE mutation_id=?", (mutation["mutation_id"],))
                else:
                    db.execute("UPDATE living_mutations SET transmitted_at=? WHERE mutation_id=?", (utc_now(), mutation["mutation_id"]))
            if mode != "fail_before_write":
                try:
                    if mutation["kind"] == "insert":
                        self.calendar.insert(mutation["intent"])
                    elif mutation["kind"] == "update":
                        success, _ = self.calendar.update_if_unchanged(mutation["event_id"], mutation["expected_etag"], mutation["intent"])
                        require(success, "Calendar precondition conflict.")
                    else:
                        success, _ = self.calendar.delete_if_unchanged(mutation["event_id"], mutation["expected_etag"])
                        require(success, "Calendar precondition conflict.")
                    if mode == "timeout_after_write":
                        with self.vault.transaction() as db:
                            db.execute("UPDATE living_mutations SET status='AMBIGUOUS',error='Calendar acknowledgement lost; readback is required.' WHERE mutation_id=?", (mutation["mutation_id"],))
                        with self.vault.connect() as db:
                            return self.receipt(db.execute("SELECT * FROM living_mutations WHERE mutation_id=?", (mutation["mutation_id"],)).fetchone())
                except (HTTPException, ValueError):
                    with self.vault.transaction() as db:
                        db.execute("UPDATE living_mutations SET status='NEEDS_ATTENTION',error='Calendar precondition conflict; existing content preserved.' WHERE mutation_id=?", (mutation["mutation_id"],))
                except Exception:
                    with self.vault.transaction() as db:
                        db.execute("UPDATE living_mutations SET status='AMBIGUOUS',error='Calendar transmission outcome is uncertain; readback is required.' WHERE mutation_id=?", (mutation["mutation_id"],))
            with self.vault.connect() as db:
                row = db.execute("SELECT * FROM living_mutations WHERE mutation_id=?", (mutation["mutation_id"],)).fetchone()
            return self.observe(row) if mode != "fail_before_write" else self.receipt(row)

    def events(self, agreement_id=None):
        with self.lock, self.vault.connect() as db:
            rows = db.execute("SELECT * FROM living_mutations" + (" WHERE agreement_id=?" if agreement_id else "") + " ORDER BY rowid", (agreement_id,) if agreement_id else ()).fetchall()
        return [self.observe(row) for row in rows]

    def signed_observation(self, agreement_id):
        require(isinstance(agreement_id, str) and bool(agreement_id), "An exact locally approved agreement is required for an observation.", 422)
        with self.lock:
            state = self.read()
            require(any(a["agreement_id"] == agreement_id and (any(c["owner_id"] == self.owner_id for c in a["commitments"]) or bool(self.own_mutations(a)))
                        for a in state["reviewed_agreements"].values()), "No locally approved agreement scope exists for this observation.", 404)
            receipts = self.events(agreement_id)
            authorities = [self.observed_authority(agreement, state) for agreement in sorted(state["reviewed_agreements"].values(), key=lambda a: a["revision"])
                           if agreement["agreement_id"] == agreement_id]
            payload = {"agreement_id": agreement_id, "owner_id": self.owner_id, "receipts": receipts, "authorities": authorities, "observed_at": utc_now()}
            observation = self.signed("LivingObservation", payload, state)
            return {"owner_id": self.owner_id, "receipts": receipts, "observation": observation}

    def observed_authority(self, agreement, state):
        """Public current authority, derived without calendar/private reason text."""
        own_ids = {c["commitment_id"] for c in agreement["commitments"] if c["owner_id"] == self.owner_id}
        withdrawn = sorted(own_ids & set(state["withdrawn"].get(agreement["agreement_id"], [])))
        consent = state["approvals"].get(self.agreement_key(agreement))
        current = False
        if consent is not None:
            try:
                self.authenticate(agreement, consent, state)
                require(not withdrawn, "Some commitments in this exact revision were withdrawn.")
                goal_id = agreement["goal"]["goal_id"]
                grants = []
                for message in state["offers"].get(goal_id, {}).values():
                    try:
                        self.public_message(message, "LivingRelease")
                        grant = message["body"]["payload"]
                        if grant["goal_digest"] == agreement["goal_digest"] and grant["constraint_revision"] == self.constraint_revision(state, goal_id) and future(grant["expires_at"]):
                            grants.append(grant)
                    except HTTPException:
                        continue
                for commitment in agreement["commitments"]:
                    if commitment["owner_id"] == self.owner_id:
                        require(any(g["offer_id"] == commitment["offer_id"] and g["offer_revision"] == commitment["offer_revision"] and commitment["task_id"] in g["task_ids"] for g in grants), "The exact per-goal release is no longer current.")
                current = True
            except (HTTPException, ValueError, KeyError, TypeError):
                current = False
        return {"revision": agreement["revision"], "agreement_digest": agreement_digest(agreement),
                "consent_message_id": consent["body"]["message_id"] if consent is not None else None,
                "authority_current": current, "withdrawn_commitment_ids": withdrawn}

    def withdraw(self, agreement_id, base_revision, commitment_ids, expected_revision):
        require(isinstance(commitment_ids, list) and commitment_ids and len(set(commitment_ids)) == len(commitment_ids), "Name the exact commitments to withdraw.", 422)
        with self.lock:
            with self.vault.transaction() as db:
                state = self.read(db)
                self.check_revision(state, expected_revision)
                agreement = state["reviewed_agreements"].get(f"{agreement_id}:{base_revision}")
                require(agreement is not None, "Only a locally reviewed exact agreement can be withdrawn.")
                own = {c["commitment_id"]: c for c in agreement["commitments"] if c["owner_id"] == self.owner_id}
                require(set(commitment_ids) <= set(own), "Withdrawal exceeds this owner's commitment scope.")
                state["consent_revision"] += 1
                state["withdrawn"].setdefault(agreement_id, [])
                state["withdrawn"][agreement_id] = sorted(set(state["withdrawn"][agreement_id]) | set(commitment_ids))
                goal_id = agreement["goal"]["goal_id"]
                state["excluded_tasks"][goal_id] = sorted(set(state["excluded_tasks"].get(goal_id, [])) | {own[c]["task_id"] for c in commitment_ids})
                self.invalidate(db, state, {goal_id}, set(commitment_ids))
                payload = {"agreement_id": agreement_id, "base_revision": base_revision, "goal_id": goal_id, "owner_id": self.owner_id, "commitment_ids": commitment_ids, "consent_revision": state["consent_revision"]}
                message = self.signed("LivingWithdrawal", payload, state)
                self._queue(db, "/v2/withdrawals", message)
                self.bump(state)
                self.write(db, state)
                rows = db.execute("SELECT * FROM living_mutations WHERE agreement_id=?", (agreement_id,)).fetchall()
            # Existing effects remain until an exact amendment executes its scoped
            # conditional delete. Withdrawal itself does not count a calendar write.
            effects = [self.observe(row) for row in rows if json.loads(row["payload"])["commitment_id"] in commitment_ids]
        self.flush()
        return {"withdrawal": message, "effects": effects, "revision": state["revision"], "consent_revision": state["consent_revision"]}

    def question(self, request):
        require(isinstance(request, dict) and not set(request) - {"request_id", "goal_id", "task_id", "category", "disruption_id", "invitation", "label"}, "Invalid coordination question.", 422)
        for key in ("request_id", "goal_id", "task_id", "category", "disruption_id"):
            require(isinstance(request.get(key), str) and 1 <= len(request[key]) <= 200, "Question scope is required.", 422)
        with self.lock, self.vault.transaction() as db:
            state = self.read(db)
            previous = next((q for q in state["requests"] if q["request_id"] == request["request_id"]), None)
            if previous:
                require(all(previous.get(key) == value for key, value in request.items()), "An immutable coordination request changed.")
                status = "accepted" if previous["status"] == "accepted" else "declined"
                return {"request_id": request["request_id"], "accepted": status == "accepted", "status": status}
            goal = state["goals"].get(request["goal_id"])
            scope = f"{request['goal_id']}:{request['task_id']}"
            accepted = goal is not None and any(t["task_id"] == request["task_id"] and t["capability"] == request["category"] for t in goal["tasks"])
            if goal:
                memories = self.active_memories(state, goal)
                accepted = accepted and not any(m["type"] == "request_category" and m["value"]["category"] == request["category"] and not m["value"]["allowed"] for m in memories)
                permissions = []
                for message in state["offers"].get(request["goal_id"], {}).values():
                    try:
                        self.public_message(message, "LivingRelease")
                        grant = message["body"]["payload"]
                        if grant["constraint_revision"] == self.constraint_revision(state, request["goal_id"]) and future(grant["expires_at"]):
                            permissions.extend(grant["request_categories"])
                    except HTTPException:
                        continue
                accepted = accepted and request["category"] in permissions
            accepted = accepted and scope not in state["refusals"]
            budget = min(3, max(0, int(self.config.get("living_question_budget", 3))))
            accepted = accepted and sum(q["status"] in {"accepted", "refused"} and q["disruption_id"] == request["disruption_id"] for q in state["requests"]) < budget
            record = {**deepcopy(request), "status": "accepted" if accepted else "declined", "received_at": utc_now()}
            if not accepted and request.get("invitation") is True:
                record["status"] = "invitation_pending"
            state["requests"].append(record)
            if accepted and request["goal_id"] in state.get("task_choices", {}):
                state["task_choices"][request["goal_id"]] = sorted(set(state["task_choices"][request["goal_id"]]) | {request["task_id"]})
            self.bump(state)
            self.write(db, state)
        return {"request_id": request["request_id"], "accepted": accepted, "status": "accepted" if accepted else "declined"}

    def accept_invitation(self, request_id, expected_revision):
        with self.lock, self.vault.transaction() as db:
            state = self.read(db)
            self.check_revision(state, expected_revision)
            request = next((q for q in state["requests"] if q["request_id"] == request_id and q["status"] == "invitation_pending"), None)
            require(request is not None, "No explicit invitation is awaiting owner review.")
            state["refusals"].pop(f"{request['goal_id']}:{request['task_id']}", None)
            if request["goal_id"] in state.get("task_choices", {}):
                state["task_choices"][request["goal_id"]] = sorted(set(state["task_choices"][request["goal_id"]]) | {request["task_id"]})
            request["status"] = "accepted"
            request["reinvited_at"] = utc_now()
            self.bump(state)
            self.write(db, state)
        return {"accepted": True, "revision": state["revision"]}

    def refuse(self, request_id, expected_revision):
        with self.lock, self.vault.transaction() as db:
            state = self.read(db)
            self.check_revision(state, expected_revision)
            request = next((q for q in state["requests"] if q["request_id"] == request_id), None)
            require(request is not None and request["status"] == "accepted", "No accepted request exists in this scope.")
            scope = f"{request['goal_id']}:{request['task_id']}"
            require(scope not in state["refusals"], "A refusal already closes this scope until an explicit reinvitation.")
            state["consent_revision"] += 1
            payload = {"goal_id": request["goal_id"], "request_id": request_id, "owner_id": self.owner_id, "task_id": request["task_id"], "consent_revision": state["consent_revision"]}
            message = self.signed("LivingRefusal", payload, state)
            request["status"] = "refused"
            state["refusals"][scope] = message
            self._queue(db, "/v2/refusals", message)
            self.bump(state)
            self.write(db, state)
        self.flush()
        return {"refusal": message, "revision": state["revision"]}

    def status(self, goal_id=None):
        state = self.read()
        offers = state["offers"].get(goal_id, {}) if goal_id else {}
        current = []
        for message in offers.values():
            try:
                self.public_message(message, "LivingRelease")
                if future(message["body"]["payload"]["expires_at"]):
                    current.append(message)
            except HTTPException:
                continue
        return {"owner_id": self.owner_id, "goal_id": goal_id, "releases": current,
                "release": current[-1] if current else None, "consent_revision": state["consent_revision"],
                "constraint_revision": self.constraint_revision(state, goal_id) if goal_id else state["constraint_revision"],
                "key_id": self.engine.identity["key_id"], "public_key": self.engine.identity["public_key"],
                "revoked_keys": self.engine.status()["revoked_keys"]}

    def state(self):
        available = True
        try:
            self.flush()
            current = self.current()
            for raw in [current.get("goal")]:
                if raw:
                    self.remember_goal(raw)
        except HTTPException:
            available, current = False, {}
        state = self.read()
        calendar_available = True
        try:
            calendar_events = self.calendar.list()
        except Exception:
            calendar_available = False
            calendar_events = []
        pending = current.get("pending")
        return {"owner": self.engine.owner(), "sample": self.config.get("fictional_sample") is True,
                "broker_ui_url": self.config.get("broker_ui_url", "http://127.0.0.1:4301"),
                **{key: deepcopy(state[key]) for key in ("revision", "memories", "policy", "requests", "consent_revision", "constraint_revision")},
                "goals": list(state["goals"].values()), "offers": state["offers"], "agreement": current.get("agreement"),
                "pending": pending, "pending_digest": agreement_digest(pending) if pending else None,
                "current_disruption_id": current.get("disruption_id"),
                "receipts": self.events(), "calendar_events": calendar_events, "coordinator_available": available,
                "calendar_available": calendar_available, "calendar_error": None if calendar_available else "Calendar observation is unavailable; effects remain unconfirmed.",
                "withdrawn": state["withdrawn"], "deletions": state["deletions"]}

    def sample_setup(self, goal, provider, enable_policy=False):
        require(self.config.get("fictional_sample") is True, "Fictional setup is unavailable for this owner.", 404)
        goal = authored_sample_goal(goal)
        require(self.owner_id in goal["participants"] and set(goal["participants"]) == set(self.config.get("registered_owners", ["asha", "ravi", "leena"])), "This is not the registered authored fictional setup.")
        with self.lock:
            return self._sample_setup(goal, provider, enable_policy)

    def _sample_setup(self, goal, provider, enable_policy):
        self.remember_goal(goal)
        state = self.read()
        existing = next((r for r in state["sample_setups"] if r["goal_id"] == goal["goal_id"] and r.get("goal_digest") == goal_digest(goal)), None)
        if existing is not None:
            require(existing.get("provider") == provider and existing.get("enable_policy") is enable_policy,
                    "The first authored sample options are immutable; later changes require the private owner surface.")
            cached = existing.get("setup_release") or state["offers"].get(goal["goal_id"], {}).get(provider)
            if cached:
                self.flush()
                return {"authored": True, "fictional_sample": True, "release": deepcopy(cached), "revision": state["revision"], "consent_revision": cached["body"]["consent_revision"]}
            # A process may have stopped after recording the first exact setup
            # choice but before its release was durably signed. Finish only that
            # same initial decision, without resetting memories or policy.
            preview = self.preview(goal["goal_id"], provider)
            result = self.release(goal["goal_id"], provider, preview["preview_digest"], state["revision"], sample_setup_digest=goal_digest(goal))
            return {"authored": True, "fictional_sample": True, **result}
        with self.lock, self.vault.transaction() as db:
            state = self.read(db)
            if not state["sample_setups"]:
                if self.owner_id == "asha":
                    raw = {"type": "excluded_capability", "value": {"capability": "driving"}, "scope": {}, "provenance": "Explicit authored fictional setup: Asha does not offer driving", "owner_confirmed": True}
                    state["memories"].append(self._memory(raw))
                if self.owner_id == "leena":
                    raw = {"type": "require_receiver", "value": {"capability": "driving", "receiver_id": "asha", "receiver_task_id": "handoff", "by": 975}, "scope": {}, "provenance": "Explicit authored fictional setup: Leena requires Asha's confirmed handoff by 16:15", "owner_confirmed": True}
                    state["memories"].append(self._memory(raw))
                if self.owner_id == "asha":
                    state["memories"].append(self._memory({"type": "request_category", "value": {"category": "driving", "allowed": False}, "scope": {}, "provenance": "Explicit authored fictional setup: Asha declines driving requests", "owner_confirmed": True}))
                state["constraint_revision"] += 1
                state["goal_constraint_revisions"][goal["goal_id"]] = state["constraint_revision"]
            may_author_sample_policy = state["policy"]["revision"] == 0 or "authored fictional" in state["policy"].get("provenance", "")
            if enable_policy is True and may_author_sample_policy and not (state["policy"]["enabled"] and state["policy"].get("expires_at") and future(state["policy"]["expires_at"])):
                state["policy"] = {"enabled": True, "revision": state["policy"]["revision"] + 1, "expires_at": expires_in(14400), "provenance": "Explicitly selected authored fictional carry-forward policy", "updated_at": utc_now()}
            state["sample_setups"].append({"goal_id": goal["goal_id"], "goal_digest": goal_digest(goal), "provider": provider,
                                          "enable_policy": enable_policy, "at": utc_now(), "authored": True})
            if goal["goal_id"] not in state.setdefault("task_choices", {}):
                capabilities = {"asha": {"preparation", "handoff"}, "ravi": {"driving"}, "leena": {"accompaniment"}}.get(self.owner_id, set(self.config.get("owner_profile", {}).get("capabilities", [])))
                state["task_choices"][goal["goal_id"]] = [t["task_id"] for t in goal["tasks"] if t["capability"] in capabilities]
            self.bump(state)
            self.write(db, state)
        preview = self.preview(goal["goal_id"], provider)
        result = self.release(goal["goal_id"], provider, preview["preview_digest"], self.read()["revision"], sample_setup_digest=goal_digest(goal))
        return {"authored": True, "fictional_sample": True, **result}

    def sample_approve(self, agreement):
        require(self.config.get("fictional_sample") is True, "Fictional approval is unavailable for this owner.", 404)
        with self.lock:
            state = self.read()
            record = self.sample_approval_record(agreement, state)
            if record.get("approval_digest") == agreement_digest(agreement) and record.get("approval"):
                # Returning previously issued bytes is historical delivery, never
                # fresh signing or renewed authority after a later owner change.
                message = deepcopy(record["approval"])
                self.flush()
                return {"authored": True, "fictional_sample": True, "consent": message, "revision": state["revision"]}
        result = self._approve(agreement, agreement_digest(agreement), sample_bootstrap=True)
        return {"authored": True, "fictional_sample": True, **result}

    def sample_approval_record(self, raw, state):
        raw = normalized(validate_agreement, raw)
        require(raw.get("revision") == 1 and raw.get("base_revision") == 0, "Fictional bootstrap cannot approve amendments.")
        goal = authored_sample_goal(raw.get("goal"))
        require(self.owner_id in goal["participants"] and state["goals"].get(goal["goal_id"]) == goal,
                "No matching local authored setup exists.")
        record = next((r for r in state["sample_setups"] if r["goal_id"] == goal["goal_id"] and r.get("goal_digest") == goal_digest(goal) and r.get("authored") is True), None)
        require(record is not None and (not record.get("approval_digest") or record["approval_digest"] == agreement_digest(raw)), "Only the first exact authored bootstrap may be approved.")
        if not record.get("approval_digest"):
            require(not any(a["goal"]["goal_id"] == goal["goal_id"] and agreement_digest(a) != agreement_digest(raw)
                            for key, a in state["reviewed_agreements"].items() if key in state["approvals"]), "Only the first exact authored bootstrap may be approved.")
        ownership = {"prepare": "asha", "outbound": "ravi", "accompany": "leena", "return": "ravi", "handoff": "asha"}
        commitments = raw.get("commitments", [])
        require(len(commitments) == len(ownership) and {c.get("task_id"): c.get("owner_id") for c in commitments} == ownership,
                "The bootstrap ownership differs from the authored starting arrangement.")
        return record
