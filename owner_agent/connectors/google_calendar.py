"""Conditional Google Calendar v3 adapter, not enabled by the sample launcher.

An owner supplies a token callback and a dedicated app-created calendar ID.
OAuth acquisition/refresh and live-account qualification are deliberately outside
this module. Tokens are never persisted here. Requests do not follow redirects,
send guest invitations, or retry an uncertain write. A durable pending intent
allows later exact readback after a lost response or process restart.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from owner_agent.living_calendar import event_id_for, normalize_intent, require_same_identity

BASE_URL = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar.app.created"
_READ_ONLY = {"kind", "etag", "id", "created", "updated", "htmlLink", "iCalUID", "creator", "organizer"}
_DEFAULTS = {"eventType": "default", "endTimeUnspecified": False, "status": "confirmed", "transparency": "opaque", "visibility": "default", "sequence": 0, "guestsCanInviteOthers": True, "guestsCanModify": False, "guestsCanSeeOtherGuests": True, "anyoneCanAddSelf": False, "locked": False, "privateCopy": False}


class CalendarUnavailable(RuntimeError):
    """No authoritative observation was obtained; never means event absence."""


class CalendarAmbiguous(CalendarUnavailable):
    """A write may have happened. Reconcile by reading; do not blindly retry."""


class CalendarConflict(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _surface(raw: dict) -> dict:
    """Include all mutable fields, including unknown future fields, in checks."""
    result = {k: deepcopy(v) for k, v in raw.items() if k not in _READ_ONLY}
    for key, default in _DEFAULTS.items():
        if result.get(key) == default:
            result.pop(key)
    for key in ("description", "location", "colorId"):
        if result.get(key) == "":
            result.pop(key)
    for key in ("attendees", "recurrence", "attachments"):
        if result.get(key) == []:
            result.pop(key)
    for key in ("start", "end"):
        if key in result and "dateTime" in result[key]:
            stamp = datetime.fromisoformat(result[key]["dateTime"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise CalendarUnavailable("Calendar returned a timezone-free instant")
            result[key]["dateTime"] = stamp.astimezone(timezone.utc).isoformat()
    return result


def _body(intent: dict) -> dict:
    tz = ZoneInfo(intent["timezone"])
    start = datetime.fromisoformat(intent["date"]).replace(tzinfo=tz) + timedelta(minutes=intent["start"])
    end = datetime.fromisoformat(intent["date"]).replace(tzinfo=tz) + timedelta(minutes=intent["end"])
    # Reject nonexistent or ambiguous wall times rather than choosing a hidden fold.
    for stamp in (start, end):
        if stamp.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != stamp.replace(tzinfo=None) or stamp.replace(fold=0).utcoffset() != stamp.replace(fold=1).utcoffset():
            raise ValueError("Calendar wall time is nonexistent or ambiguous; review a different interval")
    return {"id": intent["event_id"], "summary": intent["label"], "location": intent["location"]["start"] + " → " + intent["location"]["end"], "start": {"dateTime": start.isoformat(), "timeZone": intent["timezone"]}, "end": {"dateTime": end.isoformat(), "timeZone": intent["timezone"]}, "reminders": {"useDefault": False}, "extendedProperties": {"private": {"cg_version": "2", "cg_action": intent["action_id"], "cg_intent": hashlib.sha256(_canonical(intent).encode()).hexdigest()}}}


class GoogleCalendarStore:
    event_id_for = staticmethod(event_id_for)
    intended = staticmethod(normalize_intent)

    def __init__(self, path: str | Path, calendar_id: str, token_provider: Callable[[], str], *, transport: httpx.BaseTransport | None = None):
        if not isinstance(calendar_id, str) or not calendar_id or calendar_id == "primary":
            raise ValueError("Use a dedicated app-created calendar, not the primary calendar")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.calendar_id, self.token_provider = calendar_id, token_provider
        self.transport = transport
        self.lock = threading.RLock()
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS calendar_ledger(event_id TEXT PRIMARY KEY,state TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS calendar_identity(calendar_id TEXT NOT NULL)")
            row = db.execute("SELECT calendar_id FROM calendar_identity").fetchone()
            if row and row[0] != calendar_id:
                raise ValueError("Calendar ledger is bound to a different calendar")
            if not row:
                db.execute("INSERT INTO calendar_identity VALUES(?)", (calendar_id,))
        os.chmod(self.path, 0o600)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _read(self, event_id):
        with self._db() as db:
            row = db.execute("SELECT state FROM calendar_ledger WHERE event_id=?", (event_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def _save(self, event_id, state):
        with self._db() as db:
            db.execute("INSERT INTO calendar_ledger VALUES(?,?) ON CONFLICT(event_id) DO UPDATE SET state=excluded.state", (event_id, _canonical(state)))

    def _request(self, method, event_id=None, *, body=None, etag=None):
        token = self.token_provider()
        if not isinstance(token, str) or not token:
            raise CalendarUnavailable("Owner calendar authorization is unavailable")
        url = BASE_URL + "/calendars/" + quote(self.calendar_id, safe="") + "/events"
        if event_id:
            url += "/" + quote(event_id, safe="")
        headers = {"Authorization": "Bearer " + token}
        if etag:
            headers["If-Match"] = etag
        try:
            with httpx.Client(transport=self.transport, follow_redirects=False, timeout=20, trust_env=False) as client:
                response = client.request(method, url, headers=headers, json=body, params={"sendUpdates": "none"} if method != "GET" else None)
        except httpx.HTTPError as exc:
            cls = CalendarUnavailable if method == "GET" else CalendarAmbiguous
            raise cls("Calendar transport failed; no successful effect is inferred") from exc
        if response.status_code in (401, 403):
            raise CalendarUnavailable("Owner calendar access is unavailable")
        if response.status_code >= 500 or response.status_code in (408, 429):
            cls = CalendarUnavailable if method == "GET" else CalendarAmbiguous
            raise cls("Calendar provider did not confirm the request")
        if response.status_code not in (200, 201, 204, 404, 409, 410, 412):
            raise CalendarUnavailable(f"Calendar request returned HTTP {response.status_code}")
        return response

    def _observe(self, raw: dict, state: dict | None):
        event_id, etag = raw.get("id"), raw.get("etag")
        if not event_id or not isinstance(etag, str) or not etag:
            raise CalendarUnavailable("Calendar response lacks event identity or version")
        if not state:
            return {"event_id": event_id, "etag": etag, "user_edited": True, "unmanaged": True}
        surface = _surface(raw)
        pending = state.get("pending")
        if pending and pending["kind"] in ("insert", "update") and surface == pending["surface"]:
            intent = pending["intent"]
            state = {"intent": intent, "etag": etag, "surface": surface, "pending": None}
            self._save(event_id, state)
        intent = state["intent"]
        edited = etag != state.get("etag") or surface != state.get("surface")
        # Expose edited event content only to its owner's local surface. The broker
        # receives receipts, never this object. Identity remains the durable binding.
        observed = deepcopy(intent)
        if "summary" in raw:
            observed["label"] = raw["summary"]
        for key in ("start", "end"):
            part = raw.get(key, {})
            if "dateTime" in part:
                stamp = datetime.fromisoformat(part["dateTime"].replace("Z", "+00:00")).astimezone(ZoneInfo(intent["timezone"]))
                offset_days = (stamp.date() - datetime.fromisoformat(intent["date"]).date()).days
                observed[key] = offset_days * 1440 + stamp.hour * 60 + stamp.minute
            else:
                edited = True
        return {**observed, "etag": etag, "user_edited": edited}

    def get(self, event_id):
        with self.lock:
            response = self._request("GET", event_id)
            if response.status_code == 404:
                # A 404 can also mean lost calendar access. Prove calendar access
                # independently before treating the specific event as absent.
                self._confirm_calendar_access()
                return None
            if response.status_code == 410:
                self._confirm_calendar_access()
                return None
            raw = response.json()
            if raw.get("id") != event_id:
                raise CalendarUnavailable("Calendar returned a different event")
            if raw.get("status") == "cancelled":
                return None
            return self._observe(raw, self._read(event_id))

    def _confirm_calendar_access(self):
        token = self.token_provider()
        try:
            with httpx.Client(transport=self.transport, follow_redirects=False, timeout=20, trust_env=False) as client:
                response = client.get(BASE_URL + "/calendars/" + quote(self.calendar_id, safe=""), headers={"Authorization": "Bearer " + token})
        except httpx.HTTPError as exc:
            raise CalendarUnavailable("Calendar absence could not be confirmed") from exc
        if response.status_code != 200 or response.json().get("id") != self.calendar_id:
            raise CalendarUnavailable("Calendar access could not be confirmed; absence is unknown")

    def list(self):
        # Read only app-known IDs. Never enumerate unrelated personal events.
        with self._db() as db:
            ids = [row[0] for row in db.execute("SELECT event_id FROM calendar_ledger ORDER BY event_id")]
        return [item for event_id in ids if (item := self.get(event_id)) is not None]

    def insert(self, intent):
        intent = self.intended(intent)
        body = _body(intent)
        event_id = intent["event_id"]
        with self.lock:
            observed = self.get(event_id)
            if observed:
                if observed.get("user_edited") or self.intended(observed) != intent:
                    raise CalendarConflict("Calendar precondition conflict")
                return observed
            state = self._read(event_id)
            if state and state.get("intent"):
                require_same_identity(state["intent"], intent)
            self._save(event_id, {"intent": intent, "etag": None, "surface": None, "pending": {"kind": "insert", "intent": intent, "surface": _surface(body)}})
            response = self._request("POST", body=body)
            if response.status_code == 409:
                observed = self.get(event_id)
                if not observed or observed.get("user_edited") or self.intended(observed) != intent:
                    raise CalendarConflict("Calendar insert collided with another event")
                return observed
            if response.status_code not in (200, 201):
                raise CalendarAmbiguous("Calendar insert was not confirmed")
            observed = self.get(event_id)  # independent readback; never trust write ack alone
            if not observed or observed["user_edited"] or self.intended(observed) != intent:
                raise CalendarAmbiguous("Calendar insert readback did not match the intent")
            return observed

    def update_if_unchanged(self, event_id, expected_etag, intent):
        intent = self.intended(intent)
        if intent["event_id"] != event_id:
            raise CalendarConflict("Calendar event ID mismatch")
        with self.lock:
            observed = self.get(event_id)
            if not observed or not expected_etag or observed["etag"] != expected_etag or observed["user_edited"]:
                return False, observed
            require_same_identity(observed, intent)
            if self.intended(observed) == intent:
                return True, observed
            body = _body(intent)
            state = self._read(event_id)
            state["pending"] = {"kind": "update", "intent": intent, "surface": _surface(body)}
            self._save(event_id, state)
            response = self._request("PATCH", event_id, body=body, etag=expected_etag)
            if response.status_code in (404, 410, 412):
                state["pending"] = None
                self._save(event_id, state)
                return False, self.get(event_id)
            if response.status_code not in (200, 201):
                raise CalendarAmbiguous("Calendar update was not confirmed")
            result = self.get(event_id)
            if not result or result["user_edited"] or self.intended(result) != intent:
                raise CalendarAmbiguous("Calendar update readback did not match the intent")
            return True, result

    def delete_if_unchanged(self, event_id, expected_etag):
        with self.lock:
            observed = self.get(event_id)
            if observed is None:
                return True, None
            if not expected_etag or observed["etag"] != expected_etag or observed["user_edited"]:
                return False, observed
            state = self._read(event_id)
            state["pending"] = {"kind": "delete", "etag": expected_etag}
            self._save(event_id, state)
            response = self._request("DELETE", event_id, etag=expected_etag)
            if response.status_code == 412:
                state["pending"] = None
                self._save(event_id, state)
                return False, self.get(event_id)
            if response.status_code not in (200, 204, 404, 410):
                raise CalendarAmbiguous("Calendar deletion was not confirmed")
            current = self.get(event_id)
            if current is not None:
                raise CalendarAmbiguous("Calendar deletion was not confirmed by readback")
            state["pending"] = None
            self._save(event_id, state)
            return True, None

    def edit(self, event_id, summary):
        raise NotImplementedError("Manual-edit fixtures apply only to the local calendar adapter")
