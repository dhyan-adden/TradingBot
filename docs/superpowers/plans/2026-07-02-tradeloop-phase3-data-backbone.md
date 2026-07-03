# TradeLoop Phase 3 — Research-Data Backbone Implementation Plan

**Goal:** Make TradeLoop's inputs REAL and auditable — hardened HTTP, four news sources, Kite price/candles, word-boundary ticker tagging, deterministic sentiment, a frozen hashed snapshot with `news_id`s, an evidence-trailer validator, and a wired scanner — replacing the empty `render_news_raw(NewsExtraction())` / `render_setups([])` seam in `prepare_cycle.py`.

**Architecture:** A plain-Python `ingest.run()` orchestrator fetches from four throttled news sources plus Kite (price via an MCP-over-stdio client to the project-local `src/mcp/zerodha.ts`), tags stories to tickers by word boundary over `ticker_master`, scores sentiment deterministically, freezes every raw item into a per-cycle snapshot folder (hashed, each item minting a `news_id`), and renders `01_news_raw.md` / `02_setups_raw.md`. `prepare_cycle.py` calls it behind the existing renderers; a standalone evidence validator rejects any cycle citing a `news_id` absent from that cycle's snapshot. Degrade-not-abort: a total news failure writes a loud `NO NEWS DATA` artifact, never a silent blank.

**Tech Stack:** Python 3.11, `httpx` (hardened HTTP, already a dep), `feedparser` (new dep — RSS with ETag/If-Modified-Since), `pydantic` v2 (already a dep), `pandas` (already a dep, scanner frames), stdlib `subprocess`+`json` for the Kite MCP stdio client, `pytest` with recorded fixtures only. Kite candles via a new `zerodha_historical` tool added to `src/mcp/zerodha.ts` (TypeScript / Zod).

---

## VERIFICATION (2026-07-04, post-P2 + post-option-D re-verify)

This plan was written 2026-07-02, before the propose/approve split (option D) and the P2 audit ledger merged. Re-verified against `main` @ `af4f3c0`. **This block OVERRIDES the task bodies below wherever they conflict.** Build against the corrections here.

**Confirmed still valid (no change):**
- The reasoning DAG really consumes the raw files: `stages.py:30` `"10_news": ["01_news_raw.md", "00_context.md"]`, `stages.py:33` `"13_technical": [..., "02_setups_raw.md", ...]`. Wiring real data into these files feeds the models. The seam `prepare_cycle.py:44-45` (`render_news_raw(NewsExtraction())` / `render_setups([])`) still exists — Task 13 target is live.
- `schemas.py:16` already defines `EvidenceMixin` (`evidence: list[str]  # news_ids, checked in P3`) on every recommendation-bearing model; prompts already instruct news_id citation. So the Task 12 validator has a real field to check and real teeth once wired (see V4).
- `zerodha.ts` helpers `requireCredentials`/`textJson`/`buildUrl`/`kiteRequest`/`registerTool` present; `zerodha_ltp`→`/quote/ltp`, `zerodha_ohlc`→`/quote/ohlc` both take `{instruments}`; `const transport = new StdioServerTransport()` present (Task 8 inserts before it). `kiteRequest` does `JSON.parse(text)` — so Task 8 is right to use a raw `fetch` for the CSV `/instruments/:exchange` endpoint. `npm run -s mcp:zerodha` → `tsx src/mcp/zerodha.ts` exists (Task 9 default command).
- `universe.yaml`: RELIANCE sector=Energy isin=INE002A01018 ✓; `amap["INFOSYS"]` resolves to INFY via the **name** index (INFY name is "Infosys"), not an alias — Task 3 test passes as written. `feedparser` NOT installed (Task 1 pip step genuinely needed). `scan_universe`/`scan_symbol` have zero external callers; no existing scanner test — Task 10 is safe.

**V1 — Task 1 dependency block drops `pandas`.** The block as written omits `pandas>=2.0`, which the scanner imports. Corrected `dependencies` (add feedparser, KEEP pandas):
```toml
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.7",
  "PyYAML>=6.0",
  "pandas>=2.0",
  "yfinance>=0.2.40",
  "feedparser>=6.0.11",
  "langgraph>=0.2.0"
]
```
The `[tool.setuptools.packages.find]` block already reads `where=["src","."]`, `include=["tradingbot*","tradeloop*"]` — **no change**, that half of Task 1 is a no-op. Also create an empty `tradeloop/tests/data/__init__.py` (the new test dir is a package; existing `tradeloop/tests/__init__.py` sets the pattern). Fixtures go under `tradeloop/tests/data/fixtures/` (a NEW dir — the existing `fixtures/` lives at `tradeloop/tests/fixtures/`, do not reuse it).

**V2 — Task 11 `ingest.run` makes `symbols` optional.** So `prepare` need not pre-resolve the universe (see V3). Corrected signature + guard:
```python
def run(as_of: datetime, symbols: "list[str] | None" = None, max_fetch: int = 30,
        run_dir: Path = None, *, http=None, kite_client=None,
        master: "TickerMaster | None" = None, config_dir: Path = Path("tradeloop/config")) -> Snapshot:
    assert run_dir is not None, "ingest.run requires run_dir"
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    if master is None:
        master = load_master(config_dir / "universe.yaml")
    if symbols is None:
        symbols = master.symbols()
    ...
```
Existing Task 11 tests still pass `symbols` positionally — unaffected.

**V3 — Task 13 must use the `root` param, pass `config_dir`, and not crash on symbols.** The current `prepare(mode, request="", root=None)` already sets `base = root or ROOT`; the orchestrator calls `_prepare(mode, request, root=root)` and the `--root` CLI depends on it. Task 13's body uses module-global `ROOT` and a manual `load_master(ROOT/config/universe.yaml)` outside the try — that reads the wrong config under an isolated root and FileNotFound-crashes when universe.yaml is absent. Corrected replacement for `prepare_cycle.py:42-45`:
```python
    # Real research ingest behind the renderers: fetch news + (later) Kite setups,
    # tag, freeze the hashed snapshot, render 01_news_raw / 02_setups_raw.
    # base-relative config so --root / isolated deployments read the right universe.
    try:
        ingest_run(now, run_dir=run_dir, config_dir=base / "config")
    except Exception as exc:  # degrade-not-abort: never leave a silent blank
        (run_dir / "01_news_raw.md").write_text(
            render_news_raw([], [], news_available=False), encoding="utf-8")
        (run_dir / "02_setups_raw.md").write_text(render_setups([]), encoding="utf-8")
        (run_dir / "ingest_error.txt").write_text(f"ingest failed: {exc}\n", encoding="utf-8")
```
Imports: `from tradeloop.lib.data.ingest import run as ingest_run` and `from tradeloop.lib.data.snapshot import render_news_raw, render_setups`; drop the `news_to_tickers` / `scanner.render_setups` imports and unused `import yaml`.

`prepare` passes **no `kite_client`** → ingest's `if kite_client is not None:` guard leaves `setups=[]`, so `02_setups_raw.md` renders empty in production for now. This is deliberate: the Kite scan path (Tasks 9-10) is built and fixture-tested but left **inactive** in the default cycle until Kite auth is confirmed in a live smoke run — activating live candles is promotion-gated, out of P3's hermetic scope. `# ponytail: news is live; Kite scan wired but dormant until a live smoke verifies auth — flip on by passing kite_client=KiteClient() here.` NEWS is live in production; tests stay offline via V3-hermeticity below.

**V3-hermeticity — Task 13 must keep `test_adhoc_mode.py` offline.** `test_adhoc_mode.py:43,56` call the real `prepare_cycle.prepare("adhoc", ...)`; once prepare calls `ingest_run`, those become live-network tests (Google/RSS/Reddit). Both tests only assert run-dir scaffolding, not news. Fix in Task 13's step: monkeypatch `prepare_cycle.ingest_run` to a no-op that writes the two artifacts, in both `test_adhoc_mode` cases (add an autouse fixture or explicit `monkeypatch.setattr`). No live I/O in the suite — non-negotiable.

**V4 — NEW Task 15: wire the evidence validator (Task 12 is dead code otherwise).** Nothing in Tasks 1-14 calls `validate_evidence`, so DoD #3's "evidence checked against snapshot" is unmet. Wire it into the **propose** phase (`run_cycle`), the cheap fail-fast point before a human/Opus reviews:

- Add to `snapshot.py`:
```python
def load_snapshot(run_dir: Path):
    """Rehydrate a frozen snapshot's news_ids for the post-reason evidence check.
    Returns None when this run has no frozen snapshot (e.g. a monkeypatched prepare),
    so legacy/unit cycles skip the check instead of failing."""
    items = Path(run_dir) / "snapshot" / "items.jsonl"
    if not items.exists():
        return None
    news_ids = set()
    for line in items.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("kind") in ("story", "macro") and rec.get("news_id"):
            news_ids.add(rec["news_id"])
    hash_file = Path(run_dir) / "snapshot" / "snapshot_hash.txt"
    snap_hash = hash_file.read_text().strip() if hash_file.exists() else ""
    return Snapshot(run_dir=Path(run_dir), snapshot_hash=snap_hash, news_ids=news_ids)
```
- In `orchestrator.run_cycle`, AFTER the `load_orders(...)` validation and BEFORE printing `AWAITING_APPROVAL`:
```python
        snap = load_snapshot(run_dir)
        if snap is not None:
            ev = validate_evidence(run_dir, snap)
            if not ev.ok:
                print(f"tradeloop_cycle=EVIDENCE_INVALID missing={len(ev.missing)} run_dir={run_dir}")
                return 1
```
with top-level imports `from tradeloop.lib.data.snapshot import load_snapshot` and `from tradeloop.lib.data.evidence import validate_evidence`. **Block, don't warn:** a cycle whose reasoning cites a news_id absent from its own frozen snapshot is fabricated evidence and must not become approvable (DoD #3/#4). No snapshot on disk → skip (keeps the monkeypatched `_prepare` orchestrator tests green). `route_cycle` does NOT re-check — evidence is immutable after reasoning, checked once at propose.
- Test `tradeloop/tests/data/test_evidence_wiring.py` (real, e2e through `run_cycle`): build a real frozen snapshot via `freeze([...one story with known news_id...], [], [], run_dir)`; monkeypatch `_prepare` to return that run_dir and `_run_reasoning` to write a valid `orders.json` plus (a) a `20_bull.json` citing the KNOWN id → assert `AWAITING_APPROVAL`, then (b) one citing a PHANTOM id → assert rc==1 and `EVIDENCE_INVALID`. Update `meta`/commit: `git commit -m "P3: wire evidence validator into propose (block cycles citing phantom news_id)"`.

