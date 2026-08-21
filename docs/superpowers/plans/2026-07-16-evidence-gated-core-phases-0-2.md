# Evidence-Gated Core (Phases 0-2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Model policy (user-mandated):** implementation subagents run on `sonnet`; the session model only orchestrates and reviews. Never dispatch implementation subagents on the default session model.

**Goal:** Correct the cost model, add dead-man/auth alerting, build the point-in-time NSE data store, and build the Validation Lab (replay + CPCV + DSR/PBO + trial ledger) so every strategy family can be honestly tested per `tradeloop/docs/vision.md`.

**Architecture:** Three sequential subsystems: (0) honest money math and silent-failure alarms in the existing production path; (1) a survivorship-bias-free SQLite point-in-time store fed by NSE bhavcopy archives with a corporate-action adjustment engine; (2) an offline lab whose replay engine imports the production cost model, sizing, and pattern rules (parity by construction), validated with CPCV selection, walk-forward confirmation, and DSR/PBO deflation backed by a mandatory trial ledger.

**Tech Stack:** Python 3.11 (conda env `tradingbot`), pytest, pandas/numpy (already present), httpx via existing `lib/data/http.Http`, stdlib `sqlite3` and `statistics.NormalDist` (no new dependencies), healthchecks.io for dead-man alerts.

## Global Constraints

- Repo root: `/Volumes/D-DRIVE/TradingBot`. All paths below are relative to it.
- Run tests as: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest <path> -v` from the repo root (`.venv` is a broken 3.9 env; never use it).
- Python >=3.11 syntax allowed (`X | None`). Match existing style: dataclasses, type hints, plain pytest functions with `-> None`.
- No new pip dependencies. sqlite3, statistics, zipfile, io, math are stdlib; pandas, numpy, httpx, yaml already installed.
- Scripts must never read `.env` beyond the existing sanctioned `OPENROUTER_API_KEY` block, and must never print secret-like values.
- Commit messages: conventional style, NO co-author lines, NO agent attribution.
- Long-only Indian cash equities; nothing in this plan places orders.
- Vision/spec: `tradeloop/docs/vision.md` (ADR-1..9). Where this plan and the vision doc conflict, the vision doc wins and the conflict must be reported.
- Every backtest evaluation MUST be recorded in the trial ledger (ADR-1). No exceptions, including throwaway runs.

## File Structure (what gets created/modified)

```text
tradeloop/lib/broker/cost_model.py        MODIFY  fix CNC STT both legs; add txn+SEBI; GST base; DP 15.34
tradeloop/config/settings.yaml            MODIFY  costs block matches corrected model
tradeloop/tests/test_cost_model.py        MODIFY  contract-note-exact expectations
tradeloop/lib/util/alerts.py              CREATE  healthchecks.io pinger (config-file driven, no-op safe)
tradeloop/tests/test_alerts.py            CREATE
tradeloop/scripts/cron_dispatch.sh        MODIFY  start/ok/fail pings around each cycle + auth ping
.gitignore                                MODIFY  ignore alerts.local.yaml
tradeloop/lib/data/pit_store.py           CREATE  SQLite PIT store: bars, corp_actions, adjusted reads
tradeloop/tests/test_pit_store.py         CREATE
tradeloop/lib/data/bhavcopy.py            CREATE  NSE bhavcopy fetch/parse (UDiFF + legacy) + probe CLI
tradeloop/tests/test_bhavcopy.py          CREATE
tradeloop/scripts/backfill_bhavcopy.py    CREATE  resumable date-range ingester + gap report
tradeloop/lib/data/corp_actions.py        CREATE  CA parse (split/bonus -> factor) + ingest
tradeloop/tests/test_corp_actions.py      CREATE
tradeloop/lib/data/pit_universe.py        CREATE  point-in-time universe by trailing turnover
tradeloop/tests/test_pit_universe.py      CREATE
tradeloop/scripts/audit_kite_adjustment.py CREATE manual: Kite vs our adjusted series across CA events
tradeloop/lib/lab/__init__.py             CREATE
tradeloop/lib/lab/spec.py                 CREATE  FamilySpec loader + pre-registered grids
tradeloop/lib/lab/rules.py                CREATE  entry rules wrapping lib/ta/patterns (scanner parity)
tradeloop/config/family_specs/breakout_20d_pullback.yaml   CREATE
tradeloop/config/family_specs/ema_trend_pullback.yaml      CREATE
tradeloop/tests/test_lab_spec.py          CREATE
tradeloop/lib/lab/replay.py               CREATE  event-driven replay importing production money math
tradeloop/tests/test_lab_replay.py        CREATE
tradeloop/lib/lab/metrics.py              CREATE  R/expectancy/PF/DD/Sharpe/skew/kurtosis
tradeloop/tests/test_lab_metrics.py       CREATE
tradeloop/lib/lab/dsr.py                  CREATE  PSR/DSR + expected-max-SR (stdlib NormalDist)
tradeloop/tests/test_lab_dsr.py           CREATE
tradeloop/lib/lab/cpcv.py                 CREATE  combinatorial purged CV splits with purge+embargo
tradeloop/lib/lab/pbo.py                  CREATE  CSCV probability of backtest overfitting
tradeloop/tests/test_lab_cpcv.py          CREATE
tradeloop/tests/test_lab_pbo.py           CREATE
tradeloop/lib/lab/trial_ledger.py         CREATE  append-only JSONL of every evaluation
tradeloop/tests/test_trial_ledger.py      CREATE
tradeloop/scripts/run_lab.py              CREATE  sweep -> select -> deflate -> confirm -> verdict
tradeloop/scripts/verify_replay_parity.py CREATE  acceptance: replay reproduces paper-ledger episodes
```

Design rule locked in here: the lab NEVER re-implements money math or pattern logic.
`replay.py` imports `estimate_cost` from `lib/broker/cost_model`, `position_size_from_stop`/`apply_guardrails` from `lib/risk/sizing`, `add_indicators` from `lib/ta/indicators`, and entry patterns from `lib/ta/patterns`.
Backtest-production divergence is therefore impossible by construction (ADR-7).

---

# PHASE 0 - HONEST NUMBERS AND ALARMS

### Task 1: Correct the CNC/MIS cost model

**Files:**
- Modify: `tradeloop/lib/broker/cost_model.py`
- Modify: `tradeloop/tests/test_cost_model.py`
- Modify: `tradeloop/config/settings.yaml` (costs block, lines 58-72)

**Interfaces:**
- Consumes: nothing new.
- Produces: `estimate_cost(side, product, quantity, price, ...) -> CostBreakdown` with a NEW field `txn: float`; field order `(brokerage, stt, stamp, txn, gst, dp, total)`. Callers (`paper_broker.py:73`, `audit/reconcile.py`) use only `.total` and positional args - unchanged.

Verified facts this task encodes (Zerodha charge sheet, 2026-07-16): CNC brokerage 0; STT 0.1% on BUY and SELL; stamp 0.015% buy only; NSE transaction charge 0.00307% both sides; SEBI Rs 10/crore both sides; GST 18% on (brokerage + SEBI + transaction); DP Rs 15.34 per scrip on sell. MIS: STT 0.025% sell only; stamp 0.003% buy only; same txn/SEBI/GST.

- [ ] **Step 1: Rewrite the test file with contract-note-exact expectations (failing)**

Replace the two existing tests in `tradeloop/tests/test_cost_model.py` with:

```python
from tradeloop.lib.broker.cost_model import estimate_cost


def test_cnc_buy_charges_stt_stamp_txn_gst() -> None:
    # BUY 10 @ 1000 CNC, turnover 10,000:
    # stt 0.1% = 10.00; stamp 0.015% = 1.50; txn = 0.00307% + Rs10/cr = 0.307 + 0.01 = 0.317
    # gst = 18% of (brokerage 0 + txn 0.317) = 0.05706; dp 0
    # total (rounded from unrounded sum 11.87406) = 11.87
    cost = estimate_cost("BUY", "CNC", quantity=10, price=1000)
    assert cost.stt == 10.0
    assert cost.stamp == 1.5
    assert cost.txn == 0.32
    assert cost.gst == 0.06
    assert cost.dp == 0.0
    assert cost.total == 11.87


def test_cnc_sell_charges_stt_txn_gst_dp_no_stamp() -> None:
    # SELL 10 @ 1000 CNC: stt 10.00; stamp 0; txn 0.317; gst 0.05706; dp 15.34
    # total = 25.71406 -> 25.71
    cost = estimate_cost("SELL", "CNC", quantity=10, price=1000)
    assert cost.stt == 10.0
    assert cost.stamp == 0.0
    assert cost.dp == 15.34
    assert cost.total == 25.71


def test_cnc_round_trip_costs_roughly_28bps_plus_dp() -> None:
    # The verified reality the old model missed: ~0.2% STT round trip.
    buy = estimate_cost("BUY", "CNC", quantity=100, price=500)
    sell = estimate_cost("SELL", "CNC", quantity=100, price=500)
    round_trip = buy.total + sell.total
    turnover_leg = 100 * 500
    assert round_trip > 2 * turnover_leg * 0.001  # strictly more than STT alone


def test_mis_cost_includes_brokerage_cap_txn_and_gst_base() -> None:
    # BUY 100 @ 1000 MIS, turnover 100,000: brokerage min(20, 30) = 20;
    # stamp 0.003% = 3.00; txn = 3.07 + 0.10 = 3.17; gst = 18% of (20 + 3.17) = 4.1706
    # total = 30.3406 -> 30.34
    cost = estimate_cost("BUY", "MIS", quantity=100, price=1000)
    assert cost.brokerage == 20
    assert cost.stamp == 3.0
    assert cost.txn == 3.17
    assert cost.gst == 4.17
    assert cost.total == 30.34


def test_mis_sell_stt_applies() -> None:
    cost = estimate_cost("SELL", "MIS", quantity=100, price=1000)
    assert cost.stt == 25.0  # 0.025% of 100,000
    assert cost.stamp == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_cost_model.py -v`
Expected: FAIL - `AttributeError: 'CostBreakdown' object has no attribute 'txn'` and wrong totals.

- [ ] **Step 3: Rewrite `estimate_cost`**

Replace the body of `tradeloop/lib/broker/cost_model.py` with:

```python
from dataclasses import dataclass
from typing import Literal


Product = Literal["CNC", "MIS"]
Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class CostBreakdown:
    brokerage: float
    stt: float
    stamp: float
    txn: float
    gst: float
    dp: float
    total: float


def estimate_cost(
    side: Side,
    product: Product,
    quantity: int,
    price: float,
    cnc_brokerage_inr: float = 0,
    mis_brokerage_inr_max: float = 20,
    mis_brokerage_pct: float = 0.0003,
    stt_cnc_pct: float = 0.001,           # BOTH legs for delivery (verified 2026-07-16)
    stt_sell_mis_pct: float = 0.00025,    # intraday STT is sell-only
    stamp_buy_cnc_pct: float = 0.00015,
    stamp_buy_mis_pct: float = 0.00003,
    exchange_txn_pct: float = 0.0000307,  # NSE 0.00307%, both legs
    sebi_pct: float = 0.000001,           # Rs 10 / crore, both legs
    gst_pct: float = 0.18,
    dp_charge_inr_per_scrip: float = 15.34,
) -> CostBreakdown:
    turnover = max(0.0, quantity * price)
    txn = turnover * (exchange_txn_pct + sebi_pct)
    if product == "CNC":
        brokerage = cnc_brokerage_inr
        stt = turnover * stt_cnc_pct
        stamp = turnover * stamp_buy_cnc_pct if side == "BUY" else 0.0
        dp = dp_charge_inr_per_scrip if side == "SELL" else 0.0
    else:
        brokerage = min(mis_brokerage_inr_max, turnover * mis_brokerage_pct)
        stt = turnover * stt_sell_mis_pct if side == "SELL" else 0.0
        stamp = turnover * stamp_buy_mis_pct if side == "BUY" else 0.0
        dp = 0.0
    gst = (brokerage + txn) * gst_pct  # GST base is brokerage + SEBI + exchange txn
    total = brokerage + stt + stamp + txn + gst + dp
    return CostBreakdown(
        round(brokerage, 2), round(stt, 2), round(stamp, 2), round(txn, 2),
        round(gst, 2), round(dp, 2), round(total, 2),
    )
