"""Public-only strict protocol schemas. There are no private source identifiers here."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

OWNER_IDS = ("asha", "ravi", "leena")
BROKER_ID = "common-ground-broker"
CIRCLE_ID = "dev-circle"
DATE = "2026-11-02"
TIMEZONE = "Asia/Kolkata"
RETENTION = "Released facts remain in this local agreement audit; withdrawal stops future use."
RELEASE_FIELDS = ["owner_id", "capabilities", "task_ids", "start", "end", "capacity", "preference_cost", "constraint_revision"]
OWNER_INFO = {
    "asha": {"id": "asha", "name": "Asha", "initials": "AS", "role": "Preparation & home handoff", "accent": "clay", "port": 4311},
    "ravi": {"id": "ravi", "name": "Ravi", "initials": "RA", "role": "Pickup & return journey", "accent": "slate", "port": 4312},
    "leena": {"id": "leena", "name": "Leena", "initials": "LE", "role": "Company & accompaniment", "accent": "forest", "port": 4313},
}
TASKS = [
    {"task_id": "prepare", "label": "Get ready at home", "capability": "preparation", "duration": 20, "earliest": 740, "latest": 780, "location": "home", "predecessors": []},
    {"task_id": "outbound", "label": "Drive Dev to the appointment", "capability": "driving", "duration": 40, "earliest": 790, "latest": 830, "location": "home→clinic", "predecessors": ["prepare"]},
    {"task_id": "accompany", "label": "Stay with Dev at the appointment", "capability": "accompaniment", "duration": 90, "earliest": 830, "latest": 920, "location": "clinic", "predecessors": ["outbound"]},
    {"task_id": "return", "label": "Drive Dev home", "capability": "driving", "duration": 40, "earliest": 920, "latest": 960, "location": "clinic→home", "predecessors": ["accompany"]},
    {"task_id": "handoff", "label": "Welcome Dev home & hand over", "capability": "handoff", "duration": 15, "earliest": 960, "latest": 980, "location": "home", "predecessors": ["return"]},
]
GOAL = {
    "goal_id": "dev-appointment", "revision": 1,
    "title": "Dev’s afternoon appointment",
    "description": "Coordinate preparation, pickup, accompaniment, return and handoff for Dev’s fictional 14:00 appointment. Only deliberately released availability and capabilities may be used.",
    "date": DATE, "timezone": TIMEZONE, "appointment_start": 840, "appointment_end": 910,
    "participants": list(OWNER_IDS), "tasks": TASKS,
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Offer(StrictModel):
    offer_id: str = Field(min_length=8, max_length=128)
    owner_id: Literal["asha", "ravi", "leena"]
    revision: int = Field(ge=1)
    constraint_revision: int = Field(ge=1)
    capabilities: list[Literal["preparation", "driving", "accompaniment", "handoff"]] = Field(min_length=1, max_length=4)
    task_ids: list[Literal["prepare", "outbound", "accompany", "return", "handoff"]] = Field(min_length=1, max_length=5)
    start: int = Field(ge=0, le=1439)
    end: int = Field(ge=1, le=1440)
    capacity: Literal[1]
    preference_cost: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def coherent(self):
        if self.start >= self.end or len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("Invalid availability or duplicate task")
        return self


class Recipients(StrictModel):
    humans: list[Literal["asha", "ravi", "leena"]] = Field(min_length=3, max_length=3)
    broker: Literal["common-ground-broker"]
    inference: list[Literal["fireworks"]] = Field(max_length=1)

    @model_validator(mode="after")
    def humans_exact(self):
        if set(self.humans) != set(OWNER_IDS):
            raise ValueError("All three named circle members must be explicit")
        return self


class ReleaseGrant(StrictModel):
    goal_id: Literal["dev-appointment"]
    goal_revision: int = Field(ge=1)
    purpose: Literal["coordinate-appointment"]
    retention: str = Field(max_length=240)
    recipients: Recipients
    fields: list[str] = Field(min_length=8, max_length=8)
    offer: Offer

    @model_validator(mode="after")
    def fields_exact(self):
        if set(self.fields) != set(RELEASE_FIELDS) or self.retention != RETENTION:
            raise ValueError("Release scope/retention must match the preview")
        return self


class Approval(StrictModel):
    proposal_id: str = Field(min_length=8, max_length=128)
    version: int = Field(ge=1)
    proposal_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    action_ids: list[str] = Field(min_length=1, max_length=10)
    constraint_revision: int = Field(ge=1)
    execution_not_after: str = Field(max_length=40)
    compensation_policy: Literal["delete-only-unchanged-created-events"]


class Withdrawal(StrictModel):
    goal_id: Literal["dev-appointment"]
    offer_id: str = Field(max_length=128)
    reason_code: Literal["availability_changed", "preference_corrected", "owner_withdrew"]


class Task(StrictModel):
    task_id: Literal["prepare", "outbound", "accompany", "return", "handoff"]
    label: str = Field(min_length=1, max_length=100)
    capability: Literal["preparation", "driving", "accompaniment", "handoff"]
    duration: int = Field(ge=5, le=240)
    earliest: int = Field(ge=0, le=1439)
    latest: int = Field(ge=1, le=1440)
    location: Literal["home", "home→clinic", "clinic", "clinic→home"]
    predecessors: list[Literal["prepare", "outbound", "accompany", "return", "handoff"]] = Field(max_length=4)


class SuggestedAssignment(StrictModel):
    task_id: Literal["prepare", "outbound", "accompany", "return", "handoff"]
    owner_id: Literal["asha", "ravi", "leena"] | None
    reason: str = Field(min_length=1, max_length=400)


class ModelPlan(StrictModel):
    tasks: list[Task] = Field(min_length=5, max_length=5)
    explanation: str = Field(min_length=20, max_length=1500)
    tradeoffs: list[str] = Field(min_length=1, max_length=4)
    suggested_assignments: list[SuggestedAssignment] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def safe_graph(self):
        by_id = {t.task_id: t for t in self.tasks}
        if set(by_id) != {t["task_id"] for t in TASKS}:
            raise ValueError("The confirmed five responsibilities must each appear once")
        for reference in TASKS:
            task = by_id[reference["task_id"]]
            for key in ("capability", "duration", "earliest", "latest", "location", "predecessors"):
                if getattr(task, key) != reference[key]:
                    raise ValueError(f"Model changed a confirmed constraint: {task.task_id}.{key}")
        if {a.task_id for a in self.suggested_assignments} != set(by_id):
            raise ValueError("Suggest exactly one owner or null per responsibility")
        if any(len(t) > 500 for t in self.tradeoffs):
            raise ValueError("Tradeoff exceeds bound")
        return self


def validate_payload(message_type: str, payload: dict) -> dict:
    cls = {"ReleaseGrant": ReleaseGrant, "Approval": Approval, "Withdrawal": Withdrawal}.get(message_type)
    if cls is None:
        raise ValueError("Unsupported signed message type")
    return cls.model_validate(payload).model_dump()
