"""Durable v2 coordinator state; v1 audit/database are never rewritten."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from shared.protocol import utc_now


class LivingStore:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS living_state(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS living_deliveries(message_id TEXT PRIMARY KEY,issuer TEXT NOT NULL,nonce TEXT NOT NULL,message_digest TEXT NOT NULL,result TEXT NOT NULL,UNIQUE(issuer,nonce))")
            if not db.execute("SELECT 1 FROM living_state WHERE id=1").fetchone():
                state={"schema_version":2,"revision":1,"goal":None,"draft":None,"offers":{},"agreement":None,"pending":None,"archive":{},"goals":{},"consents":{},"receipts":{},"withdrawn":[],"withdrawals":[],"refusals":[],"questions":[],"history":[],"model_runs":[],"protocol_messages":[],"reservations":{},"outbox":{},"planning":{"status":"IDLE","purpose":None,"provider":None,"request_id":None},"status":"INITIAL","disruption_id":None,"observed_at":None,"sample_count":0,"created_at":utc_now()}
                db.execute("INSERT INTO living_state VALUES(1,?)",(json.dumps(state),))
        self.path.chmod(0o600)

    def connect(self):
        db=sqlite3.connect(self.path,timeout=10); db.row_factory=sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000"); db.execute("PRAGMA journal_mode=WAL")
        return db

    def read(self):
        with self.lock,self.connect() as db:
            return json.loads(db.execute("SELECT value FROM living_state WHERE id=1").fetchone()[0])

    @contextmanager
    def transaction(self):
        with self.lock,self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state=json.loads(db.execute("SELECT value FROM living_state WHERE id=1").fetchone()[0])
            try:
                yield state,db
                db.execute("UPDATE living_state SET value=? WHERE id=1",(json.dumps(state,ensure_ascii=False),))
                db.commit()
            except BaseException:
                db.rollback(); raise

    @staticmethod
    def event(state,kind,text,data=None):
        state["revision"]+=1
        state["history"].append({"sequence":len(state["history"])+1,"time":utc_now(),"type":kind,"summary":text,"data":data or {}})