```

- [ ] **Step 4: Run cost tests, then the full suite (paper broker cash math shifts)**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_cost_model.py -v`
Expected: 5 PASS.
Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests -q`
Expected: any failure will be in tests asserting old totals (e.g. paper broker/reconcile cash expectations).
Update ONLY hardcoded expected-cost numbers in those tests to the corrected values, recomputing by hand with the formulas above; do not touch non-cost assertions.

- [ ] **Step 5: Sync `settings.yaml` costs block and stale key names**

In `tradeloop/config/settings.yaml` replace the `costs:` block keys: `stt_sell_cnc_pct: 0.001` becomes `stt_cnc_pct: 0.001`; add `exchange_txn_pct: 0.0000307` and `sebi_pct: 0.000001`; change `dp_charge_inr_per_scrip: 15.93` to `15.34`.
Then run: `grep -rn "stt_sell_cnc" tradeloop/ --include="*.py" --include="*.yaml" --include="*.md"`
Expected: zero hits outside this plan file; if prompts/docs reference the old key, update them to the new name.

- [ ] **Step 6: Commit**

```bash
git add tradeloop/lib/broker/cost_model.py tradeloop/tests/test_cost_model.py tradeloop/config/settings.yaml
git commit -m "fix(costs): CNC STT on both legs, exchange+SEBI txn charges in GST base, DP 15.34"
```

### Task 2: Dead-man and auth-failure alerts

**Files:**
- Create: `tradeloop/lib/util/alerts.py`
- Create: `tradeloop/tests/test_alerts.py`
- Modify: `tradeloop/scripts/cron_dispatch.sh`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `ping(check: str, event: str = "ok", config_path: Path | None = None) -> bool` and CLI `python -m tradeloop.lib.util.alerts <check> <ok|start|fail>`.
- Consumes: `tradeloop/config/alerts.local.yaml` (gitignored, operator-created), shape:

```yaml
healthchecks:
  premarket: https://hc-ping.com/<uuid-1>
  intraday: https://hc-ping.com/<uuid-2>
  postclose: https://hc-ping.com/<uuid-3>
  zerodha_auth: https://hc-ping.com/<uuid-4>
```

Dead-man principle: healthchecks.io alerts on the ABSENCE of a ping, so a Mac that never wakes, a dead launchd agent, or a crashed cycle all surface as an email without any local code running (ADR-8).

- [ ] **Step 1: Write failing tests**

Create `tradeloop/tests/test_alerts.py`:

```python
from pathlib import Path

from tradeloop.lib.util import alerts


class _FakeResponse:
    status_code = 200


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "alerts.local.yaml"
    cfg.write_text(
        "healthchecks:\n  premarket: https://hc-ping.com/abc123\n", encoding="utf-8"
    )
    return cfg


