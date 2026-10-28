"""Owner-local FastAPI factory. Browser sessions and service capabilities never mix."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from owner_agent.engine import CAPABILITIES, FAULTS, OwnerEngine, require
from shared.protocol import digest, expires_in, parse_time


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PairInput(Input):
    pair_code: str = Field(min_length=1, max_length=300)


class PreferenceInput(Input):
    expected_revision: StrictInt = Field(ge=1)
    availability_start: StrictInt = Field(ge=0, le=1439)
    availability_end: StrictInt = Field(ge=1, le=1440)
    task_ids: list[str] = Field(min_length=1, max_length=5)
    ask_before_driving: StrictBool
    private_note: str | None = Field(default=None, max_length=2000)
    preference_cost: StrictInt | None = Field(default=None, ge=0, le=100)

    @field_validator("task_ids")
    @classmethod
    def valid_tasks(cls, tasks):
        if len(set(tasks)) != len(tasks) or any(task not in CAPABILITIES for task in tasks):
            raise ValueError("Select unique tasks from the appointment catalog")
        return tasks

    @model_validator(mode="after")
    def valid_interval(self):
        if self.availability_start >= self.availability_end:
            raise ValueError("Availability must end after it starts")
        return self


class ReleaseInput(Input):
    expected_revision: StrictInt = Field(ge=1)
    allow_inference: StrictBool
    preview_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class RevisionInput(Input):
    expected_revision: StrictInt = Field(ge=0)


class ApprovalInput(Input):
    proposal_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    expected_version: StrictInt = Field(ge=1)


class FaultInput(Input):
    mode: Literal["none", "timeout_after_write", "fail_before_write", "pause_before_send", "conflict_before_write"]


class EditInput(Input):
    summary: str = Field(min_length=1, max_length=300)


class RemoveInput(Input):
    expected_etag: str = Field(min_length=3, max_length=200)
    confirmation: Literal["remove-this-local-event"]


class PrepareInput(Input):
    proposal: dict
    approval: dict


class DispatchInput(Input):
    proposal_id: str = Field(min_length=1, max_length=200)
    action_id: str = Field(min_length=1, max_length=200)
    reservation_id: str = Field(min_length=1, max_length=200)
    fence: StrictInt = Field(ge=1)


class CancelInput(Input):
    proposal_id: str = Field(min_length=1, max_length=200)


class CompensateInput(Input):
    action_id: str = Field(min_length=1, max_length=200)


def create_app(config: dict | str | Path | None = None) -> FastAPI:
    if config is None:
        config = os.environ.get("COMMON_GROUND_OWNER_CONFIG")
        if not config:
            raise ValueError("Provide the owner-local configuration file")
    if isinstance(config, (str, Path)):
        config = json.loads(Path(config).read_text())
    engine = OwnerEngine(config)
    app = FastAPI(title=f"Common Ground · {engine.owner_id}'s private agent", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.owner = engine
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.get("allowed_hosts", ["127.0.0.1", "localhost"]))
    attempts: dict[str, list[float]] = {}

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        path = request.url.path
        origin = request.headers.get("origin")
        is_private = path.startswith("/api/")
        is_service = path.startswith("/coordination/")
        if is_private:
            if origin is not None and origin != engine.origin:
                return JSONResponse({"detail": "This owner accepts only its own trusted browser origin."}, status_code=403)
            if request.method not in ("GET", "HEAD") and origin != engine.origin:
                return JSONResponse({"detail": "An exact owner Origin is required for browser mutations."}, status_code=403)
            if not (path == "/api/session" and request.method == "POST"):
                authorization = request.headers.get("authorization", "")
                token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
                with engine.vault.connect() as db:
                    row = db.execute("SELECT expires_at FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone() if token else None
                if row is None or parse_time(row["expires_at"]) <= datetime.now(timezone.utc):
                    return JSONResponse({"detail": "Pair this owner to open its private workspace."}, status_code=401)
        if is_service:
            if origin is not None:
                return JSONResponse({"detail": "Coordination capabilities cannot be used by browser origins."}, status_code=403)
            expected = "Bearer " + config["service_token"]
            if not hmac.compare_digest(request.headers.get("authorization", ""), expected):
                return JSONResponse({"detail": "This coordination capability does not belong to this owner."}, status_code=401)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.get("/meta")
    def meta():
        return engine.meta()

    @app.get("/health")
    def health():
        return {"ok": True, "owner_id": engine.owner_id}

    @app.post("/api/session")
    def pair(payload: PairInput, request: Request):
        address = request.client.host if request.client else "local"
        now = time.monotonic()
        with engine.lock:
            recent = [stamp for stamp in attempts.get(address, []) if now - stamp < 60]
            require(len(recent) < 10, "Too many pairing attempts. Wait one minute.", 429)
            if not hmac.compare_digest(payload.pair_code, config["pair_code"]):
                attempts[address] = recent + [now]
                raise HTTPException(401, "The local pairing secret is incorrect.")
            attempts.pop(address, None)
            token = secrets.token_urlsafe(40)
            expires_at = expires_in(config.get("session_ttl", 3600))
            with engine.vault.transaction() as db:
                db.execute("DELETE FROM sessions WHERE expires_at<=?", (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),))
                db.execute("INSERT INTO sessions(token_hash,expires_at) VALUES(?,?)", (hashlib.sha256(token.encode()).hexdigest(), expires_at))
        return {"token": token, "expires_at": expires_at, "owner_id": engine.owner_id}

    @app.get("/api/session")
    def session():
        return {"owner_id": engine.owner_id, "authenticated": True}

    @app.get("/api/state")
    def state():
        return engine.state()

    @app.get("/api/release-preview")
    def preview(allow_inference: bool = False):
        payload = engine.preview(allow_inference)
        return JSONResponse(payload, headers={"X-Preview-Digest": digest(payload)})

    @app.post("/api/preferences")
    def preferences(payload: PreferenceInput):
        return engine.preferences(payload.model_dump())

    @app.post("/api/release")
    def release(payload: ReleaseInput):
        return engine.release(payload.expected_revision, payload.allow_inference, payload.preview_digest)

    @app.post("/api/approve")
    def approve(payload: ApprovalInput):
        return engine.approve(payload.proposal_id, payload.expected_version)

    @app.post("/api/withdraw")
    def withdraw(payload: RevisionInput):
        return engine.withdraw(payload.expected_revision)

    @app.post("/api/fault")
    def fault(payload: FaultInput):
        return engine.set_fault(payload.mode)

    @app.post("/api/calendar/{event_id}/edit")
    def edit(event_id: str, payload: EditInput):
        try:
            with engine.lock:
                return engine.calendar.edit(event_id, payload.summary)
        except KeyError as exc:
            raise HTTPException(404, "Local calendar entry not found.") from exc

    @app.post("/api/calendar/{event_id}/remove")
    def remove_event(event_id: str, payload: RemoveInput):
        return engine.remove_calendar_event(event_id, payload.expected_etag)

    @app.get("/api/calendar.ics")
    def calendar_export():
        from datetime import timedelta
        from icalendar import Calendar, Event
        calendar = Calendar()
        calendar.add("version", "2.0")
        calendar.add("prodid", "-//Common Ground//Owner local calendar//EN")
        calendar.add("calscale", "GREGORIAN")
        for stored in engine.calendar.list():
            day = datetime.fromisoformat(stored["date"])
            def instant(minutes):
                local = (day + timedelta(minutes=minutes)).replace(tzinfo=ZoneInfo(stored["timezone"]))
                return local.astimezone(timezone.utc)
            event = Event()
            event.add("uid", stored["event_id"] + "@common-ground.local")
            event.add("dtstamp", datetime.now(timezone.utc))
            event.add("dtstart", instant(stored["start"]))
            event.add("dtend", instant(stored["end"]))
            event.add("summary", stored["summary"])
            event.add("description", "Verified in an independent local sample calendar. No invitations sent.")
            calendar.add_component(event)
        return Response(calendar.to_ical(), media_type="text/calendar", headers={"Content-Disposition": f'attachment; filename="{engine.owner_id}-local-calendar.ics"'})

    @app.get("/coordination/status")
    def coordination_status():
        return engine.status()

    @app.post("/coordination/prepare")
    def prepare(payload: PrepareInput):
        return engine.prepare(payload.proposal, payload.approval)

    @app.post("/coordination/dispatch")
    def dispatch(payload: DispatchInput):
        return engine.dispatch(payload.model_dump())

    @app.post("/coordination/reconcile")
    def reconcile(payload: DispatchInput):
        return engine.dispatch(payload.model_dump(), reconcile=True)

    @app.post("/coordination/cancel")
    def cancel(payload: CancelInput):
        return engine.cancel(payload.proposal_id)

    @app.post("/coordination/compensate")
    def compensate(payload: CompensateInput):
        return engine.compensate(payload.action_id)

    @app.get("/coordination/events")
    def events(proposal_id: str | None = None):
        return {"owner_id": engine.owner_id, "events": engine.events(proposal_id)}

    # V2 routes must precede the frontend catch-all. Browser and service routes
    # retain the same distinct capability/Origin checks enforced above.
    from owner_agent.living_routes import mount_living_routes
    mount_living_routes(app, engine)

    dist = Path(config.get("dist_dir", Path(__file__).resolve().parents[1] / "dist" / "owner")).resolve()

    @app.get("/{path:path}")
    def frontend(path: str):
        if path.startswith(("api/", "coordination/")):
            raise HTTPException(404, "Endpoint not found")
        asset = (dist / path).resolve()
        if asset.is_relative_to(dist) and asset.is_file():
            return FileResponse(asset)
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        return Response("Owner frontend has not been built. Run npm run build.", status_code=503, media_type="text/plain")

    return app
