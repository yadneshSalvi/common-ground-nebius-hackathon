from __future__ import annotations
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from shared.schema import GOAL
from shared.protocol import utc_now


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS nonces (issuer TEXT, nonce TEXT, PRIMARY KEY(issuer,nonce)); CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires_at TEXT NOT NULL);")
            db.execute("CREATE TABLE IF NOT EXISTS deliveries(message_id TEXT PRIMARY KEY, issuer TEXT NOT NULL, nonce TEXT NOT NULL, message_digest TEXT NOT NULL, result TEXT NOT NULL, UNIQUE(issuer,nonce))")
            if not db.execute("SELECT 1 FROM state WHERE id=1").fetchone():
                initial = {"goal": GOAL, "owners": [], "offers": {}, "consent_revisions": {}, "proposal": None, "archive": {}, "approvals": {}, "state": "COLLECTING", "actions": {}, "model_runs": [], "disclosures": [], "history": [], "revision": 1, "planning": {"status": "IDLE", "phase": None, "error": None}, "outbox": {}, "reservations": {}, "version": 0, "cancel_requested": False, "revoked_keys": [], "created_at": utc_now()}
                db.execute("INSERT INTO state VALUES(1,?)", (json.dumps(initial),))
        self.path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def transaction(self):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = json.loads(db.execute("SELECT value FROM state WHERE id=1").fetchone()[0])
            try:
                yield state, db
                db.execute("UPDATE state SET value=? WHERE id=1", (json.dumps(state, ensure_ascii=False),))
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def read(self):
        with self.lock, self.connect() as db:
            return json.loads(db.execute("SELECT value FROM state WHERE id=1").fetchone()[0])

    @staticmethod
    def event(state, kind, summary, data=None):
        state["history"].append({"sequence": len(state["history"]) + 1, "time": utc_now(), "type": kind, "summary": summary, "data": data or {}})
        state["revision"] += 1