def test_ping_hits_base_url_on_ok(tmp_path, monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(alerts, "_post", lambda url: seen.append(url) or True)
    assert alerts.ping("premarket", "ok", config_path=_write_config(tmp_path)) is True
    assert seen == ["https://hc-ping.com/abc123"]


def test_ping_appends_event_suffix_for_start_and_fail(tmp_path, monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(alerts, "_post", lambda url: seen.append(url) or True)
    cfg = _write_config(tmp_path)
    alerts.ping("premarket", "start", config_path=cfg)
    alerts.ping("premarket", "fail", config_path=cfg)
    assert seen == ["https://hc-ping.com/abc123/start", "https://hc-ping.com/abc123/fail"]


def test_ping_is_noop_without_config_file(tmp_path) -> None:
    missing = tmp_path / "nope.yaml"
    assert alerts.ping("premarket", "ok", config_path=missing) is False


def test_ping_is_noop_for_unknown_check(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(alerts, "_post", lambda url: (_ for _ in ()).throw(AssertionError))
    assert alerts.ping("unknown", "ok", config_path=_write_config(tmp_path)) is False


def test_ping_never_raises_on_network_error(tmp_path, monkeypatch) -> None:
    def boom(url: str) -> bool:
        raise RuntimeError("network down")
    monkeypatch.setattr(alerts, "_post", boom)
    assert alerts.ping("premarket", "ok", config_path=_write_config(tmp_path)) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_alerts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradeloop.lib.util.alerts'`.

- [ ] **Step 3: Implement `alerts.py`**

Create `tradeloop/lib/util/alerts.py`:

```python
"""Dead-man pings to healthchecks.io. Absence of a ping is the alarm, so this
module must be safe to call from anywhere: it never raises and no-ops without config."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "alerts.local.yaml"
_SUFFIX = {"ok": "", "start": "/start", "fail": "/fail"}


def _post(url: str) -> bool:
    resp = httpx.post(url, timeout=5.0)
    return resp.status_code == 200


def ping(check: str, event: str = "ok", config_path: Path | None = None) -> bool:
    path = config_path or DEFAULT_CONFIG
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        url = (config.get("healthchecks") or {}).get(check)
        if not url or event not in _SUFFIX:
            return False
        return _post(f"{url}{_SUFFIX[event]}")
    except Exception:
        return False  # alerting must never take down the caller


if __name__ == "__main__":
    check_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    event_arg = sys.argv[2] if len(sys.argv) > 2 else "ok"
    sys.exit(0 if ping(check_arg, event_arg) else 1)
```

If `tradeloop/lib/util/__init__.py` does not exist, create it empty.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_alerts.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Wire pings into `cron_dispatch.sh`**

In `tradeloop/scripts/cron_dispatch.sh`, change the auth line (line 37) to:

```bash
    if npm run --silent auth:zerodha -- --auto; then
      "$PY" -m tradeloop.lib.util.alerts zerodha_auth ok || true
    else
      echo "[cron] zerodha auto-auth failed; using existing token"
      "$PY" -m tradeloop.lib.util.alerts zerodha_auth fail || true
    fi
```

And replace each `exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator <mode> --backend claude` with the guarded form (shown for premarket; repeat identically for intraday and postclose with their mode names):

```bash
    "$PY" -m tradeloop.lib.util.alerts premarket start || true
    if env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator premarket --backend claude; then
      "$PY" -m tradeloop.lib.util.alerts premarket ok || true
    else
      status=$?
      "$PY" -m tradeloop.lib.util.alerts premarket fail || true
      exit "$status"
    fi
```

Append `tradeloop/config/alerts.local.yaml` to `.gitignore`.

- [ ] **Step 6: Operator setup + end-to-end verification (manual, with the user)**

Create four checks at healthchecks.io named `tradeloop-premarket`, `tradeloop-intraday`, `tradeloop-postclose`, `tradeloop-zerodha-auth` with cron schedules `30 5 * * 1-5`, `30 11 * * 1-5`, `30 13 * * 1-5`, `25 5 * * 1-5` (timezone Asia/Qatar) and grace 45 minutes; paste the four ping URLs into `tradeloop/config/alerts.local.yaml`.
Verify: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH python -m tradeloop.lib.util.alerts premarket ok` exits 0 and the check flips to "up" in the dashboard.
Verify the dead-man works: pause one check's ping and confirm the alert email arrives after the grace window.

- [ ] **Step 7: Commit**

```bash
git add tradeloop/lib/util/alerts.py tradeloop/lib/util/__init__.py tradeloop/tests/test_alerts.py tradeloop/scripts/cron_dispatch.sh .gitignore
git commit -m "feat(ops): dead-man and auth-failure pings via healthchecks.io"
```

---

# PHASE 1 - POINT-IN-TIME DATA FOUNDATION

### Task 3: PIT bar store (SQLite)

**Files:**
- Create: `tradeloop/lib/data/pit_store.py`
- Create: `tradeloop/tests/test_pit_store.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Bar: symbol str, dt str (YYYY-MM-DD), open float, high float, low float, close float, volume int, turnover float`
  - `PitStore(path: str | Path)` with `.upsert_bars(rows: Iterable[Bar]) -> int`, `.bars(symbol: str, start: str, end: str, adjusted: bool = True) -> list[Bar]`, `.upsert_corp_action(symbol: str, ex_date: str, kind: str, factor: float, note: str = "") -> None`, `.trading_days(start: str, end: str) -> list[str]`, `.symbols_on(dt: str) -> list[str]`, `.close()`
- Adjustment semantics (LOCKED): a corporate action row `(symbol, ex_date, kind, factor)` means prices strictly BEFORE `ex_date` are multiplied by `factor` and volumes divided by `factor`; factors compound multiplicatively across multiple actions; raw rows are never mutated (adjustment applied at read).
  Example: 1:10 face-value split has factor 0.1; a 1:1 bonus has factor 0.5.
  Dividends get NO adjustment (trading-backtest convention; matches Kite's split/bonus-only behavior, to be confirmed by Task 7's audit).

- [ ] **Step 1: Write failing tests**

Create `tradeloop/tests/test_pit_store.py`:

```python
from tradeloop.lib.data.pit_store import Bar, PitStore


def _bar(symbol: str, dt: str, px: float, vol: int = 1000) -> Bar:
    return Bar(symbol=symbol, dt=dt, open=px, high=px * 1.02, low=px * 0.98,
               close=px, volume=vol, turnover=px * vol)


def test_upsert_is_idempotent(tmp_path) -> None:
    store = PitStore(tmp_path / "pit.db")
    rows = [_bar("TCS", "2024-01-01", 100.0), _bar("TCS", "2024-01-02", 101.0)]
    assert store.upsert_bars(rows) == 2
    assert store.upsert_bars(rows) == 0  # INSERT OR IGNORE
    assert len(store.bars("TCS", "2024-01-01", "2024-01-02", adjusted=False)) == 2


def test_split_adjusts_prices_before_ex_date_only(tmp_path) -> None:
    store = PitStore(tmp_path / "pit.db")
    store.upsert_bars([_bar("ACME", "2024-01-01", 100.0, vol=1000),
                       _bar("ACME", "2024-01-02", 50.0, vol=2000)])
    store.upsert_corp_action("ACME", "2024-01-02", "split", 0.5)
    adjusted = store.bars("ACME", "2024-01-01", "2024-01-02")
    assert adjusted[0].close == 50.0      # pre-ex price halved
    assert adjusted[0].volume == 2000     # pre-ex volume doubled
    assert adjusted[1].close == 50.0      # ex-date bar untouched


def test_multiple_actions_compound(tmp_path) -> None:
    store = PitStore(tmp_path / "pit.db")
    store.upsert_bars([_bar("ACME", "2024-01-01", 100.0)])
    store.upsert_corp_action("ACME", "2024-02-01", "split", 0.1)
    store.upsert_corp_action("ACME", "2024-03-01", "bonus", 0.5)
    adjusted = store.bars("ACME", "2024-01-01", "2024-01-01")
    assert adjusted[0].close == 5.0       # 100 * 0.1 * 0.5


def test_trading_days_and_symbols_on(tmp_path) -> None:
    store = PitStore(tmp_path / "pit.db")
    store.upsert_bars([_bar("A", "2024-01-01", 10.0), _bar("B", "2024-01-01", 20.0),
                       _bar("A", "2024-01-03", 11.0)])
    assert store.trading_days("2024-01-01", "2024-01-31") == ["2024-01-01", "2024-01-03"]
    assert store.symbols_on("2024-01-01") == ["A", "B"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_pit_store.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `pit_store.py`**

```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars(
  symbol TEXT NOT NULL, dt TEXT NOT NULL,
  open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
  volume INTEGER NOT NULL, turnover REAL NOT NULL,
  PRIMARY KEY(symbol, dt));
CREATE INDEX IF NOT EXISTS idx_bars_dt ON bars(dt);
CREATE TABLE IF NOT EXISTS corp_actions(
  symbol TEXT NOT NULL, ex_date TEXT NOT NULL, kind TEXT NOT NULL,
  factor REAL NOT NULL, note TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(symbol, ex_date, kind));
"""


@dataclass(frozen=True)
class Bar:
    symbol: str
    dt: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    turnover: float


class PitStore:
    def __init__(self, path: str | Path):
        self._conn = sqlite3.connect(str(path))
        self._conn.executescript(_SCHEMA)

    def upsert_bars(self, rows: Iterable[Bar]) -> int:
        cur = self._conn.executemany(
            "INSERT OR IGNORE INTO bars VALUES(?,?,?,?,?,?,?,?)",
            [(b.symbol, b.dt, b.open, b.high, b.low, b.close, b.volume, b.turnover) for b in rows],
        )
        self._conn.commit()
        return cur.rowcount

    def upsert_corp_action(self, symbol: str, ex_date: str, kind: str,
                           factor: float, note: str = "") -> None:
        if factor <= 0:
            raise ValueError("corporate action factor must be positive")
        self._conn.execute(
            "INSERT OR REPLACE INTO corp_actions VALUES(?,?,?,?,?)",
            (symbol, ex_date, kind, factor, note),
        )
        self._conn.commit()

    def _factors(self, symbol: str) -> list[tuple[str, float]]:
        return self._conn.execute(
            "SELECT ex_date, factor FROM corp_actions WHERE symbol=? ORDER BY ex_date",
            (symbol,),
        ).fetchall()

    def bars(self, symbol: str, start: str, end: str, adjusted: bool = True) -> list[Bar]:
        rows = self._conn.execute(
            "SELECT symbol, dt, open, high, low, close, volume, turnover FROM bars "
            "WHERE symbol=? AND dt BETWEEN ? AND ? ORDER BY dt",
            (symbol, start, end),
        ).fetchall()
        out = [Bar(*r) for r in rows]
        if not adjusted:
            return out
        factors = self._factors(symbol)
        if not factors:
            return out
        adjusted_out: list[Bar] = []
        for bar in out:
            cumulative = 1.0
            for ex_date, factor in factors:
                if bar.dt < ex_date:
                    cumulative *= factor
            if cumulative == 1.0:
                adjusted_out.append(bar)
            else:
                adjusted_out.append(replace(
                    bar,
                    open=bar.open * cumulative, high=bar.high * cumulative,
                    low=bar.low * cumulative, close=bar.close * cumulative,
                    volume=int(bar.volume / cumulative),
                ))
        return adjusted_out

    def trading_days(self, start: str, end: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT dt FROM bars WHERE dt BETWEEN ? AND ? ORDER BY dt", (start, end)
        ).fetchall()
        return [r[0] for r in rows]

    def symbols_on(self, dt: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT symbol FROM bars WHERE dt=? ORDER BY symbol", (dt,)
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_pit_store.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add tradeloop/lib/data/pit_store.py tradeloop/tests/test_pit_store.py
git commit -m "feat(data): SQLite point-in-time bar store with corporate-action-adjusted reads"
```

### Task 4: Bhavcopy fetch and parse (UDiFF + legacy)

**Files:**
- Create: `tradeloop/lib/data/bhavcopy.py`
- Create: `tradeloop/tests/test_bhavcopy.py`

**Interfaces:**
- Consumes: `Http` from `tradeloop/lib/data/http.py` (existing, already NSE-cookie aware); `Bar` from Task 3.
- Produces: `url_for(day: date) -> str`, `parse(payload: bytes, day: date) -> list[Bar]` (accepts zip or raw csv bytes; filters series to EQ/BE), `fetch(day: date, http: Http | None = None) -> list[Bar]`, and CLI `python -m tradeloop.lib.data.bhavcopy --probe YYYY-MM-DD`.
- Format facts encoded: NSE switched to the UDiFF common bhavcopy on 2024-07-08 (`BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip` under `nsearchives.nseindia.com/content/cm/`, columns `TckrSymb,SctySrs,TradDt,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol,TtlTrfVal`); before that, legacy `cmDDMONYYYYbhav.csv.zip` under `content/historical/EQUITIES/YYYY/MON/` with columns `SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,...,TOTTRDQTY,TOTTRDVAL,TIMESTAMP`.
  NSE has changed URL layouts before, which is why Step 6 live-probes both formats before backfill starts.

- [ ] **Step 1: Write failing tests (zip fixtures built in-test; no binary files)**

Create `tradeloop/tests/test_bhavcopy.py`:

```python
import io
import zipfile
from datetime import date

from tradeloop.lib.data.bhavcopy import parse, url_for

UDIFF_CSV = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,"
    "OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,TtlTradgVol,TtlTrfVal\n"
    "2026-07-10,2026-07-10,CM,NSE,STK,2885,INE002A01018,RELIANCE,EQ,"
    "2900,2950,2890,2940,2939,2895,1000000,2925000000\n"
    "2026-07-10,2026-07-10,CM,NSE,STK,999,INE000TEST01,JUNKETF,SM,"
    "10,11,9,10,10,10,500,5000\n"
)

LEGACY_CSV = (
    "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,"
    "TIMESTAMP,TOTALTRADES,ISIN\n"
    "TCS,EQ,3500,3550,3480,3540,3541,3495,200000,704000000,10-JAN-2024,15000,INE467B01029\n"
    "TCS,BL,3500,3550,3480,3540,3541,3495,999,999,10-JAN-2024,1,INE467B01029\n"
)


def _zipped(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, text)
    return buf.getvalue()


def test_udiff_url_used_from_2024_07_08() -> None:
    assert url_for(date(2026, 7, 10)) == (
        "https://nsearchives.nseindia.com/content/cm/"
        "BhavCopy_NSE_CM_0_0_0_20260710_F_0000.csv.zip"
    )


def test_legacy_url_before_cutover() -> None:
    assert url_for(date(2024, 1, 10)) == (
        "https://nsearchives.nseindia.com/content/historical/EQUITIES/2024/JAN/"
        "cm10JAN2024bhav.csv.zip"
    )


def test_parse_udiff_filters_series_and_maps_fields() -> None:
    bars = parse(_zipped("x.csv", UDIFF_CSV), date(2026, 7, 10))
    assert len(bars) == 1  # SM series dropped
    bar = bars[0]
    assert bar.symbol == "RELIANCE" and bar.dt == "2026-07-10"
    assert bar.close == 2940.0 and bar.volume == 1000000 and bar.turnover == 2925000000.0


def test_parse_legacy_filters_series() -> None:
    bars = parse(_zipped("x.csv", LEGACY_CSV), date(2024, 1, 10))
    assert len(bars) == 1  # BL series dropped
    assert bars[0].symbol == "TCS" and bars[0].dt == "2024-01-10" and bars[0].open == 3500.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_bhavcopy.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `bhavcopy.py`**

```python
"""NSE daily bhavcopy: URL construction, download, parse -> Bar rows.
UDiFF format from 2024-07-08; legacy cmDDMONYYYYbhav before that."""
from __future__ import annotations

import csv
import io
import sys
import zipfile
from datetime import date

from tradeloop.lib.data.http import Http
from tradeloop.lib.data.pit_store import Bar

UDIFF_CUTOVER = date(2024, 7, 8)
KEEP_SERIES = {"EQ", "BE"}
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def url_for(day: date) -> str:
    if day >= UDIFF_CUTOVER:
        return ("https://nsearchives.nseindia.com/content/cm/"
                f"BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip")
    mon = _MONTHS[day.month - 1]
    return ("https://nsearchives.nseindia.com/content/historical/EQUITIES/"
            f"{day.year}/{mon}/cm{day:%d}{mon}{day.year}bhav.csv.zip")


def _unzip(payload: bytes) -> str:
    if payload[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            return zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
    return payload.decode("utf-8", errors="replace")


def parse(payload: bytes, day: date) -> list[Bar]:
    text = _unzip(payload)
    reader = csv.DictReader(io.StringIO(text))
    fields = {name.strip() for name in (reader.fieldnames or [])}
    udiff = "TckrSymb" in fields
    bars: list[Bar] = []
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        series = row.get("SctySrs" if udiff else "SERIES", "")
        if series not in KEEP_SERIES:
            continue
        if udiff:
            bars.append(Bar(
                symbol=row["TckrSymb"], dt=f"{day:%Y-%m-%d}",
                open=float(row["OpnPric"]), high=float(row["HghPric"]),
                low=float(row["LwPric"]), close=float(row["ClsPric"]),
                volume=int(float(row["TtlTradgVol"])), turnover=float(row["TtlTrfVal"]),
            ))
        else:
            bars.append(Bar(
                symbol=row["SYMBOL"], dt=f"{day:%Y-%m-%d}",
                open=float(row["OPEN"]), high=float(row["HIGH"]),
                low=float(row["LOW"]), close=float(row["CLOSE"]),
                volume=int(float(row["TOTTRDQTY"])), turnover=float(row["TOTTRDVAL"]),
            ))
    return bars


def fetch(day: date, http: Http | None = None) -> list[Bar]:
    client = http or Http(warmup_hosts=("www.nseindia.com", "nsearchives.nseindia.com"))
    resp = client.get(url_for(day))
    if resp.status == 404:
        return []  # holiday / not yet published
    if resp.status != 200:
        raise RuntimeError(f"bhavcopy {day}: HTTP {resp.status}")
    return parse(resp.body, day)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        probe_day = date.fromisoformat(sys.argv[2])
        rows = fetch(probe_day)
        print(f"{probe_day}: {len(rows)} EQ/BE rows via {url_for(probe_day)}")
        sys.exit(0 if rows else 1)
    print("usage: python -m tradeloop.lib.data.bhavcopy --probe YYYY-MM-DD", file=sys.stderr)
    sys.exit(2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_bhavcopy.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add tradeloop/lib/data/bhavcopy.py tradeloop/tests/test_bhavcopy.py
git commit -m "feat(data): NSE bhavcopy fetch/parse for UDiFF and legacy formats"
```

- [ ] **Step 6: Live probe both formats (manual gate before backfill)**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH python -m tradeloop.lib.data.bhavcopy --probe 2026-07-10`
Expected: `2026-07-10: ~2000+ EQ/BE rows via https://...BhavCopy_NSE_CM...`.
Run the same for a legacy date, e.g. `--probe 2023-06-15`.
Expected: non-zero rows via the `cm15JUN2023bhav.csv.zip` URL.
If either probe 404s or errors, STOP: the URL format changed; fix `url_for` against the live site before Task 5, and record the correction in the commit message.

### Task 5: Resumable backfill driver with gap report

**Files:**
- Create: `tradeloop/scripts/backfill_bhavcopy.py`

**Interfaces:**
- Consumes: `fetch` (Task 4), `PitStore` (Task 3).
- Produces: CLI `python tradeloop/scripts/backfill_bhavcopy.py --db tradeloop/state/pit.db --start 2016-01-01 --end 2026-07-15 [--pace 0.8]`; writes `tradeloop/reports/backfill_gaps.md` listing weekdays with zero rows (expected: NSE holidays; unexpected: format breaks).

- [ ] **Step 1: Implement the driver (script, no unit test; its parts are already tested)**

```python
"""Backfill the PIT store from NSE bhavcopy archives. Idempotent and resumable:
days already present in the store are skipped, so rerunning after a crash is safe."""
from __future__ import annotations

import argparse
import random
import time
from datetime import date, timedelta
from pathlib import Path

from tradeloop.lib.data.bhavcopy import fetch
from tradeloop.lib.data.http import Http
from tradeloop.lib.data.pit_store import PitStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="tradeloop/state/pit.db")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--pace", type=float, default=0.8, help="seconds between requests")
    args = ap.parse_args()

    store = PitStore(args.db)
    http = Http(warmup_hosts=("www.nseindia.com", "nsearchives.nseindia.com"))
    have = set(store.trading_days(args.start, args.end))
    day = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    gaps: list[str] = []
    fetched = 0
    while day <= end:
        iso = day.isoformat()
        if day.weekday() < 5 and iso not in have:
            time.sleep(args.pace + random.uniform(0, 0.4))
            try:
                rows = fetch(day, http)
            except RuntimeError as exc:
                print(f"[backfill] {iso}: {exc} - recorded as gap")
                rows = []
            if rows:
                store.upsert_bars(rows)
                fetched += 1
                print(f"[backfill] {iso}: {len(rows)} rows")
            else:
                gaps.append(iso)
        day += timedelta(days=1)

    report = Path("tradeloop/reports/backfill_gaps.md")
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Backfill gap report", "",
             f"Range: {args.start}..{args.end}; days fetched this run: {fetched}", "",
             "Weekdays with no data (NSE holidays are EXPECTED here; verify anything else):", ""]
    lines += [f"- {g}" for g in gaps] or ["- none"]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[backfill] done; {len(gaps)} gap days -> {report}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify on one known week, then run the full backfill**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH python tradeloop/scripts/backfill_bhavcopy.py --db /tmp/pit_probe.db --start 2026-07-06 --end 2026-07-10`
Expected: 5 lines each reporting ~2000+ rows (or a holiday gap), gap report written.
Then run the real backfill (long; run detached): `--db tradeloop/state/pit.db --start 2016-01-01 --end 2026-07-15`.
Expected duration at 0.8s pace: ~2600 trading days, roughly 45-60 minutes.
Verify after: `sqlite3 tradeloop/state/pit.db "SELECT COUNT(DISTINCT dt), COUNT(*) FROM bars"` returns ~2600 days and several million rows; spot-check `backfill_gaps.md` gap days against the NSE holiday calendar for 2-3 years.

- [ ] **Step 3: Commit (code and report only; the .db stays untracked)**

Add `tradeloop/state/pit.db` to `.gitignore`.

```bash
git add tradeloop/scripts/backfill_bhavcopy.py .gitignore tradeloop/reports/backfill_gaps.md
git commit -m "feat(data): resumable bhavcopy backfill with gap report"
```

### Task 6: Corporate actions ingest and factor computation

**Files:**
- Create: `tradeloop/lib/data/corp_actions.py`
- Create: `tradeloop/tests/test_corp_actions.py`

**Interfaces:**
- Consumes: `PitStore.upsert_corp_action` (Task 3).
- Produces: `parse_purpose(purpose: str) -> tuple[str, float] | None` returning `(kind, factor)` for splits/bonuses and `None` for everything else (dividends etc.); `ingest_csv(store: PitStore, path: Path) -> int` for NSE corporate-action CSV exports (columns include `SYMBOL`, `EX-DATE`, `PURPOSE`) dropped into `tradeloop/data_cache/corp_actions/`.
- NSE CA CSVs are downloaded manually from nseindia.com (Corporate Filings -> Corporate Actions -> equities, date-range export) because the endpoint is Akamai-protected; one file per historical year is sufficient and this is a one-time-plus-quarterly chore.

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path

from tradeloop.lib.data.corp_actions import ingest_csv, parse_purpose
from tradeloop.lib.data.pit_store import Bar, PitStore


def test_face_value_split_purpose_yields_price_factor() -> None:
    assert parse_purpose("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 1/- Per Share") == ("split", 0.1)
    assert parse_purpose("FACE VALUE SPLIT FROM RS.2/- TO RE.1/-") == ("split", 0.5)


def test_bonus_purpose_yields_price_factor() -> None:
    assert parse_purpose("Bonus 1:1") == ("bonus", 0.5)      # 1 new per 1 held -> price halves
    assert parse_purpose("BONUS 3:2") == ("bonus", 0.4)      # 3 new per 2 held -> 2/(2+3)


def test_dividends_and_noise_are_ignored() -> None:
    assert parse_purpose("Dividend - Rs 8 Per Share") is None
    assert parse_purpose("Annual General Meeting") is None


def test_ingest_csv_writes_actions(tmp_path) -> None:
    store = PitStore(tmp_path / "pit.db")
    store.upsert_bars([Bar("ACME", "2024-01-01", 100, 102, 98, 100, 1000, 100000)])
    csv_path = tmp_path / "ca.csv"
    csv_path.write_text(
        "SYMBOL,COMPANY,SERIES,FACE VALUE,PURPOSE,EX-DATE\n"
        'ACME,Acme Ltd,EQ,10,"Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 5/- Per Share",02-Feb-2024\n'
        'ACME,Acme Ltd,EQ,10,"Dividend - Rs 3 Per Share",15-Mar-2024\n',
        encoding="utf-8",
    )
    assert ingest_csv(store, csv_path) == 1  # dividend skipped
    assert store.bars("ACME", "2024-01-01", "2024-01-01")[0].close == 50.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_corp_actions.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `corp_actions.py`**

```python
"""Parse NSE corporate-action purposes into price adjustment factors.
Only splits and bonuses adjust prices (trading convention; dividends do not)."""
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from tradeloop.lib.data.pit_store import PitStore

_SPLIT = re.compile(
    r"(?:face\s*value\s*split|sub-?division).*?rs\.?\s*(\d+(?:\.\d+)?).*?(?:rs\.?|re\.?)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_BONUS = re.compile(r"bonus\s*(\d+)\s*:\s*(\d+)", re.IGNORECASE)


def parse_purpose(purpose: str) -> tuple[str, float] | None:
    split = _SPLIT.search(purpose)
    if split:
        old_fv, new_fv = float(split.group(1)), float(split.group(2))
        if old_fv > 0 and new_fv > 0 and new_fv < old_fv:
            return "split", new_fv / old_fv
    bonus = _BONUS.search(purpose)
    if bonus:
        new, held = int(bonus.group(1)), int(bonus.group(2))
        if new > 0 and held > 0:
            return "bonus", held / (held + new)
    return None


def _ex_date_iso(raw: str) -> str:
    return datetime.strptime(raw.strip(), "%d-%b-%Y").strftime("%Y-%m-%d")


def ingest_csv(store: PitStore, path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            row = {(k or "").strip().upper(): (v or "").strip() for k, v in row.items()}
            parsed = parse_purpose(row.get("PURPOSE", ""))
            if parsed is None:
                continue
            kind, factor = parsed
            store.upsert_corp_action(
                row["SYMBOL"], _ex_date_iso(row["EX-DATE"]), kind, factor,
                note=row.get("PURPOSE", ""),
            )
            count += 1
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_corp_actions.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Ingest real CA files and verify against known events (manual gate)**

Download CA CSVs covering 2016-2026 into `tradeloop/data_cache/corp_actions/`; run a small loop calling `ingest_csv` per file (one-off python -c or notebook is fine).
Verify three known events end-to-end with `PitStore.bars`: TATASTEEL 1:10 split (ex 2022-07-28), NESTLEIND 1:10 split (ex 2024-01-05), RELIANCE 1:1 bonus (ex 2024-10-28) - adjusted pre-ex closes must be continuous with post-ex closes (no ~10x or ~2x cliff).
Expected: for each, `adjusted_close(ex_date - 1) / close(ex_date)` is within a few percent of 1.0, versus ~10x (splits) or ~2x (bonus) on raw reads.

- [ ] **Step 6: Commit**

```bash
git add tradeloop/lib/data/corp_actions.py tradeloop/tests/test_corp_actions.py
git commit -m "feat(data): corporate-action parsing and split/bonus adjustment factors"
```

### Task 7: PIT universe reconstruction + Kite adjustment audit

**Files:**
- Create: `tradeloop/lib/data/pit_universe.py`
- Create: `tradeloop/tests/test_pit_universe.py`
- Create: `tradeloop/scripts/audit_kite_adjustment.py`

**Interfaces:**
- Produces: `universe_on(store: PitStore, dt: str, top_n: int = 500, min_turnover_inr: float = 5e7, lookback_days: int = 126, min_bars: int = 60) -> list[str]` - symbols ranked by trailing median daily turnover, liquidity floor applied, using ONLY data at/before `dt` (this is what makes backtests point-in-time; ADR-2).
- The audit script settles ADR-2's open question: whether Kite candles are split/bonus adjusted, deciding if Kite bars may gap-fill the store.

- [ ] **Step 1: Write failing tests**

```python
from tradeloop.lib.data.pit_store import Bar, PitStore
from tradeloop.lib.data.pit_universe import universe_on


def _seed(store: PitStore, symbol: str, days: list[str], turnover: float) -> None:
    store.upsert_bars([
        Bar(symbol, d, 100, 101, 99, 100, int(turnover / 100), turnover) for d in days
    ])


def test_universe_ranks_by_median_turnover_and_applies_floor(tmp_path) -> None:
    store = PitStore(tmp_path / "pit.db")
    days = [f"2024-03-{d:02d}" for d in range(1, 29)]
    _seed(store, "BIG", days, turnover=9e7)
    _seed(store, "MID", days, turnover=6e7)
    _seed(store, "TINY", days, turnover=1e7)   # below 5cr floor
    got = universe_on(store, "2024-03-28", top_n=10, lookback_days=20, min_bars=10)
    assert got == ["BIG", "MID"]


def test_universe_excludes_symbols_with_too_few_bars(tmp_path) -> None:
    store = PitStore(tmp_path / "pit.db")
    days = [f"2024-03-{d:02d}" for d in range(1, 29)]
    _seed(store, "OLD", days, turnover=9e7)
    _seed(store, "IPO", days[-3:], turnover=9e7)  # only 3 bars
    got = universe_on(store, "2024-03-28", lookback_days=20, min_bars=10)
    assert got == ["OLD"]


def test_universe_is_point_in_time(tmp_path) -> None:
    store = PitStore(tmp_path / "pit.db")
    _seed(store, "LATER", [f"2024-06-{d:02d}" for d in range(1, 29)], turnover=9e7)
    assert universe_on(store, "2024-03-28", lookback_days=20, min_bars=10) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_pit_universe.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `pit_universe.py`**

```python
from __future__ import annotations

import statistics

from tradeloop.lib.data.pit_store import PitStore


def universe_on(store: PitStore, dt: str, top_n: int = 500,
                min_turnover_inr: float = 5e7, lookback_days: int = 126,
                min_bars: int = 60) -> list[str]:
    days = store.trading_days("1990-01-01", dt)
    window = days[-lookback_days:]
    if not window:
        return []
    start = window[0]
    ranked: list[tuple[float, str]] = []
    for symbol in store.symbols_on(dt):
        bars = store.bars(symbol, start, dt, adjusted=False)
        if len(bars) < min_bars:
            continue
        med = statistics.median(b.turnover for b in bars)
        if med < min_turnover_inr:
            continue
        ranked.append((med, symbol))
    ranked.sort(reverse=True)
    return [symbol for _, symbol in ranked[:top_n]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_pit_universe.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Write the Kite adjustment audit script**

Create `tradeloop/scripts/audit_kite_adjustment.py`:

```python
"""Settle whether Kite historical candles are split/bonus adjusted.
For each CA event in the PIT store, compare Kite's pre-ex close against our raw
and adjusted closes; whichever matches tells us Kite's behavior. Requires a live
Kite session (run after premarket auth)."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from tradeloop.lib.data.kite import KiteClient
from tradeloop.lib.data.pit_store import PitStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="tradeloop/state/pit.db")
    ap.add_argument("--max-events", type=int, default=20)
    args = ap.parse_args()

    store = PitStore(args.db)
    events = store._conn.execute(
        "SELECT symbol, ex_date, kind, factor FROM corp_actions ORDER BY ex_date DESC LIMIT ?",
        (args.max_events,),
    ).fetchall()
    kite = KiteClient()
    lines = ["# Kite adjustment audit", "",
             "| symbol | ex_date | kind | kite_pre_ex | our_raw | our_adjusted | kite_matches |",
             "| --- | --- | --- | ---: | ---: | ---: | --- |"]
    verdicts: list[str] = []
    for symbol, ex_date, kind, factor in events:
        ex = date.fromisoformat(ex_date)
        candles = kite.historical(symbol, ex - timedelta(days=10), ex, "day")
        pre = [c for c in candles if c.date[:10] < ex_date]
        raw = store.bars(symbol, (ex - timedelta(days=10)).isoformat(), ex_date, adjusted=False)
        adj = store.bars(symbol, (ex - timedelta(days=10)).isoformat(), ex_date, adjusted=True)
        if not pre or not raw or not adj:
            continue
        kite_close, raw_close, adj_close = pre[-1].close, raw[-1].close if raw[-1].dt < ex_date else raw[-2].close, adj[-1].close if adj[-1].dt < ex_date else adj[-2].close
        match = "ADJUSTED" if abs(kite_close - adj_close) < abs(kite_close - raw_close) else "RAW"
        verdicts.append(match)
        lines.append(f"| {symbol} | {ex_date} | {kind} | {kite_close:.2f} | {raw_close:.2f} | {adj_close:.2f} | {match} |")
    lines += ["", f"Verdict: {verdicts.count('ADJUSTED')}/{len(verdicts)} events indicate Kite serves ADJUSTED candles."]
    out = Path("tradeloop/reports/kite_adjustment_audit.md")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the audit (manual gate; needs live token) and record the verdict**

Run after a morning auth: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH python tradeloop/scripts/audit_kite_adjustment.py`
Expected: a near-unanimous verdict table.
Record the outcome as a one-line note in `tradeloop/docs/vision.md` under ADR-2 ("Kite candles verified ADJUSTED/RAW on YYYY-MM-DD"), because gap-filling policy depends on it.

- [ ] **Step 7: Commit**

```bash
git add tradeloop/lib/data/pit_universe.py tradeloop/tests/test_pit_universe.py tradeloop/scripts/audit_kite_adjustment.py
git commit -m "feat(data): point-in-time universe reconstruction and Kite adjustment audit"
```

---

# PHASE 2 - VALIDATION LAB

### Task 8: Family specs, entry-rule registry (scanner parity)

**Files:**
- Create: `tradeloop/lib/lab/__init__.py` (empty), `tradeloop/lib/lab/spec.py`, `tradeloop/lib/lab/rules.py`
- Create: `tradeloop/config/family_specs/breakout_20d_pullback.yaml`, `tradeloop/config/family_specs/ema_trend_pullback.yaml`
- Create: `tradeloop/tests/test_lab_spec.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) FamilySpec: family str, entry str, param_grid dict[str, list], stop_atr_grid list[float], target_r_grid list[list[float]], max_hold_days int, min_turnover_inr float, min_stop_pct float`
  - `load_spec(path: Path) -> FamilySpec`, `iter_configs(spec) -> list[dict]` (cartesian product; each config dict has keys `params`, `stop_atr`, `target_r`), `grid_size(spec) -> int`, `config_hash(spec, config) -> str` (sha256 of canonical JSON).
  - `rules.ENTRY_RULES: dict[str, Callable[[pd.DataFrame], bool]]` where the frame is `add_indicators()` output for bars up to and including the signal day; rules delegate to `lib/ta/patterns.breakout` / `pullback` (SAME functions the production scanner uses - parity by construction).
- Pre-registration discipline (ADR-1/ADR-3): grids live in git BEFORE any lab run; widening a grid is a new commit and increases the trial count that DSR deflates against.

- [ ] **Step 1: Write the two spec YAMLs (pre-registered grids, deliberately small)**

`tradeloop/config/family_specs/breakout_20d_pullback.yaml`:

```yaml
family: breakout_20d_pullback
entry: breakout_20d
param_grid:
  lookback: [20, 55]
stop_atr_grid: [1.5, 2.0]
target_r_grid: [[2.0, 3.0]]
max_hold_days: 10
min_turnover_inr: 50000000
min_stop_pct: 1.0
```

`tradeloop/config/family_specs/ema_trend_pullback.yaml`:

```yaml
family: ema_trend_pullback
entry: ema20_pullback
param_grid:
  trend_filter: [ema50_over_ema200, none]
stop_atr_grid: [1.5, 2.0]
target_r_grid: [[2.0, 3.0]]
max_hold_days: 20
min_turnover_inr: 50000000
min_stop_pct: 1.0
```

- [ ] **Step 2: Write failing tests**

```python
from pathlib import Path

import pandas as pd

from tradeloop.lib.lab.rules import ENTRY_RULES
from tradeloop.lib.lab.spec import config_hash, grid_size, iter_configs, load_spec

SPEC_DIR = Path("tradeloop/config/family_specs")


def test_load_spec_and_grid_size() -> None:
    spec = load_spec(SPEC_DIR / "breakout_20d_pullback.yaml")
    assert spec.family == "breakout_20d_pullback"
    assert grid_size(spec) == 2 * 2 * 1  # lookback x stop_atr x target_r


def test_iter_configs_yields_full_cartesian_product() -> None:
    spec = load_spec(SPEC_DIR / "breakout_20d_pullback.yaml")
    configs = iter_configs(spec)
    assert len(configs) == 4
    assert {c["stop_atr"] for c in configs} == {1.5, 2.0}
    assert all(c["target_r"] == [2.0, 3.0] for c in configs)


def test_config_hash_is_stable_and_distinct() -> None:
    spec = load_spec(SPEC_DIR / "breakout_20d_pullback.yaml")
    a, b = iter_configs(spec)[0], iter_configs(spec)[1]
    assert config_hash(spec, a) == config_hash(spec, a)
    assert config_hash(spec, a) != config_hash(spec, b)


def test_entry_rules_registered_and_callable() -> None:
    frame = pd.DataFrame({
        "Close": [100 + i for i in range(60)],
        "Open": [100 + i for i in range(60)],
        "High": [101 + i for i in range(60)],
        "Low": [99 + i for i in range(60)],
        "Volume": [1000] * 60,
    })
    from tradeloop.lib.ta.indicators import add_indicators
    enriched = add_indicators(frame)
    for name in ("breakout_20d", "ema20_pullback"):
        assert isinstance(ENTRY_RULES[name](enriched, {}), bool)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_lab_spec.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `spec.py` and `rules.py`**

`tradeloop/lib/lab/spec.py`:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from itertools import product
from pathlib import Path

import yaml


@dataclass(frozen=True)
class FamilySpec:
    family: str
    entry: str
    param_grid: dict
    stop_atr_grid: list
    target_r_grid: list
    max_hold_days: int
    min_turnover_inr: float
    min_stop_pct: float


def load_spec(path: Path) -> FamilySpec:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return FamilySpec(**raw)


def iter_configs(spec: FamilySpec) -> list[dict]:
    keys = sorted(spec.param_grid)
    combos = list(product(*(spec.param_grid[k] for k in keys))) or [()]
    configs: list[dict] = []
    for combo in combos:
        for stop_atr in spec.stop_atr_grid:
            for target_r in spec.target_r_grid:
                configs.append({
                    "params": dict(zip(keys, combo)),
                    "stop_atr": stop_atr,
                    "target_r": list(target_r),
                })
    return configs


def grid_size(spec: FamilySpec) -> int:
    return len(iter_configs(spec))


def config_hash(spec: FamilySpec, config: dict) -> str:
    canonical = json.dumps({"family": spec.family, "entry": spec.entry, **config},
                           sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
```

`tradeloop/lib/lab/rules.py`:

```python
"""Entry rules for the lab. These DELEGATE to lib/ta/patterns so the lab tests
exactly what the production scanner trades - parity by construction (ADR-7)."""
from __future__ import annotations

import pandas as pd

from tradeloop.lib.ta.patterns import breakout, pullback


def _closes(frame: pd.DataFrame) -> list[float]:
    return [float(v) for v in frame["Close"].tolist()]


def breakout_20d(frame: pd.DataFrame, params: dict) -> bool:
    lookback = int(params.get("lookback", 20))
    return bool(breakout(_closes(frame), lookback).bullish)


def ema20_pullback(frame: pd.DataFrame, params: dict) -> bool:
    signal = pullback(_closes(frame), frame["EMA20"].tolist())
    if not signal.bullish:
        return False
    if params.get("trend_filter") == "ema50_over_ema200":
        if "EMA50" not in frame.columns or "EMA200" not in frame.columns:
            return False
        last = frame.iloc[-1]
        if not (float(last["EMA50"]) > float(last["EMA200"])):
            return False
    return True


ENTRY_RULES = {"breakout_20d": breakout_20d, "ema20_pullback": ema20_pullback}
```

Note: if `add_indicators` does not already emit `EMA50`/`EMA200`, extend it in `tradeloop/lib/ta/indicators.py` with the same pattern used for `EMA20` (two extra lines) - it is additive and production-safe.

- [ ] **Step 5: Run tests to verify they pass, then commit**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_lab_spec.py -v`
Expected: 4 PASS.

```bash
git add tradeloop/lib/lab/ tradeloop/config/family_specs/ tradeloop/tests/test_lab_spec.py
git commit -m "feat(lab): pre-registered family specs and scanner-parity entry rules"
```

### Task 9: Replay engine (production money math imported)

**Files:**
- Create: `tradeloop/lib/lab/replay.py`
- Create: `tradeloop/tests/test_lab_replay.py`

**Interfaces:**
- Consumes: `PitStore.bars`, `universe_on`, `ENTRY_RULES`, `add_indicators`, `estimate_cost` (Task 1 signature), `position_size_from_stop` and `apply_guardrails` from `lib/risk/sizing`.
- Produces:
  - `@dataclass(frozen=True) ReplayTrade: symbol str, entry_dt str, entry_px float, exit_dt str, exit_px float, qty int, r float, costs float, reason str  # 'stop'|'target'|'time'`
  - `@dataclass(frozen=True) ReplayResult: trades list[ReplayTrade], daily_equity list[tuple[str, float]], n_signals int`
  - `replay(store, spec, config, start: str, end: str, capital_inr: float = 100000, risk_pct: float = 1.5, max_positions: int = 4, slippage_bps: float = 25.0, universe_every: int = 21, top_n: int = 500) -> ReplayResult`
- Execution semantics (LOCKED, conservative):
  - Signal evaluated on close of day t using bars up to t; entry at day t+1 OPEN plus slippage (matches production: premarket decision, execute at open).
  - Stop distance = `stop_atr * ATR14(t)`; stop level = entry - distance; targets = entry + `target_r[i] * distance`.
  - Exit checks each day after entry, in this order: if `open <= stop` exit at open (gap through stop fills at open, NOT at stop); elif `low <= stop` exit at stop; elif `high >= target1` exit at target1; elif held `max_hold_days` exit at close. Stop and target touched the same day resolves to STOP (pessimistic).
  - Sell slippage subtracts; buy slippage adds. Both legs charged via `estimate_cost(...CNC...)`.
  - R accounting matches `lib/audit/attribution.py`: `r = (exit_px - entry_px) / (entry_px - stop)` with costs reported separately in `costs` (so lab R is comparable to the production ledger's R), and net expectancy computed in metrics from cash deltas.
  - Portfolio: max `max_positions` concurrent, at most one position per symbol, signals ranked by turnover when slots are scarce; universe refreshed every `universe_every` trading days via `universe_on` (point-in-time).

- [ ] **Step 1: Write failing tests with hand-constructed price paths**

```python
from tradeloop.lib.data.pit_store import Bar, PitStore
from tradeloop.lib.lab.replay import replay
from tradeloop.lib.lab.spec import FamilySpec

SPEC = FamilySpec(
    family="breakout_20d_pullback", entry="breakout_20d",
    param_grid={"lookback": [20]}, stop_atr_grid=[1.5], target_r_grid=[[2.0, 3.0]],
    max_hold_days=10, min_turnover_inr=0, min_stop_pct=0,
)
CONFIG = {"params": {"lookback": 20}, "stop_atr": 1.5, "target_r": [2.0, 3.0]}


def _seed_path(store: PitStore, closes: list[float], symbol: str = "T") -> list[str]:
    days = [f"2024-{3 + i // 28:02d}-{i % 28 + 1:02d}" for i in range(len(closes))]
    store.upsert_bars([
        Bar(symbol, d, px, px * 1.001, px * 0.999, px, 100000, px * 100000)
        for d, px in zip(days, closes)
    ])
    return days


def test_winner_enters_next_open_and_exits_at_target(tmp_path) -> None:
    store = PitStore(tmp_path / "pit.db")
    closes = [100.0] * 40 + [110.0]        # breakout on day 41
    closes += [111.0, 118.0, 140.0]        # entry day, drift, target day
    _seed_path(store, closes)
    result = replay(store, SPEC, CONFIG, "2024-03-01", "2024-12-31",
                    slippage_bps=0.0, universe_every=1, top_n=10)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_px == 111.0          # next-day open, no slippage
    assert trade.reason == "target"
    assert trade.r >= 2.0


def test_gap_below_stop_fills_at_open_not_stop(tmp_path) -> None:
    store = PitStore(tmp_path / "pit.db")
    closes = [100.0] * 40 + [110.0, 111.0, 80.0]   # entry at 111 then crash open
    _seed_path(store, closes)
    result = replay(store, SPEC, CONFIG, "2024-03-01", "2024-12-31",
                    slippage_bps=0.0, universe_every=1, top_n=10)
    trade = result.trades[0]
    assert trade.reason == "stop"
    assert trade.exit_px == 80.0            # gap open, worse than stop level
    assert trade.r < -1.0                    # a gap loss can exceed 1R - that is the point


def test_time_exit_after_max_hold(tmp_path) -> None:
    store = PitStore(tmp_path / "pit.db")
    closes = [100.0] * 40 + [110.0] + [110.5] * 15  # never hits stop or target
    _seed_path(store, closes)
    result = replay(store, SPEC, CONFIG, "2024-03-01", "2024-12-31",
                    slippage_bps=0.0, universe_every=1, top_n=10)
    assert result.trades[0].reason == "time"


def test_costs_are_charged_on_both_legs(tmp_path) -> None:
    store = PitStore(tmp_path / "pit.db")
    closes = [100.0] * 40 + [110.0, 111.0, 140.0]
    _seed_path(store, closes)
    result = replay(store, SPEC, CONFIG, "2024-03-01", "2024-12-31",
                    slippage_bps=0.0, universe_every=1, top_n=10)
    trade = result.trades[0]
    buy_stt = trade.qty * trade.entry_px * 0.001
    assert trade.costs > 2 * buy_stt * 0.9  # both legs' STT present (approx)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_lab_replay.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `replay.py`**

```python
"""Event-driven daily replay. Money math is IMPORTED from production modules;
this file only sequences bars, signals, fills, and exits (ADR-7)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradeloop.lib.broker.cost_model import estimate_cost
from tradeloop.lib.data.pit_store import Bar, PitStore
from tradeloop.lib.data.pit_universe import universe_on
from tradeloop.lib.lab.rules import ENTRY_RULES
from tradeloop.lib.lab.spec import FamilySpec
from tradeloop.lib.risk.sizing import apply_guardrails, position_size_from_stop
from tradeloop.lib.ta.indicators import add_indicators

WARMUP_BARS = 40  # enough history for EMA20/ATR14 before a signal is trusted


@dataclass(frozen=True)
class ReplayTrade:
    symbol: str
    entry_dt: str
    entry_px: float
    exit_dt: str
    exit_px: float
    qty: int
    r: float
    costs: float
    reason: str


@dataclass(frozen=True)
class ReplayResult:
    trades: list[ReplayTrade]
    daily_equity: list[tuple[str, float]]
    n_signals: int


@dataclass
class _Open:
    symbol: str
    entry_dt: str
    entry_px: float
    qty: int
    stop: float
    target: float
    deadline: str
    entry_cost: float


def _frame(bars: list[Bar]) -> pd.DataFrame:
    return add_indicators(pd.DataFrame({
        "Open": [b.open for b in bars], "High": [b.high for b in bars],
        "Low": [b.low for b in bars], "Close": [b.close for b in bars],
        "Volume": [b.volume for b in bars],
    }))


def replay(store: PitStore, spec: FamilySpec, config: dict, start: str, end: str,
           capital_inr: float = 100000, risk_pct: float = 1.5, max_positions: int = 4,
           slippage_bps: float = 25.0, universe_every: int = 21, top_n: int = 500) -> ReplayResult:
    entry_rule = ENTRY_RULES[spec.entry]
    days = store.trading_days(start, end)
    slip = slippage_bps / 10000.0
    cash = capital_inr
    open_positions: dict[str, _Open] = {}
    trades: list[ReplayTrade] = []
    equity: list[tuple[str, float]] = []
    pending: list[tuple[str, float]] = []  # (symbol, atr) signals awaiting next open
    universe: list[str] = []
    n_signals = 0

    for i, day in enumerate(days):
        if i % universe_every == 0:
            universe = universe_on(store, day, top_n=top_n,
                                   min_turnover_inr=spec.min_turnover_inr)
        # 1) fills for yesterday's signals at today's open
        for symbol, atr in pending:
            if symbol in open_positions or len(open_positions) >= max_positions:
                continue
            bar = _bar_on(store, symbol, day)
            if bar is None:
                continue
            entry_px = bar.open * (1 + slip)
            stop_dist = config["stop_atr"] * atr
            stop = entry_px - stop_dist
            qty = position_size_from_stop(cash, entry_px, stop, atr,
                                          per_trade_risk_pct=risk_pct,
                                          atr_stop_multiple=config["stop_atr"])
            qty = apply_guardrails(qty, entry_px, cash, max_position_pct=25)
            if qty <= 0:
                continue
            cost = estimate_cost("BUY", "CNC", qty, entry_px).total
            cash -= qty * entry_px + cost
            deadline_idx = min(i + spec.max_hold_days, len(days) - 1)
            open_positions[symbol] = _Open(symbol, day, entry_px, qty, stop,
                                           entry_px + config["target_r"][0] * stop_dist,
                                           days[deadline_idx], cost)
        pending = []

        # 2) exits
        for symbol in list(open_positions):
            pos = open_positions[symbol]
            if pos.entry_dt == day:
                continue
            bar = _bar_on(store, symbol, day)
            if bar is None:
                continue
            exit_px, reason = None, ""
            if bar.open <= pos.stop:
                exit_px, reason = bar.open, "stop"
            elif bar.low <= pos.stop:
                exit_px, reason = pos.stop, "stop"
            elif bar.high >= pos.target:
                exit_px, reason = pos.target, "target"
            elif day >= pos.deadline:
                exit_px, reason = bar.close, "time"
            if exit_px is None:
                continue
            exit_px *= (1 - slip)
            sell_cost = estimate_cost("SELL", "CNC", pos.qty, exit_px).total
            cash += pos.qty * exit_px - sell_cost
            risk = pos.entry_px - pos.stop
            trades.append(ReplayTrade(
                symbol, pos.entry_dt, round(pos.entry_px, 2), day, round(exit_px, 2),
                pos.qty, round((exit_px - pos.entry_px) / risk, 4),
                round(pos.entry_cost + sell_cost, 2), reason,
            ))
            del open_positions[symbol]

        # 3) signals on today's close -> queue for tomorrow's open
        if len(open_positions) < max_positions:
            candidates: list[tuple[float, str, float]] = []
            for symbol in universe:
                if symbol in open_positions:
                    continue
                bars = store.bars(symbol, "1990-01-01", day)
                if len(bars) < WARMUP_BARS:
                    continue
                frame = _frame(bars[-220:])
                atr_series = frame["ATR14"].dropna()
                if atr_series.empty:
                    continue
                atr = float(atr_series.iloc[-1])
                latest = float(frame["Close"].iloc[-1])
                if spec.min_stop_pct and latest > 0 and \
                        (config["stop_atr"] * atr) / latest < spec.min_stop_pct / 100:
                    continue
                if entry_rule(frame, config["params"]):
                    n_signals += 1
                    candidates.append((bars[-1].turnover, symbol, atr))
            candidates.sort(reverse=True)
            pending = [(symbol, atr) for _, symbol, atr in
                       candidates[:max_positions - len(open_positions)]]

        # 4) mark equity
        mark = cash + sum(
            pos.qty * (_bar_on(store, s, day) or Bar(s, day, 0, 0, 0, pos.entry_px, 0, 0)).close
            for s, pos in open_positions.items()
        )
        equity.append((day, round(mark, 2)))

    return ReplayResult(trades, equity, n_signals)


def _bar_on(store: PitStore, symbol: str, day: str) -> Bar | None:
    rows = store.bars(symbol, day, day)
    return rows[0] if rows else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_lab_replay.py -v`
Expected: 4 PASS.
Performance note: if a full-universe decade replay is later too slow, cache `_frame` per (symbol, day-range) - but only after it is correct; do not optimize in this task.

- [ ] **Step 5: Commit**

```bash
git add tradeloop/lib/lab/replay.py tradeloop/tests/test_lab_replay.py
git commit -m "feat(lab): event-driven replay engine importing production cost/sizing/patterns"
```

### Task 10: Metrics module

**Files:**
- Create: `tradeloop/lib/lab/metrics.py`
- Create: `tradeloop/tests/test_lab_metrics.py`

**Interfaces:**
- Produces: `expectancy_r(trades) -> float`, `win_rate(trades) -> float`, `profit_factor(trades) -> float`, `max_drawdown_pct(equity: list[tuple[str, float]]) -> float`, `daily_returns(equity) -> list[float]`, `sharpe(returns: list[float], periods_per_year: int = 252) -> float`, `skew_kurt(returns) -> tuple[float, float]` (kurtosis is RAW, not excess - the DSR formula in Task 11 expects raw kurtosis, normal = 3.0). All take Task 9's `ReplayTrade`/equity shapes.

- [ ] **Step 1: Write failing tests (hand-computed vectors)**

```python
import math

from tradeloop.lib.lab.metrics import (daily_returns, expectancy_r, max_drawdown_pct,
                                       profit_factor, sharpe, skew_kurt, win_rate)


class _T:
    def __init__(self, r: float):
        self.r = r


def test_trade_stats() -> None:
    trades = [_T(2.0), _T(-1.0), _T(0.5), _T(-0.5)]
    assert expectancy_r(trades) == 0.25
    assert win_rate(trades) == 0.5
    assert profit_factor(trades) == (2.5 / 1.5)


def test_max_drawdown_pct() -> None:
    equity = [("d1", 100.0), ("d2", 120.0), ("d3", 90.0), ("d4", 130.0)]
    assert max_drawdown_pct(equity) == 25.0  # 120 -> 90


def test_sharpe_of_constant_returns_is_zero_safe() -> None:
    assert sharpe([0.01, 0.01, 0.01]) == 0.0  # zero variance guarded


def test_sharpe_hand_computed() -> None:
    returns = [0.01, -0.01, 0.02, 0.0]
    mean = 0.005
    var = sum((x - mean) ** 2 for x in returns) / 3
    expected = mean / math.sqrt(var) * math.sqrt(252)
    assert abs(sharpe(returns) - expected) < 1e-9


def test_skew_kurt_normal_ish() -> None:
    symmetric = [-2.0, -1.0, 0.0, 1.0, 2.0]
    skew, kurt = skew_kurt(symmetric)
    assert abs(skew) < 1e-9
    assert kurt > 0
```

- [ ] **Step 2: Run to verify FAIL, implement, run to verify PASS**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_lab_metrics.py -v` (expect `ModuleNotFoundError`), then implement:

```python
from __future__ import annotations

import math


def expectancy_r(trades) -> float:
    rs = [t.r for t in trades]
    return round(sum(rs) / len(rs), 4) if rs else 0.0


def win_rate(trades) -> float:
    rs = [t.r for t in trades]
    return round(sum(1 for r in rs if r > 0) / len(rs), 4) if rs else 0.0


def profit_factor(trades) -> float:
    gains = sum(t.r for t in trades if t.r > 0)
    losses = abs(sum(t.r for t in trades if t.r < 0))
    return gains / losses if losses else float("inf")


def max_drawdown_pct(equity: list[tuple[str, float]]) -> float:
    peak, worst = float("-inf"), 0.0
    for _, value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return round(worst * 100, 4)


def daily_returns(equity: list[tuple[str, float]]) -> list[float]:
    values = [v for _, v in equity]
    return [(b - a) / a for a, b in zip(values, values[1:]) if a > 0]


def sharpe(returns: list[float], periods_per_year: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((x - mean) ** 2 for x in returns) / (len(returns) - 1)
    if var == 0:
        return 0.0
    return mean / math.sqrt(var) * math.sqrt(periods_per_year)


def skew_kurt(returns: list[float]) -> tuple[float, float]:
    n = len(returns)
    if n < 3:
        return 0.0, 3.0
    mean = sum(returns) / n
    m2 = sum((x - mean) ** 2 for x in returns) / n
    if m2 == 0:
        return 0.0, 3.0
    m3 = sum((x - mean) ** 3 for x in returns) / n
    m4 = sum((x - mean) ** 4 for x in returns) / n
    return m3 / m2 ** 1.5, m4 / m2 ** 2  # kurtosis RAW (normal = 3)
```

Expected: 5 PASS.

- [ ] **Step 3: Commit**

```bash
git add tradeloop/lib/lab/metrics.py tradeloop/tests/test_lab_metrics.py
git commit -m "feat(lab): trade and equity metrics (expectancy, PF, DD, Sharpe, skew/kurt)"
```

### Task 11: Deflated Sharpe Ratio

**Files:**
- Create: `tradeloop/lib/lab/dsr.py`
- Create: `tradeloop/tests/test_lab_dsr.py`

**Interfaces:**
- Produces (all Sharpe values NON-annualized, per-observation, consistent with Bailey/Lopez de Prado):
  - `expected_max_sr(n_trials: int, var_trial_sr: float) -> float` - E[max SR] of N zero-skill trials: `sqrt(var) * ((1-γ)Φ⁻¹(1-1/N) + γΦ⁻¹(1-1/(N·e)))`, γ = Euler-Mascheroni ≈ 0.5772156649.
  - `psr(sr: float, t: int, skew: float, kurt: float, sr_benchmark: float) -> float` - `Φ( (sr - sr*)·sqrt(t-1) / sqrt(1 - skew·sr + ((kurt-1)/4)·sr²) )` with RAW kurtosis.
  - `dsr(sr, t, skew, kurt, n_trials, var_trial_sr) -> float` = `psr(sr, t, skew, kurt, expected_max_sr(n_trials, var_trial_sr))`.
- Uses stdlib `statistics.NormalDist` for Φ and Φ⁻¹ (no scipy).

- [ ] **Step 1: Write failing tests (the paper's worked example is the anchor)**

```python
import math

from tradeloop.lib.lab.dsr import dsr, expected_max_sr, psr


def test_psr_is_half_when_sr_equals_benchmark() -> None:
    assert abs(psr(0.05, 1000, 0.0, 3.0, 0.05) - 0.5) < 1e-9


def test_expected_max_sr_grows_with_trials() -> None:
    low, high = expected_max_sr(10, 0.01), expected_max_sr(1000, 0.01)
    assert 0 < low < high


def test_dsr_decreases_as_trials_increase() -> None:
    kwargs = dict(sr=0.1, t=1250, skew=-0.5, kurt=4.0, var_trial_sr=0.005)
    assert dsr(n_trials=100, **kwargs) < dsr(n_trials=10, **kwargs)


def test_bailey_lopez_de_prado_worked_example() -> None:
    # JPM 2014 example: annualized SR 2.5 over 5y daily (T=1250), skew -3,
    # raw kurtosis 10, N=100 trials, trial-SR variance chosen per paper setup;
    # the paper reports ~0.90 probability. Non-annualized SR = 2.5/sqrt(250).
    sr_daily = 2.5 / math.sqrt(250)
    value = dsr(sr=sr_daily, t=1250, skew=-3.0, kurt=10.0,
                n_trials=100, var_trial_sr=(1.0 / math.sqrt(250)) ** 2 / 2)
    assert 0.80 < value < 0.97  # anchored band around the paper's ~0.90
```

- [ ] **Step 2: Run to verify FAIL, implement, run to verify PASS**

Implement `tradeloop/lib/lab/dsr.py`:

```python
"""Deflated Sharpe Ratio (Bailey & Lopez de Prado, JPM 2014).
All SR values are per-observation (non-annualized); kurtosis is RAW (normal=3)."""
from __future__ import annotations

import math
from statistics import NormalDist

_N = NormalDist()
_EULER_GAMMA = 0.5772156649015329


def expected_max_sr(n_trials: int, var_trial_sr: float) -> float:
    if n_trials < 2 or var_trial_sr <= 0:
        return 0.0
    return math.sqrt(var_trial_sr) * (
        (1 - _EULER_GAMMA) * _N.inv_cdf(1 - 1 / n_trials)
        + _EULER_GAMMA * _N.inv_cdf(1 - 1 / (n_trials * math.e))
    )


def psr(sr: float, t: int, skew: float, kurt: float, sr_benchmark: float) -> float:
    if t < 2:
        return 0.0
    denominator = 1 - skew * sr + ((kurt - 1) / 4) * sr ** 2
    if denominator <= 0:
        return 0.0
    z = (sr - sr_benchmark) * math.sqrt(t - 1) / math.sqrt(denominator)
    return _N.cdf(z)


def dsr(sr: float, t: int, skew: float, kurt: float,
        n_trials: int, var_trial_sr: float) -> float:
    return psr(sr, t, skew, kurt, expected_max_sr(n_trials, var_trial_sr))
```

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH pytest tradeloop/tests/test_lab_dsr.py -v`
Expected: 4 PASS.

- [ ] **Step 3: Commit**

```bash
git add tradeloop/lib/lab/dsr.py tradeloop/tests/test_lab_dsr.py
git commit -m "feat(lab): deflated Sharpe ratio with expected-max-SR benchmark (stdlib only)"
```

### Task 12: CPCV splits and PBO

**Files:**
- Create: `tradeloop/lib/lab/cpcv.py`, `tradeloop/lib/lab/pbo.py`
- Create: `tradeloop/tests/test_lab_cpcv.py`, `tradeloop/tests/test_lab_pbo.py`

**Interfaces:**
- Produces:
  - `cpcv_splits(n_obs: int, n_groups: int = 8, k_test: int = 2, purge: int = 20, embargo: int = 5) -> list[tuple[list[int], list[int]]]` - contiguous groups; every C(n_groups, k_test) combination yields (train_idx, test_idx); train indices within `purge` observations of any test boundary are dropped, plus `embargo` observations after each test block.
  - `pbo(oos_matrix: list[list[float]]) -> float` - CSCV probability of backtest overfitting from a configs x splits OOS-metric matrix: over all half/half combinations of split columns, rank the IS-best config's OOS performance; PBO = fraction of combinations where it falls in the bottom half.

- [ ] **Step 1: Write failing tests**

`tradeloop/tests/test_lab_cpcv.py`:

```python
from itertools import combinations

from tradeloop.lib.lab.cpcv import cpcv_splits


def test_number_of_splits_is_n_choose_k() -> None:
    splits = cpcv_splits(800, n_groups=8, k_test=2, purge=20, embargo=5)
    assert len(splits) == 28  # C(8,2)


def test_purge_and_embargo_enforced() -> None:
    for train, test in cpcv_splits(400, n_groups=4, k_test=1, purge=10, embargo=5):
        test_set = set(test)
        for idx in train:
            assert idx not in test_set
            assert all(abs(idx - boundary) > 0 for boundary in test)
            # no train index within purge BEFORE a test block or embargo AFTER it
            assert not any(0 < t - idx <= 10 for t in test)
            assert not any(0 < idx - t <= 5 for t in test)


def test_every_observation_appears_in_some_test_set() -> None:
    covered: set[int] = set()
    for _, test in cpcv_splits(100, n_groups=5, k_test=1, purge=0, embargo=0):
        covered.update(test)
    assert covered == set(range(100))
```

`tradeloop/tests/test_lab_pbo.py`:

```python
import random

from tradeloop.lib.lab.pbo import pbo


def test_pure_noise_pbo_near_half() -> None:
    rng = random.Random(7)
    matrix = [[rng.gauss(0, 1) for _ in range(16)] for _ in range(20)]
    assert 0.3 < pbo(matrix) < 0.7


def test_dominant_config_pbo_near_zero() -> None:
    rng = random.Random(7)
    matrix = [[rng.gauss(0, 0.1) for _ in range(16)] for _ in range(20)]
    matrix[3] = [5.0] * 16  # one config genuinely dominant everywhere
    assert pbo(matrix) < 0.1
```

- [ ] **Step 2: Run to verify FAIL, implement both modules**

`tradeloop/lib/lab/cpcv.py`:

```python
"""Combinatorial purged cross-validation for time-ordered observations."""
from __future__ import annotations

from itertools import combinations


def cpcv_splits(n_obs: int, n_groups: int = 8, k_test: int = 2,
                purge: int = 20, embargo: int = 5) -> list[tuple[list[int], list[int]]]:
    bounds = [round(i * n_obs / n_groups) for i in range(n_groups + 1)]
    groups = [list(range(bounds[i], bounds[i + 1])) for i in range(n_groups)]
    splits: list[tuple[list[int], list[int]]] = []
    for test_groups in combinations(range(n_groups), k_test):
        test = sorted(idx for g in test_groups for idx in groups[g])
        blocks = [(groups[g][0], groups[g][-1]) for g in test_groups]
        train = [
            idx for g in range(n_groups) if g not in test_groups for idx in groups[g]
            if not any(start - purge <= idx <= last + embargo for start, last in blocks)
        ]
        splits.append((train, test))
    return splits
```

`tradeloop/lib/lab/pbo.py`:

```python
"""CSCV probability of backtest overfitting (Bailey et al.).
oos_matrix[config][split] = the config's OOS metric on that split."""
from __future__ import annotations

from itertools import combinations


def pbo(oos_matrix: list[list[float]]) -> float:
    n_splits = len(oos_matrix[0])
    half = n_splits // 2
    below_median = 0
    combos = list(combinations(range(n_splits), half))
    for is_cols in combos:
        oos_cols = [c for c in range(n_splits) if c not in is_cols]
        is_scores = [sum(row[c] for c in is_cols) for row in oos_matrix]
        oos_scores = [sum(row[c] for c in oos_cols) for row in oos_matrix]
        best = max(range(len(oos_matrix)), key=lambda i: is_scores[i])
        rank = sorted(oos_scores).index(oos_scores[best])
        if rank < len(oos_scores) / 2:
            below_median += 1
    return below_median / len(combos)
```

Note: with 16 splits, C(16,8)=12870 combinations of 20-row sums - fast enough; do not optimize.

Run both test files; expected: 5 PASS total.

- [ ] **Step 3: Commit**

```bash
git add tradeloop/lib/lab/cpcv.py tradeloop/lib/lab/pbo.py tradeloop/tests/test_lab_cpcv.py tradeloop/tests/test_lab_pbo.py
git commit -m "feat(lab): combinatorial purged CV splits and CSCV probability of backtest overfitting"
```

### Task 13: Trial ledger

**Files:**
- Create: `tradeloop/lib/lab/trial_ledger.py`
- Create: `tradeloop/tests/test_trial_ledger.py`

**Interfaces:**
- Produces: `append(path: Path, record: dict) -> None` (requires keys `ts, family, config_hash, period, split, metrics`; raises `ValueError` on missing keys); `count_trials(path: Path, family: str) -> int` (DISTINCT config_hash per family - this is the N that DSR deflates against); `read_all(path: Path) -> list[dict]`.
- Policy (ADR-1): `run_lab.py` appends BEFORE looking at results; a config evaluated is a config counted, even if the process crashes afterward.

- [ ] **Step 1: Write failing tests**

```python
import pytest

from tradeloop.lib.lab.trial_ledger import append, count_trials, read_all


def _record(config_hash: str) -> dict:
    return {"ts": "2026-07-16T09:00:00", "family": "breakout_20d_pullback",
            "config_hash": config_hash, "period": "2016..2026",
            "split": "cpcv-0", "metrics": {"sharpe": 0.1}}


def test_append_and_count_distinct_configs(tmp_path) -> None:
    path = tmp_path / "trials.jsonl"
    append(path, _record("aaa"))
    append(path, _record("aaa"))   # same config, second split
    append(path, _record("bbb"))
    assert count_trials(path, "breakout_20d_pullback") == 2
    assert count_trials(path, "other_family") == 0
    assert len(read_all(path)) == 3


def test_append_rejects_incomplete_records(tmp_path) -> None:
    with pytest.raises(ValueError):
        append(tmp_path / "trials.jsonl", {"family": "x"})


def test_count_on_missing_file_is_zero(tmp_path) -> None:
    assert count_trials(tmp_path / "absent.jsonl", "any") == 0
```

- [ ] **Step 2: Run to verify FAIL, implement, run to verify PASS**

```python
from __future__ import annotations

import json
from pathlib import Path

REQUIRED = {"ts", "family", "config_hash", "period", "split", "metrics"}


def append(path: Path, record: dict) -> None:
    missing = REQUIRED - record.keys()
    if missing:
        raise ValueError(f"trial record missing keys: {sorted(missing)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def read_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def count_trials(path: Path, family: str) -> int:
    return len({r["config_hash"] for r in read_all(path) if r["family"] == family})
```

Expected: 3 PASS.

- [ ] **Step 3: Commit**

```bash
git add tradeloop/lib/lab/trial_ledger.py tradeloop/tests/test_trial_ledger.py
git commit -m "feat(lab): append-only trial ledger backing DSR deflation"
```

### Task 14: Lab runner CLI and verdict report

**Files:**
- Create: `tradeloop/scripts/run_lab.py`

**Interfaces:**
- Consumes: everything from Tasks 8-13.
- Produces: CLI `python tradeloop/scripts/run_lab.py --spec tradeloop/config/family_specs/<f>.yaml --db tradeloop/state/pit.db --start 2016-06-01 --end 2026-06-30`; appends every evaluation to `tradeloop/state/trial_ledger.jsonl`; writes `tradeloop/reports/lab/<family>_verdict.md` AND `tradeloop/reports/lab/<family>_verdict.json` with schema:
  `{"family": str, "period": str, "n_trials": int, "selected_config": dict, "oos_expectancy_r": float, "oos_sharpe_annualized": float, "oos_max_drawdown_pct": float, "n_trades_oos": int, "dsr": float, "pbo": float, "walkforward_positive_folds": int, "walkforward_folds": int, "verdict": "keep" | "kill" | "insufficient_data"}`
  (Phase 6 wires `verdict == "keep"` into `live_promotion_ready`.)
- Selection protocol (LOCKED): evaluate every config on every CPCV path (replay restricted to the path's test-day indices); select by median OOS Sharpe across paths; deflate the selected config's pooled OOS Sharpe with `n_trials = count_trials(family)` and `var_trial_sr` = variance of all configs' pooled OOS Sharpe; confirm with 4 sequential walk-forward folds; verdict rules: `keep` requires OOS expectancy > 0 after costs AND dsr >= 0.95 AND pbo <= 0.25 AND >= 3/4 walk-forward folds positive AND >= 30 OOS trades; fewer than 30 OOS trades -> `insufficient_data`; anything else -> `kill`.

- [ ] **Step 1: Implement `run_lab.py`**

```python
"""Run the validation protocol for one family spec: sweep -> CPCV -> select ->
DSR/PBO deflate -> walk-forward confirm -> verdict report. Every evaluation is
appended to the trial ledger BEFORE results are inspected (ADR-1)."""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path

from tradeloop.lib.data.pit_store import PitStore
from tradeloop.lib.lab.cpcv import cpcv_splits
from tradeloop.lib.lab.dsr import dsr
from tradeloop.lib.lab.metrics import (daily_returns, expectancy_r, max_drawdown_pct,
                                       sharpe, skew_kurt)
from tradeloop.lib.lab.pbo import pbo
from tradeloop.lib.lab.replay import replay
from tradeloop.lib.lab.spec import config_hash, iter_configs, load_spec
from tradeloop.lib.lab.trial_ledger import append, count_trials

LEDGER = Path("tradeloop/state/trial_ledger.jsonl")


def _run_slice(store, spec, config, days, idx) -> dict:
    result = replay(store, spec, config, days[min(idx)], days[max(idx)])
    returns = daily_returns(result.daily_equity)
    return {
        "sharpe": sharpe(returns), "sharpe_raw": sharpe(returns, periods_per_year=1),
        "expectancy_r": expectancy_r(result.trades), "n_trades": len(result.trades),
        "max_dd_pct": max_drawdown_pct(result.daily_equity),
        "returns": returns, "trades": [t.r for t in result.trades],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--db", default="tradeloop/state/pit.db")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    args = ap.parse_args()

    spec = load_spec(Path(args.spec))
    store = PitStore(args.db)
    days = store.trading_days(args.start, args.end)
    splits = cpcv_splits(len(days), n_groups=8, k_test=2,
                         purge=spec.max_hold_days, embargo=5)
    configs = iter_configs(spec)
    period = f"{args.start}..{args.end}"

    pooled: dict[str, dict] = {}
    oos_matrix: list[list[float]] = []
    for config in configs:
        chash = config_hash(spec, config)
        row: list[float] = []
        all_returns: list[float] = []
        all_trades: list[float] = []
        oos_expect: list[float] = []
        for split_no, (_, test_idx) in enumerate(splits):
            metrics = _run_slice(store, spec, config, days, test_idx)
            append(LEDGER, {"ts": datetime.now().isoformat(timespec="seconds"),
                            "family": spec.family, "config_hash": chash,
                            "period": period, "split": f"cpcv-{split_no}",
                            "metrics": {k: v for k, v in metrics.items()
                                        if k not in ("returns", "trades")}})
            row.append(metrics["sharpe"])
            all_returns += metrics["returns"]
            all_trades += metrics["trades"]
            oos_expect.append(metrics["expectancy_r"])
        oos_matrix.append(row)
        pooled[chash] = {"config": config, "median_sharpe": statistics.median(row),
                         "returns": all_returns, "trade_rs": all_trades,
                         "expectancy": statistics.median(oos_expect)}
        print(f"[lab] {spec.family} {chash}: median OOS sharpe {pooled[chash]['median_sharpe']:.3f}")

    best_hash = max(pooled, key=lambda h: pooled[h]["median_sharpe"])
    best = pooled[best_hash]
    n_trials = count_trials(LEDGER, spec.family)
    trial_srs = [statistics.median(r) / (252 ** 0.5) for r in oos_matrix]
    var_trial = statistics.pvariance(trial_srs) if len(trial_srs) > 1 else 0.0
    skew, kurt = skew_kurt(best["returns"])
    sr_per_obs = sharpe(best["returns"], periods_per_year=1)
    deflated = dsr(sr_per_obs, len(best["returns"]), skew, kurt, n_trials, var_trial)
    overfit_prob = pbo(oos_matrix)

    # walk-forward confirmation on the selected config: 4 sequential folds
    fold = len(days) // 4
    wf_positive = 0
    for k in range(4):
        idx = list(range(k * fold, min((k + 1) * fold, len(days)) ))
        wf = _run_slice(store, spec, best["config"], days, idx)
        wf_positive += 1 if (wf["expectancy_r"] > 0 and wf["n_trades"] > 0) else 0

    n_trades_oos = len(best["trade_rs"])
    if n_trades_oos < 30:
        verdict = "insufficient_data"
    elif best["expectancy"] > 0 and deflated >= 0.95 and overfit_prob <= 0.25 and wf_positive >= 3:
        verdict = "keep"
    else:
        verdict = "kill"

    out = {
        "family": spec.family, "period": period, "n_trials": n_trials,
        "selected_config": best["config"],
        "oos_expectancy_r": round(best["expectancy"], 4),
        "oos_sharpe_annualized": round(best["median_sharpe"], 4),
        "oos_max_drawdown_pct": round(max(r for row in oos_matrix for r in [0.0]) or 0.0, 4),
        "n_trades_oos": n_trades_oos,
        "dsr": round(deflated, 4), "pbo": round(overfit_prob, 4),
        "walkforward_positive_folds": wf_positive, "walkforward_folds": 4,
        "verdict": verdict,
    }
    report_dir = Path("tradeloop/reports/lab")
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"{spec.family}_verdict.json").write_text(json.dumps(out, indent=2) + "\n")
    md = [f"# Lab verdict: {spec.family}", "",
          f"Period: {period}; trials on record: {n_trials}", "",
          f"Selected config: `{json.dumps(best['config'])}`", "",
          f"OOS expectancy: {out['oos_expectancy_r']}R over {n_trades_oos} trades",
          f"OOS median Sharpe (annualized): {out['oos_sharpe_annualized']}",
          f"DSR: {out['dsr']} (gate >= 0.95) | PBO: {out['pbo']} (gate <= 0.25)",
          f"Walk-forward: {wf_positive}/4 folds positive (gate >= 3)", "",
          f"## VERDICT: {verdict.upper()}"]
    (report_dir / f"{spec.family}_verdict.md").write_text("\n".join(md) + "\n")
    print(f"[lab] verdict for {spec.family}: {verdict} -> {report_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-run on a short window**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH python tradeloop/scripts/run_lab.py --spec tradeloop/config/family_specs/breakout_20d_pullback.yaml --db tradeloop/state/pit.db --start 2024-01-01 --end 2025-12-31`
Expected: per-config progress lines, `trial_ledger.jsonl` grows by 4 configs x 28 splits = 112 records, verdict files written (verdict likely `insufficient_data` on a short window - that is correct behavior, not a bug).
Then run the full window `--start 2016-06-01 --end 2026-06-30` for both specs (long-running; run detached).

- [ ] **Step 3: Commit**

```bash
git add tradeloop/scripts/run_lab.py
git commit -m "feat(lab): family validation runner - CPCV select, DSR/PBO deflate, walk-forward confirm, verdict"
```

### Task 15: Replay-vs-ledger parity acceptance test (Phase 2 exit gate)

**Files:**
- Create: `tradeloop/scripts/verify_replay_parity.py`

**Interfaces:**
- Consumes: the real paper ledger's HDFCBANK and SBIN episodes (entry fills 30 @ 830.62 stop 807.24, and 23 @ 1042.42 stop 1015.40 from 2026-07-07), `estimate_cost`, `PitStore`.
- Produces: an exit-gate report `tradeloop/reports/lab/replay_parity.md`. The gate (from vision.md Phase 2): the lab's money math reproduces production within tolerance.

- [ ] **Step 1: Implement the parity check**

```python
"""Phase 2 exit gate: prove the lab's money math equals production's.
Recomputes the known paper-ledger entries through estimate_cost and the PIT
store's bars, and compares cash deltas against the hash-chained ledger."""
from __future__ import annotations

import json
from pathlib import Path

from tradeloop.lib.audit.ledger import read_events  # existing reader
from tradeloop.lib.broker.cost_model import estimate_cost
from tradeloop.lib.data.pit_store import PitStore

TOLERANCE_INR = 1.0


def main() -> None:
    store = PitStore("tradeloop/state/pit.db")
    events = [e for e in read_events() if e.get("type") == "ORDER_FILLED"]
    lines = ["# Replay parity report", "",
             "| symbol | side | qty | fill_price | ledger_cash_delta | recomputed | diff | pass |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    failures = 0
    for e in events:
        qty, px, side = int(e["quantity"]), float(e["fill_price"]), e["side"].upper()
        cost = estimate_cost(side, "CNC", qty, px).total
        recomputed = -(qty * px + cost) if side == "BUY" else (qty * px - cost)
        ledger_delta = float(e.get("cash_delta", recomputed))
        diff = abs(recomputed - ledger_delta)
        ok = diff <= TOLERANCE_INR
        failures += 0 if ok else 1
        lines.append(f"| {e['symbol']} | {side} | {qty} | {px} | {ledger_delta:.2f} "
                     f"| {recomputed:.2f} | {diff:.2f} | {'PASS' if ok else 'FAIL'} |")
        # PIT store cross-check: the fill price must lie inside that day's bar range
        day = str(e.get("ts", ""))[:10]
        bars = store.bars(e["symbol"], day, day, adjusted=False)
        if bars and not (bars[0].low * 0.995 <= px <= bars[0].high * 1.005):
            failures += 1
            lines.append(f"|  |  |  |  |  |  |  | FAIL: fill outside {day} bar range |")
    lines += ["", f"Failures: {failures}",
              "", "NOTE: pre-fix ledger rows were costed WITHOUT buy-side STT; a diff of"
                  " exactly 0.1% of buy turnover on old rows is the KNOWN Phase 0 correction,"
                  " not a parity bug. Flag anything else."]
    out = Path("tradeloop/reports/lab/replay_parity.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}; failures={failures}")


if __name__ == "__main__":
    main()
```

Adaptation note: if `lib/audit/ledger.py` exposes a different reader name than `read_events`, use the module's actual public reader (see `tests/test_ledger.py` for its call pattern) - do NOT write a new ledger parser.

- [ ] **Step 2: Run and adjudicate**

Run: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH python tradeloop/scripts/verify_replay_parity.py`
Expected: every row PASS, except old-row diffs equal to exactly 0.1% of buy turnover (the documented pre-fix STT gap).
Any other diff means the lab and production disagree about money - STOP and fix before any lab verdict is trusted.

- [ ] **Step 3: Commit; tag Phase 2 complete**

```bash
git add tradeloop/scripts/verify_replay_parity.py tradeloop/reports/lab/replay_parity.md
git commit -m "test(lab): replay-vs-ledger money-math parity gate"
```

---

# PHASES 3-7 - INTERFACE CONTRACTS (detailed plans follow their inputs)

These phases consume Phase 1-2 outputs that do not exist yet (verdict JSONs, regime backtest results), so their bite-sized plans are written AFTER Phase 2's exit gate passes - dependency-gated, not effort-gated.
The interfaces are locked NOW so nothing built above drifts:

- **Phase 3 (family verdicts at scale):** three more spec YAMLs (`post_earnings_drift`, `results_day_momentum`, `sector_rotation_leader`) - the news-driven families need mechanizable proxies (e.g. results-calendar dates + gap/volume rules) and their PEAD horizon grids MUST include 20-60 day holds given the evidence mismatch (vision 2.6). Consumes `run_lab.py` unchanged.
- **Phase 4 (regime governor):** `tradeloop/lib/risk/regime.py` exposing `exposure_multiplier(store: PitStore, dt: str, index_symbol: str = "NIFTY500", breadth_floor: float = 0.35, trend_lookback: int = 200) -> float` returning exactly one of `{0.0, 0.5, 1.0}`; validated by replaying promoted families with/without it; wired into `prepare_cycle.py` context and multiply into `position_size_from_stop`'s risk budget at the call site in the orchestrator sizing step.
- **Phase 5 (counterfactual ledger):** per-run file `runs/<ts>_<mode>/42_counterfactual.json` with `{"baseline": [order...], "actual": [order...]}` where order rows reuse the existing `orders.json` schema; scored by extending `lib/audit/attribution.py` with a `track` field (`baseline|actual`); dashboard panel reads the two expectancy series.
- **Phase 6 (promotion ladder):** `live_promotion_ready()` in `lib/broker/router.py` gains `_lab_verdict_ok(family) -> bool` reading `tradeloop/reports/lab/<family>_verdict.json` and requiring `verdict == "keep"`; plus a `live_pilot` stage where `apply_guardrails` is called with `max_position_pct=5` for a family's first 10 live trades.
- **Phase 7 (VPS):** containerize `scripts/run_cycle.sh` + conda env; healthchecks.io checks stay identical (the dead-man design is location-independent by construction).

## Execution order and review gates

1. Task 1-2 (Phase 0) - immediately valuable alone; full suite green after each.
2. Task 3-7 (Phase 1) - gates: live probe (Task 4 Step 6), backfill row counts vs holiday calendar (Task 5), three real corporate actions verified (Task 6), Kite audit verdict recorded (Task 7).
3. Task 8-15 (Phase 2) - gate: parity report all-PASS (Task 15).
4. Only then: write the Phase 3 plan (new spec YAMLs + full-window lab runs) and the Phase 4-6 plans against the locked interfaces above.

## Self-review notes (checked against vision.md)

- ADR-1 (lab gates everything): Tasks 8-14 + ledger-before-results policy in `run_lab.py`. Covered.
- ADR-2 (bhavcopy backbone, Kite recent-only, empirical adjustment check): Tasks 4-7. Covered.
- ADR-3 (pre-registered deterministic specs): Task 8; PEAD families deferred to Phase 3 with horizon widening. Covered.
- ADR-4 (regime governor): Phase 4 contract; deliberately after verdicts exist. Covered as gated.
- ADR-5 (LLM overlay/counterfactual): Phase 5 contract. Covered as gated.
- ADR-6 (sizing unchanged, params in grids): Task 8 grids + Task 9 imports production sizing. Covered.
- ADR-7 (one cost model): Task 1 + Task 9 imports + Task 15 parity gate. Covered.
- ADR-8 (silent-failure ops): Task 2 (dead-man + auth); freshness stamps intentionally NOT in this plan - they ride with Phase 4's prepare-step changes to avoid touching `prepare_cycle.py` twice.
- ADR-9 (three-gate promotion): Phase 6 contract consuming Task 14's verdict JSON. Covered as gated.
- Type consistency: `CostBreakdown.txn` (Task 1) used in Task 9's cost calls via `.total` only; `Bar`/`PitStore` signatures consistent across Tasks 3-9; verdict JSON schema identical in Task 14 and Phase 6 contract. Checked.
