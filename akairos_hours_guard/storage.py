from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).with_name("hours_guard.db")


def connect(path: str | Path | None = None):
    db = Path(path) if path else DB_PATH
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def init_db(path=None):
    with connect(path) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            employee_id TEXT NOT NULL,
            name TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sent_alerts (
            fingerprint TEXT PRIMARY KEY,
            sent_at TEXT NOT NULL,
            severity TEXT,
            channel TEXT,
            recipient TEXT,
            message TEXT
        );
        """)


def save_snapshot(week_key: str, rows: list[dict], path=None):
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with connect(path) as con:
        for row in rows:
            con.execute(
                "INSERT INTO snapshots(week_key, created_at, employee_id, name, payload) VALUES(?,?,?,?,?)",
                (week_key, now, row.get("employee_id", ""), row.get("name", ""), json.dumps(row, default=str)),
            )


def was_sent(fingerprint: str, path=None) -> bool:
    with connect(path) as con:
        row = con.execute("SELECT 1 FROM sent_alerts WHERE fingerprint=?", (fingerprint,)).fetchone()
        return bool(row)


def mark_sent(fingerprint: str, severity: str, channel: str, recipient: str, message: str, path=None):
    with connect(path) as con:
        con.execute(
            "INSERT OR REPLACE INTO sent_alerts(fingerprint, sent_at, severity, channel, recipient, message) VALUES(?,?,?,?,?,?)",
            (fingerprint, datetime.utcnow().isoformat(timespec="seconds") + "Z", severity, channel, recipient, message),
        )


def recent_alerts(limit=100, path=None):
    with connect(path) as con:
        rows = con.execute("SELECT * FROM sent_alerts ORDER BY sent_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
