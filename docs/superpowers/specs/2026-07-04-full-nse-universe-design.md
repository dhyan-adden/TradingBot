# Full-NSE Scan Universe - Design Spec

Date: 2026-07-04

## Problem

The daily chart scan only covers a hardcoded 6-symbol `universe.yaml` (RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK, SBIN).
The news/shortlister stages, by contrast, reason freely over the whole market and surface names like DLF, APOLLOHOSP, INFY - none of which the scan has price data for.
So the technical/trader stages find "no clean setups" for those names and the cycle holds.
The two lists must be reconciled: the scan must cover the real Indian cash-equity universe so the trader has real candles (entry/stop/target) for the names the research surfaces.

## Decision (user-approved)

- **Coverage:** the full NSE cash-equity universe (~1,800 stocks), pulled live from Zerodha.
- **Liquidity floor:** scan everything but auto-skip stocks below a configurable average daily traded value (default Rs 5 crore/day) - avoids manipulation-prone micro-caps that cannot be safely exited.
- **Downstream cost cap:** the full ranked scan is saved to disk (audit + dashboard), but only the top N setups (default 25) feed the AI reasoning stages, to bound daily token cost. The cap is **news/research-first**: a stock with a real news catalyst outranks a merely-clean chart (chart cleanliness breaks ties within each group), so catalysts are never cut before the trader sees them. Never market cap.

## Architecture

Five small units, each independently testable:

1. **`zerodha_instruments` MCP tool** (`src/mcp/zerodha.ts`): one call returns every NSE `EQ` instrument as `[{tradingsymbol, instrument_token}]`. Today `zerodha_instrument_token` downloads the whole `/instruments/NSE` CSV to resolve ONE symbol; scanning 1,800 that way would re-download the CSV 1,800 times. This tool downloads it once.

2. **`KiteClient.instruments(exchange)`** (`tradeloop/lib/data/kite.py`): calls the tool, returns `{SYMBOL: token}`, and seeds the per-symbol token cache so subsequent `historical()` calls need no extra lookups.

3. **`universe.py`** (`tradeloop/lib/data/universe.py`): `load_universe(kite_client, cache_path, max_age_days=7)` returns the symbol list. Reads a JSON cache when fresh; otherwise pulls from Kite and rewrites the cache (the instrument list barely changes - weekly refresh). Falls back to `universe.yaml` symbols when Kite is unavailable, so the pipeline degrades rather than crashes.

4. **Scanner throughput + liquidity** (`tradeloop/lib/ta/scanner.py`):
   - `scan_symbol` computes average daily turnover (mean of `close*volume` over the lookback) and returns `None` when it is below the floor - the setup is dropped as untradeable. Uses candles already fetched; no extra API calls.
   - `scan_universe` paces historical calls (Kite caps ~3 req/s) via an injectable sleeper (`pace_seconds`, 0 in tests), logs progress, and continues past per-symbol errors (already the behavior). It already returns setups sorted by cleanliness descending.

5. **Ingest wiring** (`tradeloop/lib/data/ingest.py`): lift the `max_fetch=30` cap, source symbols from `load_universe`, save the full ranked scan to `full_scan.jsonl` (audit/dashboard), and pass only the top `max_setups_downstream` setups to `render_setups` + `freeze` (so grounding + trader see exactly the tradeable slice).

## Config (settings.yaml, new `scan:` block)

```yaml
scan:
  universe: full_nse            # full_nse | config_yaml
  universe_cache_days: 7
  min_daily_turnover_inr: 50000000   # Rs 5 crore liquidity floor; 0 disables
  pace_seconds: 0.34            # ~3 req/s to respect Kite rate limits
  max_symbols: 2500             # hard safety ceiling on symbols scanned
  max_setups_downstream: 25     # cleanest-N setups fed to the AI stages
```

All thresholds are config values, changeable without code edits.

## Data flow

`load_universe(kite)` -> ~1,800 symbols -> `scan_universe` (paced, liquidity-filtered, per-symbol tolerant) -> full ranked setups.
Full list -> `full_scan.jsonl` (disk).
Top 25 (news-catalyst setups first, then cleanest charts) -> `02_setups_raw.md` + frozen snapshot -> technical/trader stages -> grounding gate.

## Error handling

- Kite unavailable / stale token: `load_universe` falls back to `universe.yaml`; `scan_universe` degrades per symbol; scan may be empty -> loud "no setups" (existing behavior), never a crash.
- Rate-limit (429) on a symbol: tolerated like any per-symbol error; pacing makes it rare.
- Cache file missing/corrupt: treated as stale -> refetch.

## Testing

- MCP tool: verified against a live Kite call (TS is outside pytest); parse logic covered by the Python client test with a fake transport.
- `kite.instruments`: fake transport returns a small instrument list -> assert `{symbol: token}` map + token cache seeded.
- `universe.load_universe`: fresh cache read, stale-cache refetch, Kite-down fallback to yaml.
- scanner: liquidity floor drops a low-turnover symbol; pacing sleeper invoked once per symbol; ranking preserved.
- ingest: top-N cap feeds only N downstream while `full_scan.jsonl` holds all; universe loader used.
- E2E live smoke: real scan over a liquid subset confirms real setups reach `02_setups_raw.md`; full suite green under `-W error`.

## Out of scope (v1)

- Sector/industry metadata for 1,800 names (the scan needs only symbol + token; the rich `universe.yaml` metadata stays for the 6 seed names / context only).
- Intraday or F&O instruments (cash equity `EQ` only).
- Parallel/concurrent fetching (paced sequential is within the 10-15 min morning budget and simplest to keep within rate limits).
- ETF exclusion (EQ ETFs pass through; they are liquid and tradeable - revisit only if unwanted names appear).
