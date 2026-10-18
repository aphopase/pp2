"""Durable SQLite outbox for offline-first telemetry delivery."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class Outbox:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT NOT NULL UNIQUE,
                gateway_sequence INTEGER NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._connection.commit()

    def append(self, record: dict[str, Any]) -> bool:
        key = record["idempotency_key"]
        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO telemetry_outbox
                (idempotency_key, gateway_sequence, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, record["gateway_sequence"], json.dumps(record), record["event_time"]),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT payload FROM telemetry_outbox
            WHERE sent = 0 ORDER BY gateway_sequence LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def acknowledge(self, idempotency_keys: list[str]) -> None:
        if not idempotency_keys:
            return
        placeholders = ",".join("?" for _ in idempotency_keys)
        self._connection.execute(
            f"DELETE FROM telemetry_outbox WHERE idempotency_key IN ({placeholders})",
            idempotency_keys,
        )
        self._connection.commit()

    def stats(self) -> dict[str, Any]:
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS pending_count, MIN(created_at) AS oldest_record
            FROM telemetry_outbox WHERE sent = 0
            """
        ).fetchone()
        return {
            "pending_count": row["pending_count"],
            "oldest_record": row["oldest_record"],
        }

    def close(self) -> None:
        self._connection.close()
