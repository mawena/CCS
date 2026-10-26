"""Historique local : relevés d'usage et événements (SQLite)."""

import json
import os
import sqlite3
import threading
from dataclasses import dataclass

from . import core

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    ts REAL NOT NULL, profile TEXT NOT NULL, kind TEXT NOT NULL,
    percent REAL NOT NULL, resets_at REAL
);
CREATE INDEX IF NOT EXISTS samples_idx ON samples (profile, kind, ts);
CREATE TABLE IF NOT EXISTS events (
    ts REAL NOT NULL, type TEXT NOT NULL, profile TEXT, detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_idx ON events (type, ts);
"""

RETENTION_S = 60 * 24 * 3600


@dataclass
class Event:
    ts: float
    type: str
    profile: str | None
    detail: dict


class Store:
    def __init__(self, path=None):
        self.path = path or core.paths().store / "history.db"
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.path.exists():
            os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600))
        self._lock = threading.Lock()
        self.db = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    def _write(self, sql, rows):
        with self._lock, self.db:
            self.db.executemany(sql, rows)

    def add_samples(self, ts, profile, limits):
        self._write("INSERT INTO samples VALUES (?, ?, ?, ?, ?)", [
            (ts, profile, lim.kind, lim.percent,
             lim.resets_at.timestamp() if lim.resets_at else None)
            for lim in limits])

    def samples(self, profile, kind, since):
        with self._lock:
            return self.db.execute(
                "SELECT ts, percent, resets_at FROM samples "
                "WHERE profile = ? AND kind = ? AND ts >= ? ORDER BY ts",
                (profile, kind, since)).fetchall()

    def add_event(self, ts, type, profile, detail):
        self._write("INSERT INTO events VALUES (?, ?, ?, ?)",
                    [(ts, type, profile, json.dumps(detail))])

    def events(self, since, type=None, profile=None):
        sql, args = "SELECT ts, type, profile, detail FROM events WHERE ts >= ?", [since]
        if type:
            sql, args = sql + " AND type = ?", args + [type]
        if profile:
            sql, args = sql + " AND profile = ?", args + [profile]
        with self._lock:
            rows = self.db.execute(sql + " ORDER BY ts", args).fetchall()
        return [Event(ts, t, p, json.loads(d)) for ts, t, p, d in rows]

    def last_event(self, type, profile=None):
        sql, args = "SELECT ts, type, profile, detail FROM events WHERE type = ?", [type]
        if profile:
            sql, args = sql + " AND profile = ?", args + [profile]
        with self._lock:
            row = self.db.execute(sql + " ORDER BY ts DESC LIMIT 1", args).fetchone()
        return Event(row[0], row[1], row[2], json.loads(row[3])) if row else None

    def active_periods(self, since, until):
        """Périodes (début, fin, profil) d'après les événements de bascule."""
        with self._lock:
            before = self.db.execute(
                "SELECT ts, profile FROM events WHERE type = 'switch' AND ts <= ? "
                "ORDER BY ts DESC LIMIT 1", (since,)).fetchone()
            after = self.db.execute(
                "SELECT ts, profile FROM events WHERE type = 'switch' AND ts > ? AND ts < ? "
                "ORDER BY ts", (since, until)).fetchall()
        points = ([(since, before[1])] if before else []) + list(after)
        out = []
        for i, (start, profile) in enumerate(points):
            end = points[i + 1][0] if i + 1 < len(points) else until
            if end > start:
                out.append((start, end, profile))
        return out

    def prune(self, before):
        with self._lock, self.db:
            self.db.execute("DELETE FROM samples WHERE ts < ?", (before,))
            self.db.execute("DELETE FROM events WHERE ts < ?", (before,))