**V5 — dead code (note, don't delete).** After Task 10, `tradeloop/lib/data/nse_quotes.py` (`fetch_ohlcv`) has no callers. Per surgical rules leave it; flag as a follow-up removal. Task 14's deletions stand as written (et_markets_rss / moneycontrol_rss / corp_announcements / reddit_sentiment); do NOT add nse_quotes to that list.

**Build order:** Tasks 1-14 as corrected above, then Task 15. Full suite (`python -m pytest tradeloop/tests -q` under `-W error`) green at the end. Report per-task pass/fail as coverage-of-plan (which guard/edge each test kills), not a bare count.

---

## Global Constraints

- India cash equities only — no other exchanges/segments; symbols resolve through `config/universe.yaml` / `ticker_master`.
- Long-only: `BUY` opens/adds, `SELL` exits only; no shorts, no F&O, no NRML, no leverage. (This phase produces research inputs only — it never emits an order — but scanner setups are long-biased and never suggest shorts.)
- CNC/MIS product types only.
- `tradeloop/kill_switch.md` halts orders (enforced in the P0 order path; Phase 3 does not route orders).
- Paper default: `ZERODHA_ENABLE_TRADING=false`; live only past the promotion gate (`settings.yaml` `live_promotion_gates`). Kite reads (ltp/ohlc/historical) are read-only and paper-safe.
- The risk gate `checks.evaluate()` runs on every order in the P0 order path (unchanged here).
- Security (AGENTS.md): never read/print `.env`; never print env values whose name contains KEY/SECRET/TOKEN/PASSWORD/AUTH/CREDENTIAL. Kite auth stays inside the project-local `src/mcp/zerodha.ts`; the Python client never touches credentials.

## File Structure

| File | Responsibility |
|---|---|
| `tradeloop/lib/data/http.py` | **new** — one hardened `httpx.Client` factory + `get()` (UA, retry/backoff/jitter, per-request timeout, conditional GET via ETag/If-Modified-Since, NSE/BSE cookie-warmup session). |
| `tradeloop/lib/data/kite.py` | **new** — MCP-over-stdio client to `src/mcp/zerodha.ts`; `ltp()`, `ohlc()`, `historical()` returning `Candle`s. |
| `tradeloop/lib/data/tickers.py` | **new** — word-boundary `extract()` over `TickerMaster`; skips aliases <3 chars; produces `TaggedStory`. |
| `tradeloop/lib/data/ticker_master.py` | **modify** — add `TickerMaster` wrapper with `symbols()`, `sector_of()`, `isin_index()`, ambiguity-safe alias map. |
| `tradeloop/lib/data/sentiment.py` | **new** — deterministic lexicon+negation `score(text) -> float` in [-1, 1]. |
| `tradeloop/lib/data/snapshot.py` | **new** — `news_id()`, `freeze()` raw items + render `01_news_raw`/`02_setups_raw`, compute `snapshot_hash`. |
| `tradeloop/lib/data/ingest.py` | **new** — sequential throttled `run()`; bounded pre-filtered scan + `max_fetch`; degrade-not-abort. |
| `tradeloop/lib/data/sources/__init__.py` | **new** — package marker + shared `RawItem` dataclass. |
| `tradeloop/lib/data/sources/google_news.py` | **rewrite of `google_news_rss.py` logic** — hardened Google News (tier-C generic). |
| `tradeloop/lib/data/sources/rss_native.py` | **new** — Moneycontrol/ET/Mint/BS native RSS via feedparser (tier-A/B). |
| `tradeloop/lib/data/sources/nse_bse.py` | **new** — official NSE/BSE announcements (tier-A). |
| `tradeloop/lib/data/sources/reddit.py` | **new** — Reddit `.json` public listing (tier-C). |
| `tradeloop/lib/data/evidence.py` | **new** — `validate_evidence(run_dir, snapshot)` rejecting cited `news_id`s not in the snapshot. |
| `tradeloop/lib/ta/scanner.py` | **modify** — bounded scan, kill silent `except`, fix ATR fabrication. |
| `tradeloop/scripts/prepare_cycle.py` | **modify** — call `ingest.run()` behind the two renderers. |
| `src/mcp/zerodha.ts` | **modify** — add `zerodha_historical` + `zerodha_instrument_token` tools. |
| `pyproject.toml` | **modify** — declare `feedparser>=6.0`; package `tradeloop`. |
| `tradeloop/config/news_sources.yaml` | **modify** — add real feed URLs per source id. |
| `tradeloop/tests/data/*` | **new** — recorded fixtures + tests. |

Fixtures live under `tradeloop/tests/data/fixtures/` (recorded RSS XML, Reddit JSON, Kite MCP responses). No test performs live network I/O.

---

### Task 1: Declare `feedparser`, package `tradeloop`

**Files:** modify `pyproject.toml`; test `tradeloop/tests/data/test_packaging.py` (new).

**Interfaces:** Produces: nothing importable; enables `import tradeloop.lib.data.*` and `import feedparser`.

1. Write failing test `tradeloop/tests/data/test_packaging.py`:
```python
import importlib


def test_feedparser_available():
    assert importlib.import_module("feedparser") is not None


def test_tradeloop_data_package_importable():
    assert importlib.import_module("tradeloop.lib.data") is not None
```
2. Run: `python -m pytest tradeloop/tests/data/test_packaging.py -q` → **FAIL** (`ModuleNotFoundError: No module named 'feedparser'`).
3. Implement — edit `pyproject.toml`. Add `feedparser>=6.0.11` to `dependencies`; add `tradeloop` to the package find config:
```toml
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.7",
  "PyYAML>=6.0",
  "yfinance>=0.2.40",
  "feedparser>=6.0.11",
  "langgraph>=0.2.0"
]
```
```toml
[tool.setuptools.packages.find]
where = ["src", "."]
include = ["tradingbot*", "tradeloop*"]
```
Then install: `pip install -e . && pip install feedparser>=6.0.11`.
4. Run: `python -m pytest tradeloop/tests/data/test_packaging.py -q` → **PASS**.
5. Commit: `git add pyproject.toml tradeloop/tests/data/test_packaging.py && git commit -m "P3: declare feedparser dep, package tradeloop"`

---

### Task 2: Hardened HTTP client (`data/http.py`)

**Files:** create `tradeloop/lib/data/http.py`; test `tradeloop/tests/data/test_http.py`.

**Interfaces:**
- Consumes: `httpx` (installed).
- Produces:
  - `DEFAULT_UA: str`
  - `@dataclass HttpResponse{status: int, body: bytes, headers: dict[str,str], not_modified: bool}`
  - `class Http: __init__(self, timeout: float = 10.0, retries: int = 3, warmup_hosts: tuple[str,...] = ())`
  - `Http.get(self, url: str, *, etag: str|None=None, modified: str|None=None, extra_headers: dict|None=None) -> HttpResponse`
  - `Http.close(self) -> None`

1. Write failing test `tradeloop/tests/data/test_http.py`:
```python
import httpx
import pytest

from tradeloop.lib.data.http import Http, HttpResponse, DEFAULT_UA


def _client_with(handler):
    transport = httpx.MockTransport(handler)
    http = Http()
    http._client = httpx.Client(transport=transport, headers={"User-Agent": DEFAULT_UA})
    return http


def test_get_sends_user_agent_and_returns_body():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, content=b"hello")

    http = _client_with(handler)
    resp = http.get("https://example.test/feed")
    assert isinstance(resp, HttpResponse)
    assert resp.status == 200
    assert resp.body == b"hello"
    assert seen["ua"] == DEFAULT_UA
    assert resp.not_modified is False


def test_conditional_get_sends_etag_and_flags_304():
    seen = {}

    def handler(request):
        seen["inm"] = request.headers.get("if-none-match")
        seen["ims"] = request.headers.get("if-modified-since")
        return httpx.Response(304)

    http = _client_with(handler)
    resp = http.get("https://example.test/feed", etag='"abc"', modified="Wed, 01 Jan 2026 00:00:00 GMT")
    assert seen["inm"] == '"abc"'
    assert seen["ims"] == "Wed, 01 Jan 2026 00:00:00 GMT"
    assert resp.status == 304
    assert resp.not_modified is True


def test_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, content=b"ok")

    http = _client_with(handler)
    http._sleep = lambda _s: None  # no real backoff sleep in tests
    resp = http.get("https://example.test/feed")
    assert resp.status == 200
    assert calls["n"] == 3


def test_retries_exhausted_raises():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    http = _client_with(handler)
    http._sleep = lambda _s: None
    with pytest.raises(httpx.HTTPError):
        http.get("https://example.test/feed")
```
2. Run: `python -m pytest tradeloop/tests/data/test_http.py -q` → **FAIL** (`ModuleNotFoundError: tradeloop.lib.data.http`).
3. Implement `tradeloop/lib/data/http.py`:
```python
from __future__ import annotations

import random
import time
from dataclasses import dataclass

import httpx

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 TradeLoop/1.0"
)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: dict
    not_modified: bool


class Http:
    """One shared hardened client: UA, retry/backoff/jitter, timeout, conditional GET,
    optional cookie warmup for hosts (NSE/BSE) that hand out a cookie on the homepage first."""

    def __init__(self, timeout: float = 10.0, retries: int = 3, warmup_hosts: tuple[str, ...] = ()):
        self.retries = retries
        self.warmup_hosts = warmup_hosts
        self._warmed: set[str] = set()
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_UA, "Accept-Language": "en-IN,en;q=0.9"},
        )

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def _warmup(self, url: str) -> None:
        host = httpx.URL(url).host or ""
        if host and host in self.warmup_hosts and host not in self._warmed:
            try:
                self._client.get(f"https://{host}/", timeout=self._client.timeout)
            except httpx.HTTPError:
                pass  # warmup is best-effort; the real request still carries any cookie set
            self._warmed.add(host)

    def get(self, url, *, etag=None, modified=None, extra_headers=None) -> HttpResponse:
        self._warmup(url)
        headers: dict = dict(extra_headers or {})
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = self._client.get(url, headers=headers)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.retries - 1:
                    self._sleep((2 ** attempt) + random.uniform(0, 0.5))
                    continue
                return HttpResponse(
                    status=resp.status_code,
                    body=resp.content,
                    headers=dict(resp.headers),
                    not_modified=resp.status_code == 304,
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < self.retries - 1:
                    self._sleep((2 ** attempt) + random.uniform(0, 0.5))
                    continue
        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self._client.close()
```
4. Run: `python -m pytest tradeloop/tests/data/test_http.py -q` → **PASS**.
5. Commit: `git add tradeloop/lib/data/http.py tradeloop/tests/data/test_http.py && git commit -m "P3: hardened HTTP client (UA/retry/backoff/conditional-GET/warmup)"`

---

### Task 3: `TickerMaster` wrapper + ISIN index (`ticker_master.py`)

**Files:** modify `tradeloop/lib/data/ticker_master.py`; test `tradeloop/tests/data/test_ticker_master.py`.

**Interfaces:**
- Consumes: existing `TickerRecord`, `load_ticker_master(path) -> list[TickerRecord]` (§5 keep).
- Produces:
  - `class TickerMaster` with:
    - `records: list[TickerRecord]`
    - `symbols(self) -> list[str]`
    - `sector_of(self, symbol: str) -> str`
    - `record_for(self, symbol: str) -> TickerRecord | None`
    - `by_isin(self, isin: str) -> TickerRecord | None`
    - `alias_map(self) -> dict[str, TickerRecord]` (upper-cased symbol/name/alias → record; first-writer-wins so a symbol never gets shadowed by another record's alias)
  - `load_master(path: Path) -> TickerMaster`

1. Write failing test `tradeloop/tests/data/test_ticker_master.py`:
```python
from pathlib import Path

from tradeloop.lib.data.ticker_master import load_master

UNIVERSE = Path("tradeloop/config/universe.yaml")


def test_symbols_and_sector():
    tm = load_master(UNIVERSE)
    assert "RELIANCE" in tm.symbols()
    assert tm.sector_of("RELIANCE") == "Energy"


def test_isin_index():
    tm = load_master(UNIVERSE)
    rec = tm.by_isin("INE002A01018")
    assert rec is not None and rec.symbol == "RELIANCE"


def test_alias_map_symbol_not_shadowed():
    tm = load_master(UNIVERSE)
    amap = tm.alias_map()
    assert amap["RELIANCE"].symbol == "RELIANCE"
    assert amap["INFOSYS"].symbol == "INFY"
```
2. Run: `python -m pytest tradeloop/tests/data/test_ticker_master.py -q` → **FAIL** (`ImportError: cannot import name 'load_master'`).
3. Implement — append to `tradeloop/lib/data/ticker_master.py`:
```python
class TickerMaster:
    def __init__(self, records: List[TickerRecord]):
        self.records = records
        self._by_symbol = {r.symbol.upper(): r for r in records}
        self._by_isin = {r.isin.upper(): r for r in records if r.isin}

    def symbols(self) -> List[str]:
        return [r.symbol for r in self.records]

    def record_for(self, symbol: str) -> "TickerRecord | None":
        return self._by_symbol.get(symbol.strip().upper())

    def sector_of(self, symbol: str) -> str:
        rec = self.record_for(symbol)
        return rec.sector if rec else ""

    def by_isin(self, isin: str) -> "TickerRecord | None":
        return self._by_isin.get(isin.strip().upper())

    def alias_map(self) -> Dict[str, TickerRecord]:
        # symbols first (never shadowed), then names, then aliases; first writer wins.
        index: Dict[str, TickerRecord] = {}
        for record in self.records:
            index.setdefault(record.symbol.upper(), record)
        for record in self.records:
            index.setdefault(record.name.upper(), record)
        for record in self.records:
            for alias in record.aliases:
                index.setdefault(alias.upper(), record)
        return index


def load_master(path: Path) -> TickerMaster:
    return TickerMaster(load_ticker_master(path))
```
4. Run: `python -m pytest tradeloop/tests/data/test_ticker_master.py -q` → **PASS**.
5. Commit: `git add tradeloop/lib/data/ticker_master.py tradeloop/tests/data/test_ticker_master.py && git commit -m "P3: TickerMaster wrapper with ISIN index + ambiguity-safe alias map"`

---

### Task 4: Word-boundary ticker tagging (`data/tickers.py`)

**Files:** create `tradeloop/lib/data/tickers.py`; test `tradeloop/tests/data/test_tickers.py`. (Fixes the substring bug at `news_to_tickers.py:45-46`.)

**Interfaces:**
- Consumes: `TickerMaster.alias_map()` (Task 3); `RawItem` (defined here for now, re-exported by Task 6 sources) with fields `news_id: str, title: str, url: str, source: str, tier: str, published_at: str, body: str = ""`.
- Produces:
  - `@dataclass(frozen=True) TaggedStory{ticker,title,url,source,tier,category,news_id,confidence}` (same field names as the legacy `news_to_tickers.TaggedStory` plus `news_id`).
  - `MIN_ALIAS_LEN = 3`
  - `extract(items: Iterable[RawItem], master: TickerMaster) -> list[TaggedStory]`
  - `categorize(title: str) -> str`

1. Write failing test `tradeloop/tests/data/test_tickers.py`:
```python
from tradeloop.lib.data.ticker_master import load_master
from tradeloop.lib.data.tickers import extract, TaggedStory
from tradeloop.lib.data.sources import RawItem
from pathlib import Path

TM = load_master(Path("tradeloop/config/universe.yaml"))


def _item(title, nid="deadbeef1234"):
    return RawItem(news_id=nid, title=title, url="http://x", source="google_news_generic",
                   tier="tier_C", published_at="2026-07-02T00:00:00Z")


def test_word_boundary_match_hits_full_word():
    tagged = extract([_item("Reliance posts record quarterly profit")], TM)
    assert any(t.ticker == "RELIANCE" and t.category == "earnings" for t in tagged)


def test_substring_false_positive_is_rejected():
    # legacy substring matcher tagged 'INFY' inside 'INFYMEDIA' etc.; word-boundary must not.
    tagged = extract([_item("INFYMEDIALABS launches app")], TM)
    assert all(t.ticker != "INFY" for t in tagged)


def test_short_alias_skipped():
    # a 2-char alias must never match (guards symbols like 'IT'); none of our records
    # expose a <3 char alias, so a headline of pure noise yields no tags.
    tagged = extract([_item("IT is a fine day in IN")], TM)
    assert tagged == []


def test_news_id_propagates():
    tagged = extract([_item("Infosys wins large deal", nid="cafebabe0001")], TM)
    assert tagged and tagged[0].news_id == "cafebabe0001"
```
2. Run: `python -m pytest tradeloop/tests/data/test_tickers.py -q` → **FAIL** (`ModuleNotFoundError: tradeloop.lib.data.tickers`).
3. Implement `tradeloop/lib/data/sources/__init__.py` (the shared `RawItem` lives with the sources that produce it):
```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawItem:
    news_id: str
    title: str
    url: str
    source: str
    tier: str
    published_at: str
    body: str = ""
```
Then `tradeloop/lib/data/tickers.py`:
```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List

from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.ticker_master import TickerMaster

MIN_ALIAS_LEN = 3

CATEGORY_TERMS = {
    "earnings": ["profit", "quarter", "results", "earnings"],
    "order_win": ["order", "contract", "deal", "wins"],
    "regulatory": ["sebi", "penalty", "probe", "regulator"],
    "macro": ["rbi", "inflation", "oil", "rupee", "fed"],
    "m&a": ["acquire", "merger", "stake", "buyout"],
    "management": ["ceo", "cfo", "resigns", "appoints"],
}


@dataclass(frozen=True)
class TaggedStory:
    ticker: str
    title: str
    url: str
    source: str
    tier: str
    category: str
    news_id: str
    confidence: float


def categorize(title: str) -> str:
    lowered = title.lower()
    for category, terms in CATEGORY_TERMS.items():
        if any(term in lowered for term in terms):
            return category
    return "other"


def extract(items: Iterable[RawItem], master: TickerMaster) -> List[TaggedStory]:
    amap = master.alias_map()
    # Pre-compile one word-boundary pattern per alias >= MIN_ALIAS_LEN.
    patterns = [
        (re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE), record.symbol)
        for alias, record in amap.items()
        if len(alias) >= MIN_ALIAS_LEN
    ]
    tagged: List[TaggedStory] = []
    for item in items:
        matched: set[str] = set()
        for pattern, symbol in patterns:
            if symbol in matched:
                continue
            if pattern.search(item.title):
                matched.add(symbol)
        category = categorize(item.title)
        for symbol in sorted(matched):
            tagged.append(
                TaggedStory(
                    ticker=symbol,
                    title=item.title,
                    url=item.url,
                    source=item.source,
                    tier=item.tier,
                    category=category,
                    news_id=item.news_id,
                    confidence=1.0,
                )
            )
    return tagged
```
4. Run: `python -m pytest tradeloop/tests/data/test_tickers.py -q` → **PASS**.
5. Commit: `git add tradeloop/lib/data/tickers.py tradeloop/lib/data/sources/__init__.py tradeloop/tests/data/test_tickers.py && git commit -m "P3: word-boundary ticker tagging (fixes substring false positives)"`

---

### Task 5: Deterministic sentiment (`data/sentiment.py`)

**Files:** create `tradeloop/lib/data/sentiment.py`; test `tradeloop/tests/data/test_sentiment.py`.

**Decision:** deterministic, dependency-free lexicon + negation flip (no FinVADER dep — nuanced sentiment is the model's job in P1). `// ponytail: lexicon+negation baseline; the P1 LLM does nuanced per-name sentiment.`

**Interfaces:** Produces `score(text: str) -> float` (clamped to [-1.0, 1.0]); `label(score: float) -> str` (`positive`/`neutral`/`negative`).

1. Write failing test `tradeloop/tests/data/test_sentiment.py`:
```python
from tradeloop.lib.data.sentiment import score, label


def test_positive():
    assert score("Company posts strong profit and record growth") > 0
    assert label(score("strong growth beat")) == "positive"


def test_negative():
    assert score("Shares fall on fraud probe and heavy loss") < 0


def test_negation_flips():
    assert score("no profit growth this quarter") < score("profit growth this quarter")


def test_clamped():
    s = score("strong strong bullish growth profit beat up rally surge")
    assert -1.0 <= s <= 1.0


def test_empty_is_neutral():
    assert score("") == 0.0
    assert label(0.0) == "neutral"
```
2. Run: `python -m pytest tradeloop/tests/data/test_sentiment.py -q` → **FAIL** (`ModuleNotFoundError`).
3. Implement `tradeloop/lib/data/sentiment.py`:
```python
from __future__ import annotations

import re

POSITIVE = {"strong", "bullish", "growth", "profit", "beat", "up", "rally", "surge",
            "record", "wins", "gain", "upgrade", "outperform"}
NEGATIVE = {"weak", "bearish", "fall", "fraud", "loss", "down", "probe", "penalty",
            "miss", "cut", "downgrade", "default", "resigns"}
NEGATORS = {"no", "not", "never", "without", "fails", "failed"}


def score(text: str) -> float:
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    if not tokens:
        return 0.0
    raw = 0
    for i, tok in enumerate(tokens):
        negated = i > 0 and tokens[i - 1] in NEGATORS
        if tok in POSITIVE:
            raw += -1 if negated else 1
        elif tok in NEGATIVE:
            raw += 1 if negated else -1
    # normalise by a soft cap so a few strong terms saturate toward +/-1.
    return max(-1.0, min(1.0, raw / 3.0))


def label(value: float) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"
```
4. Run: `python -m pytest tradeloop/tests/data/test_sentiment.py -q` → **PASS**.
5. Commit: `git add tradeloop/lib/data/sentiment.py tradeloop/tests/data/test_sentiment.py && git commit -m "P3: deterministic lexicon+negation sentiment"`

---

### Task 6: News sources — google_news, rss_native, nse_bse, reddit

**Files:** create `tradeloop/lib/data/sources/google_news.py`, `rss_native.py`, `nse_bse.py`, `reddit.py`; modify `tradeloop/config/news_sources.yaml`; test `tradeloop/tests/data/test_sources.py` with fixtures under `tradeloop/tests/data/fixtures/`.

**Interfaces:**
- Consumes: `Http.get()` / `HttpResponse` (Task 2); `RawItem` + `news_id` (Task 7 provides `news_id`; to avoid a cycle, `news_id` is imported from `snapshot` — build Task 7 first is unnecessary because sources only *call* it; see step 3 note). To keep tasks orderable, `news_id` is defined in Task 7 (`snapshot.py`) and sources import it; Task 7 has no dep on sources, so import order is fine.
- Produces (each source, same signature so `ingest` treats them uniformly):
  - `fetch_google_news(http: Http, query: str, limit: int = 15) -> list[RawItem]`
  - `fetch_rss(http: Http, feed_url: str, source: str, tier: str, limit: int = 25) -> list[RawItem]`
  - `fetch_nse_bse(http: Http, limit: int = 40) -> list[RawItem]`
  - `fetch_reddit(http: Http, subreddits: list[str], limit: int = 25) -> list[RawItem]`

1. Write failing test `tradeloop/tests/data/test_sources.py`:
```python
from pathlib import Path

import httpx

from tradeloop.lib.data.http import Http, DEFAULT_UA
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.sources.google_news import fetch_google_news
from tradeloop.lib.data.sources.rss_native import fetch_rss
from tradeloop.lib.data.sources.reddit import fetch_reddit

FX = Path("tradeloop/tests/data/fixtures")


def _http_serving(body: bytes, content_type="application/xml"):
    def handler(request):
        return httpx.Response(200, content=body, headers={"content-type": content_type})
    http = Http()
    http._client = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": DEFAULT_UA})
    return http


def test_google_news_parses_items():
    http = _http_serving((FX / "google_news.xml").read_bytes())
    items = fetch_google_news(http, "Reliance", limit=5)
    assert items and all(isinstance(i, RawItem) for i in items)
    assert items[0].tier == "tier_C"
    assert items[0].source == "google_news_generic"
    assert len(items[0].news_id) == 12


def test_rss_native_tier_and_source_label():
    http = _http_serving((FX / "moneycontrol.xml").read_bytes())
    items = fetch_rss(http, "http://feed", source="moneycontrol_news", tier="tier_B", limit=10)
    assert items and items[0].source == "moneycontrol_news" and items[0].tier == "tier_B"


def test_reddit_parses_json_listing():
    http = _http_serving((FX / "reddit.json").read_bytes(), content_type="application/json")
    items = fetch_reddit(http, ["IndianStreetBets"], limit=10)
    assert items and items[0].tier == "tier_C"
    assert items[0].source == "reddit_indianstreetbets"


def test_source_failure_returns_empty_not_raise():
    def handler(request):
        raise httpx.ConnectError("down", request=request)
    http = Http()
    http._client = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": DEFAULT_UA})
    http._sleep = lambda _s: None
    assert fetch_rss(http, "http://feed", source="mint_markets", tier="tier_A") == []
```
Create fixtures:
- `tradeloop/tests/data/fixtures/google_news.xml` — a minimal RSS `<rss><channel><item><title>Reliance posts record profit</title><link>https://news.google.com/x</link><guid>g1</guid><pubDate>Wed, 02 Jul 2026 06:00:00 GMT</pubDate></item></channel></rss>`.
- `moneycontrol.xml` — same RSS shape, one item titled "Infosys wins large deal".
- `reddit.json` — `{"data":{"children":[{"data":{"id":"abc","title":"SBIN breakout watch","permalink":"/r/IndianStreetBets/comments/abc/","created_utc":1750000000}}]}}`.
2. Run: `python -m pytest tradeloop/tests/data/test_sources.py -q` → **FAIL** (`ModuleNotFoundError`).
3. Implement. `tradeloop/lib/data/sources/google_news.py`:
```python
from __future__ import annotations

import html
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List

import httpx

from tradeloop.lib.data.http import Http
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.snapshot import news_id


def _parse_rss(body: bytes, source: str, tier: str, limit: int) -> List[RawItem]:
    root = ET.fromstring(body)
    items: List[RawItem] = []
    for node in root.findall("./channel/item")[:limit]:
        title = html.unescape(node.findtext("title", default="")).strip()
        link = node.findtext("link", default="").strip()
        guid = node.findtext("guid", default="").strip()
        pub = node.findtext("pubDate", default="").strip() or datetime.now(timezone.utc).isoformat()
        if not title:
            continue
        items.append(RawItem(
            news_id=news_id(guid, link, title),
            title=title, url=link, source=source, tier=tier, published_at=pub,
        ))
    return items


def fetch_google_news(http: Http, query: str, limit: int = 15) -> List[RawItem]:
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        resp = http.get(url)
    except httpx.HTTPError:
        return []
    if resp.status != 200 or not resp.body:
        return []
    return _parse_rss(resp.body, source="google_news_generic", tier="tier_C", limit=limit)
```
`tradeloop/lib/data/sources/rss_native.py` (feedparser handles the many real-world feed dialects — Moneycontrol/ET/Mint/BS — better than hand XML):
```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import feedparser
import httpx

from tradeloop.lib.data.http import Http
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.snapshot import news_id


def fetch_rss(http: Http, feed_url: str, source: str, tier: str, limit: int = 25) -> List[RawItem]:
    try:
        resp = http.get(feed_url)
    except httpx.HTTPError:
        return []
    if resp.status not in (200,) or not resp.body:
        return []
    parsed = feedparser.parse(resp.body)
    items: List[RawItem] = []
    for entry in parsed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        guid = (entry.get("id") or link).strip()
        pub = (entry.get("published") or datetime.now(timezone.utc).isoformat()).strip()
        if not title:
            continue
        items.append(RawItem(
            news_id=news_id(guid, link, title),
            title=title, url=link, source=source, tier=tier, published_at=pub,
        ))
    return items
```
`tradeloop/lib/data/sources/nse_bse.py` (official RSS feeds; NSE hands a cookie on its homepage first, so this source runs through an `Http` built with `warmup_hosts=("www.nseindia.com","www.bseindia.com")` — see Task 8):
```python
from __future__ import annotations

from typing import List

from tradeloop.lib.data.http import Http
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.sources.rss_native import fetch_rss

# Official corporate-announcement RSS endpoints (tier-A).
NSE_ANN = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
BSE_ANN = "https://www.bseindia.com/data/xml/notices.xml"


def fetch_nse_bse(http: Http, limit: int = 40) -> List[RawItem]:
    items: List[RawItem] = []
    items += fetch_rss(http, NSE_ANN, source="nse_announcements", tier="tier_A", limit=limit)
    items += fetch_rss(http, BSE_ANN, source="bse_announcements", tier="tier_A", limit=limit)
    return items
```
`tradeloop/lib/data/sources/reddit.py`:
```python
from __future__ import annotations

import json
from typing import List

import httpx

from tradeloop.lib.data.http import Http
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.snapshot import news_id

_SOURCE = {"IndianStreetBets": "reddit_indianstreetbets", "IndiaInvestments": "reddit_indiainvestments"}


def fetch_reddit(http: Http, subreddits: List[str], limit: int = 25) -> List[RawItem]:
    items: List[RawItem] = []
    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}"
        try:
            resp = http.get(url)
        except httpx.HTTPError:
            continue
        if resp.status != 200 or not resp.body:
            continue
        try:
            payload = json.loads(resp.body)
        except (ValueError, json.JSONDecodeError):
            continue
        for child in payload.get("data", {}).get("children", []):
            d = child.get("data", {})
            title = (d.get("title") or "").strip()
            if not title:
                continue
            link = "https://www.reddit.com" + d.get("permalink", "")
            guid = d.get("id", "") or link
            items.append(RawItem(
                news_id=news_id(guid, link, title),
                title=title, url=link,
                source=_SOURCE.get(sub, f"reddit_{sub.lower()}"), tier="tier_C",
                published_at=str(d.get("created_utc", "")),
            ))
    return items
```
Then add feed URLs to `tradeloop/config/news_sources.yaml` (append a `feeds:` map the ingest reads — see Task 8):
```yaml
feeds:
  moneycontrol_news: https://www.moneycontrol.com/rss/latestnews.xml
  economic_times_markets: https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms
  mint_markets: https://www.livemint.com/rss/markets
  business_standard_markets: https://www.business-standard.com/rss/markets-106.rss
tiers:
  moneycontrol_news: tier_B
  economic_times_markets: tier_A
  mint_markets: tier_A
  business_standard_markets: tier_A
```
4. Run: `python -m pytest tradeloop/tests/data/test_sources.py -q` → **PASS**.
5. Commit: `git add tradeloop/lib/data/sources tradeloop/config/news_sources.yaml tradeloop/tests/data/test_sources.py tradeloop/tests/data/fixtures && git commit -m "P3: four hardened news sources (google/rss-native/nse-bse/reddit) with news_id"`

---

### Task 7: Snapshot — `news_id`, freeze, hash, renderers (`data/snapshot.py`)

**Files:** create `tradeloop/lib/data/snapshot.py`; test `tradeloop/tests/data/test_snapshot.py`.

**Interfaces:**
- Consumes: `TaggedStory` (Task 4), `SetupScan` (existing `ta/scanner.py`).
- Produces:
  - `news_id(guid: str, url: str, title: str) -> str` — `sha256("<guid>|<url>|<title>")[:12]` (§6).
  - `@dataclass Snapshot{run_dir: Path, snapshot_hash: str, news_ids: set[str], stories: list[TaggedStory], macro: list[RawItem], setups: list[SetupScan], news_available: bool}`
  - `freeze(stories, macro, setups, run_dir) -> tuple[Path, str]` — writes `run_dir/snapshot/items.jsonl` (one raw item per line) + `snapshot_hash.txt`; returns `(snapshot_dir, snapshot_hash)`. (§6 `freeze(items, run_dir) -> tuple[Path, str]`.)
  - `render_news_raw(stories, macro, news_available: bool) -> str`
  - `render_setups(setups) -> str` (replaces `scanner.render_setups`; signature preserved).

1. Write failing test `tradeloop/tests/data/test_snapshot.py`:
```python
import hashlib
from pathlib import Path

from tradeloop.lib.data.snapshot import news_id, freeze, render_news_raw
from tradeloop.lib.data.tickers import TaggedStory
from tradeloop.lib.data.sources import RawItem


def _story(nid):
    return TaggedStory("RELIANCE", "Reliance profit", "http://x", "google_news_generic",
                       "tier_C", "earnings", nid, 1.0)


def test_news_id_deterministic_and_12():
    a = news_id("g", "u", "t")
    assert a == hashlib.sha256("g|u|t".encode()).hexdigest()[:12]
    assert len(a) == 12
    assert news_id("g", "u", "t") == a


def test_freeze_writes_and_hashes(tmp_path):
    stories = [_story("abc123abc123")]
    snap_dir, snap_hash = freeze(stories, [], [], tmp_path)
    assert (snap_dir / "items.jsonl").exists()
    assert (snap_dir / "snapshot_hash.txt").read_text().strip() == snap_hash
    assert len(snap_hash) == 64  # full sha256 over frozen bytes


def test_render_marks_no_news_loudly():
    out = render_news_raw([], [], news_available=False)
    assert "NO NEWS DATA" in out
```
2. Run: `python -m pytest tradeloop/tests/data/test_snapshot.py -q` → **FAIL** (`ModuleNotFoundError`).
3. Implement `tradeloop/lib/data/snapshot.py`:
```python
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List

from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.tickers import TaggedStory


def news_id(guid: str, url: str, title: str) -> str:
    return hashlib.sha256(f"{guid}|{url}|{title}".encode("utf-8")).hexdigest()[:12]


@dataclass
class Snapshot:
    run_dir: Path
    snapshot_hash: str
    news_ids: set
    stories: List[TaggedStory] = field(default_factory=list)
    macro: List[RawItem] = field(default_factory=list)
    setups: list = field(default_factory=list)
    news_available: bool = True


def freeze(stories, macro, setups, run_dir: Path):
    snap_dir = Path(run_dir) / "snapshot"
    snap_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for s in stories:
        records.append({"kind": "story", **asdict(s)})
    for m in macro:
        records.append({"kind": "macro", **asdict(m)})
    for c in setups:
        records.append({"kind": "setup", **asdict(c)})
    # deterministic order so the hash is reproducible regardless of fetch order.
    records.sort(key=lambda r: (r["kind"], r.get("news_id", ""), r.get("ticker", "")))
    lines = [json.dumps(r, sort_keys=True, default=str) for r in records]
    blob = "\n".join(lines).encode("utf-8")
    snapshot_hash = hashlib.sha256(blob).hexdigest()
    (snap_dir / "items.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    (snap_dir / "snapshot_hash.txt").write_text(snapshot_hash + "\n", encoding="utf-8")
    return snap_dir, snapshot_hash


def render_news_raw(stories, macro, news_available: bool) -> str:
    if not news_available:
        return "# Raw News\n\n> NO NEWS DATA — every news source failed this cycle. Decisions must not rely on news catalysts.\n"
    lines = ["# Raw News", "", "## Macro Stories"]
    for item in macro:
        lines.append(f"- [{item.news_id}] {item.title} ({item.source}) {item.url}")
    lines.extend(["", "## Ticker Stories"])
    by_ticker: dict = {}
    for s in stories:
        by_ticker.setdefault(s.ticker, []).append(s)
    for ticker, items in sorted(by_ticker.items()):
        lines.append(f"### {ticker}")
        for s in items:
            lines.append(f"- [{s.news_id}] [{s.tier}] {s.category}: {s.title} ({s.source}) {s.url}")
    lines.append("")
    return "\n".join(lines)


def render_setups(setups) -> str:
    lines = ["# Raw Technical Setups", ""]
    for scan in setups:
        lines.append(
            f"- {scan.ticker}: {scan.setup_type}, score={scan.cleanliness_score}, "
            f"entry={scan.entry_zone}, stop={scan.stop_zone}, targets={scan.target_zone}, volume={scan.volume_context}"
        )
    lines.append("")
    return "\n".join(lines)
```
4. Run: `python -m pytest tradeloop/tests/data/test_snapshot.py -q` → **PASS**.
5. Commit: `git add tradeloop/lib/data/snapshot.py tradeloop/tests/data/test_snapshot.py && git commit -m "P3: snapshot freeze/hash + news_id + NO NEWS DATA renderer"`

---

### Task 8: Add `zerodha_historical` + token lookup to `src/mcp/zerodha.ts`

**Files:** modify `src/mcp/zerodha.ts`; test `tradeloop/tests/data/test_zerodha_historical.ts` is skipped (no TS test harness) — instead a Python contract fixture `tradeloop/tests/data/fixtures/kite_historical.json` documents the expected shape and Task 9's Python test asserts `kite.historical()` parses it.

**Decision (kite candles):** The project-local `src/mcp/zerodha.ts` is the sanctioned MCP (AGENTS.md keeps it project-local). It currently lacks historical candles. **Add** two tools rather than depending on the separately-connected `kite` MCP, so the whole price backbone flows through one audited, credential-contained server. Kite's historical API needs an `instrument_token`; add a token resolver that reads the instruments dump.

**Interfaces:** Produces MCP tools:
- `zerodha_instrument_token{exchange, tradingsymbol} -> {instrument_token: number}` (resolves via `GET /instruments/:exchange` CSV, cached in-process).
- `zerodha_historical{instrument_token, from_date, to_date, interval, continuous?, oi?} -> {candles:[{date,open,high,low,close,volume}]}` (calls `GET /instruments/historical/:token/:interval?from=&to=`).

1. Write the contract fixture `tradeloop/tests/data/fixtures/kite_historical.json`:
```json
{"candles": [["2026-06-30T00:00:00+0530", 1400.0, 1420.5, 1395.0, 1410.2, 1200000],
             ["2026-07-01T00:00:00+0530", 1410.0, 1440.0, 1405.0, 1435.7, 1500000]]}
```
(Kite returns candles as arrays `[date,o,h,l,c,v]` — this is the shape `kite.historical()` in Task 9 parses.)
2. Run (documents intent; no TS runner): `node --check src/mcp/zerodha.ts` → **FAIL if syntactically broken** after edit; before edit the tools are simply absent.
3. Implement — add to `src/mcp/zerodha.ts` before `const transport`:
```typescript
const instrumentTokenCache = new Map<string, number>();

server.registerTool(
  "zerodha_instrument_token",
  {
    title: "Resolve instrument token",
    description: "Resolve a Kite instrument_token for exchange+tradingsymbol (e.g. NSE + INFY).",
    inputSchema: {
      exchange: z.string().min(1),
      tradingsymbol: z.string().min(1)
    }
  },
  async ({ exchange, tradingsymbol }) => {
    const key = `${exchange}:${tradingsymbol}`;
    if (instrumentTokenCache.has(key)) {
      return textJson({ instrument_token: instrumentTokenCache.get(key) });
    }
    const { apiKey, accessToken } = requireCredentials();
    const resp = await fetch(buildUrl(`/instruments/${encodeURIComponent(exchange)}`), {
      headers: new Headers({ Authorization: `token ${apiKey}:${accessToken}`, "X-Kite-Version": "3" })
    });
    const csv = await resp.text();
    const rows = csv.split("\n");
    const header = rows[0].split(",");
    const tokIdx = header.indexOf("instrument_token");
    const symIdx = header.indexOf("tradingsymbol");
    for (const row of rows.slice(1)) {
      const cols = row.split(",");
      if (cols[symIdx] === tradingsymbol) {
        const token = Number(cols[tokIdx]);
        instrumentTokenCache.set(key, token);
        return textJson({ instrument_token: token });
      }
    }
    throw new Error(`instrument_token not found for ${key}`);
  }
);

server.registerTool(
  "zerodha_historical",
  {
    title: "Get Zerodha historical candles",
    description:
      "Fetch historical OHLCV candles for an instrument_token. Dates in 'YYYY-MM-DD HH:MM:SS'. interval one of minute/day/3minute/5minute/10minute/15minute/30minute/60minute.",
    inputSchema: {
      instrument_token: z.number().int().positive(),
      from_date: z.string().min(1),
      to_date: z.string().min(1),
      interval: z.enum(["minute", "day", "3minute", "5minute", "10minute", "15minute", "30minute", "60minute"]),
      continuous: z.boolean().default(false),
      oi: z.boolean().default(false)
    }
  },
  async ({ instrument_token, from_date, to_date, interval, continuous, oi }) => {
    const data = await kiteRequest<{ candles: unknown[] }>(
      `/instruments/historical/${instrument_token}/${interval}`,
      { query: { from: from_date, to: to_date, continuous: continuous ? 1 : 0, oi: oi ? 1 : 0 } }
    );
    return textJson(data);
  }
);
```
4. Run: `node --check src/mcp/zerodha.ts` → **PASS** (syntactically valid). (Runtime call is exercised only past live auth; Python side is fixture-tested in Task 9.)
5. Commit: `git add src/mcp/zerodha.ts tradeloop/tests/data/fixtures/kite_historical.json && git commit -m "P3: add zerodha_historical + instrument_token tools to project MCP"`

---

### Task 9: Kite MCP-over-stdio client (`data/kite.py`)

**Files:** create `tradeloop/lib/data/kite.py`; test `tradeloop/tests/data/test_kite.py`.

**Decision (transport):** The orchestrator is plain Python; it speaks MCP over stdio to `tsx src/mcp/zerodha.ts`. No `mcp` Python package is installed and it is not worth a new dep — a hand-rolled newline-delimited JSON-RPC over `subprocess` (initialize → tools/call) is ~1 file. `// ponytail: minimal stdio JSON-RPC client; swap to the official mcp python client only if we need notifications/streaming.` Tests inject a fake transport (a callable `_call_tool`), so no subprocess/network runs in CI.

**Interfaces:**
- Consumes: Task 8 tools (`zerodha_ltp`, `zerodha_ohlc`, `zerodha_instrument_token`, `zerodha_historical`).
- Produces (§6 signatures):
  - `@dataclass(frozen=True) Candle{date: str, open: float, high: float, low: float, close: float, volume: int}`
  - `class KiteClient` with `ltp(symbols: list[str]) -> dict[str, float]`, `ohlc(symbol: str) -> dict`, `historical(symbol: str, frm: date, to: date, interval: str) -> list[Candle]`, `close()`.
  - Module-level convenience `ltp/ohlc/historical` bound to a lazily-created default client (matches §6 `kite.ltp(...)`).

1. Write failing test `tradeloop/tests/data/test_kite.py`:
```python
import json
from datetime import date
from pathlib import Path

from tradeloop.lib.data.kite import KiteClient, Candle

FX = Path("tradeloop/tests/data/fixtures")


class FakeTransport:
    """Stand-in for the stdio MCP transport; maps tool name -> canned JSON result."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.responses[name]


def test_ltp_maps_symbol_to_price():
    ft = FakeTransport({"zerodha_ltp": {"NSE:INFY": {"last_price": 1500.5}}})
    kc = KiteClient(transport=ft)
    assert kc.ltp(["INFY"]) == {"INFY": 1500.5}
    assert ft.calls[0][0] == "zerodha_ltp"


def test_historical_resolves_token_then_parses_candles():
    hist = json.loads((FX / "kite_historical.json").read_text())
    ft = FakeTransport({
        "zerodha_instrument_token": {"instrument_token": 408065},
        "zerodha_historical": hist,
    })
    kc = KiteClient(transport=ft)
    candles = kc.historical("INFY", date(2026, 6, 30), date(2026, 7, 1), "day")
    assert candles and isinstance(candles[0], Candle)
    assert candles[0].close == 1410.2
    assert ("zerodha_instrument_token", {"exchange": "NSE", "tradingsymbol": "INFY"}) in [
        (n, a) for n, a in ft.calls
    ]
```
2. Run: `python -m pytest tradeloop/tests/data/test_kite.py -q` → **FAIL** (`ModuleNotFoundError`).
3. Implement `tradeloop/lib/data/kite.py`:
```python
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import date
from typing import List, Protocol


@dataclass(frozen=True)
class Candle:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class Transport(Protocol):
    def call_tool(self, name: str, arguments: dict) -> dict: ...


class StdioTransport:
    """Minimal MCP stdio JSON-RPC: spawn `tsx src/mcp/zerodha.ts`, initialize, tools/call.
    ponytail: newline-delimited JSON-RPC by hand; adopt the official mcp python client
    only if streaming/notifications are ever needed."""

    def __init__(self, command=("npm", "run", "-s", "mcp:zerodha")):
        self._proc = subprocess.Popen(
            list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1
        )
        self._id = 0
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "tradeloop", "version": "1.0"},
        })
        self._notify("notifications/initialized", {})

    def _rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError("kite MCP closed stdout")
            resp = json.loads(line)
            if resp.get("id") == self._id:
                if "error" in resp:
                    raise RuntimeError(f"kite MCP error: {resp['error']}")
                return resp["result"]

    def _notify(self, method: str, params: dict) -> None:
        self._proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
        self._proc.stdin.flush()

    def call_tool(self, name: str, arguments: dict) -> dict:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        # server returns {"content":[{"type":"text","text":"<json>"}]}
        text = result["content"][0]["text"]
        return json.loads(text)

    def close(self) -> None:
        try:
            self._proc.terminate()
        except Exception:
            pass


class KiteClient:
    def __init__(self, transport: "Transport | None" = None):
        self._transport = transport
        self._token_cache: dict = {}

    @property
    def transport(self) -> Transport:
        if self._transport is None:
            self._transport = StdioTransport()
        return self._transport

    def ltp(self, symbols: List[str]) -> dict:
        instruments = [f"NSE:{s.strip().upper()}" for s in symbols]
        raw = self.transport.call_tool("zerodha_ltp", {"instruments": instruments})
        out: dict = {}
        for s in symbols:
            key = f"NSE:{s.strip().upper()}"
            if key in raw and isinstance(raw[key], dict) and "last_price" in raw[key]:
                out[s.strip().upper()] = float(raw[key]["last_price"])
        return out

    def ohlc(self, symbol: str) -> dict:
        key = f"NSE:{symbol.strip().upper()}"
        raw = self.transport.call_tool("zerodha_ohlc", {"instruments": [key]})
        return raw.get(key, {})

    def _token(self, symbol: str) -> int:
        sym = symbol.strip().upper()
        if sym not in self._token_cache:
            res = self.transport.call_tool(
                "zerodha_instrument_token", {"exchange": "NSE", "tradingsymbol": sym}
            )
            self._token_cache[sym] = int(res["instrument_token"])
        return self._token_cache[sym]

    def historical(self, symbol: str, frm: date, to: date, interval: str) -> List[Candle]:
        token = self._token(symbol)
        res = self.transport.call_tool("zerodha_historical", {
            "instrument_token": token,
            "from_date": f"{frm.isoformat()} 00:00:00",
            "to_date": f"{to.isoformat()} 23:59:59",
            "interval": interval,
        })
        candles: List[Candle] = []
        for row in res.get("candles", []):
            candles.append(Candle(
                date=str(row[0]), open=float(row[1]), high=float(row[2]),
                low=float(row[3]), close=float(row[4]), volume=int(row[5]),
            ))
        return candles


_default: "KiteClient | None" = None


def _client() -> KiteClient:
    global _default
    if _default is None:
        _default = KiteClient()
    return _default


def ltp(symbols: List[str]) -> dict:
    return _client().ltp(symbols)


def ohlc(symbol: str) -> dict:
    return _client().ohlc(symbol)


def historical(symbol: str, frm: date, to: date, interval: str) -> List[Candle]:
    return _client().historical(symbol, frm, to, interval)
```
4. Run: `python -m pytest tradeloop/tests/data/test_kite.py -q` → **PASS**.
5. Commit: `git add tradeloop/lib/data/kite.py tradeloop/tests/data/test_kite.py && git commit -m "P3: Kite MCP stdio client (ltp/ohlc/historical) — drops yfinance for price"`

---

### Task 10: Wire the scanner to Kite; kill silent except; fix ATR fabrication

**Files:** modify `tradeloop/lib/ta/scanner.py`; test `tradeloop/tests/data/test_scanner.py`.

**Interfaces:**
- Consumes: `kite.historical()` + `Candle` (Task 9); `add_indicators` (existing); `TickerMaster.symbols()` (Task 3).
- Produces:
  - `candles_to_frame(candles: list[Candle]) -> pandas.DataFrame` (columns Open/High/Low/Close/Volume).
  - `scan_symbol(symbol, kite_client, as_of: date) -> SetupScan | None` (rewritten signature — takes a Kite client, drops `cache_dir`/yfinance).
  - `scan_universe(symbols, kite_client, as_of, max_fetch: int = 30) -> list[SetupScan]` — bounded scan; **re-raises** on unexpected errors after logging (no blanket silent `except`).
  - `render_setups` moves to `snapshot.py` (Task 7); scanner imports it back for backward-compat re-export.

**Map fixes applied:** (a) `scanner.py:33` fabricated ATR as `latest * 0.02` when `ATR14` was empty — now if ATR is unavailable the setup is **skipped** (no fabricated stop). (b) `scanner.py:60-63` swallowed every exception silently — now only `LookupError`/`ValueError`/Kite `RuntimeError` for a single symbol are caught-and-logged; anything else propagates.

1. Write failing test `tradeloop/tests/data/test_scanner.py`:
```python
from datetime import date

import pandas as pd
import pytest

from tradeloop.lib.data.kite import Candle
from tradeloop.lib.ta import scanner


class OneSymbolKite:
    def __init__(self, candles):
        self._candles = candles

    def historical(self, symbol, frm, to, interval):
        return self._candles


def _uptrend_candles(n=60):
    out = []
    base = 100.0
    for i in range(n):
        o = base + i
        out.append(Candle(f"2026-0{1 + i % 9}-01T00:00:00+0530", o, o + 3, o - 1, o + 2, 1000 + i))
    return out


def test_scan_symbol_skips_when_too_few_candles():
    kc = OneSymbolKite(_uptrend_candles(10))
    assert scanner.scan_symbol("INFY", kc, date(2026, 7, 1)) is None


def test_scan_symbol_uses_real_atr_no_fabrication():
    kc = OneSymbolKite(_uptrend_candles(60))
    scan = scanner.scan_symbol("INFY", kc, date(2026, 7, 1))
    # a clean uptrend yields a breakout setup with a stop derived from real ATR (< entry).
    assert scan is not None
    assert float(scan.stop_zone) < float(scan.entry_zone)


def test_scan_universe_bounded_by_max_fetch():
    kc = OneSymbolKite(_uptrend_candles(60))
    scans = scanner.scan_universe(["A", "B", "C", "D"], kc, date(2026, 7, 1), max_fetch=2)
    assert len(scans) <= 2


def test_scan_universe_reraises_unexpected():
    class Boom:
        def historical(self, *a, **k):
            raise KeyError("unexpected internal bug")

    with pytest.raises(KeyError):
        scanner.scan_universe(["A"], Boom(), date(2026, 7, 1), max_fetch=5)
```
2. Run: `python -m pytest tradeloop/tests/data/test_scanner.py -q` → **FAIL** (old `scan_symbol` signature / yfinance path).
3. Implement — rewrite `tradeloop/lib/ta/scanner.py`:
```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, List

import pandas as pd

from tradeloop.lib.data.kite import Candle
from tradeloop.lib.ta.indicators import add_indicators
from tradeloop.lib.ta.patterns import breakout, pullback, volume_spike

log = logging.getLogger("tradeloop.scanner")


@dataclass(frozen=True)
class SetupScan:
    ticker: str
    setup_type: str
    cleanliness_score: float
    entry_zone: str
    stop_zone: str
    target_zone: str
    volume_context: str


def candles_to_frame(candles: List[Candle]) -> pd.DataFrame:
    return pd.DataFrame({
        "Open": [c.open for c in candles],
        "High": [c.high for c in candles],
        "Low": [c.low for c in candles],
        "Close": [c.close for c in candles],
        "Volume": [c.volume for c in candles],
    })


def scan_symbol(symbol: str, kite_client, as_of: date) -> "SetupScan | None":
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
        return None  # no fabricated stop — a setup without a real ATR is not tradeable
    atr_value = float(atr_series.iloc[-1])
    latest = closes[-1]
    breakout_signal = breakout(closes, 20)
    pullback_signal = pullback(closes, ema20)
    volume_signal = volume_spike(volumes, 20) if volumes else None
    setup_type = ""
    score = 0.0
    if breakout_signal.bullish:
        setup_type = "20d_breakout"
        score += 6
    if pullback_signal.bullish:
        setup_type = setup_type or "ema20_pullback"
        score += 4
    if volume_signal and volume_signal.bullish:
        score += 2
    if score <= 0:
        return None
    return SetupScan(
        ticker=symbol.strip().upper(),
        setup_type=setup_type,
        cleanliness_score=round(min(score, 10), 2),
        entry_zone=f"{latest:.2f}",
        stop_zone=f"{latest - (1.5 * atr_value):.2f}",
        target_zone=f"{latest + (2.0 * atr_value):.2f}/{latest + (3.0 * atr_value):.2f}",
        volume_context=volume_signal.reason if volume_signal else "volume_unavailable",
    )


# expected, per-symbol data problems we tolerate; anything else is a real bug and propagates.
_TOLERATED = (LookupError, ValueError, RuntimeError)


def scan_universe(symbols: Iterable[str], kite_client, as_of: date, max_fetch: int = 30) -> List["SetupScan"]:
    scans: List[SetupScan] = []
    for symbol in list(symbols)[:max_fetch]:
        try:
            scan = scan_symbol(symbol, kite_client, as_of)
        except _TOLERATED as exc:
            log.warning("scan skipped %s: %s", symbol, exc)
            continue
        if scan is not None:
            scans.append(scan)
    scans.sort(key=lambda item: item.cleanliness_score, reverse=True)
    return scans


from tradeloop.lib.data.snapshot import render_setups  # noqa: E402  backward-compat re-export
```
4. Run: `python -m pytest tradeloop/tests/data/test_scanner.py -q` → **PASS**.
5. Commit: `git add tradeloop/lib/ta/scanner.py tradeloop/tests/data/test_scanner.py && git commit -m "P3: wire scanner to Kite candles; kill silent except; drop fabricated ATR"`

---

### Task 11: Ingest orchestrator (`data/ingest.py`)

**Files:** create `tradeloop/lib/data/ingest.py`; test `tradeloop/tests/data/test_ingest.py`.

**Interfaces:**
- Consumes: `Http` (T2), `TickerMaster`/`load_master` (T3), `extract` (T4), source `fetch_*` (T6), `freeze`/`render_news_raw`/`render_setups`/`Snapshot` (T7), `scan_universe` + Kite client (T9/T10), `sentiment.score` (T5).
- Produces (§6 `ingest.run(as_of, symbols, max_fetch) -> Snapshot`):
  - `run(as_of: datetime, symbols: list[str], max_fetch: int, run_dir: Path, *, http: Http | None = None, kite_client=None, master: TickerMaster | None = None, config_dir: Path = Path("tradeloop/config")) -> Snapshot`
  - Behavior: sequential + throttled (one source at a time, `Http` retry handles backoff); pre-filtered bounded scan (`symbols[:max_fetch]`); degrade-not-abort — if **every** news source yields nothing, `news_available=False` and the rendered `01_news_raw.md` carries `NO NEWS DATA`; writes `run_dir/01_news_raw.md`, `02_setups_raw.md`, and freezes the snapshot.

1. Write failing test `tradeloop/tests/data/test_ingest.py`:
```python
from datetime import date, datetime
from pathlib import Path

from tradeloop.lib.data import ingest
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.ticker_master import load_master

TM = load_master(Path("tradeloop/config/universe.yaml"))


class NoKite:
    def historical(self, *a, **k):
        return []


def test_run_with_news_freezes_and_renders(tmp_path, monkeypatch):
    def fake_news(http, master, cfg):
        stories = [RawItem("nid000000001", "Reliance posts record profit",
                           "http://x", "google_news_generic", "tier_C", "2026-07-02")]
        return stories, []  # (all_items, macro_items)

    monkeypatch.setattr(ingest, "_collect_news", fake_news)
    snap = ingest.run(datetime(2026, 7, 2), TM.symbols(), max_fetch=5, run_dir=tmp_path,
                      kite_client=NoKite(), master=TM)
    assert snap.news_available is True
    assert "nid000000001" in snap.news_ids
    body = (tmp_path / "01_news_raw.md").read_text()
    assert "RELIANCE" in body
    assert (tmp_path / "snapshot" / "snapshot_hash.txt").exists()


def test_run_total_news_failure_is_loud_not_blank(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "_collect_news", lambda http, master, cfg: ([], []))
    snap = ingest.run(datetime(2026, 7, 2), TM.symbols(), max_fetch=5, run_dir=tmp_path,
                      kite_client=NoKite(), master=TM)
    assert snap.news_available is False
    assert "NO NEWS DATA" in (tmp_path / "01_news_raw.md").read_text()
```
2. Run: `python -m pytest tradeloop/tests/data/test_ingest.py -q` → **FAIL** (`ModuleNotFoundError`).
3. Implement `tradeloop/lib/data/ingest.py`:
```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import yaml

from tradeloop.lib.data.http import Http
from tradeloop.lib.data.snapshot import Snapshot, freeze, render_news_raw, render_setups
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.sources.google_news import fetch_google_news
from tradeloop.lib.data.sources.nse_bse import fetch_nse_bse
from tradeloop.lib.data.sources.reddit import fetch_reddit
from tradeloop.lib.data.sources.rss_native import fetch_rss
from tradeloop.lib.data.ticker_master import TickerMaster, load_master
from tradeloop.lib.data.tickers import extract
from tradeloop.lib.ta.scanner import scan_universe

MACRO_TERMS = {"RBI", "INR", "RUPEE", "OIL", "FED", "FII", "DII", "INFLATION", "GDP"}
_NSE_WARMUP = ("www.nseindia.com", "www.bseindia.com", "nsearchives.nseindia.com")


def _collect_news(http: Http, master: TickerMaster, cfg: dict) -> Tuple[List[RawItem], List[RawItem]]:
    """Sequential, throttled fetch across all four source families. Returns (all_items, macro_items)."""
    items: List[RawItem] = []
    feeds = (cfg.get("feeds") or {})
    tiers = (cfg.get("tiers") or {})
    for source_id, url in feeds.items():
        items += fetch_rss(http, url, source=source_id, tier=tiers.get(source_id, "tier_B"))
    items += fetch_nse_bse(http)
    for symbol in master.symbols():
        items += fetch_google_news(http, symbol, limit=5)
    items += fetch_reddit(http, ["IndianStreetBets", "IndiaInvestments"])
    macro = [i for i in items if any(t in i.title.upper() for t in MACRO_TERMS)]
    return items, macro


def run(as_of: datetime, symbols: List[str], max_fetch: int, run_dir: Path, *,
        http: "Http | None" = None, kite_client=None, master: "TickerMaster | None" = None,
        config_dir: Path = Path("tradeloop/config")) -> Snapshot:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    if master is None:
        master = load_master(config_dir / "universe.yaml")
    if http is None:
        http = Http(warmup_hosts=_NSE_WARMUP)
    cfg_path = config_dir / "news_sources.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}

    all_items, macro = _collect_news(http, master, cfg)
    news_available = bool(all_items)
    stories = extract(all_items, master)  # word-boundary tagging (+ news_id already minted)

    setups = []
    if kite_client is not None:
        setups = scan_universe(symbols[:max_fetch], kite_client, as_of.date(), max_fetch=max_fetch)

    (run_dir / "01_news_raw.md").write_text(
        render_news_raw(stories, macro, news_available), encoding="utf-8")
    (run_dir / "02_setups_raw.md").write_text(render_setups(setups), encoding="utf-8")

    _snap_dir, snapshot_hash = freeze(stories, macro, setups, run_dir)
    news_ids = {s.news_id for s in stories} | {m.news_id for m in macro}
    return Snapshot(run_dir=run_dir, snapshot_hash=snapshot_hash, news_ids=news_ids,
                    stories=stories, macro=macro, setups=setups, news_available=news_available)
```
4. Run: `python -m pytest tradeloop/tests/data/test_ingest.py -q` → **PASS**.
5. Commit: `git add tradeloop/lib/data/ingest.py tradeloop/tests/data/test_ingest.py && git commit -m "P3: ingest orchestrator (throttled, bounded, degrade-not-abort)"`

---

### Task 12: Evidence-trailer validator (`data/evidence.py`)

**Files:** create `tradeloop/lib/data/evidence.py`; test `tradeloop/tests/data/test_evidence.py`.

**Design decision (P1 seam):** P1's stage schemas do not exist yet, so this validator works against the *stored* stage outputs generically: it scans the run dir's JSON artifacts (any `*.json` a stage writes) for an `evidence` array of `news_id` strings, and rejects the cycle if any cited id is not in the snapshot's `news_ids`. When P1 lands typed schemas with an `evidence: list[str]` field, they serialize exactly this shape, so no rework. `// ponytail: scans json artifacts for an 'evidence' list; P1's typed evidence field serializes to the same shape.`

**Interfaces:**
- Consumes: `Snapshot.news_ids` (T7/T11).
- Produces:
  - `@dataclass EvidenceResult{ok: bool, missing: list[tuple[str,str]]}` (list of `(artifact_name, bad_news_id)`).
  - `collect_cited_ids(run_dir: Path) -> dict[str, list[str]]` (artifact → cited ids).
  - `validate_evidence(run_dir: Path, snapshot: Snapshot) -> EvidenceResult` — `ok=False` if any cited id ∉ `snapshot.news_ids`.

1. Write failing test `tradeloop/tests/data/test_evidence.py`:
```python
import json
from pathlib import Path

from tradeloop.lib.data.evidence import validate_evidence
from tradeloop.lib.data.snapshot import Snapshot


def _snap(ids):
    return Snapshot(run_dir=Path("."), snapshot_hash="x", news_ids=set(ids))


def test_all_cited_ids_present_passes(tmp_path):
    (tmp_path / "20_bull.json").write_text(json.dumps(
        {"claims": [{"text": "strong", "evidence": ["aaaaaaaaaaaa"]}]}))
    res = validate_evidence(tmp_path, _snap({"aaaaaaaaaaaa", "bbbbbbbbbbbb"}))
    assert res.ok is True and res.missing == []


def test_missing_cited_id_rejected(tmp_path):
    (tmp_path / "20_bull.json").write_text(json.dumps(
        {"evidence": ["ffffffffffff"]}))
    res = validate_evidence(tmp_path, _snap({"aaaaaaaaaaaa"}))
    assert res.ok is False
    assert ("20_bull.json", "ffffffffffff") in res.missing


def test_no_evidence_arrays_is_ok(tmp_path):
    (tmp_path / "10_news.json").write_text(json.dumps({"names": ["RELIANCE"]}))
    assert validate_evidence(tmp_path, _snap(set())).ok is True
```
2. Run: `python -m pytest tradeloop/tests/data/test_evidence.py -q` → **FAIL** (`ModuleNotFoundError`).
3. Implement `tradeloop/lib/data/evidence.py`:
```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from tradeloop.lib.data.snapshot import Snapshot


@dataclass
class EvidenceResult:
    ok: bool
    missing: List[Tuple[str, str]] = field(default_factory=list)


def _walk_evidence(node) -> List[str]:
    found: List[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "evidence" and isinstance(value, list):
                found += [v for v in value if isinstance(v, str)]
            else:
                found += _walk_evidence(value)
    elif isinstance(node, list):
        for item in node:
            found += _walk_evidence(item)
    return found


def collect_cited_ids(run_dir: Path) -> Dict[str, List[str]]:
    cited: Dict[str, List[str]] = {}
    for path in sorted(Path(run_dir).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        ids = _walk_evidence(data)
        if ids:
            cited[path.name] = ids
    return cited


def validate_evidence(run_dir: Path, snapshot: Snapshot) -> EvidenceResult:
    missing: List[Tuple[str, str]] = []
    for artifact, ids in collect_cited_ids(run_dir).items():
        for nid in ids:
            if nid not in snapshot.news_ids:
                missing.append((artifact, nid))
    return EvidenceResult(ok=not missing, missing=missing)
```
4. Run: `python -m pytest tradeloop/tests/data/test_evidence.py -q` → **PASS**.
5. Commit: `git add tradeloop/lib/data/evidence.py tradeloop/tests/data/test_evidence.py && git commit -m "P3: evidence-trailer validator (reject news_id not in snapshot)"`

---

### Task 13: Wire real ingest behind `prepare_cycle.py`

**Files:** modify `tradeloop/scripts/prepare_cycle.py`; test `tradeloop/tests/data/test_prepare_cycle_wired.py`.

**Interfaces:**
- Consumes: `ingest.run` (T11).
- Replaces `prepare_cycle.py:43-44` (`render_news_raw(NewsExtraction())` / `render_setups([])`) with a real `ingest.run(...)` call that writes `01_news_raw.md` / `02_setups_raw.md` and freezes the snapshot. On any ingest exception, degrade-not-abort: write a `NO NEWS DATA` news artifact and empty setups, never crash the cycle scaffold. The `NewsExtraction`/`empty renderer` imports are dropped.

1. Write failing test `tradeloop/tests/data/test_prepare_cycle_wired.py`:
```python
import sys
from pathlib import Path

from tradeloop.scripts import prepare_cycle


def test_prepare_calls_ingest(monkeypatch, tmp_path):
    called = {}

    def fake_run(as_of, symbols, max_fetch, run_dir, **kw):
        called["run_dir"] = Path(run_dir)
        (Path(run_dir) / "01_news_raw.md").write_text("# Raw News\n\n### RELIANCE\n- [nid] hit\n")
        (Path(run_dir) / "02_setups_raw.md").write_text("# Raw Technical Setups\n")
        from tradeloop.lib.data.snapshot import Snapshot
        return Snapshot(run_dir=Path(run_dir), snapshot_hash="h", news_ids={"nid"}, news_available=True)

    monkeypatch.setattr(prepare_cycle, "ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text("capital:\n  paper_starting_inr: 100000\n")
    monkeypatch.setattr(prepare_cycle, "ingest_run", fake_run)
    # stub context rendering that reads settings/memory so the test is hermetic
    monkeypatch.setattr(prepare_cycle, "empty_state_from_settings", lambda p: object())
    monkeypatch.setattr(prepare_cycle, "render_context", lambda s, m, mac: "# Context\n")

    run_dir = prepare_cycle.prepare("premarket")
    assert "RELIANCE" in (run_dir / "01_news_raw.md").read_text()
    assert called["run_dir"] == run_dir
```
2. Run: `python -m pytest tradeloop/tests/data/test_prepare_cycle_wired.py -q` → **FAIL** (`AttributeError: module ... has no attribute 'ingest_run'`).
3. Implement — edit `tradeloop/scripts/prepare_cycle.py`:
- Replace the news/scanner imports:
```python
from tradeloop.lib.data.ingest import run as ingest_run
from tradeloop.lib.data.snapshot import render_news_raw, render_setups
from tradeloop.lib.portfolio.state import empty_state_from_settings, render_context
from tradeloop.lib.util.ist_clock import IST
```
(Remove the `NewsExtraction, render_news_raw` import from `news_to_tickers` and the `render_setups` import from `scanner`; drop the unused `import yaml`.)
- Replace lines 41-44 with:
```python
    # Real research ingest: fetch news + Kite setups, tag, freeze the hashed snapshot,
    # and render 01_news_raw / 02_setups_raw. Degrade-not-abort on total failure.
    symbols = [s.symbol for s in __import__(
        "tradeloop.lib.data.ticker_master", fromlist=["load_master"]
    ).load_master(ROOT / "config" / "universe.yaml").records]
    try:
        ingest_run(now, symbols, max_fetch=30, run_dir=run_dir)
    except Exception as exc:  # never leave the cycle with a silent blank
        (run_dir / "01_news_raw.md").write_text(
            render_news_raw([], [], news_available=False), encoding="utf-8")
        (run_dir / "02_setups_raw.md").write_text(render_setups([]), encoding="utf-8")
        (run_dir / "ingest_error.txt").write_text(f"ingest failed: {exc}\n", encoding="utf-8")
```
(`ingest_run` writes the two artifacts itself on success; the `except` branch guarantees they exist even on failure.)
4. Run: `python -m pytest tradeloop/tests/data/test_prepare_cycle_wired.py -q` → **PASS**.
5. Commit: `git add tradeloop/scripts/prepare_cycle.py tradeloop/tests/data/test_prepare_cycle_wired.py && git commit -m "P3: wire real ingest behind prepare_cycle (replace empty renderers)"`

---

### Task 14: Retire dead stubs; delete `et_markets_rss`; full-suite green

**Files:** delete `tradeloop/lib/data/et_markets_rss.py`, `moneycontrol_rss.py`, `corp_announcements.py`, `reddit_sentiment.py`; update `tradeloop/lib/data/news_to_tickers.py` to re-export the new `TaggedStory`/renderer for any lingering importer; final full-suite run.

**Interfaces:** Produces: nothing new. Removes duplicate/stub modules the map marked `delete`/`rewrite` now superseded (`et_markets_rss` = dup of google news; `moneycontrol_rss`/`corp_announcements` = empty stubs replaced by `sources/rss_native.py` + `sources/nse_bse.py`; `reddit_sentiment` toy scorer replaced by `sources/reddit.py` + `data/sentiment.py`).

1. Write failing test `tradeloop/tests/data/test_no_dead_stubs.py`:
```python
import importlib

import pytest


@pytest.mark.parametrize("mod", [
    "tradeloop.lib.data.et_markets_rss",
    "tradeloop.lib.data.moneycontrol_rss",
    "tradeloop.lib.data.corp_announcements",
    "tradeloop.lib.data.reddit_sentiment",
])
def test_dead_stub_removed(mod):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(mod)
```
2. Run: `python -m pytest tradeloop/tests/data/test_no_dead_stubs.py -q` → **FAIL** (modules still import).
3. Implement:
- `git rm tradeloop/lib/data/et_markets_rss.py tradeloop/lib/data/moneycontrol_rss.py tradeloop/lib/data/corp_announcements.py tradeloop/lib/data/reddit_sentiment.py`
- Grep for stragglers: `grep -rn "et_markets_rss\|moneycontrol_rss\|corp_announcements\|reddit_sentiment" tradeloop src` — expected: only the deletion test. If `news_to_tickers` is imported elsewhere for `TaggedStory`, leave the module (its `render_news_raw`/`NewsExtraction` are no longer used by `prepare_cycle` after Task 13, but the module stays importable to avoid breaking test_news_to_tickers). No code change needed if grep is clean.
4. Run: `python -m pytest tradeloop/tests/data/test_no_dead_stubs.py -q` → **PASS**; then full suite `python -m pytest tradeloop/tests -q` → **PASS**.
5. Commit: `git add -A && git commit -m "P3: delete dead news stubs superseded by real sources"`

---

## Self-review

**Spec / DoD coverage (Phase 3 = DoD #1 + second half of #3):**
- **DoD #1 (inputs real & auditable):** Kite price backbone (`kite.py` ltp/ohlc/historical via the project MCP + new `zerodha_historical` tool — Tasks 8-9); four real news sources (Task 6); word-boundary tagging (Task 4, fixes `news_to_tickers.py:45-46`); frozen hashed snapshot with `news_id` (Task 7); scanner wired to Kite, silent-except killed, ATR fabrication removed (Task 10); ingest degrade-not-abort with a loud `NO NEWS DATA` artifact (Tasks 11, 13). yfinance dropped from the live price path (scanner now uses Kite).
- **DoD #3 second half (evidence checked against snapshot):** `evidence.py` validator rejects any cited `news_id` not in the cycle snapshot (Task 12), keyed on the `news_id` minted at fetch time.
- **§6 interface fidelity:** `kite.ltp/ohlc/historical`, `ingest.run(as_of, symbols, max_fetch) -> Snapshot`, `snapshot.freeze(...) -> (Path, str)`, `tickers.extract(items, master) -> list[TaggedStory]`, `news_id(guid, url, title) -> sha256(guid|url|title)[:12]` — all match §6 verbatim. `ingest.run` adds keyword-only injection params (`http`, `kite_client`, `master`, `run_dir`) for testability without changing the positional §6 signature.
- **Constraints preserved:** research-only phase emits no orders; scanner setups are long-biased (breakout/pullback, never shorts); Kite reads are paper-safe (read-only); credentials stay inside `src/mcp/zerodha.ts` (Python client never reads `.env`); AGENTS.md honored (no `.env` access anywhere in the plan).

**Placeholder scan:** No "TBD" / "similar to Task N" / "add error handling later". Every module ships complete real code and a real pytest. Every referenced type is defined in-plan: `Http`/`HttpResponse` (T2), `TickerMaster` (T3), `RawItem` (T4 via `sources/__init__`), `TaggedStory` (T4), `SentimentScore`→`score/label` (T5), source `fetch_*` (T6), `news_id`/`Snapshot`/`freeze`/renderers (T7), `Candle`/`KiteClient` (T9), `SetupScan`/`scan_universe` (T10), `EvidenceResult`/`validate_evidence` (T12). External types (`add_indicators`, `breakout`/`pullback`/`volume_spike`, `empty_state_from_settings`, `render_context`) are existing keep-modules.

**Type-consistency notes:** (a) `RawItem` is defined once in `sources/__init__.py` and imported by `tickers.py`, all sources, `snapshot.py`, `ingest.py` — no duplicate definition. (b) `news_id` lives in `snapshot.py`; sources import it (snapshot has no source import → no cycle). (c) `render_setups`/`render_news_raw` live in `snapshot.py`; `scanner.py` re-exports `render_setups` for backward compat; `prepare_cycle` imports both from `snapshot`. (d) `scan_symbol`/`scan_universe` changed signature (Kite client + `as_of` instead of `cache_dir`) — the only caller is `ingest.run`, updated in the same phase; the old yfinance `fetch_ohlcv` path is no longer referenced by the scanner (Task 10). (e) `Snapshot.news_ids` is a `set[str]`; `evidence.validate_evidence` membership-checks against it. (f) The evidence validator is schema-agnostic (walks any `evidence: [str]` array) so it composes with P1's typed stage outputs without rework.
