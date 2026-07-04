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
