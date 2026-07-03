# TradeLoop Phase 2 — Audit Ledger + Derived State Implementation Plan

**Goal:** Replace P0's flat-file paper book with an append-only, hash-**chained** SQLite ledger that records every fetch/model-call/risk-verdict/fill, derives positions/cash by replaying `paper.order.filled` events, and projects the event log to human-readable markdown journals.

> **2026-07-04 verification patch (re-checked against current post-option-D code — apply these deltas):**
>
> Verified correct: `paper_broker._apply_fill` at line 71 does NOT append to `self.fills` (Task 3's explicit `broker.fills.append(fill)` is right, no double-append); `PaperBroker.slippage_bps` defaults to 5, so `project_positions` returns a broker at slippage 5 for new orders (the old P0 restore-after-replay dance is unnecessary — Task 5 dropping the `slippage_bps` param is fine since `route_cycle` never passed it); `Fill` has `order_id,symbol,side,quantity,fill_price,status,product,reason` (all Task 3/5/8 constructions valid); `load_ticker_master`/`TickerRecord.symbol/.sector` exist and are already imported by `router.py` (Task 6's test import works); the router loop names `verdict = evaluate(...)` and exposes `ticket.symbol/.side/.quantity/.price` exactly as Task 6 patches.
>
> **Fix 1 (Task 4, minor):** `config/memory.yaml` does not exist and the Task 4 implementation never reads it (it embeds `source_event_hash` unconditionally). Delete the "Idempotency source: config/memory.yaml (...)" sentence from Task 4 — it is a phantom reference. No config read.
>
> **Fix 2 (NEW Task 9 — DoD-critical production wiring; the plan's Task 6 note claims the orchestrator constant changes "in Task 6" but no task does it):** In `tradeloop/orchestrator.py` `route_cycle`, after computing settings and before hydrate:
>   - change `book_path = root / "state" / "paper_book.jsonl"` → `book_path = root / "state" / "ledger.db"`.
>   - construct `led = Ledger(book_path)` and call `led.verify_chain()` on entry; on `LedgerTamperError` print `tradeloop_route=LEDGER_TAMPERED` and `return 1` (a tampered audit trail must halt routing — fail loud).
>   - pass `ledger=led` into the `route_orders_file(...)` call so risk verdicts are logged in production (fills are already logged via the swapped `paper_book.append`).
>   Add an **e2e test through the real route_cycle** (`tradeloop/tests/test_ledger_production.py`): run a fixture cycle through `route_cycle`, then assert `ledger.db` holds a `risk.verdict` AND a `paper.order.filled` event, `verify_chain()` passes, and `hydrate(book_path, ...)` shows the position; then corrupt a ledger row and assert the NEXT `route_cycle` returns 1 with `LEDGER_TAMPERED`. This is the production-path proof the plan's Task 8 (module-level integration) does not provide.
>
> **Fix 3 (breaking tests — the book is now SQLite, not JSONL):** These currently assert on `state/paper_book.jsonl` as a text file and MUST be rewritten to the ledger backend (assert via `hydrate`/`Ledger(...).replay()`), not by counting JSONL lines: `test_end_to_end_gate_runs_on_every_order` (test_orchestrator.py) and `test_sell_exit_routes_and_updates_book` (test_cycle_guards.py). DELETE `tradeloop/tests/test_paper_book.py` — it tests the old JSONL `hydrate`/`append` body that Task 5 fully replaces (its role is taken by `test_paper_book_ledger.py`); grep-confirm no other importer first. Check `test_router_gate.py`'s `paper_book.jsonl` path vars — they build in-memory brokers, so a rename to a neutral tmp path is enough; do not let them seed JSONL.
>
> **Fix 4 (model-call logging — conscious scope decision, state it, don't silently skip):** P2's hash-chained ledger covers the MONEY PATH: `risk.verdict` + `paper.order.filled` (both in the route phase). Model-call provenance stays in P1's `llm_calls.jsonl` (which is richer than the ledger's usage-only `log_model_call`); **P2 does NOT retrofit `client.py`**. Ship `log_model_call`/`log_fetch_ok`/`log_fetch_fail` as helpers (P3 wires the fetch loggers where fetches actually happen). If model calls must also live in the tamper-proof chain, that is a small follow-up — flag it, don't pretend Task 7 covers it.
>
> **Testing standard:** every guard branch gets a test (tamper by mutation, tamper by deletion, tamper-on-load halts routing, empty-ledger hydrate, non-FILLED skip) AND the route_cycle e2e above. Report coverage of these branches, not a bare pass count.

**Architecture:** A single `tradeloop/lib/audit/ledger.py` owns one SQLite file (`tradeloop/state/ledger.db`). Every row is a canonical-JSON event whose `row_hash = sha256(prev_hash + "|" + seq + "|" + canonical(event))` — a true chain (each row binds to the one before it, unlike engine-1's `src/tradingbot/event_log.py` per-row-only hash). `project_positions()` replays `paper.order.filled` events through a fresh `PaperBroker` to derive live positions/avg/cash; this becomes `paper_book.hydrate()`'s new body (P0's callers unchanged). A `MarkdownProjector` regenerates journals atomically with content-hash idempotency.

**Tech Stack:** Python 3.11, stdlib `sqlite3` + `hashlib` + `json` (no external dep), pydantic 2 (already declared), pytest with recorded fixtures only (no network).

## Global Constraints

- India cash equities only; no shorts/F&O/NRML/leverage.
- Long-only: `BUY` opens/adds, `SELL` exits only.
- CNC/MIS products only.
- `tradeloop/kill_switch.md` halts orders (enforced in P0 order path; ledger only records verdicts).
- Paper default: `ZERODHA_ENABLE_TRADING=false`.
- Live only past the promotion gate (`settings.yaml live_promotion_gates`).
- The risk gate `checks.evaluate()` runs on every order (P0); Phase 2 logs its verdict, never replaces it.
- Ledger is append-only: rows are never updated or deleted; `hydrate`/`append` signatures from P0 stay byte-identical so P0 callers are untouched.
- Security (AGENTS.md): never read/print `.env`; never log values whose names contain KEY/SECRET/TOKEN/PASSWORD/AUTH/CREDENTIAL. Model-call events log role/model/usage/latency only — never prompt secrets or API keys.

## File Structure

| File | Responsibility |
|---|---|
| `tradeloop/lib/audit/__init__.py` | Package marker (created if absent). |
| `tradeloop/lib/audit/ledger.py` | **new** — hash-chained append-only SQLite ledger: `append`, `replay`, `project_positions`, plus `verify_chain` and event-type constants. |
| `tradeloop/lib/audit/projections.py` | **new** — `MarkdownProjector`: event log → `memory/journal/*.md`, atomic write, content-hash idempotency. |
| `tradeloop/lib/broker/paper_book.py` | **modify** — swap `hydrate()` body to delegate to `ledger.project_positions()`; keep signature. `append()` now writes ledger `paper.order.filled` events. |
| `tradeloop/tests/test_ledger.py` | **new** — append+replay, hash-chain tamper detection, `project_positions` matches known fills. |
| `tradeloop/tests/test_projections.py` | **new** — projection content + idempotency (no rewrite on unchanged). |
| `tradeloop/tests/test_paper_book_ledger.py` | **new** — `hydrate`/`append` P0 interface still holds over the ledger backend. |

The single ledger DB path is `tradeloop/state/ledger.db`; the P0 `book_path` argument is reinterpreted as the ledger DB path (P0 passed `state/paper_book.jsonl`; Phase 2 changes the orchestrator's constant to `state/ledger.db` in Task 6).

---

### Task 1: Ledger schema, canonical JSON, and hash chain

**Files**
- create `tradeloop/lib/audit/__init__.py`
- create `tradeloop/lib/audit/ledger.py`
- create `tradeloop/tests/test_ledger.py`

**Interfaces**
- Consumes: nothing (stdlib only).
- Produces:
  - `canonical(event: dict) -> str` — `json.dumps(event, sort_keys=True, separators=(",", ":"))`.
  - `row_hash(prev_hash: str, seq: int, event: dict) -> str` — `sha256(f"{prev_hash}|{seq}|{canonical(event)}").hexdigest()`.
  - `class Ledger` with `__init__(self, db_path: Path)`, `append(self, event: dict) -> str`, `replay(self, types: list[str] | None = None) -> list[dict]`.
  - Table `events(seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, type TEXT, payload_json TEXT, prev_hash TEXT, row_hash TEXT)`.
  - `GENESIS_HASH = "0" * 64`.
  - `append` returns the new row's `row_hash` (matches §6 `ledger.append(event) -> str`).

Each stored `event` must carry a `"type"` key; `append` reads `event["type"]` for the `type` column and stamps `ts` (UTC ISO) into the row and into the hashed payload so the timestamp is tamper-evident too.

**Steps**

1. Write failing test `tradeloop/tests/test_ledger.py`:

```python
import json
from pathlib import Path

import pytest

from tradeloop.lib.audit import ledger as L


def _ledger(tmp_path: Path) -> L.Ledger:
    return L.Ledger(tmp_path / "ledger.db")


def test_append_returns_hash_and_replay_roundtrips(tmp_path):
    led = _ledger(tmp_path)
    h1 = led.append({"type": "fetch.ok", "source": "google_news", "count": 3})
    h2 = led.append({"type": "model.call", "role": "news", "model": "x", "tokens": 42})
    assert isinstance(h1, str) and len(h1) == 64
    rows = led.replay()
    assert [r["type"] for r in rows] == ["fetch.ok", "model.call"]
    assert rows[0]["seq"] == 1 and rows[1]["seq"] == 2
    assert rows[0]["prev_hash"] == L.GENESIS_HASH
    assert rows[1]["prev_hash"] == h1
    assert rows[1]["row_hash"] == h2
    # payload fields survive the round trip
    assert rows[0]["source"] == "google_news"
    assert rows[0]["count"] == 3


def test_replay_filters_by_type(tmp_path):
    led = _ledger(tmp_path)
    led.append({"type": "fetch.ok", "source": "rss"})
    led.append({"type": "model.call", "role": "bull"})
    led.append({"type": "fetch.fail", "source": "nse"})
    fetches = led.replay(["fetch.ok", "fetch.fail"])
    assert [r["type"] for r in fetches] == ["fetch.ok", "fetch.fail"]


def test_chain_links_each_row_to_previous(tmp_path):
    led = _ledger(tmp_path)
    led.append({"type": "a"})
    led.append({"type": "b"})
    led.append({"type": "c"})
    rows = led.replay()
    for i in range(1, len(rows)):
        assert rows[i]["prev_hash"] == rows[i - 1]["row_hash"]


def test_append_requires_type(tmp_path):
    led = _ledger(tmp_path)
    with pytest.raises(KeyError):
        led.append({"source": "no_type"})
```

2. Run it — expect FAIL (module does not exist):
   `python -m pytest tradeloop/tests/test_ledger.py -q`
   Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.audit'` / collection error.

3. Minimal implementation. Create `tradeloop/lib/audit/__init__.py` (empty), then `tradeloop/lib/audit/ledger.py`:

```python
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
        event_type = event["type"]  # raises KeyError if absent — loud by design
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
```

4. Run pass:
   `python -m pytest tradeloop/tests/test_ledger.py -q`
   Expected: 4 passed.

5. Commit:
   `git commit -am "Phase 2 Task 1: hash-chained append-only SQLite ledger (append/replay)"`

---

### Task 2: Chain verification + tamper detection

**Files**
- modify `tradeloop/lib/audit/ledger.py`
- modify `tradeloop/tests/test_ledger.py`

**Interfaces**
- Consumes: `Ledger`, `row_hash`, `GENESIS_HASH` (Task 1).
- Produces: `Ledger.verify_chain(self) -> None` — raises `LedgerTamperError` on the first row whose recomputed hash or `prev_hash` link breaks; `class LedgerTamperError(Exception)`.

**Steps**

1. Add failing tests to `tradeloop/tests/test_ledger.py`:

```python
def test_verify_chain_passes_on_untouched_ledger(tmp_path):
    led = _ledger(tmp_path)
    led.append({"type": "a", "v": 1})
    led.append({"type": "b", "v": 2})
    led.verify_chain()  # must not raise


def test_mutating_a_row_breaks_the_chain(tmp_path):
    led = _ledger(tmp_path)
    led.append({"type": "a", "v": 1})
    led.append({"type": "b", "v": 2})
    led.append({"type": "c", "v": 3})
    # tamper: rewrite row 2's payload directly, bypassing append
    import sqlite3
    conn = sqlite3.connect(str(led.db_path))
    tampered = L.canonical({"type": "b", "v": 999, "ts": "2026-07-02T00:00:00+00:00"})
    conn.execute("UPDATE events SET payload_json = ? WHERE seq = 2", (tampered,))
    conn.commit()
    conn.close()
    with pytest.raises(L.LedgerTamperError):
        led.verify_chain()


def test_deleting_a_row_breaks_the_chain(tmp_path):
    led = _ledger(tmp_path)
    led.append({"type": "a"})
    led.append({"type": "b"})
    led.append({"type": "c"})
    import sqlite3
    conn = sqlite3.connect(str(led.db_path))
    conn.execute("DELETE FROM events WHERE seq = 2")
    conn.commit()
    conn.close()
    with pytest.raises(L.LedgerTamperError):
        led.verify_chain()
```

2. Run — expect FAIL:
   `python -m pytest tradeloop/tests/test_ledger.py -q`
   Expected: `AttributeError: 'Ledger' object has no attribute 'verify_chain'` and `AttributeError: module ... has no attribute 'LedgerTamperError'`.

3. Implement. Add to `tradeloop/lib/audit/ledger.py`:

```python
class LedgerTamperError(Exception):
    pass
```

and this method on `Ledger`:

```python
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
```

Note: a deleted middle row leaves a seq gap (autoincrement never reuses seq), so the `seq != expected_seq` check catches deletion; mutation is caught by the recomputed-hash check.

4. Run pass:
   `python -m pytest tradeloop/tests/test_ledger.py -q`
   Expected: 7 passed.

5. Commit:
   `git commit -am "Phase 2 Task 2: verify_chain tamper detection (mutation + deletion)"`

---

### Task 3: `project_positions()` — derive PaperBroker by replaying fills

**Files**
- modify `tradeloop/lib/audit/ledger.py`
- create `tradeloop/tests/test_ledger.py` additions (same file)

**Interfaces**
- Consumes: `Ledger.replay` (Task 1); `PaperBroker`, `OrderTicket`, `Fill` from `tradeloop.lib.broker.paper_broker`.
- Produces: `Ledger.project_positions(self, starting_cash_inr: float = 0.0) -> PaperBroker` (matches §6 `ledger.project_positions() -> PaperBroker`; `starting_cash_inr` default keeps the §6 zero-arg call valid).

Fill events are appended (Task 5) with payload `{"type": "paper.order.filled", "symbol", "side", "quantity", "fill_price", "product", "order_id", "hard_stop"}`. Projection replays them **through `PaperBroker._apply_fill`** so avg/cash/cost math is identical to live placement — the source of truth is the same code path, not a re-implementation.

**Steps**

1. Add failing test to `tradeloop/tests/test_ledger.py`:

```python
from tradeloop.lib.broker.paper_broker import PaperBroker


def test_project_positions_matches_known_fill_sequence(tmp_path):
    led = _ledger(tmp_path)
    # BUY 10 @ 100, BUY 10 @ 120  -> qty 20, avg 110 ; SELL 5 @ 130 -> qty 15
    for ev in [
        {"type": L.ORDER_FILLED, "symbol": "TCS", "side": "BUY", "quantity": 10,
         "fill_price": 100.0, "product": "CNC", "order_id": "P1", "hard_stop": 90.0},
        {"type": L.ORDER_FILLED, "symbol": "TCS", "side": "BUY", "quantity": 10,
         "fill_price": 120.0, "product": "CNC", "order_id": "P2", "hard_stop": 95.0},
        {"type": L.ORDER_FILLED, "symbol": "TCS", "side": "SELL", "quantity": 5,
         "fill_price": 130.0, "product": "CNC", "order_id": "P3", "hard_stop": 0.0},
    ]:
        led.append(ev)

    broker = led.project_positions(starting_cash_inr=1_000_000.0)

    assert isinstance(broker, PaperBroker)
    assert broker.positions["TCS"] == 15
    assert broker.avg_prices["TCS"] == pytest.approx(110.0)


def test_project_positions_ignores_non_fill_events(tmp_path):
    led = _ledger(tmp_path)
    led.append({"type": L.FETCH_OK, "source": "rss"})
    led.append({"type": L.MODEL_CALL, "role": "news"})
    led.append({"type": L.ORDER_FILLED, "symbol": "INFY", "side": "BUY", "quantity": 4,
                "fill_price": 50.0, "product": "CNC", "order_id": "P9", "hard_stop": 45.0})
    broker = led.project_positions(starting_cash_inr=500_000.0)
    assert broker.positions == {"INFY": 4}
```

2. Run — expect FAIL:
   `python -m pytest tradeloop/tests/test_ledger.py -q -k project_positions`
   Expected: `AttributeError: 'Ledger' object has no attribute 'project_positions'`.

3. Implement. Add to `tradeloop/lib/audit/ledger.py` (top-level import at module head):

```python
from tradeloop.lib.broker.paper_broker import PaperBroker, Fill
```

and the method:

```python
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
```

`_apply_fill` (paper_broker.py:71) applies the exact avg/cash/cost math used at placement time, so replay reproduces the book precisely. `hard_stop` is not on `Fill`; it lives in the ledger payload and is read directly from events by `risk_state` (P0's order path), so it is not lost.

4. Run pass:
   `python -m pytest tradeloop/tests/test_ledger.py -q`
   Expected: 9 passed.

5. Commit:
   `git commit -am "Phase 2 Task 3: project_positions replays fills through PaperBroker"`

---

### Task 4: Markdown journal projection (atomic, content-hash idempotent)

**Files**
- create `tradeloop/lib/audit/projections.py`
- create `tradeloop/tests/test_projections.py`

**Interfaces**
- Consumes: `Ledger.replay` (Task 1).
- Produces:
  - `content_hash(content: str) -> str` — `sha256(content).hexdigest()`.
  - `class ProjectionResult` (frozen dataclass): `path: Path`, `changed: bool`.
  - `class MarkdownProjector` with `__init__(self, ledger: Ledger, memory_root: Path)` and `regenerate_journal(self) -> ProjectionResult` writing `memory_root/journal/event_log.md` (one line per event, grouped by day), atomic via `.tmp` + `replace`, skipping the write when content is unchanged.

Idempotency source: `config/memory.yaml` (`atomic_writes: true`, `require_source_event_hash: true`). The projection embeds a `source_event_hash` (hash of all row hashes) in the frontmatter and only rewrites when the rendered content differs — mirroring engine-1's `MemoryProjector._write_projection` (`src/tradingbot/memory/projections.py:146`).

**Steps**

1. Write failing test `tradeloop/tests/test_projections.py`:

```python
from pathlib import Path

from tradeloop.lib.audit import ledger as L
from tradeloop.lib.audit.projections import MarkdownProjector


def _seed(tmp_path: Path) -> L.Ledger:
    led = L.Ledger(tmp_path / "ledger.db")
    led.append({"type": L.FETCH_OK, "source": "google_news", "count": 5})
    led.append({"type": L.RISK_VERDICT, "symbol": "TCS", "approved": True, "reasons": []})
    led.append({"type": L.ORDER_FILLED, "symbol": "TCS", "side": "BUY", "quantity": 10,
                "fill_price": 100.0, "product": "CNC", "order_id": "P1", "hard_stop": 90.0})
    return led


def test_journal_written_with_all_events(tmp_path):
    led = _seed(tmp_path)
    proj = MarkdownProjector(led, tmp_path / "memory")
    result = proj.regenerate_journal()
    assert result.changed is True
    text = result.path.read_text(encoding="utf-8")
    assert "fetch.ok" in text
    assert "risk.verdict" in text
    assert "paper.order.filled" in text
    assert "source_event_hash:" in text


def test_journal_idempotent_no_rewrite_when_unchanged(tmp_path):
    led = _seed(tmp_path)
    proj = MarkdownProjector(led, tmp_path / "memory")
    first = proj.regenerate_journal()
    mtime_1 = first.path.stat().st_mtime_ns
    second = proj.regenerate_journal()
    assert second.changed is False
    assert second.path.stat().st_mtime_ns == mtime_1  # file untouched


def test_journal_rewrites_when_new_event_appended(tmp_path):
    led = _seed(tmp_path)
    proj = MarkdownProjector(led, tmp_path / "memory")
    proj.regenerate_journal()
    led.append({"type": L.FETCH_FAIL, "source": "nse_bse", "error": "timeout"})
    result = proj.regenerate_journal()
    assert result.changed is True
    assert "fetch.fail" in result.path.read_text(encoding="utf-8")
```

2. Run — expect FAIL:
   `python -m pytest tradeloop/tests/test_projections.py -q`
   Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.audit.projections'`.

3. Implement `tradeloop/lib/audit/projections.py`:

```python
import hashlib
from dataclasses import dataclass
from pathlib import Path

from tradeloop.lib.audit.ledger import Ledger


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProjectionResult:
    path: Path
    changed: bool


class MarkdownProjector:
    def __init__(self, ledger: Ledger, memory_root: Path):
        self.ledger = ledger
        self.memory_root = Path(memory_root)

    def regenerate_journal(self) -> ProjectionResult:
        events = self.ledger.replay()
        source_hash = content_hash("".join(e["row_hash"] for e in events))
        lines = [
            "---",
            "projection: event_log",
            f"source_event_hash: {source_hash}",
            f"event_count: {len(events)}",
            "---",
            "",
            "## Event Log",
        ]
        last_day = None
        for e in events:
            day = e.get("ts", "")[:10]
            if day != last_day:
                lines.append("")
                lines.append(f"### {day}")
                last_day = day
            lines.append(f"- `{e['row_hash'][:12]}` seq={e['seq']} {e['type']} {self._summary(e)}")
        lines.append("")
        content = "\n".join(lines)
        path = self.memory_root / "journal" / "event_log.md"
        return self._write(path, content)

    def _summary(self, e: dict) -> str:
        keys = [k for k in e if k not in {"type", "ts", "seq", "prev_hash", "row_hash"}]
        return " ".join(f"{k}={e[k]}" for k in sorted(keys))

    def _write(self, path: Path, content: str) -> ProjectionResult:
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing == content:
            return ProjectionResult(path=path, changed=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
        return ProjectionResult(path=path, changed=True)
```

4. Run pass:
   `python -m pytest tradeloop/tests/test_projections.py -q`
   Expected: 3 passed.

5. Commit:
   `git commit -am "Phase 2 Task 4: markdown journal projection (atomic, content-hash idempotent)"`

---

### Task 5: Swap `paper_book` backend to the ledger (keep P0 signatures)

**Files**
- modify `tradeloop/lib/broker/paper_book.py`
- create `tradeloop/tests/test_paper_book_ledger.py`

**Interfaces**
- Consumes: `Ledger`, `ORDER_FILLED`, `project_positions` (Tasks 1, 3); `Fill` from `paper_broker`.
- Produces (unchanged from P0 §6):
  - `paper_book.hydrate(path: Path, starting_cash_inr: float) -> PaperBroker` — now `Ledger(path).project_positions(starting_cash_inr)`.
  - `paper_book.append(path: Path, fills: list[Fill]) -> None` — now appends one `paper.order.filled` ledger event per FILLED fill.

`path` is now the ledger DB path (`state/ledger.db`), not the JSONL. The signature is byte-identical so P0's orchestrator and `route_orders_file` callers are unchanged. `append` writes `hard_stop` into the event payload; because `Fill` (paper_broker.py:22) has no `hard_stop` field, `append` accepts an optional parallel `hard_stops` mapping defaulting to `0.0` per fill.

**Steps**

1. Write failing test `tradeloop/tests/test_paper_book_ledger.py`:

```python
from pathlib import Path

from tradeloop.lib.broker import paper_book
from tradeloop.lib.broker.paper_broker import Fill, PaperBroker


def test_hydrate_empty_ledger_returns_starting_cash(tmp_path):
    broker = paper_book.hydrate(tmp_path / "ledger.db", starting_cash_inr=750_000.0)
    assert isinstance(broker, PaperBroker)
    assert broker.cash_inr == 750_000.0
    assert broker.positions == {}


def test_append_then_hydrate_roundtrips_position(tmp_path):
    db = tmp_path / "ledger.db"
    fill = Fill(order_id="P1", symbol="TCS", side="BUY", quantity=10,
                fill_price=100.0, status="FILLED", product="CNC")
    paper_book.append(db, [fill])
    broker = paper_book.hydrate(db, starting_cash_inr=1_000_000.0)
    assert broker.positions == {"TCS": 10}
    assert broker.avg_prices["TCS"] == 100.0


def test_append_skips_non_filled(tmp_path):
    db = tmp_path / "ledger.db"
    rejected = Fill(order_id="P2", symbol="TCS", side="BUY", quantity=10,
                    fill_price=0.0, status="REJECTED", product="CNC", reason="insufficient_cash")
    paper_book.append(db, [rejected])
    broker = paper_book.hydrate(db, starting_cash_inr=1_000_000.0)
    assert broker.positions == {}
```

2. Run — expect FAIL:
   `python -m pytest tradeloop/tests/test_paper_book_ledger.py -q`
   Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.broker.paper_book'` (P0's module, but this phase rewrites its body; if P0 shipped a JSONL version, tests fail on `state/ledger.db` semantics).

3. Implement `tradeloop/lib/broker/paper_book.py` (full replacement of the body — signatures identical to P0 §6):

```python
from pathlib import Path
from typing import Mapping

from tradeloop.lib.audit.ledger import Ledger, ORDER_FILLED
from tradeloop.lib.broker.paper_broker import Fill, PaperBroker


def hydrate(path: Path, starting_cash_inr: float) -> PaperBroker:
    # ponytail: body swapped from P0's JSONL replay to the hash-chained ledger;
    # signature unchanged so orchestrator + route_orders_file callers are untouched.
    return Ledger(path).project_positions(starting_cash_inr)


def append(path: Path, fills: list[Fill], hard_stops: Mapping[str, float] | None = None) -> None:
    hard_stops = hard_stops or {}
    led = Ledger(path)
    for fill in fills:
        if fill.status != "FILLED":
            continue
        led.append(
            {
                "type": ORDER_FILLED,
                "order_id": fill.order_id,
                "symbol": fill.symbol,
                "side": fill.side,
                "quantity": fill.quantity,
                "fill_price": fill.fill_price,
                "product": fill.product,
                "hard_stop": float(hard_stops.get(fill.symbol, 0.0)),
            }
        )
```

4. Run pass:
   `python -m pytest tradeloop/tests/test_paper_book_ledger.py -q`
   Expected: 3 passed.

5. Commit:
   `git commit -am "Phase 2 Task 5: paper_book hydrate/append delegate to the ledger"`

---

### Task 6: Wire ledger logging into the order path (risk verdicts + fills)

**Files**
- modify `tradeloop/lib/broker/router.py`
- modify `tradeloop/tests/test_ledger.py` (integration assertion)
- create `tradeloop/tests/test_router_ledger.py`

**Interfaces**
- Consumes: `Ledger`, `RISK_VERDICT`, `ORDER_FILLED` (Task 1); `route_orders_file` from P0 (`lib/broker/router.py`); `evaluate`/`RiskDecision` (`lib/risk/checks.py`); `Fill`/`RoutedOrder` from P0.
- Produces: `route_orders_file` gains an optional `ledger: Ledger | None = None` kwarg (default `None` preserves every P0 caller and P0 test). When a ledger is passed, it appends one `risk.verdict` event per order and (P0 already calls `paper_book.append` for fills, which now writes `paper.order.filled`). No new positional args, so P0's §6 signature and existing callers stay valid.

**Steps**

1. Write failing test `tradeloop/tests/test_router_ledger.py`. This drives the existing P0 `route_orders_file` with a real hydrated book and asserts a verdict event lands per order. (Uses P0's `orders.json` object shape and a 6-symbol universe from `config/universe.yaml`.)

```python
import json
from pathlib import Path

from tradeloop.lib.audit.ledger import Ledger, RISK_VERDICT
from tradeloop.lib.broker import paper_book
from tradeloop.lib.broker.router import route_orders_file
from tradeloop.lib.config import load_settings

ROOT = Path("tradeloop")


def _orders(tmp_path: Path, symbol: str, qty: int, price: float) -> Path:
    p = tmp_path / "orders.json"
    p.write_text(json.dumps({
        "mode": "premarket",
        "live_orders_enabled": False,
        "orders": [{"ticker": symbol, "side": "BUY", "product": "CNC",
                    "quantity": qty, "price": price, "order_type": "LIMIT"}],
        "held": [],
    }))
    return p


def test_route_logs_a_risk_verdict_per_order(tmp_path):
    settings = load_settings(ROOT / "config" / "settings.yaml")
    db = tmp_path / "ledger.db"
    led = Ledger(db)
    book = paper_book.hydrate(db, starting_cash_inr=settings.paper_starting_inr)
    # pick a symbol guaranteed in config/universe.yaml (first configured symbol).
    # load_ticker_master returns List[TickerRecord] (P0); TickerMaster.symbols()
    # only exists in P3, so index the list and read .symbol here.
    from tradeloop.lib.data.ticker_master import load_ticker_master
    symbol = load_ticker_master(ROOT / "config" / "universe.yaml")[0].symbol
    orders = _orders(tmp_path, symbol, qty=1, price=100.0)  # tiny -> below_min_position_size -> rejected

    route_orders_file(orders, tmp_path / "fills.json", book, settings, root=ROOT, ledger=led)

    verdicts = led.replay([RISK_VERDICT])
    assert len(verdicts) == 1
    assert verdicts[0]["symbol"] == symbol.upper()
    assert verdicts[0]["approved"] is False
    assert "below_min_position_size" in verdicts[0]["reasons"]
    led.verify_chain()  # chain stays intact after logging
```

2. Run — expect FAIL:
   `python -m pytest tradeloop/tests/test_router_ledger.py -q`
   Expected: `TypeError: route_orders_file() got an unexpected keyword argument 'ledger'`.

3. Implement. In `tradeloop/lib/broker/router.py`, add the kwarg and the verdict append inside the per-order loop (locations mirror the P0 spec §5.5 body). Add import at the top:

```python
from tradeloop.lib.audit.ledger import Ledger, RISK_VERDICT
```

Change the signature:

```python
def route_orders_file(orders_path, fills_path, book, settings, root=Path("tradeloop"), ledger: "Ledger | None" = None):
```

Inside the `for order in of.orders:` loop, immediately after `verdict = evaluate(ticket, state, caps)` and after `routed.append(...)`:

```python
        if ledger is not None:
            ledger.append({
                "type": RISK_VERDICT,
                "symbol": ticket.symbol.strip().upper(),
                "side": ticket.side,
                "quantity": ticket.quantity,
                "price": ticket.price,
                "approved": verdict.approved,
                "reasons": verdict.reasons,
            })
```

(`paper.order.filled` events are already written by `paper_book.append` from Task 5, which the orchestrator calls with the new FILLED fills; the router does not double-log fills.)

4. Run pass:
   `python -m pytest tradeloop/tests/test_router_ledger.py -q`
   Expected: 1 passed.

5. Commit:
   `git commit -am "Phase 2 Task 6: log risk verdicts to the ledger from the order path"`

---

### Task 7: Fetch + model-call logging helpers (DoD #2 wire points)

**Files**
- modify `tradeloop/lib/audit/ledger.py`
- modify `tradeloop/tests/test_ledger.py`

**Interfaces**
- Consumes: `Ledger.append`, `FETCH_OK`, `FETCH_FAIL`, `MODEL_CALL` (Task 1).
- Produces convenience methods on `Ledger` (thin, typed wrappers so P1/P3 producers log a consistent shape without hand-building dicts):
  - `log_fetch_ok(self, source: str, count: int, url: str | None = None) -> str`
  - `log_fetch_fail(self, source: str, error: str, url: str | None = None) -> str`
  - `log_model_call(self, role: str, model: str, prompt_tokens: int, completion_tokens: int, latency_ms: int) -> str`

The model-call wrapper logs **usage/latency only** — no prompt/response text, no API key — satisfying AGENTS.md. Wire points: P3 news/kite fetchers call `log_fetch_ok/fail` (DoD #2); P1 `llm.client.call_json` calls `log_model_call`; P0's order path (Task 6) already logs verdicts + fills. This task ships the loggers; the producers call them in their own phases.

**Steps**

1. Add failing test to `tradeloop/tests/test_ledger.py`:

```python
def test_fetch_and_model_loggers(tmp_path):
    led = _ledger(tmp_path)
    led.log_fetch_ok("google_news", count=7, url="https://news.example/rss")
    led.log_fetch_fail("nse_bse", error="HTTP 503")
    led.log_model_call("bull", "anthropic/claude", prompt_tokens=800,
                        completion_tokens=200, latency_ms=1420)
    rows = led.replay()
    assert [r["type"] for r in rows] == [L.FETCH_OK, L.FETCH_FAIL, L.MODEL_CALL]
    assert rows[0]["count"] == 7 and rows[0]["source"] == "google_news"
    assert rows[1]["error"] == "HTTP 503"
    assert rows[2]["prompt_tokens"] == 800 and rows[2]["latency_ms"] == 1420
    # no secret-like keys leaked into the model-call event
    assert not any(k.lower().endswith(("key", "secret", "token")) for k in rows[2])
    led.verify_chain()
```

2. Run — expect FAIL:
   `python -m pytest tradeloop/tests/test_ledger.py -q -k fetch_and_model`
   Expected: `AttributeError: 'Ledger' object has no attribute 'log_fetch_ok'`.

3. Implement. Add to `Ledger` in `tradeloop/lib/audit/ledger.py`:

```python
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
```

4. Run pass:
   `python -m pytest tradeloop/tests/test_ledger.py -q`
   Expected: all ledger tests pass (11 total in the file).

5. Commit:
   `git commit -am "Phase 2 Task 7: fetch/model-call logging helpers (DoD #2 wire points)"`

---

### Task 8: Full-suite green + chain-integrity regression across the phase

**Files**
- create `tradeloop/tests/test_ledger_integration.py`

**Interfaces**
- Consumes: `Ledger`, `MarkdownProjector`, `paper_book`, `project_positions`, all loggers (Tasks 1-7).
- Produces: an end-to-end regression proving a mixed event stream (fetch + model + verdict + fill) yields a valid chain, a correct projected book, and a stable journal projection.

**Steps**

1. Write failing test `tradeloop/tests/test_ledger_integration.py`:

```python
from pathlib import Path

from tradeloop.lib.audit.ledger import Ledger
from tradeloop.lib.audit.projections import MarkdownProjector
from tradeloop.lib.broker import paper_book
from tradeloop.lib.broker.paper_broker import Fill


def test_end_to_end_mixed_stream(tmp_path):
    db = tmp_path / "ledger.db"
    led = Ledger(db)
    led.log_fetch_ok("google_news", count=4)
    led.log_model_call("news", "m", prompt_tokens=100, completion_tokens=20, latency_ms=300)
    led.append({"type": "risk.verdict", "symbol": "TCS", "side": "BUY",
                "quantity": 10, "price": 100.0, "approved": True, "reasons": []})
    paper_book.append(db, [Fill("P1", "TCS", "BUY", 10, 100.0, "FILLED", "CNC")],
                      hard_stops={"TCS": 90.0})

    led.verify_chain()  # whole mixed chain intact

    broker = paper_book.hydrate(db, starting_cash_inr=1_000_000.0)
    assert broker.positions == {"TCS": 10}

    proj = MarkdownProjector(led, tmp_path / "memory")
    first = proj.regenerate_journal()
    assert first.changed is True
    assert proj.regenerate_journal().changed is False  # idempotent
```

2. Run — expect FAIL initially only if any prior task regressed; on a clean build this is the acceptance gate:
   `python -m pytest tradeloop/tests/test_ledger_integration.py -q`
   Expected FAIL only if a wiring bug exists; otherwise this task's first run is the confirmation. If it fails, fix the offending task before proceeding.

3. Implementation: none beyond Tasks 1-7 (this is the acceptance net). If it fails, the failure localizes to one prior module.

4. Run the whole Phase 2 suite:
   `python -m pytest tradeloop/tests/test_ledger.py tradeloop/tests/test_projections.py tradeloop/tests/test_paper_book_ledger.py tradeloop/tests/test_router_ledger.py tradeloop/tests/test_ledger_integration.py -q`
   Expected: all passed. Then full suite: `python -m pytest -q` — expected: green (P0 tests unaffected since signatures are additive-only).

5. Commit:
   `git commit -am "Phase 2 Task 8: end-to-end ledger integration + chain regression"`

---

## Self-review

**Spec/DoD coverage (Phase 2 = DoD #2, "add the flight recorder; derive positions/P&L from it; log every fetch"):**
- Append-only hash-**chained** SQLite ledger with canonical-JSON rows — Task 1 (`row_hash(prev_hash, seq, event)`, a true chain that engine-1's `event_log.py` lacks: engine-1 hashes only `type|aggregate|payload` per row with no `prev_hash`).
- Tamper detection (mutation + deletion break the chain) — Task 2 `verify_chain`.
- `replay(types)` — Task 1; `project_positions() -> PaperBroker` replaying `paper.order.filled` through `PaperBroker._apply_fill` — Task 3; matches §6 signatures.
- Replaces `paper_book.hydrate()` body, P0 callers unchanged (identical signatures) — Task 5.
- Log every event as it happens: risk verdict + fill from P0's order path — Task 6; fetch success/failure + model call loggers (wire points for P1/P3) — Task 7.
- Markdown projection: event log → human-readable journal, atomic write (`.tmp`+`replace`), content-hash idempotency, `source_event_hash` frontmatter per `config/memory.yaml` — Task 4.
- Required tests all present: append+replay (T1), hash-chain tamper detection (T2), `project_positions` matches a known fill sequence (T3), projection idempotency (T4), plus integration (T8).
- SQLite is stdlib — no new dependency added (pyproject untouched).

**Placeholder scan:** No "TBD"/"similar to Task N"/"add error handling" left. Every test is real pytest; every implementation block is complete runnable code. Every referenced symbol is defined: `Ledger`/`canonical`/`row_hash`/`GENESIS_HASH`/event-type constants (T1), `verify_chain`/`LedgerTamperError` (T2), `project_positions` (T3), `content_hash`/`ProjectionResult`/`MarkdownProjector` (T4), `hydrate`/`append` (T5, §6), the `ledger` kwarg on `route_orders_file` (T6), loggers (T7). `PaperBroker`/`OrderTicket`/`Fill`/`_apply_fill` come from P0's `paper_broker.py` (verified: `_apply_fill` at line 71, `Fill` at line 22 has no `hard_stop` — handled via the `hard_stops` map in T5/T8). `evaluate`/`RiskState`/`RiskCaps` from `checks.py` (verified). `load_settings`/`paper_starting_inr`, `load_ticker_master` (returns `List[TickerRecord]`; T6 reads `[0].symbol` — `TickerMaster.symbols()` is P3-only), and `route_orders_file`'s P0 body are consumed, not redefined.

**Type consistency:** `append(event: dict) -> str` returns the 64-char row hash (§6). `replay(types: list[str] | None) -> list[dict]` where each dict is the payload plus `seq`/`prev_hash`/`row_hash` (§6). `project_positions(starting_cash_inr: float = 0.0) -> PaperBroker` — default arg keeps §6's zero-arg call valid while letting `paper_book.hydrate` pass real starting cash. `paper_book.hydrate/append` keep P0 signatures exactly (the `hard_stops` param is keyword-only-defaulted, so P0's positional `append(path, fills)` calls remain valid). `route_orders_file` gains only a defaulted keyword (`ledger=None`), so P0's §6 signature and every existing caller/test stay valid.
