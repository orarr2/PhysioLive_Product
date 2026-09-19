"""SQLite session log.

Two tables:

- `sessions(id, exercise, started_at, ended_at, rep_count, good_count,
   avg_primary_min, avg_torso_max, notes)`
- `reps(id, session_id, rep_index, level, text, primary_min,
   primary_max, hip_min, hip_max, knee_min, knee_max,
   shoulder_min, shoulder_max, elbow_min, elbow_max,
   torso_vertical_max, knee_over_toe_max, frames, ts)`

Writes are batched: `SessionLog.append_rep()` queues rows in memory and
`SessionLog.flush()` commits them. The main loop should call `flush()`
about once per second to keep IO off the hot path.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_DB = (Path(__file__).resolve().parents[2]
              / "data" / "sessions" / "physiolive.db")


SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        exercise TEXT NOT NULL,
        started_at REAL NOT NULL,
        ended_at REAL,
        rep_count INTEGER DEFAULT 0,
        good_count INTEGER DEFAULT 0,
        avg_primary_min REAL,
        avg_torso_max REAL,
        notes TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS reps (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        rep_index INTEGER NOT NULL,
        level TEXT,
        text TEXT,
        primary_min REAL,
        primary_max REAL,
        hip_min REAL,
        hip_max REAL,
        knee_min REAL,
        knee_max REAL,
        shoulder_min REAL,
        shoulder_max REAL,
        elbow_min REAL,
        elbow_max REAL,
        torso_vertical_max REAL,
        knee_over_toe_max REAL,
        frames INTEGER,
        ts REAL NOT NULL,
        FOREIGN KEY(session_id) REFERENCES sessions(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS ix_reps_session ON reps(session_id);",
    "CREATE INDEX IF NOT EXISTS ix_sessions_started ON sessions(started_at DESC);",
)


class SessionLog:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path or DEFAULT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path),
                                     check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        for stmt in SCHEMA:
            self._conn.execute(stmt)
        self._conn.commit()
        self._pending_reps: List[tuple] = []
        self.session_id: Optional[str] = None

    def open_session(self, exercise: str, notes: str = "") -> str:
        session_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions(id, exercise, started_at, notes) "
                "VALUES(?, ?, ?, ?)",
                (session_id, exercise, time.time(), notes),
            )
            self._conn.commit()
        self.session_id = session_id
        return session_id

    def append_rep(self, rep_index: int, verdict_level: str,
                   verdict_text: str, sample) -> None:
        if not self.session_id:
            return
        row = (
            uuid.uuid4().hex,
            self.session_id,
            int(rep_index),
            verdict_level or "",
            verdict_text or "",
            _safe(sample.get_min, "primary"),
            _safe(sample.get_max, "primary"),
            _safe(sample.get_min, "hip"),
            _safe(sample.get_max, "hip"),
            _safe(sample.get_min, "knee"),
            _safe(sample.get_max, "knee"),
            _safe(sample.get_min, "shoulder"),
            _safe(sample.get_max, "shoulder"),
            _safe(sample.get_min, "elbow"),
            _safe(sample.get_max, "elbow"),
            _safe(sample.get_max, "torso_vertical"),
            _safe(sample.get_max, "knee_over_toe_norm"),
            int(sample.frames),
            time.time(),
        )
        self._pending_reps.append(row)

    def flush(self) -> None:
        if not self._pending_reps:
            return
        with self._lock:
            self._conn.executemany(
                "INSERT INTO reps(id, session_id, rep_index, level, text, "
                "primary_min, primary_max, hip_min, hip_max, "
                "knee_min, knee_max, shoulder_min, shoulder_max, "
                "elbow_min, elbow_max, torso_vertical_max, "
                "knee_over_toe_max, frames, ts) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                self._pending_reps,
            )
            self._conn.commit()
            self._pending_reps.clear()

    def close_session(self) -> None:
        if not self.session_id:
            return
        self.flush()
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*), SUM(CASE WHEN level='good' THEN 1 ELSE 0 END), "
                "AVG(primary_min), AVG(torso_vertical_max) "
                "FROM reps WHERE session_id=?",
                (self.session_id,),
            ).fetchone()
            rep_count, good_count, avg_pmin, avg_tv = row or (0, 0, None, None)
            self._conn.execute(
                "UPDATE sessions SET ended_at=?, rep_count=?, good_count=?, "
                "avg_primary_min=?, avg_torso_max=? WHERE id=?",
                (time.time(), int(rep_count or 0), int(good_count or 0),
                 float(avg_pmin) if avg_pmin is not None else None,
                 float(avg_tv) if avg_tv is not None else None,
                 self.session_id),
            )
            self._conn.commit()
        self.session_id = None

    def current_session_summary(self) -> Optional[Dict]:
        if not self.session_id:
            return None
        with self._lock:
            s = self._conn.execute(
                "SELECT id, exercise, started_at FROM sessions WHERE id=?",
                (self.session_id,),
            ).fetchone()
            if not s:
                return None
            reps = self._conn.execute(
                "SELECT rep_index, level, text, primary_min, primary_max, "
                "knee_min, hip_min, hip_max, shoulder_max, "
                "torso_vertical_max, knee_over_toe_max, frames FROM reps "
                "WHERE session_id=? ORDER BY rep_index ASC",
                (self.session_id,),
            ).fetchall()
        return {
            "id": s[0],
            "exercise": s[1],
            "started_at": _fmt_time(s[2]),
            "reps": [
                {
                    "rep_index": r[0], "level": r[1], "text": r[2],
                    "primary_min": r[3], "primary_max": r[4],
                    "knee_min_deg": r[5], "hip_min": r[6], "hip_max": r[7],
                    "shoulder_max": r[8],
                    "torso_max_deg": r[9], "knee_over_toe_max": r[10],
                    "frames": r[11],
                }
                for r in reps
            ],
        }

    def past_sessions(self, limit: int = 30) -> Dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, exercise, started_at, rep_count, good_count, "
                "avg_primary_min FROM sessions "
                "WHERE ended_at IS NOT NULL "
                "ORDER BY started_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return {
            "sessions": [
                {
                    "id": r[0],
                    "exercise": r[1],
                    "started_at": _fmt_time(r[2]),
                    "rep_count": r[3] or 0,
                    "good_count": r[4] or 0,
                    "avg_knee_min": r[5],
                }
                for r in rows
            ],
        }

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


def _safe(getter, key):
    try:
        v = getter(key)
        return None if v is None else float(v)
    except Exception:
        return None


def _fmt_time(ts) -> str:
    if ts is None:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except Exception:
        return ""
