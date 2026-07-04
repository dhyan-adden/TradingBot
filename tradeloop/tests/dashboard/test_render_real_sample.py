from pathlib import Path

from tradeloop.dashboard.runs import read_run

SAMPLE = Path(__file__).parent / "sample_run"


def test_real_sample_renders_without_raw_enums_or_crashes():
    out = read_run(SAMPLE)
    blob = " ".join(s["summary"] + " ".join(s["points"]) for s in out["stages"])
    # raw enum tokens must have been translated, not shown to the user
    for raw_token in ("bullish_entry", "tradeable", '"ticker"', "composite_score"):
        assert raw_token not in blob
    assert out["decision"]["summary"]
