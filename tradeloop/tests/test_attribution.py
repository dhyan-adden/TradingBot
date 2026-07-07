from tradeloop.lib.audit.attribution import (
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
