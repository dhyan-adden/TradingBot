from tradeloop.lib.data.grounding import (
    GROUNDING_TOLERANCE,
    load_scan_levels,
    validate_grounding,
)


def _order(ticker, price, hard_stop):
    return {"ticker": ticker, "price": price, "hard_stop": hard_stop}


SCAN = {"HDFCBANK": {"entry": 801.05, "stop": 779.48}}


def test_entry_matching_scan_passes():
    res = validate_grounding([_order("HDFCBANK", 801.05, 779.48)], SCAN)
    assert res.ok and res.violations == []


def test_tick_rounding_within_tolerance_passes():
    # a small limit offset / tick rounding stays grounded
    res = validate_grounding([_order("HDFCBANK", 802.0, 778.0)], SCAN)
    assert res.ok


def test_news_anchored_entry_is_blocked():
    # the exact bug: entry lifted from a stale news headline (1680 vs real 801)
    res = validate_grounding([_order("HDFCBANK", 1680.0, 1640.0)], SCAN)
    assert not res.ok
    assert any("entry" in reason for _, reason in res.violations)


def test_drifted_stop_alone_is_blocked():
    res = validate_grounding([_order("HDFCBANK", 801.05, 700.0)], SCAN)
    assert not res.ok
    assert any("hard_stop" in reason for _, reason in res.violations)


def test_ticker_absent_from_scan_is_blocked():
    # no scan setup => no real stop => cannot be grounded
    res = validate_grounding([_order("TCS", 3000.0, 2900.0)], SCAN)
    assert not res.ok
    assert any("no scan setup" in reason for _, reason in res.violations)


def test_missing_stop_is_blocked():
    res = validate_grounding([_order("HDFCBANK", 801.05, None)], SCAN)
    assert not res.ok


def test_accepts_attribute_objects_not_just_dicts():
    class O:
        ticker, price, hard_stop = "HDFCBANK", 801.05, 779.48
    assert validate_grounding([O()], SCAN).ok


def test_seLL_exit_order_exempt_from_grounding():
    # long-only: SELL orders are deterministic LTP-priced exits of existing
    # positions with no scanner setup; they must never be blocked as ungrounded
    res = validate_grounding(
        [{"ticker": "CDSL", "side": "SELL", "price": 1345.9, "hard_stop": None}],
        SCAN)
    assert res.ok and res.violations == []


def test_load_scan_levels_parses_frozen_setups(tmp_path):
    snap = tmp_path / "snapshot"
    snap.mkdir()
    (snap / "items.jsonl").write_text(
        '{"kind": "story", "news_id": "x", "ticker": "HDFCBANK"}\n'
        '{"kind": "setup", "ticker": "HDFCBANK", "entry_zone": "801.05",'
        ' "stop_zone": "779.48", "target_zone": "829.81/844.20"}\n',
        encoding="utf-8",
    )
    levels = load_scan_levels(tmp_path)
    assert levels == {"HDFCBANK": {"entry": 801.05, "stop": 779.48}}


def test_load_scan_levels_empty_when_no_snapshot(tmp_path):
    assert load_scan_levels(tmp_path) == {}


def test_tolerance_constant_is_tight():
    # a sanity guard: the gate must be tight enough to catch a 2x news-frame drift
    assert GROUNDING_TOLERANCE <= 0.05
