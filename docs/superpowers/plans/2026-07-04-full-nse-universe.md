# Full-NSE Scan Universe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the daily chart scan cover the full NSE cash-equity universe (~1,800 stocks) - pulled live from Zerodha, liquidity-filtered, rate-paced - so the trader has real candles for the names the research surfaces, while keeping daily AI cost bounded via a top-N cap.

**Architecture:** One new MCP tool downloads the whole NSE instrument list once; a Python bulk loader turns it into a `{symbol: token}` map; a cache-backed `universe` module supplies the symbol list (weekly refresh, yaml fallback); the scanner gains a liquidity floor (computed from candles it already fetches) and rate-pacing; ingest sources symbols from the loader, lifts the 30-symbol cap, saves the full ranked scan to disk, and feeds only the cleanest N setups downstream.

**Tech Stack:** Python 3.11 stdlib + existing deps (pandas, yaml, httpx already present); TypeScript MCP server (`src/mcp/zerodha.ts`, run via `tsx`). No new dependencies. Test interpreter: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest`.

## Global Constraints

- No new Python/JS dependencies.
- Cash equity only (`EQ`); no F&O/intraday instruments.
- Scan degrades, never crashes: Kite down -> yaml fallback; per-symbol error -> skip and continue; empty scan -> loud "no setups" (existing behavior).
- Liquidity floor and top-N cap are config values in `settings.yaml`'s existing `universe:` block, changeable without code edits.
- Order path (evaluate() gate, grounding gate, ledger) is UNCHANGED - this plan only widens the input scan.
- Run tests under `-W error` where practical.

---

### Task 1: `zerodha_instruments` MCP tool (bulk NSE instrument list)

**Files:**
- Modify: `src/mcp/zerodha.ts` (add one tool after `zerodha_instrument_token`, ~line 274)

**Interfaces:**
- Produces: MCP tool `zerodha_instruments({exchange, instrument_type?})` -> `{instruments: [{tradingsymbol, instrument_token}]}`. Downloads `/instruments/<exchange>` once, filters to `instrument_type` (default `EQ`).

- [ ] **Step 1: Add the tool**

```typescript
server.registerTool(
  "zerodha_instruments",
  {
    title: "List instruments",
    description: "List all instruments for an exchange, filtered by instrument_type (default EQ). Returns [{tradingsymbol, instrument_token}].",
    inputSchema: {
      exchange: z.string().min(1),
      instrument_type: z.string().default("EQ")
    }
  },
  async ({ exchange, instrument_type }) => {
    const { apiKey, accessToken } = requireCredentials();
    const resp = await fetch(buildUrl(`/instruments/${encodeURIComponent(exchange)}`), {
      headers: new Headers({ Authorization: `token ${apiKey}:${accessToken}`, "X-Kite-Version": "3" })
    });
    const csv = await resp.text();
    const rows = csv.split("\n").filter((r) => r.trim().length > 0);
    const header = rows[0].split(",");
    const tokIdx = header.indexOf("instrument_token");
    const symIdx = header.indexOf("tradingsymbol");
    const typeIdx = header.indexOf("instrument_type");
    const out: { tradingsymbol: string; instrument_token: number }[] = [];
    for (const row of rows.slice(1)) {
      const cols = row.split(",");
      if (typeIdx >= 0 && cols[typeIdx] !== instrument_type) continue;
      const token = Number(cols[tokIdx]);
      if (!Number.isFinite(token)) continue;
      out.push({ tradingsymbol: cols[symIdx], instrument_token: token });
    }
    return textJson({ instruments: out });
  }
);
```

- [ ] **Step 2: Live-verify the tool** (TS is outside pytest; verify against real Kite)

Requires a fresh daily token (`npm run auth:zerodha`). Run:

```bash
/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -c "
from tradeloop.lib.data.kite import KiteClient
k = KiteClient()
raw = k.transport.call_tool('zerodha_instruments', {'exchange': 'NSE', 'instrument_type': 'EQ'})
insts = raw['instruments']
print('NSE EQ instruments:', len(insts))
print('sample:', insts[0])
assert len(insts) > 1000, 'expected ~1800 NSE equities'
assert 'RELIANCE' in {i['tradingsymbol'] for i in insts}
print('OK')
"
```
Expected: `NSE EQ instruments: ~1800`, sample has `tradingsymbol` + `instrument_token`, `OK`. If the token is stale it will raise - re-auth and retry.

- [ ] **Step 3: Commit**

```bash
git add src/mcp/zerodha.ts
git commit -m "mcp(zerodha): bulk zerodha_instruments tool (whole exchange in one call)"
```

---

### Task 2: `KiteClient.instruments()` bulk loader

**Files:**
- Modify: `tradeloop/lib/data/kite.py` (add method to `KiteClient`)
- Test: `tradeloop/tests/data/test_kite_instruments.py`

**Interfaces:**
- Consumes: the `zerodha_instruments` tool (Task 1).
- Produces: `KiteClient.instruments(exchange="NSE", instrument_type="EQ") -> dict[str, int]` (`{SYMBOL: token}`), and seeds `self._token_cache` so later `historical()` needs no per-symbol lookup.

- [ ] **Step 1: Write the failing test**

```python
# tradeloop/tests/data/test_kite_instruments.py
from tradeloop.lib.data.kite import KiteClient


