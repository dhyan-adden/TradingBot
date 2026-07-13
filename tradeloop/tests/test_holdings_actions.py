import json

from tradeloop import orchestrator
from tradeloop.lib.audit.ledger import ORDER_FILLED, Ledger


def _root_with_position(tmp_path, symbol="HDFCBANK", qty=30, price=830.62, stop=807.24):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "settings.yaml").write_text(
        "capital:\n  paper_starting_inr: 100000\n", encoding="utf-8")
    (tmp_path / "state").mkdir(exist_ok=True)
    Ledger(tmp_path / "state" / "ledger.db").append(
        {"type": ORDER_FILLED, "order_id": "X1", "symbol": symbol, "side": "BUY",
         "quantity": qty, "fill_price": price, "product": "CNC", "hard_stop": stop})
    return tmp_path


def _run_dir(root, name="2026-07-14_1400_intraday"):
    d = root / "runs" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_review(d, reviews, carry_forward=""):
    payload = {"reviews": reviews, "carry_forward": carry_forward, "evidence": []}
    (d / "15_holdings_review.json").write_text(json.dumps(payload), encoding="utf-8")


def test_exit_verdict_becomes_full_sell_at_ltp(tmp_path):
    root = _root_with_position(tmp_path)
    d = _run_dir(root)
    (d / "holdings_ltp.json").write_text(json.dumps({"HDFCBANK": 812.5}), encoding="utf-8")
    _write_review(d, [{"ticker": "HDFCBANK", "verdict": "EXIT", "conviction": 2.0,
                       "reason_code": "thesis_break", "rationale": "bad results", "evidence": []}])
    orders, stops = orchestrator._holdings_actions(d, "intraday", root)
    assert len(orders) == 1
    assert (orders[0].ticker, orders[0].side, orders[0].quantity, orders[0].price) == \
        ("HDFCBANK", "SELL", 30, 812.5)
    assert stops == {}


def test_trim_clamped_to_position(tmp_path):
    root = _root_with_position(tmp_path)
    d = _run_dir(root)
    (d / "holdings_ltp.json").write_text(json.dumps({"HDFCBANK": 812.5}), encoding="utf-8")
    _write_review(d, [{"ticker": "HDFCBANK", "verdict": "TRIM", "conviction": 4.0,
                       "reason_code": "event_risk", "rationale": "derisk into earnings",
                       "exit_quantity": 500, "evidence": []}])
    orders, _ = orchestrator._holdings_actions(d, "intraday", root)
    assert orders[0].quantity == 30   # never sell more than held


def test_stop_breach_forces_exit_even_if_review_missed_it(tmp_path):
    root = _root_with_position(tmp_path, stop=807.24)
    d = _run_dir(root)
    (d / "holdings_ltp.json").write_text(json.dumps({"HDFCBANK": 806.0}), encoding="utf-8")
    _write_review(d, [{"ticker": "HDFCBANK", "verdict": "HOLD", "conviction": 6.0,
                       "reason_code": "thesis_intact", "rationale": "looks fine", "evidence": []}])
    orders, _ = orchestrator._holdings_actions(d, "intraday", root)
    assert len(orders) == 1
    assert orders[0].side == "SELL" and orders[0].quantity == 30
    assert orders[0].reason == "exit:stop_breach_enforced"


def test_postclose_never_produces_orders_but_keeps_stop_updates(tmp_path):
    root = _root_with_position(tmp_path)
    d = _run_dir(root, "2026-07-14_1600_postclose")
    (d / "holdings_ltp.json").write_text(json.dumps({"HDFCBANK": 806.0}), encoding="utf-8")
    _write_review(d, [{"ticker": "HDFCBANK", "verdict": "TIGHTEN_STOP", "conviction": 6.0,
                       "reason_code": "profit_protect", "rationale": "lock gain",
                       "new_stop": 815.0, "evidence": []}])
    orders, stops = orchestrator._holdings_actions(d, "postclose", root)
    assert orders == []                      # market closed: nothing may fill
    assert stops == {"HDFCBANK": 815.0}


