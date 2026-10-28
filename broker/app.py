from __future__ import annotations
import hmac
import os
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from typing import Literal
from broker.engine import Engine, BrokerError
from broker.planning import begin_plan, run_plan
from broker.execution import execute, compensate, new_round
from broker.exports import evidence, calendar_bytes


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Pair(Input):
    pair_code: str = Field(min_length=1, max_length=300)

class Plan(Input):
    mode: Literal["live", "local"]
    expected_revision: StrictInt = Field(ge=1)

class Execution(Input):
    proposal_id: str = Field(min_length=8, max_length=128)
    expected_version: StrictInt = Field(ge=1)

class ProposalInput(Input):
    proposal_id: str = Field(min_length=8, max_length=128)

class RevisionInput(Input):
    expected_revision: StrictInt = Field(ge=1)

class MessageInput(Input):
    message: dict


def create_app(config=None):
    engine = Engine(config or os.environ.get("COMMON_GROUND_BROKER_CONFIG", ".runtime/config.json"))
    app = FastAPI(title="Common Ground · released agreement broker", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine
    origin = engine.config.get("origin", "http://127.0.0.1:4301")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=engine.config.get("allowed_hosts", ["127.0.0.1", "localhost"]))

    @app.exception_handler(BrokerError)
    async def broker_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        path, supplied_origin = request.url.path, request.headers.get("origin")
        authorization = request.headers.get("authorization", "")
        try:
            if path.startswith("/api/"):
                if supplied_origin is not None and supplied_origin != origin:
                    raise BrokerError("This API accepts only the paired shared-room origin.", 403)
                if request.method not in ("GET", "HEAD", "OPTIONS") and supplied_origin != origin:
                    raise BrokerError("An exact shared-room Origin is required for mutations.", 403)
                if not (path == "/api/session" and request.method == "POST") and request.method != "OPTIONS":
                    engine.authenticate(authorization[7:] if authorization.startswith("Bearer ") else "")
            if path.startswith("/v1/"):
                if supplied_origin is not None or not hmac.compare_digest(authorization, "Bearer " + engine.config["broker_ingest_token"]):
                    raise BrokerError("Owner-service authority is required for this protocol route.", 403)
            response = await call_next(request)
        except BrokerError as error:
            response = JSONResponse({"detail": str(error)}, status_code=error.status)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    # Outermost CORS middleware must cover authentication errors as well as success.
    app.add_middleware(CORSMiddleware, allow_origins=[origin], allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"], allow_credentials=False)

    @app.get("/health")
    def health():
        return {"ok": True, "service": "released-agreement-broker"}

    @app.post("/api/session")
    def pair(payload: Pair):
        return engine.pair(payload.pair_code)

    @app.get("/api/session")
    def session(request: Request):
        return engine.authenticate(request.headers["authorization"][7:])

    @app.get("/api/state")
    def state():
        return engine.public_state()

    @app.post("/api/plan", status_code=202)
    def plan(payload: Plan, background: BackgroundTasks):
        result = begin_plan(engine, payload.mode, payload.expected_revision)
        background.add_task(run_plan, engine, payload.mode)
        return result

    @app.post("/api/execute")
    def enact(payload: Execution):
        return execute(engine, payload.proposal_id, payload.expected_version)

    @app.post("/api/reconcile")
    def reconcile(payload: ProposalInput):
        return execute(engine, payload.proposal_id, reconcile=True)

    @app.post("/api/compensate")
    def cancel(payload: ProposalInput):
        return compensate(engine, payload.proposal_id)

    @app.post("/api/new-round")
    def restart(payload: RevisionInput):
        return new_round(engine, payload.expected_revision)

    @app.get("/api/evidence")
    def export():
        return JSONResponse(evidence(engine), headers={"Content-Disposition": 'attachment; filename="common-ground-proof.json"'})

    @app.get("/api/agreement.ics")
    def ics():
        return Response(calendar_bytes(engine), media_type="text/calendar", headers={"Content-Disposition": 'attachment; filename="common-ground-agreement.ics"'})

    @app.get("/api/events")
    def events(after: int = 0):
        return {"events": [event for event in engine.store.read()["history"] if event["sequence"] > after]}

    @app.post("/v1/releases")
    def release(payload: MessageInput):
        return engine.ingest_release(payload.message)

    @app.post("/v1/approvals")
    def approve(payload: MessageInput):
        return engine.ingest_approval(payload.message)

    @app.post("/v1/withdrawals")
    def withdraw(payload: MessageInput):
        return engine.ingest_withdrawal(payload.message)

    @app.get("/v1/current")
    def current():
        return engine.current()

    @app.get("/v1/proposals/{proposal_id}")
    def proposal(proposal_id: str):
        return engine.current(proposal_id)

    if engine.config.get("bootstrap_members", True):
        engine.bootstrap_members()
    return app