class FakeTransport:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"instruments": [
            {"tradingsymbol": "RELIANCE", "instrument_token": 738561},
            {"tradingsymbol": "sbin", "instrument_token": 779521},
        ]}


def test_instruments_returns_symbol_token_map_and_seeds_cache():
    t = FakeTransport()
    k = KiteClient(transport=t)
    m = k.instruments("NSE")
    assert m == {"RELIANCE": 738561, "SBIN": 779521}  # upper-cased
    # cache seeded: resolving a token needs no second tool call
    assert k._token("RELIANCE") == 738561
    assert [c[0] for c in t.calls] == ["zerodha_instruments"]  # only the one bulk call
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/data/test_kite_instruments.py -q`
Expected: FAIL - `AttributeError: 'KiteClient' object has no attribute 'instruments'`

- [ ] **Step 3: Write minimal implementation**

Add to `KiteClient` in `tradeloop/lib/data/kite.py`:

```python
    def instruments(self, exchange: str = "NSE", instrument_type: str = "EQ") -> dict:
        raw = self.transport.call_tool(
            "zerodha_instruments", {"exchange": exchange, "instrument_type": instrument_type}
        )
        out: dict = {}
        for row in raw.get("instruments", []):
            sym = str(row["tradingsymbol"]).strip().upper()
            token = int(row["instrument_token"])
            out[sym] = token
            self._token_cache[sym] = token  # seed so historical() needs no lookup
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/data/test_kite_instruments.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add tradeloop/lib/data/kite.py tradeloop/tests/data/test_kite_instruments.py
git commit -m "kite: bulk instruments() loader seeds token cache"
```

---

### Task 3: `universe.py` - cache-backed symbol list with yaml fallback

**Files:**
- Create: `tradeloop/lib/data/universe.py`
- Test: `tradeloop/tests/data/test_universe.py`

**Interfaces:**
- Consumes: `KiteClient.instruments` (Task 2), `load_master` (`tradeloop/lib/data/ticker_master.py`).
- Produces: `load_universe(kite_client, cache_path, yaml_path, max_age_days=7, max_symbols=2500, now=None) -> list[str]`.
  - Fresh cache (`< max_age_days` old, by the `fetched` date string inside it): read symbols from cache.
  - Else if `kite_client` given: fetch, write cache `{ "fetched": "<YYYY-MM-DD>", "symbols": [...] }`, return symbols.
  - Kite unavailable/errors OR no kite_client: fall back to `load_master(yaml_path).symbols()`.
  - Always truncated to `max_symbols`. `now` (a `date`) is injectable for testing freshness.

- [ ] **Step 1: Write the failing test**

```python
# tradeloop/tests/data/test_universe.py
import json
from datetime import date
from pathlib import Path

from tradeloop.lib.data.universe import load_universe


