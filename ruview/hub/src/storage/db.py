"""
SQLite-backed storage for historical presence, vitals, and event logs.

Schema is minimal to keep writes fast on Pi Zero 2 W's SD card.
"""

import aiosqlite
import asyncio
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

CREATE_DDL = """
CREATE TABLE IF NOT EXISTS presence_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    present     INTEGER NOT NULL,
    confidence  REAL    NOT NULL,
    zone        TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_presence_ts ON presence_log(ts);

CREATE TABLE IF NOT EXISTS vitals_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                  REAL    NOT NULL,
    breathing_rate      REAL    NOT NULL,
    heart_rate          REAL    NOT NULL,
    br_confidence       REAL    NOT NULL,
    hr_confidence       REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vitals_ts ON vitals_log(ts);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL    NOT NULL,
    source  TEXT    NOT NULL,
    event   TEXT    NOT NULL,
    payload TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


class Database:
    def __init__(self, db_path: str, history_days: int = 7) -> None:
        self._path         = db_path
        self._history_days = history_days
        self._conn: Optional[aiosqlite.Connection] = None
        self._write_lock   = asyncio.Lock()

    async def start(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(CREATE_DDL)
        await self._conn.commit()
        logger.info("Database opened: %s", self._path)

    async def stop(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def log_presence(self, present: bool, confidence: float, zone: str) -> None:
        async with self._write_lock:
            await self._conn.execute(
                "INSERT INTO presence_log (ts, present, confidence, zone) VALUES (?,?,?,?)",
                (time.time(), int(present), confidence, zone),
            )
            await self._conn.commit()

    async def log_vitals(self, br: float, hr: float, br_conf: float, hr_conf: float) -> None:
        if br == 0.0 and hr == 0.0:
            return
        async with self._write_lock:
            await self._conn.execute(
                "INSERT INTO vitals_log (ts, breathing_rate, heart_rate, br_confidence, hr_confidence) "
                "VALUES (?,?,?,?,?)",
                (time.time(), br, hr, br_conf, hr_conf),
            )
            await self._conn.commit()

    async def log_event(self, source: str, event: str, payload: str = "{}") -> None:
        async with self._write_lock:
            await self._conn.execute(
                "INSERT INTO events (ts, source, event, payload) VALUES (?,?,?,?)",
                (time.time(), source, event, payload),
            )
            await self._conn.commit()

    async def get_presence_history(self, hours: int = 24) -> list[dict]:
        since = time.time() - hours * 3600
        async with self._conn.execute(
            "SELECT ts, present, confidence, zone FROM presence_log "
            "WHERE ts > ? ORDER BY ts DESC LIMIT 1000",
            (since,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]

    async def get_vitals_history(self, hours: int = 1) -> list[dict]:
        since = time.time() - hours * 3600
        async with self._conn.execute(
            "SELECT ts, breathing_rate, heart_rate, br_confidence, hr_confidence "
            "FROM vitals_log WHERE ts > ? ORDER BY ts DESC LIMIT 500",
            (since,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]

    async def purge_old_records(self) -> None:
        cutoff = time.time() - self._history_days * 86400
        async with self._write_lock:
            await self._conn.execute("DELETE FROM presence_log WHERE ts < ?", (cutoff,))
            await self._conn.execute("DELETE FROM vitals_log    WHERE ts < ?", (cutoff,))
            await self._conn.execute("DELETE FROM events        WHERE ts < ?", (cutoff,))
            await self._conn.commit()
        logger.debug("Purged records older than %d days", self._history_days)
