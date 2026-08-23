from __future__ import annotations

import json
from dataclasses import asdict
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
from tradeloop.lib.data.universe import load_universe
from tradeloop.lib.ta.scanner import scan_universe

MACRO_TERMS = {"RBI", "INR", "RUPEE", "OIL", "FED", "FII", "DII", "INFLATION", "GDP"}
# overflow-only tiebreak weight (added to a 0-10 chart score) when the scan exceeds the
# prompt-size ceiling; the real selection is the aggregate shortlister, not this.
NEWS_WEIGHT = 2.0
_NSE_WARMUP = ("www.nseindia.com", "www.bseindia.com", "nsearchives.nseindia.com")


def _write_source_health(root: Path, sources: set, as_of) -> None:
    """Best-effort: stamp each source that produced items this cycle with as_of,
    MERGING over prior successes so a source that fails today keeps its last-good
    timestamp and only ages to 'stale' after the health check's max_age window.
    A source that returns 0 items (down OR genuinely quiet) is not re-stamped -
    a known limitation (success == produced items)."""
    path = Path(root) / "reports" / "source_health.json"
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(existing, dict):
            existing = {}
    except (ValueError, OSError):
        existing = {}
    stamp = as_of.isoformat()
    for src in sources:
        existing[src] = stamp
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


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


def run(as_of: datetime, symbols: "list[str] | None" = None, max_fetch: int = 2500,
        run_dir: Path = None, *, http=None, kite_client=None,
        master: "TickerMaster | None" = None, config_dir: Path = Path("tradeloop/config"),
        max_setups_downstream: "int | None" = None,
        source_health_root: "Path | None" = None) -> Snapshot:
    assert run_dir is not None, "ingest.run requires run_dir"
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    if master is None:
        master = load_master(config_dir / "universe.yaml")
    if http is None:
        http = Http(warmup_hosts=_NSE_WARMUP)
    cfg_path = config_dir / "news_sources.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    settings_path = config_dir / "settings.yaml"
    uni = ((yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}).get("universe", {})
           if settings_path.exists() else {})
    min_turnover = float(uni.get("min_avg_daily_turnover_cr", 0)) * 1_00_00_000  # cr -> INR
    min_stop = float(uni.get("min_stop_distance_pct", 0)) / 100.0  # pct -> fraction
    pace = float(uni.get("pace_seconds", 0.0))
    cfg_cap = uni.get("max_setups_downstream", 25)          # may be None (null) = uncapped
    top_n = max_setups_downstream if max_setups_downstream is not None else cfg_cap

    all_items, macro = _collect_news(http, master, cfg)
    if source_health_root is not None:
        _write_source_health(source_health_root, {i.source for i in all_items}, as_of)
    news_available = bool(all_items)
    stories = extract(all_items, master)  # word-boundary tagging (+ news_id already minted)

    setups = []
    if kite_client is not None:
        if symbols is None and str(uni.get("source", "config_yaml")) == "full_nse":
            symbols = load_universe(kite_client, config_dir / "universe_cache.json",
                                    config_dir / "universe.yaml",
                                    max_age_days=int(uni.get("cache_days", 7)),
                                    max_symbols=int(uni.get("max_symbols", 2500)),
                                    now=as_of.date())
        elif symbols is None:
            symbols = master.symbols()
        setups = scan_universe(symbols[:max_fetch], kite_client, as_of.date(),
                               max_fetch=max_fetch, min_turnover_inr=min_turnover,
                               pace_seconds=pace, min_stop_pct=min_stop,
                               config_dir=config_dir)

    # full ranked scan to disk (audit + dashboard)
    (run_dir / "full_scan.jsonl").write_text(
        "".join(json.dumps(asdict(s)) + "\n" for s in setups), encoding="utf-8")
    # Selection is AGGREGATE: the whole tradeable set flows to the analysts, and the
    # shortlister (14_shortlist) ranks it on EVERYTHING - news + mood + health + charts.
    # top_n is only a prompt-size safety ceiling, set generous so it rarely bites; when
    # the scan does exceed it, order the overflow by a blend of chart quality + news
    # catalyst (news is a weighted factor, never an override, never market cap).
    news_tickers = {s.ticker.strip().upper() for s in stories}
    setups.sort(
        key=lambda s: s.cleanliness_score + (NEWS_WEIGHT if s.ticker.strip().upper() in news_tickers else 0.0),
        reverse=True)
    if top_n:  # None or 0 -> analyze the full tradeable scan (no pre-truncation)
        setups = setups[:top_n]

    (run_dir / "01_news_raw.md").write_text(
        render_news_raw(stories, macro, news_available), encoding="utf-8")
    (run_dir / "02_setups_raw.md").write_text(render_setups(setups), encoding="utf-8")

    _snap_dir, snapshot_hash = freeze(stories, macro, setups, run_dir)
    news_ids = {s.news_id for s in stories} | {m.news_id for m in macro}
    return Snapshot(run_dir=run_dir, snapshot_hash=snapshot_hash, news_ids=news_ids,
                    stories=stories, macro=macro, setups=setups, news_available=news_available)