class FakeKite:
    def __init__(self, symbols):
        self._symbols = symbols
        self.called = 0

    def instruments(self, exchange="NSE", instrument_type="EQ"):
        self.called += 1
        return {s: i for i, s in enumerate(self._symbols, start=1)}


def _yaml(tmp_path):
    p = tmp_path / "universe.yaml"
    p.write_text("symbols:\n  - symbol: RELIANCE\n  - symbol: TCS\nwatchlist: []\n")
    return p


def test_fetches_and_writes_cache_when_missing(tmp_path):
    cache = tmp_path / "universe_cache.json"
    kite = FakeKite(["RELIANCE", "SBIN", "INFY"])
    syms = load_universe(kite, cache, _yaml(tmp_path), now=date(2026, 7, 6))
    assert set(syms) == {"RELIANCE", "SBIN", "INFY"}
    assert kite.called == 1
    assert json.loads(cache.read_text())["fetched"] == "2026-07-06"


def test_reads_fresh_cache_without_calling_kite(tmp_path):
    cache = tmp_path / "universe_cache.json"
    cache.write_text(json.dumps({"fetched": "2026-07-05", "symbols": ["AAA", "BBB"]}))
    kite = FakeKite(["RELIANCE"])
    syms = load_universe(kite, cache, _yaml(tmp_path), now=date(2026, 7, 6))
    assert syms == ["AAA", "BBB"]
    assert kite.called == 0  # cache fresh (1 day old)


def test_stale_cache_triggers_refetch(tmp_path):
    cache = tmp_path / "universe_cache.json"
    cache.write_text(json.dumps({"fetched": "2026-06-01", "symbols": ["OLD"]}))
    kite = FakeKite(["RELIANCE", "SBIN"])
    syms = load_universe(kite, cache, _yaml(tmp_path), max_age_days=7, now=date(2026, 7, 6))
    assert set(syms) == {"RELIANCE", "SBIN"}
    assert kite.called == 1


def test_falls_back_to_yaml_when_kite_errors(tmp_path):
    cache = tmp_path / "universe_cache.json"

    class Broken:
        def instruments(self, *a, **k):
            raise RuntimeError("kite down")

    syms = load_universe(Broken(), cache, _yaml(tmp_path), now=date(2026, 7, 6))
    assert set(syms) == {"RELIANCE", "TCS"}  # from yaml


def test_no_kite_uses_yaml(tmp_path):
    cache = tmp_path / "universe_cache.json"
    syms = load_universe(None, cache, _yaml(tmp_path), now=date(2026, 7, 6))
    assert set(syms) == {"RELIANCE", "TCS"}


def test_truncates_to_max_symbols(tmp_path):
    cache = tmp_path / "universe_cache.json"
    kite = FakeKite([f"S{i}" for i in range(100)])
    syms = load_universe(kite, cache, _yaml(tmp_path), max_symbols=10, now=date(2026, 7, 6))
    assert len(syms) == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/data/test_universe.py -q`
Expected: FAIL - `ModuleNotFoundError: No module named 'tradeloop.lib.data.universe'`

- [ ] **Step 3: Write minimal implementation**

```python
# tradeloop/lib/data/universe.py
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from tradeloop.lib.data.ticker_master import load_master

log = logging.getLogger("tradeloop.universe")


def _cache_symbols(cache_path: Path, max_age_days: int, today: date) -> "list[str] | None":
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        fetched = date.fromisoformat(str(data["fetched"]))
        if (today - fetched).days < max_age_days:
            return [str(s).strip().upper() for s in data.get("symbols", [])]
    except (ValueError, KeyError, OSError):
        return None  # corrupt/unreadable -> treat as stale
    return None


def _yaml_symbols(yaml_path: Path) -> "list[str]":
    try:
        return [s.strip().upper() for s in load_master(yaml_path).symbols()]
    except (OSError, ValueError):
        return []


