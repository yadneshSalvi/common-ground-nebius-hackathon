"""Strict request shapes for the owner-local v2 boundary."""
from __future__ import annotations

import hashlib
import secrets
from typing import Literal

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from owner_agent.engine import require
from shared.protocol import expires_in


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryInput(Input):
    expected_revision: StrictInt = Field(ge=1)
    memory: dict


class RevisionInput(Input):
    expected_revision: StrictInt = Field(ge=1)


class PolicyInput(RevisionInput):
    enabled: StrictBool
    expires_at: str | None = None


class ReleaseInput(RevisionInput):
    goal_id: str = Field(min_length=1, max_length=128)
    provider: Literal["fireworks", "nebius", "none"]
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ApprovalInput(Input):
    agreement_id: str = Field(min_length=1, max_length=128)
    revision: StrictInt = Field(ge=1)
    agreement_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class WithdrawalInput(RevisionInput):
    agreement_id: str = Field(min_length=1, max_length=128)
    base_revision: StrictInt = Field(ge=1)
    commitment_ids: list[str] = Field(min_length=1, max_length=12)


class RefusalInput(RevisionInput):
    request_id: str = Field(min_length=1, max_length=128)


class GoalInput(Input):
    goal: dict


class AgreementInput(Input):
    agreement: dict


class QuestionInput(Input):
    request: dict


class PrepareInput(AgreementInput):
    consent: dict


class DispatchInput(Input):
    agreement_id: str = Field(min_length=1, max_length=128)
    revision: StrictInt = Field(ge=1)
    mutation_id: str = Field(min_length=1, max_length=128)
    reservation_id: str = Field(min_length=1, max_length=200)
    fence: StrictInt = Field(ge=1)


class SampleSetupInput(GoalInput):
    provider: Literal["fireworks", "nebius", "none"] = "none"
    enable_policy: StrictBool = False


class EditInput(Input):
    summary: str = Field(min_length=1, max_length=1000)


def mount_living_routes(app, engine):
    @app.post("/sample/session")
    def sample_session(request: Request):
        require(engine.config.get("fictional_sample") is True, "Fictional sessions are unavailable for this owner.", 404)
        require(request.headers.get("origin") == engine.origin, "An exact owner Origin is required for the fictional workspace.", 403)
        token = secrets.token_urlsafe(40)
        expiry = expires_in(engine.config.get("session_ttl", 3600))
        with engine.lock, engine.vault.transaction() as db:
            db.execute("INSERT INTO sessions(token_hash,expires_at) VALUES(?,?)", (hashlib.sha256(token.encode()).hexdigest(), expiry))
        return {"token": token, "expires_at": expiry, "owner_id": engine.owner_id, "sample": True, "authority": "fictional-sample-only"}

    @app.get("/api/v2/state")
    def state():
        return engine.living.state()

    @app.post("/api/v2/memory")
    def memory(payload: MemoryInput):
        return engine.living.save_memory(payload.expected_revision, payload.memory)

    @app.post("/api/v2/memory/{memory_id}/delete")
    def delete_memory(memory_id: str, payload: RevisionInput):
        return engine.living.delete_memory(memory_id, payload.expected_revision)

    @app.post("/api/v2/policy")
    def policy(payload: PolicyInput):
        return engine.living.set_policy(payload.expected_revision, payload.enabled, payload.expires_at)

    @app.get("/api/v2/offer-preview")
    def preview(goal_id: str, provider: Literal["fireworks", "nebius", "none"] = "none"):
        result = engine.living.preview(goal_id, provider)
        return JSONResponse(result, headers={"X-Preview-Digest": result["preview_digest"]})

    @app.post("/api/v2/release")
    def release(payload: ReleaseInput):
        return engine.living.release(payload.goal_id, payload.provider, payload.preview_digest, payload.expected_revision)

    @app.post("/api/v2/approve")
    def approve(payload: ApprovalInput):
        return engine.living.approve(payload.agreement_id, payload.revision, payload.agreement_digest)

    @app.post("/api/v2/withdraw")
    def withdraw(payload: WithdrawalInput):
        return engine.living.withdraw(payload.agreement_id, payload.base_revision, payload.commitment_ids, payload.expected_revision)

    @app.post("/api/v2/refuse")
    def refuse(payload: RefusalInput):
        return engine.living.refuse(payload.request_id, payload.expected_revision)

    @app.post("/api/v2/requests/{request_id}/accept-invitation")
    def invitation(request_id: str, payload: RevisionInput):
        return engine.living.accept_invitation(request_id, payload.expected_revision)

    @app.post("/api/v2/calendar/{event_id}/edit")
    def edit(event_id: str, payload: EditInput):
        require(engine.config.get("fictional_sample") is True, "The local calendar edit fixture is fictional only.", 404)
        with engine.lock:
            try:
                return engine.living.calendar.edit(event_id, payload.summary)
            except KeyError:
                from fastapi import HTTPException
                raise HTTPException(404, "Local calendar entry not found.")

    @app.get("/coordination/v2/status")
    def status(goal_id: str | None = None):
        return engine.living.status(goal_id)

    @app.post("/coordination/v2/goal")
    def goal(payload: GoalInput):
        return engine.living.remember_goal(payload.goal)

    @app.post("/coordination/v2/question")
    def question(payload: QuestionInput):
        return engine.living.question(payload.request)

    @app.post("/coordination/v2/attest")
    def attest(payload: AgreementInput):
        return engine.living.attest(payload.agreement)

    @app.post("/coordination/v2/prepare")
    def prepare(payload: PrepareInput):
        return engine.living.prepare(payload.agreement, payload.consent)

    @app.post("/coordination/v2/dispatch")
    def dispatch(payload: DispatchInput):
        return engine.living.dispatch(payload.model_dump())

    @app.post("/coordination/v2/reconcile")
    def reconcile(payload: DispatchInput):
        return engine.living.dispatch(payload.model_dump(), reconcile=True)

    @app.get("/coordination/v2/events")
    def events(agreement_id: str):
        return engine.living.signed_observation(agreement_id)

    @app.post("/coordination/v2/sample/setup")
    def sample_setup(payload: SampleSetupInput):
        return engine.living.sample_setup(payload.goal, payload.provider, payload.enable_policy)

    @app.post("/coordination/v2/sample/approve")
    def sample_approve(payload: AgreementInput):
        return engine.living.sample_approve(payload.agreement)
