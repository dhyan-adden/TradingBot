from tradeloop.lib.audit.attribution import (
    StrategyPerformance,
    TradeAttribution,
    expected_r,
    render_strategy_performance,
    report,
)
from tradeloop.lib.audit.outcomes import Outcome
from tradeloop.lib.broker.orders_schema import Order, OrdersFile
from tradeloop.lib.broker.router import _metric  # gate parses metrics with this


def _plan(**kw):
    base = dict(ticker="TCS", side="BUY", quantity=10, price=100.0, hard_stop=90.0,
                target_1=120.0, strategy_family="breakout_20d_pullback")
    base.update(kw)
    return Order(**base)


def _fill(symbol, side, qty, price):
    return {"symbol": symbol, "side": side, "quantity": qty, "fill_price": price, "status": "FILLED"}


def test_expected_r_from_trailer():
    # (120-100)/(100-90) = 2.0
    assert expected_r(_plan()) == 2.0


def test_expected_r_zero_when_no_stop_or_target():
    assert expected_r(_plan(hard_stop=None)) == 0.0
    assert expected_r(_plan(target_1=None)) == 0.0


def test_realized_r_target_hit_is_win():
    of = OrdersFile(mode="postclose", orders=[_plan()])
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 120.0)]
    perf = report(of, fills)
    ta = next(t for t in perf.trades if t.symbol == "TCS")
    assert ta.expected_r == 2.0
    assert ta.realized_r == 2.0            # (120-100)/(100-90)
    assert ta.outcome == Outcome.THESIS_CORRECT_WON


def test_realized_r_stopped_out_is_loss():
    of = OrdersFile(mode="postclose", orders=[_plan()])
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 90.0)]
    perf = report(of, fills)
    ta = next(t for t in perf.trades if t.symbol == "TCS")
    assert ta.realized_r == -1.0
    assert ta.outcome == Outcome.THESIS_CORRECT_STOPPED


def test_open_position_not_attributed():
    of = OrdersFile(mode="postclose", orders=[_plan()])
    fills = [_fill("TCS", "BUY", 10, 100.0)]  # never sold
    perf = report(of, fills)
    assert perf.trades == []
    assert perf.paper_trades == 0


def test_ledger_stamped_fills_attribute_without_current_run_plan():
    # 2026-07-13 debt: attribution matched ALL-history ledger fills against the
    # CURRENT run's orders.json only, so a trade closed by a later run (whose
    # orders.json has no entry plan for the symbol) was silently dropped from the
    # scorecard. Entry fills now carry their own plan data (stamped at route time)
    # and attribution never needs the closing run's plan file.
    of = OrdersFile(mode="premarket", orders=[])   # the closing run knows nothing
    fills = [
        {**_fill("TCS", "BUY", 10, 100.0), "hard_stop": 90.0, "target_1": 120.0,
         "strategy_family": "breakout_20d_pullback"},
        _fill("TCS", "SELL", 10, 120.0),
    ]
    perf = report(of, fills)
    assert perf.paper_trades == 1
    ta = perf.trades[0]
    assert ta.realized_r == 2.0
    assert ta.expected_r == 2.0
    assert ta.strategy_family == "breakout_20d_pullback"
    assert ta.outcome == Outcome.THESIS_CORRECT_WON


def test_reentry_forms_two_episodes_not_one_vwap_blob():
    # A symbol traded twice must yield two trades with separate R (and distinct
    # journal keys), not one merged VWAP round trip - the merge also made
    # paper_trades DROP whenever a closed symbol was re-entered.
    of = OrdersFile(mode="premarket", orders=[_plan()])
    fills = [
        _fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 120.0),   # +2R
        _fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 90.0),    # -1R
    ]
    perf = report(of, fills)
    assert perf.paper_trades == 2
    assert sorted(t.realized_r for t in perf.trades) == [-1.0, 2.0]
    assert len({t.close_ref for t in perf.trades}) == 2


def test_closed_trade_with_no_stop_anywhere_is_skipped_not_zero():
    # No stop on the entry fill and none in the run's plan -> R is undefined. The
    # trade must be EXCLUDED, never counted as a fake realized_r=0.0 that drags
    # win rate and expectancy toward noise (premature-tuning guard).
    of = OrdersFile(mode="premarket", orders=[_plan(hard_stop=None)])
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 120.0)]
    perf = report(of, fills)
    assert perf.trades == []
    assert perf.paper_trades == 0