def load_universe(kite_client, cache_path: Path, yaml_path: Path,
                  max_age_days: int = 7, max_symbols: int = 2500,
                  now: "date | None" = None) -> "list[str]":
    cache_path = Path(cache_path)
    today = now or date.today()

    cached = _cache_symbols(cache_path, max_age_days, today)
    if cached:
        return cached[:max_symbols]

    if kite_client is not None:
        try:
            symbols = sorted(kite_client.instruments("NSE", "EQ").keys())
            if symbols:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps({"fetched": today.isoformat(), "symbols": symbols}),
                    encoding="utf-8")
                return symbols[:max_symbols]
        except Exception as exc:  # kite/token/transport failure -> degrade to yaml
            log.warning("universe fetch failed, falling back to yaml: %s", exc)

    return _yaml_symbols(yaml_path)[:max_symbols]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/data/test_universe.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add tradeloop/lib/data/universe.py tradeloop/tests/data/test_universe.py
git commit -m "universe: cache-backed NSE symbol list with weekly refresh + yaml fallback"
```

---

### Task 4: Scanner liquidity floor + rate pacing

**Files:**
- Modify: `tradeloop/lib/ta/scanner.py` (`scan_symbol`, `scan_universe`)
- Test: `tradeloop/tests/ta/test_scanner_liquidity.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `scan_symbol(symbol, kite_client, as_of, min_turnover_inr=0.0)` - returns `None` when average daily turnover (`mean(close*volume)`) is below `min_turnover_inr`.
  - `scan_universe(symbols, kite_client, as_of, max_fetch=2500, min_turnover_inr=0.0, pace_seconds=0.0, sleep=time.sleep)` - sleeps `pace_seconds` before each symbol (rate limit), tolerant per symbol, returns setups sorted by cleanliness desc (unchanged).

- [ ] **Step 1: Write the failing test**

```python
# tradeloop/tests/ta/test_scanner_liquidity.py
from datetime import date

from tradeloop.lib.ta.scanner import scan_symbol, scan_universe
from tradeloop.lib.data.kite import Candle


def _candles(close, volume, n=60):
    # a clean rising series so a setup would normally register
    out = []
    for i in range(n):
        c = close + i * 0.5
        out.append(Candle(date=f"2026-01-{(i % 28) + 1:02d}", open=c, high=c + 1,
                          low=c - 1, close=c, volume=volume))
    return out


class FakeKite:
    def __init__(self, by_symbol):
        self.by_symbol = by_symbol
        self.seen = []

    def historical(self, symbol, frm, to, interval):
        self.seen.append(symbol)
        return self.by_symbol.get(symbol, [])


def test_liquidity_floor_drops_thin_symbol():
    # turnover = close(~50) * volume(100) ~= 5,000 << 1,000,000 floor -> dropped
    kite = FakeKite({"THIN": _candles(50.0, 100)})
    assert scan_symbol("THIN", kite, date(2026, 2, 2), min_turnover_inr=1_000_000) is None


def test_liquidity_floor_keeps_liquid_symbol():
    # turnover = close(~50) * volume(1,000,000) ~= 50M >> floor -> setup allowed
    kite = FakeKite({"LIQ": _candles(50.0, 1_000_000)})
    scan = scan_symbol("LIQ", kite, date(2026, 2, 2), min_turnover_inr=1_000_000)
    assert scan is not None and scan.ticker == "LIQ"


def test_scan_universe_paces_each_symbol():
    kite = FakeKite({"A": _candles(50.0, 1_000_000), "B": _candles(50.0, 1_000_000)})
    naps = []
    scan_universe(["A", "B"], kite, date(2026, 2, 2),
                  pace_seconds=0.34, sleep=lambda s: naps.append(s))
    assert naps == [0.34, 0.34]  # one nap per symbol
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/ta/test_scanner_liquidity.py -q`
Expected: FAIL - `TypeError: scan_symbol() got an unexpected keyword argument 'min_turnover_inr'`

- [ ] **Step 3: Write minimal implementation**

In `tradeloop/lib/ta/scanner.py`, add `import time` at the top with the other imports. Change `scan_symbol`'s signature and add the turnover guard right after the ATR guard:

