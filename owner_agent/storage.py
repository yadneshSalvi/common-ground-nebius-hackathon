"""Encrypted private state with durable owner coordination records."""
from __future__ import annotations
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from cryptography.fernet import Fernet


class Vault:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        key_path = self.directory / "vault.key"
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(Fernet.generate_key())
                stream.flush()
                os.fsync(stream.fileno())
        self.cipher = Fernet(key_path.read_bytes())
        self.path = self.directory / "vault.sqlite3"
        with self.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS private_state(id INTEGER PRIMARY KEY CHECK(id=1),ciphertext BLOB NOT NULL);
              CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,expires_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS reservations(reservation_id TEXT PRIMARY KEY,proposal_id TEXT UNIQUE NOT NULL,fence INTEGER UNIQUE NOT NULL,lease_expires_at TEXT NOT NULL,consent_revision INTEGER NOT NULL,constraint_revision INTEGER NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS actions(action_id TEXT PRIMARY KEY,proposal_id TEXT NOT NULL,reservation_id TEXT NOT NULL,fence INTEGER NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,event_id TEXT NOT NULL,etag TEXT,authorized_at TEXT,transmitted_at TEXT,verified_at TEXT,error TEXT);
              CREATE TABLE IF NOT EXISTS used_nonces(nonce TEXT PRIMARY KEY,message_id TEXT NOT NULL,proposal_id TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS outbox(message_id TEXT PRIMARY KEY,route TEXT NOT NULL,payload TEXT NOT NULL,delivered INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS living_reservations(reservation_id TEXT PRIMARY KEY,agreement_id TEXT NOT NULL,revision INTEGER NOT NULL,fence INTEGER UNIQUE NOT NULL,lease_expires_at TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,UNIQUE(agreement_id,revision));
              CREATE TABLE IF NOT EXISTS living_mutations(mutation_id TEXT PRIMARY KEY,agreement_id TEXT NOT NULL,revision INTEGER NOT NULL,reservation_id TEXT NOT NULL,fence INTEGER NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,event_id TEXT NOT NULL,etag TEXT,authorized_at TEXT NOT NULL,transmitted_at TEXT,verified_at TEXT,error TEXT);
              CREATE TABLE IF NOT EXISTS living_nonces(nonce TEXT PRIMARY KEY,message_id TEXT NOT NULL,agreement_id TEXT NOT NULL,revision INTEGER NOT NULL);
            ''')
        os.chmod(self.path, 0o600)
        os.chmod(key_path, 0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def read(self, db=None):
        if db is None:
            with self.connect() as conn:
                return self.read(conn)
        row = db.execute("SELECT ciphertext FROM private_state WHERE id=1").fetchone()
        return json.loads(self.cipher.decrypt(row[0])) if row else None

    def write(self, db, state):
        ciphertext = self.cipher.encrypt(json.dumps(state, ensure_ascii=False).encode())
        db.execute("INSERT INTO private_state(id,ciphertext) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET ciphertext=excluded.ciphertext", (ciphertext,))