def test_render_matches_promotion_gate_parse_keys():
    # Patch C: the gate reads top-level portfolio metrics via router._metric,
    # so assert _metric extracts the ACTUAL numbers, not just a header string.
    of = OrdersFile(mode="postclose", orders=[_plan()])
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 120.0)]
    perf = report(of, fills)
    md = render_strategy_performance(perf, live_ready=False)
    assert "live_ready: false" in md.lower()
    assert _metric(md, "paper_trades") == 1
    assert _metric(md, "win_rate") == 1.0
    assert _metric(md, "expectancy_r") == 2.0
    assert _metric(md, "max_drawdown_pct") == 0.0   # a win is not drawdown
    assert "| Strategy | Trades | Win Rate | Expectancy R | Max Drawdown % | Confidence |" in md


def test_render_no_closed_trades_zero_metrics():
    # Patch C case 2: open buy only -> gate reads zeros, never promotes.
    of = OrdersFile(mode="postclose", orders=[_plan()])
    fills = [_fill("TCS", "BUY", 10, 100.0)]
    perf = report(of, fills)
    md = render_strategy_performance(perf, live_ready=False)
    assert _metric(md, "paper_trades") == 0
    assert _metric(md, "win_rate") == 0.0
    assert _metric(md, "expectancy_r") == 0.0


def test_render_stopped_trade_drawdown():
    # Patch C case 3: a stopped trade (realized_r -1.0) is the worst-trade R drawdown.
    of = OrdersFile(mode="postclose", orders=[_plan()])
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 90.0)]
    perf = report(of, fills)
    md = render_strategy_performance(perf, live_ready=False)
    assert _metric(md, "max_drawdown_pct") == 1.0
    assert _metric(md, "win_rate") == 0.0


def _perf_with_realized(*rs: float) -> StrategyPerformance:
    trades = [
        TradeAttribution(
            symbol=f"S{i}", strategy_family="s", expected_r=0.0, realized_r=r,
            outcome=Outcome.THESIS_CORRECT_WON if r > 0 else Outcome.THESIS_CORRECT_STOPPED,
            close_ref=f"r{i}",
        )
        for i, r in enumerate(rs)
    ]
    return StrategyPerformance(trades=list(trades), by_strategy=[], paper_trades=len(trades))


def test_max_drawdown_r_from_equity_curve_not_worst_trade():
    # Cumulative R: 1 -> 0.5 -> 0. Worst single trade is 0.5R, but the equity-curve
    # drawdown from the peak is 1.0R. Promotion must see the curve, not the single loss.
    perf = _perf_with_realized(1.0, -0.5, -0.5)
    md = render_strategy_performance(perf)
    assert _metric(md, "max_drawdown_r") == 1.0


def test_max_drawdown_r_handles_initial_drawdown_from_zero():
    # Cumulative R: -1 -> 1. The dip from the zero baseline is a 1.0R drawdown.
    perf = _perf_with_realized(-1.0, 2.0)
    md = render_strategy_performance(perf)
    assert _metric(md, "max_drawdown_r") == 1.0


def test_open_position_excluded_from_drawdown():
    # An open buy never closes, so it is not a closed paper trade and contributes
    # no realized-R to the equity curve.
    of = OrdersFile(mode="postclose", orders=[_plan()])
    fills = [_fill("TCS", "BUY", 10, 100.0)]
    perf = report(of, fills)
    md = render_strategy_performance(perf)
    assert _metric(md, "paper_trades") == 0
    assert _metric(md, "max_drawdown_r") == 0.0


def test_no_stop_fill_not_counted_in_trade_count():
    # A fill with no recorded hard stop is excluded; it must not inflate the count.
    of = OrdersFile(mode="premarket", orders=[_plan(hard_stop=None)])
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 120.0)]
    perf = report(of, fills)
    assert perf.paper_trades == 0
    assert perf.trades == []


def test_rerun_over_same_ledger_is_idempotent():
    # Re-attributing the same ledger must not duplicate trades; close_ref keys the
    # journal so a second pass yields identical counts and stable refs.
    of = OrdersFile(mode="premarket", orders=[_plan()])
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 120.0)]
    perf_a = report(of, fills)
    perf_b = report(of, fills)
    assert perf_a.paper_trades == perf_b.paper_trades == 1
    assert {t.close_ref for t in perf_a.trades} == {t.close_ref for t in perf_b.trades}