```python
def scan_symbol(symbol: str, kite_client, as_of: date, min_turnover_inr: float = 0.0) -> "SetupScan | None":
    frm = as_of - timedelta(days=200)
    candles = kite_client.historical(symbol, frm, as_of, "day")
    if len(candles) < 30:
        return None
    enriched = add_indicators(candles_to_frame(candles))
    closes = [float(v) for v in enriched["Close"].tolist()]
    volumes = [float(v) for v in enriched["Volume"].tolist()] if "Volume" in enriched.columns else []
    ema20 = enriched["EMA20"].tolist()
    atr_series = enriched["ATR14"].dropna() if "ATR14" in enriched.columns else pd.Series(dtype=float)
    if atr_series.empty:
        return None  # no fabricated stop - a setup without a real ATR is not tradeable
    # liquidity floor: mean daily traded value must clear the configured threshold
    if min_turnover_inr > 0 and volumes:
        turnover = sum(c * v for c, v in zip(closes, volumes)) / len(closes)
        if turnover < min_turnover_inr:
            return None
    atr_value = float(atr_series.iloc[-1])
    latest = closes[-1]
    ...  # rest unchanged
```

Change `scan_universe`:

```python
def scan_universe(symbols: Iterable[str], kite_client, as_of: date, max_fetch: int = 2500,
                  min_turnover_inr: float = 0.0, pace_seconds: float = 0.0,
                  sleep=time.sleep) -> List["SetupScan"]:
    scans: List[SetupScan] = []
    for symbol in list(symbols)[:max_fetch]:
        if pace_seconds > 0:
            sleep(pace_seconds)  # respect Kite ~3 req/s
        try:
            scan = scan_symbol(symbol, kite_client, as_of, min_turnover_inr=min_turnover_inr)
        except _TOLERATED as exc:
            log.warning("scan skipped %s: %s", symbol, exc)
            continue
        if scan is not None:
            scans.append(scan)
    scans.sort(key=lambda item: item.cleanliness_score, reverse=True)
    return scans
```

Note: `max_fetch` default rises from 30 to 2500 (the full-universe ceiling). Existing callers passing `max_fetch=30` keep working.

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/ta/test_scanner_liquidity.py tradeloop/tests/ta -q`
Expected: PASS (new tests + existing scanner tests unaffected)

- [ ] **Step 5: Commit**

```bash
git add tradeloop/lib/ta/scanner.py tradeloop/tests/ta/test_scanner_liquidity.py
git commit -m "scanner: liquidity floor + rate pacing for full-universe scans"
```

---

### Task 5: Ingest wiring - universe loader, lifted cap, top-N downstream, full-scan dump

**Files:**
- Modify: `tradeloop/lib/data/ingest.py`
- Modify: `tradeloop/config/settings.yaml` (extend the existing `universe:` block)
- Test: `tradeloop/tests/data/test_ingest_universe.py`

**Interfaces:**
- Consumes: `load_universe` (Task 3), `scan_universe` (Task 4).
- Produces: `ingest.run` sources symbols from `load_universe` when `symbols is None` and a `kite_client` is present; scans with the liquidity floor + pacing from config; writes the FULL ranked scan to `run_dir/full_scan.jsonl`; passes only the top `max_setups_downstream` setups to `render_setups` + `freeze`. Reads knobs from `settings.yaml`'s `universe:` block; safe defaults when absent.

- [ ] **Step 1: Add config knobs**

In `tradeloop/config/settings.yaml`, extend the existing `universe:` block (keep the existing keys) to:

```yaml
universe:
  base_index: NIFTY500
  source: full_nse            # full_nse (pull from Kite) | config_yaml (the hand-listed symbols)
  cache_days: 7
  min_avg_daily_turnover_cr: 5   # liquidity floor in Rs crore (5cr = 50,000,000 INR); 0 disables
  exclude_segments: [SME, ETF_LEVERAGED]
  pace_seconds: 0.34          # ~3 req/s to respect Kite rate limits
  max_symbols: 2500           # hard ceiling on symbols scanned
  max_setups_downstream: 25   # cleanest-N setups fed to the AI stages
  include_indices_as_context: [NIFTY50, BANKNIFTY, NIFTYIT, NIFTYAUTO, NIFTYPHARMA, NIFTYFMCG]
