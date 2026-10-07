"""Immutable experiment identity and explicit failed attempts in SQLite."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from .expressions import fingerprint


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY, identity TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL, proposal_json TEXT NOT NULL,
                config_json TEXT NOT NULL, status TEXT NOT NULL,
                metrics_json TEXT, error TEXT)""")

    def record(self, proposal, config, status, metrics=None, error=None):
        if status not in {"completed", "failed"}:
            raise ValueError("unsupported status")
        try:
            candidate = {"expression_fingerprint": fingerprint(proposal["expression"])}
        except (ValueError, TypeError, KeyError):
            candidate = proposal
        payload = json.dumps({"candidate": candidate, "config": config}, sort_keys=True, separators=(",", ":"), allow_nan=False)
        identity = hashlib.sha256(payload.encode()).hexdigest()
        with closing(sqlite3.connect(self.path)) as db, db:
            existing = db.execute("SELECT id, status FROM experiments WHERE identity=?", (identity,)).fetchone()
            if existing:
                return {"id": existing[0], "status": existing[1], "duplicate": True}
            cursor = db.execute("INSERT INTO experiments (identity,created_at,proposal_json,config_json,status,metrics_json,error) VALUES (?,?,?,?,?,?,?)",
                                (identity, datetime.now(timezone.utc).isoformat(), json.dumps(proposal, sort_keys=True), json.dumps(config, sort_keys=True), status,
                                 json.dumps(metrics, sort_keys=True, allow_nan=False) if metrics is not None else None, error))
            return {"id": cursor.lastrowid, "status": status, "duplicate": False}
