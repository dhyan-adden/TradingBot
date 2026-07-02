import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence


@dataclass(frozen=True)
class Event:
    event_id: str
    event_type: str
    aggregate_id: str
    payload: Dict[str, Any]
    created_at: str
    event_hash: str


def canonical_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def stable_event_hash(event_type: str, aggregate_id: str, payload: Dict[str, Any]) -> str:
    material = "{}|{}|{}".format(event_type, aggregate_id, canonical_payload(payload))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class EventLog:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def init_schema(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    event_hash TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_aggregate ON events (aggregate_id, id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_type ON events (event_type, id)"
            )

    def append_event(
        self,
        event_type: str,
        aggregate_id: str,
        payload: Dict[str, Any],
        event_id: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> Event:
        self.init_schema()
        next_event_id = event_id or str(uuid.uuid4())
        next_created_at = created_at or datetime.now(timezone.utc).isoformat()
        event_hash = stable_event_hash(event_type, aggregate_id, payload)
        payload_json = canonical_payload(payload)

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO events (
                    event_id, event_type, aggregate_id, payload_json,
                    created_at, event_hash
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    next_event_id,
                    event_type,
                    aggregate_id,
                    payload_json,
                    next_created_at,
                    event_hash,
                ),
            )

        return Event(
            event_id=next_event_id,
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload=payload,
            created_at=next_created_at,
            event_hash=event_hash,
        )

    def replay(self, aggregate_id: Optional[str] = None) -> Iterable[Event]:
        self.init_schema()
        query = """
            SELECT event_id, event_type, aggregate_id, payload_json, created_at, event_hash
            FROM events
        """
        params = []
        if aggregate_id:
            query += " WHERE aggregate_id = ?"
            params.append(aggregate_id)
        query += " ORDER BY id ASC"

        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()

        for row in rows:
            yield Event(
                event_id=row["event_id"],
                event_type=row["event_type"],
                aggregate_id=row["aggregate_id"],
                payload=json.loads(row["payload_json"]),
                created_at=row["created_at"],
                event_hash=row["event_hash"],
            )

    def latest(self, event_type: str, aggregate_id: Optional[str] = None) -> Optional[Event]:
        self.init_schema()
        query = """
            SELECT event_id, event_type, aggregate_id, payload_json, created_at, event_hash
            FROM events
            WHERE event_type = ?
        """
        params: list[Any] = [event_type]
        if aggregate_id:
            query += " AND aggregate_id = ?"
            params.append(aggregate_id)
        query += " ORDER BY id DESC LIMIT 1"

        with self.connect() as connection:
            row = connection.execute(query, params).fetchone()
        if row is None:
            return None
        return Event(
            event_id=row["event_id"],
            event_type=row["event_type"],
            aggregate_id=row["aggregate_id"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
            event_hash=row["event_hash"],
        )

    def by_types(self, event_types: Sequence[str]) -> Iterable[Event]:
        self.init_schema()
        if not event_types:
            return []
        placeholders = ",".join("?" for _ in event_types)
        query = f"""
            SELECT event_id, event_type, aggregate_id, payload_json, created_at, event_hash
            FROM events
            WHERE event_type IN ({placeholders})
            ORDER BY id ASC
        """
        with self.connect() as connection:
            rows = connection.execute(query, list(event_types)).fetchall()

        for row in rows:
            yield Event(
                event_id=row["event_id"],
                event_type=row["event_type"],
                aggregate_id=row["aggregate_id"],
                payload=json.loads(row["payload_json"]),
                created_at=row["created_at"],
                event_hash=row["event_hash"],
            )