```

- [ ] **Step 2: Write the failing test**

```python
# tradeloop/tests/data/test_ingest_universe.py
import json
from datetime import date, datetime
from pathlib import Path

from tradeloop.lib.data import ingest
from tradeloop.lib.ta.scanner import SetupScan


def _setup(ticker, score):
    return SetupScan(ticker=ticker, setup_type="20d_breakout", cleanliness_score=score,
                     entry_zone="100.0", stop_zone="95.0", target_zone="110.0/115.0",
                     volume_context="ok")


def test_ingest_caps_downstream_and_dumps_full_scan(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    # 3 fake setups; cap keeps top 2 by score downstream, all 3 to disk
    fake = [_setup("AAA", 9.0), _setup("BBB", 8.0), _setup("CCC", 7.0)]
    monkeypatch.setattr(ingest, "scan_universe", lambda *a, **k: sorted(
        fake, key=lambda s: s.cleanliness_score, reverse=True))
    monkeypatch.setattr(ingest, "load_universe", lambda *a, **k: ["AAA", "BBB", "CCC"])
    monkeypatch.setattr(ingest, "_collect_news", lambda *a, **k: ([], []))

    snap = ingest.run(datetime(2026, 7, 6, 9, 0), run_dir=run_dir,
                      kite_client=object(), config_dir=Path("tradeloop/config"),
                      max_setups_downstream=2)

    # downstream (frozen snapshot + trader input) sees only the top 2
    assert {s.ticker for s in snap.setups} == {"AAA", "BBB"}
    # full scan dumped to disk with all 3
    dumped = [json.loads(l) for l in (run_dir / "full_scan.jsonl").read_text().splitlines()]
    assert {d["ticker"] for d in dumped} == {"AAA", "BBB", "CCC"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/data/test_ingest_universe.py -q`
Expected: FAIL - `TypeError: run() got an unexpected keyword argument 'max_setups_downstream'`

- [ ] **Step 4: Write minimal implementation**

In `tradeloop/lib/data/ingest.py`: add imports and a config reader, and rewrite the scan/freeze section of `run`. Add near the top:

```python
import json
from dataclasses import asdict
from tradeloop.lib.data.universe import load_universe
```

Change the `run` signature to accept overrides (all default `None` so callers/tests can inject; production reads config):

```python
def run(as_of: datetime, symbols: "list[str] | None" = None, max_fetch: int = 2500,
        run_dir: Path = None, *, http=None, kite_client=None,
        master: "TickerMaster | None" = None, config_dir: Path = Path("tradeloop/config"),
        max_setups_downstream: "int | None" = None) -> Snapshot:
```

Replace the scan block (the `setups = []` / `if kite_client is not None:` lines) with:

```python
    uni = (yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8")) or {}
           ).get("universe", {}) if (config_dir / "settings.yaml").exists() else {}
    min_turnover = float(uni.get("min_avg_daily_turnover_cr", 0)) * 1_00_00_000  # cr -> INR
    pace = float(uni.get("pace_seconds", 0.0))
    top_n = max_setups_downstream if max_setups_downstream is not None else int(uni.get("max_setups_downstream", 25))
    cache_path = config_dir / "universe_cache.json"

    setups = []
    if kite_client is not None:
        if symbols is None and str(uni.get("source", "config_yaml")) == "full_nse":
            symbols = load_universe(kite_client, cache_path, config_dir / "universe.yaml",
                                    max_age_days=int(uni.get("cache_days", 7)),
                                    max_symbols=int(uni.get("max_symbols", 2500)),
                                    now=as_of.date())
        elif symbols is None:
            symbols = master.symbols()
        setups = scan_universe(symbols[:max_fetch], kite_client, as_of.date(),
                               max_fetch=max_fetch, min_turnover_inr=min_turnover,
                               pace_seconds=pace)

    # full ranked scan to disk (audit + dashboard); only the cleanest N go downstream
    (run_dir / "full_scan.jsonl").write_text(
        "".join(json.dumps(asdict(s)) + "\n" for s in setups), encoding="utf-8")
    setups = setups[:top_n]
```

(The subsequent `render_news_raw` / `render_setups` / `freeze` lines stay as-is - they now operate on the capped `setups`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/data/test_ingest_universe.py tradeloop/tests/data -q`
Expected: PASS (new test + existing data tests unaffected)

- [ ] **Step 6: Commit**

```bash
git add tradeloop/lib/data/ingest.py tradeloop/config/settings.yaml tradeloop/tests/data/test_ingest_universe.py
git commit -m "ingest: full-NSE universe scan, liquidity floor, top-N downstream cap, full-scan dump"
```

---

### Task 6: End-to-end live smoke + full suite

**Files:**
- Test: `tradeloop/tests/data/test_ingest_universe_smoke.py` (a guarded, opt-in live smoke)

**Interfaces:**
- Consumes: everything above, against real Kite. Confirms the wider scan produces real setups for liquid names and that the top-N cap holds end to end.

- [ ] **Step 1: Confirm a fresh daily token** (user step)

Run: `npm run auth:zerodha` (complete the login in the browser). The scan needs a valid `ZERODHA_ACCESS_TOKEN` for the day.

- [ ] **Step 2: Live smoke on a real subset** (bounded, not the whole 1,800, to stay fast)

Run:
```bash
ZERODHA_ENABLE_DATA=true /Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -c "
from datetime import datetime
from pathlib import Path
import tempfile
from tradeloop.lib.data import ingest
from tradeloop.lib.data.kite import KiteClient
# a liquid subset so the smoke is quick but exercises the real path
syms = ['RELIANCE','TCS','HDFCBANK','INFY','ICICIBANK','SBIN','DLF','ITC','ONGC','WIPRO']
d = Path(tempfile.mkdtemp())
snap = ingest.run(datetime(2026,7,6,9,0), symbols=syms, run_dir=d,
                  kite_client=KiteClient(), config_dir=Path('tradeloop/config'))
print('setups downstream:', [s.ticker for s in snap.setups])
full = (d/'full_scan.jsonl').read_text().splitlines()
print('full_scan rows:', len(full))
print((d/'02_setups_raw.md').read_text()[:400])
"
```
Expected: real setups (with real entry/stop/target prices) for the liquid names that pass the floor; `full_scan.jsonl` has one row per surfaced setup; `02_setups_raw.md` shows real numbers. (Weekday date pinned; a holiday/weekend or stale token degrades to an empty scan - re-auth / pin a trading day and retry.)

- [ ] **Step 3: Full suite**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests -q`
Expected: PASS (all green under the same collection as before, plus the new tests).

- [ ] **Step 4: Commit**

```bash
git add tradeloop/tests/data/test_ingest_universe_smoke.py
git commit -m "test: live smoke for full-NSE universe scan"
```

---

## Self-Review Notes

- **Spec coverage:** bulk instrument fetch (Task 1-2), full universe with weekly cache + yaml fallback (Task 3), liquidity floor from candles (Task 4), rate pacing (Task 4), lifted cap + top-N downstream + full-scan dump (Task 5), config knobs in the existing `universe:` block (Task 5), live E2E (Task 6).
- **Order path untouched:** no change to evaluate()/grounding/ledger - grounding still reads the frozen snapshot, which now holds exactly the top-N tradeable setups.
- **Degradation:** Kite down -> yaml fallback (Task 3); per-symbol error -> skip (Task 4, existing); empty scan -> loud no-setups (existing).
- **Cost control:** top-N cap (default 25) bounds tokens fed to the AI stages regardless of how many setups the full scan surfaces.
- **Deferred (out of scope, flagged):** sector metadata for all names; ETF exclusion; concurrent fetching. None block the goal.
- **Known follow-up:** `full_scan.jsonl` is written but the dashboard does not yet render it - a later dashboard card can surface "N stocks scanned, top setups" if wanted.
