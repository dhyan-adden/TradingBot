"""Deterministic position sizing overrides the LLM trader's guessed quantity.

Regression: a green-lit ICICI trade came in at 4 shares (the trader lowballing
its own risk budget ~10x), got resized DOWN to 3 by the risk LLM, then vetoed
under the 15k min-position floor - so a good setup never routed. Sizing must be
a formula: qty = risk_budget / stop_distance, floored/capped by the guardrails.
"""
from types import SimpleNamespace

from tradeloop.lib.llm.schemas import TradePlan, TradeTicket
from tradeloop import orchestrator


# equity 100k, 1.5% per-trade risk, 25% max position, 15k min position
CAPS = SimpleNamespace(paper_starting_inr=100_000.0, per_trade_risk_pct=1.5,
                       max_position_pct=25.0, min_position_size_inr=15_000.0)


def _ticket(ticker, entry, hard_stop, quantity):
    return TradeTicket(
        ticker=ticker, side="BUY", product="CNC", strategy_family="20d_breakout",
        entry=entry, hard_stop=hard_stop, target_1=entry * 1.03, target_2=entry * 1.05,
        quantity=quantity, time_horizon="2-4 weeks", thesis="t", conviction=7.0)


def test_icici_sizes_to_the_risk_budget_not_the_lowball():
    # 1.5% of 100k = 1500 risk; stop distance 34.65 -> ~43 shares, capped by the
    # 25% position limit to 17 (17*1426.5 = 24,250, clears the 15k floor).
    qty = orchestrator._deterministic_qty(1426.5, 1391.85, CAPS)
    assert qty == 17


def test_position_that_cannot_clear_the_floor_is_zero():
    # 50 rupee stock, wide 6-rupee stop -> 250 shares = 12,500, below the 15k
    # floor -> untradeable, must return 0 (not a sub-min position).
    assert orchestrator._deterministic_qty(50.0, 44.0, CAPS) == 0


def test_size_trade_plan_overwrites_qty_and_drops_untradeable(tmp_path):
    plan = TradePlan(tickets=[
        _ticket("ICICIBANK", 1426.5, 1391.85, 4),   # lowballed -> should become 17
        _ticket("CHEAPCO", 50.0, 44.0, 300),         # untradeable -> should be dropped
    ])
    (tmp_path / "30_trade_plan.json").write_text(plan.model_dump_json(indent=2))

    orchestrator._size_trade_plan(tmp_path, CAPS)

    out = TradePlan.model_validate_json((tmp_path / "30_trade_plan.json").read_text())
    assert len(out.tickets) == 1
    assert out.tickets[0].ticker == "ICICIBANK"
    assert out.tickets[0].quantity == 17          # deterministic, not the LLM's 4
    assert "17" in (tmp_path / "30_trade_plan.md").read_text()  # human artifact rewritten too


def test_size_trade_plan_is_a_noop_when_no_plan_written(tmp_path):
    orchestrator._size_trade_plan(tmp_path, CAPS)  # must not raise on missing file
