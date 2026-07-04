"""Opt-in LIVE smoke: exercises the real Kite path end to end.

Skipped by default (no network in CI, needs a fresh daily Zerodha token).
Enable with:  ZERODHA_LIVE_SMOKE=true  (plus a valid ZERODHA_ACCESS_TOKEN for the day)

Run: ZERODHA_LIVE_SMOKE=true /Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python \
        -m pytest tradeloop/tests/data/test_ingest_universe_smoke.py -q -s
"""
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("ZERODHA_LIVE_SMOKE", "").strip().lower() != "true",
    reason="live smoke: set ZERODHA_LIVE_SMOKE=true with a fresh daily token",
)


def test_full_nse_scan_produces_real_setups():
    from tradeloop.lib.data import ingest
    from tradeloop.lib.data.kite import KiteClient

    # a liquid subset so the smoke is quick but exercises the real scan path
    syms = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN",
            "DLF", "ITC", "ONGC", "WIPRO"]
    d = Path(tempfile.mkdtemp())
    snap = ingest.run(datetime(2026, 7, 6, 9, 0), symbols=syms, run_dir=d,
                      kite_client=KiteClient(), config_dir=Path("tradeloop/config"))

    full = (d / "full_scan.jsonl").read_text().splitlines()
    print("setups downstream:", [s.ticker for s in snap.setups])
    print("full_scan rows:", len(full))
    print((d / "02_setups_raw.md").read_text()[:400])
    # the scan ran and the disk artifacts exist; setup count depends on the day's price action
    assert (d / "02_setups_raw.md").exists()
    assert (d / "full_scan.jsonl").exists()