def test_tighten_stop_never_loosens_and_needs_position(tmp_path):
    root = _root_with_position(tmp_path, stop=807.24)
    d = _run_dir(root)
    _write_review(d, [
        {"ticker": "HDFCBANK", "verdict": "TIGHTEN_STOP", "conviction": 5.0,
         "reason_code": "profit_protect", "rationale": "wider", "new_stop": 790.0, "evidence": []},
        {"ticker": "GHOST", "verdict": "TIGHTEN_STOP", "conviction": 5.0,
         "reason_code": "profit_protect", "rationale": "not held", "new_stop": 100.0, "evidence": []},
    ])
    _, stops = orchestrator._holdings_actions(d, "intraday", root)
    assert stops == {}   # loosening rejected; unheld symbol rejected


def test_no_ltp_means_no_orders_flagged_for_carry_forward(tmp_path):
    root = _root_with_position(tmp_path)
    d = _run_dir(root)
    _write_review(d, [{"ticker": "HDFCBANK", "verdict": "EXIT", "conviction": 2.0,
                       "reason_code": "thesis_break", "rationale": "bad", "evidence": []}])
    orders, _ = orchestrator._holdings_actions(d, "intraday", root)
    assert orders == []   # no price -> nothing routable; verdict still reaches carry-forward


def test_run_reasoning_dag_writes_sells_and_stop_updates(tmp_path):
    """End to end through _run_reasoning: intraday fake review -> orders.json + stop_updates.json."""
    from tradeloop.lib.llm import schemas
    from tradeloop.tests.test_reasoning_wiring import StageFakeClient

    root = _root_with_position(tmp_path)
    d = _run_dir(root)
    for f in ("00_context.md", "01_news_raw.md", "02_setups_raw.md"):
        (d / f).write_text(f"# {f}\n")
    (d / "holdings_ltp.json").write_text(json.dumps({"HDFCBANK": 812.5}), encoding="utf-8")
    client = StageFakeClient()
    client.DEFAULTS = dict(StageFakeClient.DEFAULTS)
    client.DEFAULTS[schemas.HoldingsReview] = {
        "reviews": [{"ticker": "HDFCBANK", "verdict": "EXIT", "conviction": 2.0,
                     "reason_code": "thesis_break", "rationale": "bad", "evidence": []}],
        "carry_forward": "exited", "evidence": []}
    rc = orchestrator._run_reasoning(d, "intraday", "openrouter", 1200, client=client)
    assert rc == 0
    orders = json.loads((d / "orders.json").read_text())
    assert orders["orders"][0]["side"] == "SELL"
    assert orders["orders"][0]["quantity"] == 30
    assert json.loads((d / "stop_updates.json").read_text()) == {}


def _review_obj(**kw):
    from tradeloop.lib.llm.schemas import HoldingsReview
    base = {"reviews": [{"ticker": "HDFCBANK", "verdict": "HOLD", "conviction": 6.0,
                         "reason_code": "thesis_intact", "rationale": "steady", "evidence": []}],
            "carry_forward": "Q1 results Wednesday; hold through print.", "evidence": []}
    base.update(kw)
    return HoldingsReview.model_validate(base)


def test_carry_forward_written_and_replaced_not_appended(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "carry_forward_context.md").write_text(
        "- manual note: SBIN tripwire 1019\n", encoding="utf-8")
    orchestrator._write_carry_forward(mem, "2026-07-14_1400_intraday", _review_obj())
    orchestrator._write_carry_forward(mem, "2026-07-14_1600_postclose", _review_obj(
        carry_forward="All quiet after close."))
    text = (mem / "carry_forward_context.md").read_text(encoding="utf-8")
    assert "manual note: SBIN tripwire 1019" in text          # manual content survives
    assert text.count("auto:holdings_review:start") == 1       # replaced, not stacked
    assert "2026-07-14_1600_postclose" in text                 # latest run wins
    assert "2026-07-14_1400_intraday" not in text
    assert "All quiet after close." in text
    assert "HDFCBANK: HOLD" in text


def test_carry_forward_created_when_file_missing(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    orchestrator._write_carry_forward(mem, "2026-07-14_1600_postclose", _review_obj())
    text = (mem / "carry_forward_context.md").read_text(encoding="utf-8")
    assert "auto:holdings_review:start" in text
