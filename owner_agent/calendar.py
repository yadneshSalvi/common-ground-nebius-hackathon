"""Independent durable local calendar. Fault injection exercises actual writes."""
from __future__ import annotations
import hashlib
import json
import os
import secrets
import sqlite3
import threading
from pathlib import Path


def event_id_for(action_id: str) -> str:
    return "cg-" + hashlib.sha256(action_id.encode()).hexdigest()[:40]


class CalendarStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, etag TEXT NOT NULL, user_edited INTEGER NOT NULL DEFAULT 0)")
        os.chmod(self.path, 0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def intended(action: dict, proposal_id: str) -> dict:
        return {"event_id": action["event_id"], "action_id": action["action_id"], "proposal_id": proposal_id, "summary": action["label"], "start": action["start"], "end": action["end"], "date": action["date"], "timezone": action["timezone"]}

    def get(self, event_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            return {**json.loads(row["payload"]), "etag": row["etag"], "user_edited": bool(row["user_edited"])} if row else None

    def list(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM events ORDER BY event_id").fetchall()
            return [{**json.loads(r["payload"]), "etag": r["etag"], "user_edited": bool(r["user_edited"])} for r in rows]

    def insert(self, action: dict, proposal_id: str) -> dict:
        event = self.intended(action, proposal_id)
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload,etag,user_edited FROM events WHERE event_id=?", (action["event_id"],)).fetchone()
            if row:
                if json.loads(row["payload"]) != event or row["user_edited"]:
                    raise ValueError("Calendar precondition conflict")
                return {**event, "etag": row["etag"], "user_edited": False}
            etag = '"' + secrets.token_hex(24) + '"'
            db.execute("INSERT INTO events(event_id,payload,etag) VALUES(?,?,?)", (action["event_id"], json.dumps(event), etag))
        return {**event, "etag": etag, "user_edited": False}

    def edit(self, event_id: str, summary: str) -> dict:
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM events WHERE event_id=?", (event_id,)).fetchone()
            if not row:
                raise KeyError(event_id)
            event = json.loads(row["payload"])
            event["summary"] = summary
            etag = '"' + secrets.token_hex(24) + '"'
            db.execute("UPDATE events SET payload=?,etag=?,user_edited=1 WHERE event_id=?", (json.dumps(event), etag, event_id))
        return {**event, "etag": etag, "user_edited": True}

    def delete_if_unchanged(self, event_id: str, etag: str | None) -> tuple[bool, dict | None]:
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if not row:
                return True, None
            event = {**json.loads(row["payload"]), "etag": row["etag"], "user_edited": bool(row["user_edited"])}
            if etag is None or row["etag"] != etag or row["user_edited"]:
                return False, event
            db.execute("DELETE FROM events WHERE event_id=? AND etag=? AND user_edited=0", (event_id, etag))
            return True, None

    def remove_by_owner(self, event_id: str, expected_etag: str) -> dict:
        """Explicit owner decision, separate from restricted automatic compensation.

        The current ETag is still mandatory: confirming an earlier version never
        authorizes removing an entry changed after the confirmation was shown.
        """
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise KeyError(event_id)
            if row["etag"] != expected_etag:
                raise ValueError("Calendar entry changed after owner review")
            event = {**json.loads(row["payload"]), "etag": row["etag"], "user_edited": bool(row["user_edited"])}
            deleted = db.execute("DELETE FROM events WHERE event_id=? AND etag=?", (event_id, expected_etag))
            if deleted.rowcount != 1:
                raise ValueError("Calendar entry changed during conditional removal")
            return event
