"""
SQLite layer. No ORM for such a small project - direct sqlite3 works fine.
Each call opens its own connection (check_same_thread=False so the MQTT
thread can also write).
"""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional

from .config import DB_PATH

_write_lock = threading.Lock()  # SQLite is single-writer; fine at this scale

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    warehouse_id  TEXT NOT NULL,
    timestamp     TEXT NOT NULL,
    temperature   REAL,
    humidity      REAL
);
CREATE INDEX IF NOT EXISTS idx_readings_warehouse_time
    ON readings(warehouse_id, timestamp);

CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    warehouse_id  TEXT NOT NULL,
    timestamp     TEXT NOT NULL,
    alert_type    TEXT NOT NULL,   -- threshold | zscore
    metric        TEXT NOT NULL,   -- temperature | humidity
    value         REAL NOT NULL,
    message       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_time
    ON alerts(timestamp DESC);
"""


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def insert_reading(warehouse_id: str, timestamp: str, temperature: Optional[float], humidity: Optional[float]) -> None:
    with _write_lock, connect() as conn:
        conn.execute(
            "INSERT INTO readings (warehouse_id, timestamp, temperature, humidity) VALUES (?, ?, ?, ?)",
            (warehouse_id, timestamp, temperature, humidity),
        )
        conn.commit()


def upsert_last_reading(warehouse_id: str, timestamp: str, temperature: Optional[float], humidity: Optional[float]) -> None:
    """
    Temperature and humidity arrive in separate MQTT messages, so instead
    of storing two rows per timestamp we merge them: if the most recent
    row for this warehouse has the other metric empty, fill it in;
    otherwise insert a new row.
    """
    with _write_lock, connect() as conn:
        row = conn.execute(
            """
            SELECT id, temperature, humidity, timestamp FROM readings
            WHERE warehouse_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (warehouse_id,),
        ).fetchone()

        # If the counterpart column is empty, fold into the same row
        if row is not None:
            merge = False
            if temperature is not None and row["temperature"] is None:
                merge = True
            if humidity is not None and row["humidity"] is None:
                merge = True
            if merge:
                conn.execute(
                    """
                    UPDATE readings
                    SET temperature = COALESCE(?, temperature),
                        humidity    = COALESCE(?, humidity),
                        timestamp   = ?
                    WHERE id = ?
                    """,
                    (temperature, humidity, timestamp, row["id"]),
                )
                conn.commit()
                return

        conn.execute(
            "INSERT INTO readings (warehouse_id, timestamp, temperature, humidity) VALUES (?, ?, ?, ?)",
            (warehouse_id, timestamp, temperature, humidity),
        )
        conn.commit()


def latest_per_warehouse() -> List[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.*
            FROM readings r
            JOIN (
                SELECT warehouse_id, MAX(id) AS max_id
                FROM readings
                GROUP BY warehouse_id
            ) m ON r.id = m.max_id
            """
        ).fetchall()
        return [dict(r) for r in rows]


def history(warehouse_id: str, since_iso: str) -> List[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT warehouse_id, timestamp, temperature, humidity
            FROM readings
            WHERE warehouse_id = ? AND timestamp >= ?
            ORDER BY timestamp ASC
            """,
            (warehouse_id, since_iso),
        ).fetchall()
        return [dict(r) for r in rows]


def insert_alert(warehouse_id: str, timestamp: str, alert_type: str, metric: str, value: float, message: str) -> dict:
    with _write_lock, connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO alerts (warehouse_id, timestamp, alert_type, metric, value, message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (warehouse_id, timestamp, alert_type, metric, value, message),
        )
        conn.commit()
        return {
            "id": cur.lastrowid,
            "warehouse_id": warehouse_id,
            "timestamp": timestamp,
            "alert_type": alert_type,
            "metric": metric,
            "value": value,
            "message": message,
        }


def recent_alerts(limit: int = 100) -> List[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
