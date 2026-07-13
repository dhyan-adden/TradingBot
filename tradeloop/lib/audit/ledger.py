import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradeloop.lib.broker.paper_broker import PaperBroker, Fill

GENESIS_HASH = "0" * 64

# event-type constants (single source of truth for producers)
FETCH_OK = "fetch.ok"
FETCH_FAIL = "fetch.fail"
MODEL_CALL = "model.call"
RISK_VERDICT = "risk.verdict"
ORDER_FILLED = "paper.order.filled"
STOP_UPDATED = "paper.stop.updated"


def canonical(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


def row_hash(prev_hash: str, seq: int, event: dict) -> str:
    material = f"{prev_hash}|{seq}|{canonical(event)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class LedgerTamperError(Exception):
    pass


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

    def verify_chain(self) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, type, payload_json, prev_hash, row_hash FROM events ORDER BY seq ASC"
            ).fetchall()
        expected_prev = GENESIS_HASH
        expected_seq = 1
        for row in rows:
            if row["seq"] != expected_seq:
                raise LedgerTamperError(f"seq gap: expected {expected_seq}, got {row['seq']}")
            if row["prev_hash"] != expected_prev:
                raise LedgerTamperError(f"broken link at seq {row['seq']}")
            event = json.loads(row["payload_json"])
            recomputed = row_hash(row["prev_hash"], row["seq"], event)
            if recomputed != row["row_hash"]:
                raise LedgerTamperError(f"row hash mismatch at seq {row['seq']}")
            expected_prev = row["row_hash"]
            expected_seq += 1

    def log_fetch_ok(self, source: str, count: int, url: str | None = None) -> str:
        return self.append({"type": FETCH_OK, "source": source, "count": count, "url": url})

    def log_fetch_fail(self, source: str, error: str, url: str | None = None) -> str:
        return self.append({"type": FETCH_FAIL, "source": source, "error": error, "url": url})

    def log_model_call(self, role: str, model: str, prompt_tokens: int,
                       completion_tokens: int, latency_ms: int) -> str:
        return self.append({
            "type": MODEL_CALL,
            "role": role,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
        })

    def project_positions(self, starting_cash_inr: float = 0.0) -> PaperBroker:
        broker = PaperBroker(cash_inr=starting_cash_inr)
        for event in self.replay([ORDER_FILLED]):
            fill = Fill(
                order_id=event["order_id"],
                symbol=event["symbol"],
                side=event["side"],
                quantity=event["quantity"],
                fill_price=event["fill_price"],
                status="FILLED",
                product=event.get("product", "CNC"),
            )
            broker._apply_fill(fill)
            broker.fills.append(fill)
        return broker
