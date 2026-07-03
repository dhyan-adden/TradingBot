import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64

# event-type constants (single source of truth for producers)
FETCH_OK = "fetch.ok"
FETCH_FAIL = "fetch.fail"
MODEL_CALL = "model.call"
RISK_VERDICT = "risk.verdict"
ORDER_FILLED = "paper.order.filled"


def canonical(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


def row_hash(prev_hash: str, seq: int, event: dict) -> str:
    material = f"{prev_hash}|{seq}|{canonical(event)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class Ledger:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    row_hash TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events (type, seq)")

    def _tip(self, conn: sqlite3.Connection) -> tuple[int, str]:
        row = conn.execute("SELECT seq, row_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        if row is None:
            return 0, GENESIS_HASH
        return row["seq"], row["row_hash"]

    def append(self, event: dict) -> str:
        event_type = event["type"]  # raises KeyError if absent - loud by design
        stamped = dict(event)
        stamped["ts"] = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            last_seq, prev = self._tip(conn)
            seq = last_seq + 1
            digest = row_hash(prev, seq, stamped)
            conn.execute(
                "INSERT INTO events (ts, type, payload_json, prev_hash, row_hash) VALUES (?, ?, ?, ?, ?)",
                (stamped["ts"], event_type, canonical(stamped), prev, digest),
            )
        return digest

    def replay(self, types: list[str] | None = None) -> list[dict]:
        query = "SELECT seq, prev_hash, row_hash, payload_json FROM events"
        params: list[Any] = []
        if types:
            placeholders = ",".join("?" for _ in types)
            query += f" WHERE type IN ({placeholders})"
            params = list(types)
        query += " ORDER BY seq ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload["seq"] = row["seq"]
            payload["prev_hash"] = row["prev_hash"]
            payload["row_hash"] = row["row_hash"]
            result.append(payload)
        return result
