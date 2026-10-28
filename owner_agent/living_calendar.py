"""Owner-local calendar effects for v2 living agreements.

Creation provenance and stable event identity survive agreement amendments. A
write is conditional on both the last observed version and the absence of a
manual edit. This is a durable local adapter, not a Google Calendar simulation.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

INTENT_KEYS = frozenset({"schema_version", "action_id", "commitment_id", "owner_id", "task_id", "event_id", "label", "date", "timezone", "start", "end", "location", "creation"})
IMMUTABLE_KEYS = ("schema_version", "action_id", "commitment_id", "owner_id", "task_id", "event_id", "creation")


def event_id_for(action_id: str) -> str:
    if not isinstance(action_id, str) or not action_id:
        raise ValueError("A stable action ID is required")
    return "cg2" + hashlib.sha256(action_id.encode()).hexdigest()[:40]


def normalize_intent(intent: dict) -> dict:
    """Return only the reviewed public event fields, never private metadata."""
    if not isinstance(intent, dict) or not INTENT_KEYS <= intent.keys():
        raise ValueError("Incomplete calendar intent")
    value = {key: deepcopy(intent[key]) for key in INTENT_KEYS}
    if type(value["schema_version"]) is not int or value["schema_version"] != 2:
        raise ValueError("Calendar intent requires schema version 2")
    for key in ("action_id", "commitment_id", "owner_id", "task_id", "label", "date", "timezone"):
        if not isinstance(value[key], str) or not value[key] or len(value[key]) > 1000:
            raise ValueError(f"Invalid calendar field: {key}")
    if value["event_id"] != event_id_for(value["action_id"]):
        raise ValueError("Event ID does not match the stable action")
    if date.fromisoformat(value["date"]).isoformat() != value["date"]:
        raise ValueError("Use an exact ISO calendar date")
    try:
        tz = ZoneInfo(value["timezone"])
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Unknown IANA calendar timezone") from exc
    if any(type(value[k]) is not int for k in ("start", "end")) or not 0 <= value["start"] < value["end"] <= 1440:
        raise ValueError("Invalid calendar interval")
    midnight = datetime.fromisoformat(value["date"]).replace(tzinfo=tz)
    endpoints = [midnight + timedelta(minutes=value[k]) for k in ("start", "end")]
    for stamp in endpoints:
        if stamp.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != stamp.replace(tzinfo=None) or stamp.replace(fold=0).utcoffset() != stamp.replace(fold=1).utcoffset():
            raise ValueError("Calendar wall time is nonexistent or ambiguous; review the interval")
    if endpoints[0].utcoffset() != endpoints[1].utcoffset():
        raise ValueError("Calendar interval crosses a timezone transition; review separate intervals")
    location, creation = value["location"], value["creation"]
    if not isinstance(location, dict) or set(location) != {"start", "end"} or any(not isinstance(v, str) or not v or len(v) > 1000 for v in location.values()):
        raise ValueError("Invalid calendar locations")
    if not isinstance(creation, dict) or set(creation) != {"agreement_id", "revision", "created_at"}:
        raise ValueError("Invalid calendar creation provenance")
    if not isinstance(creation["agreement_id"], str) or not creation["agreement_id"] or type(creation["revision"]) is not int or creation["revision"] < 1 or not isinstance(creation["created_at"], str) or not creation["created_at"]:
        raise ValueError("Invalid calendar creation provenance")
    try:
        created = datetime.fromisoformat(creation["created_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid calendar creation timestamp") from exc
    if created.tzinfo is None:
        raise ValueError("Calendar creation timestamp requires an offset")
    return value


def require_same_identity(before: dict, after: dict) -> None:
    if any(before.get(key) != after.get(key) for key in IMMUTABLE_KEYS):
        raise ValueError("Calendar identity and creation provenance are immutable")


class LivingCalendarStore:
    event_id_for = staticmethod(event_id_for)
    intended = staticmethod(normalize_intent)

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS living_events(event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, etag TEXT NOT NULL, user_edited INTEGER NOT NULL DEFAULT 0)")
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _observed(row):
        return {**json.loads(row["payload"]), "etag": row["etag"], "user_edited": bool(row["user_edited"])} if row else None

    def get(self, event_id: str) -> dict | None:
        with self.connect() as db:
            return self._observed(db.execute("SELECT * FROM living_events WHERE event_id=?", (event_id,)).fetchone())

    def list(self) -> list[dict]:
        with self.connect() as db:
            return [self._observed(row) for row in db.execute("SELECT * FROM living_events ORDER BY event_id").fetchall()]

    def insert(self, intent: dict) -> dict:
        event = self.intended(intent)
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM living_events WHERE event_id=?", (event["event_id"],)).fetchone()
            if row:
                observed = self._observed(row)
                if self.intended(observed) != event or observed["user_edited"]:
                    raise ValueError("Calendar precondition conflict")
                return observed
            etag = '"' + secrets.token_hex(24) + '"'
            db.execute("INSERT INTO living_events VALUES(?,?,?,0)", (event["event_id"], json.dumps(event), etag))
        return {**event, "etag": etag, "user_edited": False}

    def update_if_unchanged(self, event_id: str, expected_etag: str | None, intent: dict) -> tuple[bool, dict | None]:
        event = self.intended(intent)
        if event["event_id"] != event_id:
            raise ValueError("Calendar event ID mismatch")
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM living_events WHERE event_id=?", (event_id,)).fetchone()
            observed = self._observed(row)
            if not observed or not expected_etag or observed["etag"] != expected_etag or observed["user_edited"]:
                return False, observed
            require_same_identity(observed, event)
            if self.intended(observed) == event:
                return True, observed
            etag = '"' + secrets.token_hex(24) + '"'
            db.execute("UPDATE living_events SET payload=?,etag=? WHERE event_id=? AND etag=? AND user_edited=0", (json.dumps(event), etag, event_id, expected_etag))
        return True, {**event, "etag": etag, "user_edited": False}

    def delete_if_unchanged(self, event_id: str, expected_etag: str | None) -> tuple[bool, dict | None]:
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM living_events WHERE event_id=?", (event_id,)).fetchone()
            observed = self._observed(row)
            if observed is None:
                return True, None
            if not expected_etag or observed["etag"] != expected_etag or observed["user_edited"]:
                return False, observed
            db.execute("DELETE FROM living_events WHERE event_id=? AND etag=? AND user_edited=0", (event_id, expected_etag))
        return True, None

    def edit(self, event_id: str, summary: str) -> dict:
        """Authored local manual-edit fixture; it never grants compensation."""
        if not isinstance(summary, str) or not summary or len(summary) > 1000:
            raise ValueError("Invalid calendar label")
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM living_events WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise KeyError(event_id)
            event = json.loads(row["payload"])
            event["label"] = summary
            etag = '"' + secrets.token_hex(24) + '"'
            db.execute("UPDATE living_events SET payload=?,etag=?,user_edited=1 WHERE event_id=?", (json.dumps(event), etag, event_id))
        return {**event, "etag": etag, "user_edited": True}
