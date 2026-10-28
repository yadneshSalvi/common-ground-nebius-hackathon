"""Strict v2 public contracts. Private memory never appears in these schemas.

Legacy contracts remain in schema.py. V2 authority cannot be derived from a v1
signature, and an agreement revision never changes an event's creation identity.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shared.protocol import digest, parse_time

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Capability = Literal["preparation", "driving", "accompaniment", "handoff", "meal", "visit"]
ProviderId = Literal["fireworks", "nebius"]
CAPABILITIES = ("preparation", "driving", "accompaniment", "handoff", "meal", "visit")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Task(Strict):
    task_id: Identifier
    label: str = Field(min_length=1, max_length=160)
    capability: Capability
    date: str
    duration: int = Field(ge=1, le=720)
    earliest: int = Field(ge=0, le=1439)
    latest: int = Field(ge=1, le=1440)
    start_location: str = Field(min_length=1, max_length=100)
    end_location: str = Field(min_length=1, max_length=100)
    predecessors: list[Identifier] = Field(max_length=11)
    required: bool = True
    subject: str = Field(min_length=1, max_length=100)
    source_quote: str = Field(min_length=1, max_length=2500)

    @model_validator(mode="after")
    def coherent(self):
        if date.fromisoformat(self.date).isoformat() != self.date:
            raise ValueError("Use an exact ISO calendar date")
        if self.earliest + self.duration > self.latest:
            raise ValueError("The confirmed duration does not fit its task window")
        if len(set(self.predecessors)) != len(self.predecessors) or self.task_id in self.predecessors:
            raise ValueError("Duplicate or self dependency")
        if self.capability != "driving" and self.start_location != self.end_location:
            raise ValueError("Only an explicitly confirmed journey can change location")
        return self


class Route(Strict):
    from_location: str = Field(min_length=1, max_length=100)
    to_location: str = Field(min_length=1, max_length=100)
    duration: int = Field(ge=1, le=720)
    source_quote: str = Field(min_length=1, max_length=2500)


class Goal(Strict):
    schema_version: Literal[2] = 2
    goal_id: Identifier
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    timezone: str
    participants: list[Identifier] = Field(min_length=2, max_length=6)
    subject: str = Field(min_length=1, max_length=100)
    source_text: str = Field(min_length=1, max_length=16000)
    tasks: list[Task] = Field(min_length=2, max_length=12)
    routes: list[Route] = Field(max_length=48)
    confirmed_at: str
    confirmed_by: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def graph(self):
        try:
            zone=ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown IANA timezone") from exc
        parse_time(self.confirmed_at)
        if len(set(self.participants)) != len(self.participants):
            raise ValueError("Duplicate owner")
        tasks = {t.task_id: t for t in self.tasks}
        if len(tasks) != len(self.tasks) or not any(t.required for t in self.tasks):
            raise ValueError("Unique tasks and at least one required responsibility are needed")
        visiting, visited = set(), set()
        def visit(tid):
            if tid in visiting:
                raise ValueError("Cyclic responsibilities")
            if tid in visited:
                return
            if tid not in tasks:
                raise ValueError("Unknown predecessor")
            visiting.add(tid)
            for pid in tasks[tid].predecessors:
                visit(pid)
                prior = tasks[pid]
                current = tasks[tid]
                if prior.subject == current.subject and prior.end_location != current.start_location:
                    raise ValueError("The care recipient cannot teleport between dependencies; add a confirmed journey")
                if prior.date > current.date:
                    raise ValueError("A dependency cannot occur after its responsibility")
            visiting.remove(tid)
            visited.add(tid)
        for tid in tasks:
            visit(tid)
        # A different owner cannot make simultaneous activities or an unassigned
        # transfer of the same recipient feasible. Ambiguous graphs need review.
        def ancestors(tid):
            result=set(tasks[tid].predecessors)
            for pid in tasks[tid].predecessors:
                result.update(ancestors(pid))
            return result
        ancestry={tid:ancestors(tid) for tid in tasks}
        values=list(tasks.values())
        for index,left in enumerate(values):
            for right in values[index+1:]:
                if left.subject==right.subject and left.date==right.date and left.task_id not in ancestry[right.task_id] and right.task_id not in ancestry[left.task_id]:
                    raise ValueError("Recipient continuity is ambiguous; review the ordering and explicit journeys between same-day responsibilities")
        for item in [*self.tasks, *self.routes]:
            if item.source_quote not in self.source_text:
                raise ValueError("Every task and travel fact must cite the reviewed source verbatim")
        offsets=set()
        for task in self.tasks:
            for minute in (task.earliest,task.latest):
                wall=datetime.fromisoformat(task.date)+timedelta(minutes=minute)
                local=wall.replace(tzinfo=zone,fold=0)
                roundtrip=local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
                if roundtrip!=wall or local.utcoffset()!=wall.replace(tzinfo=zone,fold=1).utcoffset():
                    raise ValueError("A reviewed window has a nonexistent or ambiguous local time; choose an unambiguous time")
                offsets.add(local.utcoffset())
        if len(offsets)>1:
            raise ValueError("This bounded goal crosses a UTC-offset change; review separate goals on either side rather than silently choosing a clock interpretation")
        routes = {(r.from_location, r.to_location): r.duration for r in self.routes}
        if len(routes) != len(self.routes):
            raise ValueError("Duplicate or conflicting confirmed travel route")
        for task in self.tasks:
            if task.capability == "driving" and task.start_location != task.end_location:
                if routes.get((task.start_location, task.end_location)) != task.duration:
                    raise ValueError("A journey duration must equal an explicitly confirmed route duration")
        return self


class Window(Strict):
    date: str
    start: int = Field(ge=0, le=1439)
    end: int = Field(ge=1, le=1440)

    @model_validator(mode="after")
    def coherent(self):
        date.fromisoformat(self.date)
        if self.start >= self.end:
            raise ValueError("Availability must end after it begins")
        return self


class Condition(Strict):
    task_id: Identifier
    receiver_id: Identifier
    by: int = Field(ge=1, le=1440)
    receiver_task_id: Identifier


class Recipients(Strict):
    humans: list[Identifier] = Field(min_length=2, max_length=6)
    broker: Literal["common-ground-broker"] = "common-ground-broker"
    inference: list[ProviderId] = Field(max_length=2)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.humans)) != len(self.humans) or len(set(self.inference)) != len(self.inference):
            raise ValueError("Duplicate recipient")
        return self


class Release(Strict):
    goal_id: Identifier
    goal_revision: int = Field(ge=1)
    goal_digest: Hash
    offer_id: Identifier
    offer_revision: int = Field(ge=1)
    owner_id: Identifier
    constraint_revision: int = Field(ge=1)
    task_ids: list[Identifier] = Field(max_length=12)
    windows: list[Window] = Field(max_length=24)
    conditions: list[Condition] = Field(max_length=12)
    recipients: Recipients
    request_categories: list[Capability] = Field(max_length=6)
    expires_at: str

    @model_validator(mode="after")
    def coherent(self):
        parse_time(self.expires_at)
        if len(set(self.task_ids)) != len(self.task_ids) or len(set(self.request_categories)) != len(self.request_categories):
            raise ValueError("Duplicate task or request category")
        if any(c.task_id not in self.task_ids for c in self.conditions):
            raise ValueError("A condition must bind a released task")
        return self


class Dependency(Strict):
    task_id: Identifier
    commitment_id: Identifier
    owner_id: Identifier
    date: str
    start: int
    end: int
    start_location: str
    end_location: str


class Commitment(Strict):
    commitment_id: Identifier
    task_id: Identifier
    owner_id: Identifier
    date: str
    timezone: str
    start: int = Field(ge=0, le=1439)
    end: int = Field(ge=1, le=1440)
    start_location: str
    end_location: str
    capability: Capability
    label: str = Field(min_length=1, max_length=160)
    subject: str
    dependencies: list[Dependency] = Field(max_length=11)
    conditions: list[Condition] = Field(max_length=12)
    offer_id: Identifier
    offer_revision: int = Field(ge=1)


class Creation(Strict):
    agreement_id: Identifier
    revision: int = Field(ge=1)
    created_at: str


class Location(Strict):
    start: str
    end: str


class CalendarIntent(Strict):
    schema_version: Literal[2] = 2
    action_id: Identifier
    commitment_id: Identifier
    owner_id: Identifier
    task_id: Identifier
    event_id: Identifier
    label: str
    date: str
    timezone: str
    start: int
    end: int
    location: Location
    creation: Creation


class Mutation(Strict):
    mutation_id: Identifier
    kind: Literal["insert", "update", "delete"]
    owner_id: Identifier
    commitment_id: Identifier
    action_id: Identifier
    event_id: Identifier
    intent: CalendarIntent | None
    expected_etag: str | None

    @model_validator(mode="after")
    def coherent(self):
        if (self.kind == "delete") != (self.intent is None):
            raise ValueError("Delete has no new intent; insert/update require one")
        if self.kind == "insert" and self.expected_etag is not None:
            raise ValueError("Insert requires absence")
        if self.kind in ("delete", "update") and not self.expected_etag:
            raise ValueError("Conditional mutation needs the observed current ETag")
        if self.intent and any(getattr(self.intent, k) != getattr(self, k) for k in ("owner_id", "commitment_id", "action_id", "event_id")):
            raise ValueError("Mutation identity differs from its intent")
        return self


class Delta(Strict):
    retained: list[Identifier]
    changed: list[Identifier]
    new: list[Identifier]
    withdrawn: list[Identifier]
    affected_owners: list[Identifier]
    approval_required: list[Identifier]
    calendar_mutations: list[Mutation]


class Agreement(Strict):
    schema_version: Literal[2] = 2
    agreement_id: Identifier
    revision: int = Field(ge=1)
    base_revision: int = Field(ge=0)
    goal: Goal
    goal_digest: Hash
    commitments: list[Commitment] = Field(min_length=1, max_length=12)
    intents: list[CalendarIntent] = Field(min_length=1, max_length=12)
    delta: Delta
    created_at: str
    expires_at: str
    checker: dict
    model_receipt_id: str | None
    explanation: str = Field(default="", max_length=2400)

    @model_validator(mode="after")
    def coherent(self):
        if self.revision != self.base_revision + 1:
            raise ValueError("An amendment must advance exactly one base revision")
        if self.goal_digest != digest(self.goal.model_dump()):
            raise ValueError("Goal digest mismatch")
        if parse_time(self.expires_at) <= parse_time(self.created_at):
            raise ValueError("Invalid agreement lifetime")
        cs = {c.task_id: c for c in self.commitments}
        if len(cs) != len(self.commitments) or len({c.commitment_id for c in self.commitments}) != len(cs):
            raise ValueError("Duplicate commitment or task")
        ts = {t.task_id: t for t in self.goal.tasks}
        if set(cs) - set(ts) or any(t.required and t.task_id not in cs for t in ts.values()):
            raise ValueError("Required responsibility coverage is incomplete")
        by_id = {c.commitment_id: c for c in self.commitments}
        if len(self.intents) != len(cs) or {i.commitment_id for i in self.intents} != set(by_id):
            raise ValueError("Every commitment needs exactly one stable calendar intent")
        if len({i.event_id for i in self.intents}) != len(self.intents):
            raise ValueError("Duplicate provider event identity")
        for c in self.commitments:
            task = ts[c.task_id]
            if c.owner_id not in self.goal.participants or c.commitment_id != commitment_id(self.agreement_id, c.task_id, c.owner_id):
                raise ValueError("Commitment identity is not registered or stable")
            for key in ("date", "start_location", "end_location", "capability", "label", "subject"):
                if getattr(c, key) != getattr(task, key):
                    raise ValueError("Commitment changes a reviewed task fact")
            if c.timezone != self.goal.timezone or c.end-c.start != task.duration or c.start < task.earliest or c.end > task.latest:
                raise ValueError("Commitment interval violates the reviewed goal")
            expected = dependency_entries(self.goal.model_dump(), [x.model_dump() for x in self.commitments], c.task_id)
            if [d.model_dump() for d in c.dependencies] != expected:
                raise ValueError("Commitment omits or alters a direct dependency/counterparty")
            for condition in c.conditions:
                receiver = cs.get(condition.receiver_task_id)
                if condition.task_id != c.task_id or not receiver or receiver.owner_id != condition.receiver_id or receiver.date != c.date or receiver.end > condition.by or receiver.start < c.end:
                    raise ValueError("A conditional handoff is not satisfied")
        for i in self.intents:
            c = by_id[i.commitment_id]
            if i.action_id != action_id(c.commitment_id) or i.event_id != calendar_event_id(i.action_id):
                raise ValueError("Invalid stable action/event identity")
            if i.creation.agreement_id != self.agreement_id or i.creation.revision > self.revision:
                raise ValueError("Invalid immutable creation provenance")
            for key in ("owner_id", "task_id", "label", "date", "timezone", "start", "end"):
                if getattr(i, key) != getattr(c, key):
                    raise ValueError("Calendar content differs from reviewed commitment")
            if (i.location.start, i.location.end) != (c.start_location, c.end_location):
                raise ValueError("Calendar locations differ from commitment")
        for ids in (self.delta.retained, self.delta.changed, self.delta.new, self.delta.withdrawn):
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate delta identity")
        if set(self.delta.retained) | set(self.delta.changed) | set(self.delta.new) != set(by_id):
            raise ValueError("Delta does not account for every present commitment")
        if len(self.delta.retained)+len(self.delta.changed)+len(self.delta.new) != len(by_id):
            raise ValueError("Overlapping delta categories")
        if len({m.mutation_id for m in self.delta.calendar_mutations}) != len(self.delta.calendar_mutations):
            raise ValueError("Duplicate mutation identity")
        return self


class Consent(Strict):
    agreement_id: Identifier
    revision: int = Field(ge=1)
    base_revision: int = Field(ge=0)
    agreement_digest: Hash
    goal_digest: Hash
    owner_id: Identifier
    consent_revision: int = Field(ge=0)
    constraint_revision: int = Field(ge=1)
    commitment_digests: dict[Identifier, Hash]
    dependency_digests: dict[Identifier, Hash]
    mutation_ids: list[Identifier]
    execution_not_after: str
    compensation_policy: Literal["unchanged-app-created-only"]
    basis: Literal["exact-review", "standing-policy"]
    policy_revision: int | None

    @model_validator(mode="after")
    def coherent(self):
        parse_time(self.execution_not_after)
        if self.revision != self.base_revision + 1 or set(self.commitment_digests) != set(self.dependency_digests):
            raise ValueError("Consent revision or dependency coverage mismatch")
        if (self.basis == "exact-review") != (self.policy_revision is None):
            raise ValueError("Standing authority must name its reviewed policy revision")
        if len(self.mutation_ids) != len(set(self.mutation_ids)):
            raise ValueError("Duplicate mutation authority")
        return self


class Withdrawal(Strict):
    agreement_id: Identifier
    base_revision: int = Field(ge=1)
    goal_id: Identifier
    owner_id: Identifier
    commitment_ids: list[Identifier] = Field(min_length=1, max_length=12)
    consent_revision: int = Field(ge=1)


class Refusal(Strict):
    goal_id: Identifier
    request_id: Identifier
    owner_id: Identifier
    task_id: Identifier
    consent_revision: int = Field(ge=1)


class ObservationAuthority(Strict):
    revision: int = Field(ge=1)
    agreement_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    consent_message_id: str | None
    authority_current: bool
    withdrawn_commitment_ids: list[Identifier] = Field(max_length=12)

    @model_validator(mode="after")
    def coherent(self):
        if len(set(self.withdrawn_commitment_ids))!=len(self.withdrawn_commitment_ids):
            raise ValueError("Duplicate withdrawn observation scope")
        if self.authority_current and (not self.consent_message_id or self.withdrawn_commitment_ids):
            raise ValueError("Current observation authority needs exact consent and no withdrawn commitments")
        return self


class Observation(Strict):
    agreement_id: Identifier
    owner_id: Identifier
    authorities: list[ObservationAuthority] = Field(min_length=1,max_length=256)
    receipts: list[dict] = Field(max_length=256)
    observed_at: str

    @model_validator(mode="after")
    def public_fields_only(self):
        parse_time(self.observed_at)
        if len({a.revision for a in self.authorities})!=len(self.authorities):
            raise ValueError("Duplicate agreement revision in observation authority")
        required={"mutation_id","commitment_id","action_id","event_id","status","etag","verified_at","intent_id","fence","transmitted_at"}
        allowed=required|{"error","remaining_effect"}
        statuses={"VERIFIED","CANCELLED","AMBIGUOUS","PAUSED","FAILED","NEEDS_ATTENTION","UNCONFIRMED","INTENT"}
        for receipt in self.receipts:
            if not required<=set(receipt) or set(receipt)-allowed or receipt["status"] not in statuses:
                raise ValueError("Observation contains unknown or private receipt fields")
            if type(receipt["fence"]) is not int or receipt["fence"]<1:
                raise ValueError("Invalid observation fence")
            for key in ("mutation_id","commitment_id","action_id","event_id","intent_id"):
                if not isinstance(receipt[key],str) or not 1<=len(receipt[key])<=200:
                    raise ValueError("Invalid public observation identity")
            if receipt.get("remaining_effect") is not None and set(receipt["remaining_effect"])-{"event_id","action_id","commitment_id","date","timezone","start","end"}:
                raise ValueError("Private edited content cannot enter an observation")
        return self


def validate_goal(value):
    return Goal.model_validate(value).model_dump()


def validate_release(value):
    return Release.model_validate(value).model_dump()


def validate_consent(value):
    return Consent.model_validate(value).model_dump()


def validate_agreement(value):
    return Agreement.model_validate(value).model_dump()


def validate_payload(kind, payload):
    cls = {"LivingRelease": Release, "LivingConsent": Consent, "LivingWithdrawal": Withdrawal, "LivingRefusal": Refusal, "LivingObservation": Observation}.get(kind)
    if cls is None:
        raise ValueError("Unknown living protocol purpose")
    return cls.model_validate(payload).model_dump()


def goal_digest(goal):
    return digest(goal)


def agreement_digest(agreement):
    return digest(agreement)


def commitment_digest(commitment):
    return digest({k: v for k, v in commitment.items() if k not in ("offer_id", "offer_revision")})


def dependency_digest(commitment):
    return digest({"dependencies": commitment["dependencies"], "conditions": commitment["conditions"]})


def commitment_id(agreement_id, task_id, owner_id):
    return "commitment-" + digest([agreement_id, task_id, owner_id])[:32]


def action_id(cid):
    return "action-" + digest(cid)[:32]


def calendar_event_id(aid):
    return "cg2" + hashlib.sha256(aid.encode()).hexdigest()[:40]


def dependency_entries(goal, commitments, task_id):
    tasks = {t["task_id"]: t for t in goal["tasks"]}
    related = set(tasks[task_id]["predecessors"]) | {t["task_id"] for t in goal["tasks"] if task_id in t["predecessors"]}
    keys = ("task_id", "commitment_id", "owner_id", "date", "start", "end", "start_location", "end_location")
    return [{k: c[k] for k in keys} for c in sorted(commitments, key=lambda c: c["task_id"]) if c["task_id"] in related]


def consent_payload(agreement, owner_id, consent_revision, constraint_revision, basis="exact-review", policy_revision=None):
    own = [c for c in agreement["commitments"] if c["owner_id"] == owner_id]
    return validate_consent({"agreement_id": agreement["agreement_id"], "revision": agreement["revision"], "base_revision": agreement["base_revision"], "agreement_digest": agreement_digest(agreement), "goal_digest": agreement["goal_digest"], "owner_id": owner_id, "consent_revision": consent_revision, "constraint_revision": constraint_revision, "commitment_digests": {c["commitment_id"]: commitment_digest(c) for c in own}, "dependency_digests": {c["commitment_id"]: dependency_digest(c) for c in own}, "mutation_ids": [m["mutation_id"] for m in agreement["delta"]["calendar_mutations"] if m["owner_id"] == owner_id], "execution_not_after": agreement["expires_at"], "compensation_policy": "unchanged-app-created-only", "basis": basis, "policy_revision": policy_revision})


def absolute_minute(day, minute):
    return date.fromisoformat(day).toordinal()*1440 + minute


def travel_minutes(goal, origin, destination):
    if origin == destination:
        return 0
    return next((r["duration"] for r in goal["routes"] if r["from_location"] == origin and r["to_location"] == destination), None)
