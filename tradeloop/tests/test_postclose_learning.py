
from tradeloop.lib.audit.postclose import LearningResult, run_postclose_learning
from tradeloop.lib.broker.orders_schema import Order, OrdersFile


def _write_orders(run_dir):
    of = OrdersFile(mode="postclose", orders=[
        Order(ticker="TCS", side="BUY", quantity=10, price=100.0, hard_stop=90.0,
              target_1=120.0, strategy_family="breakout_20d_pullback"),
    ])
    (run_dir / "orders.json").write_text(of.model_dump_json(), encoding="utf-8")


def _fill(symbol, side, qty, price):
    return {"symbol": symbol, "side": side, "quantity": qty, "fill_price": price, "status": "FILLED"}


def test_learning_loop_writes_journal_dossier_and_strategy_stats(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_orders(run_dir)
    memory = tmp_path / "memory"
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 120.0)]

    result = run_postclose_learning(run_dir, memory, fills, run_id="R1", timestamp="2026-07-02T16:00")
    assert isinstance(result, LearningResult)
    assert result.journal_entries == 1

    journal = (memory / "trade_journal.md").read_text(encoding="utf-8")
    assert "TCS" in journal and "run_id: R1" in journal and "thesis-correct-and-won" in journal

    dossier = (memory / "stock_dossiers" / "TCS.md").read_text(encoding="utf-8")
    assert "realized_r" in dossier.lower() or "realized R" in dossier

    perf = (memory / "strategy_performance.md").read_text(encoding="utf-8")
    assert "paper_trades: 1" in perf
    assert "breakout_20d_pullback" in perf


def test_rerouting_does_not_duplicate_journal_entries(tmp_path):
    # Attribution replays the FULL ledger at every route, so a later route (new
    # run_id + timestamp) re-sees every closed trade in history. Journal and
    # dossier entries must key on the trade's stable close_ref, not the routing
    # timestamp - else each route re-journals all of history.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_orders(run_dir)
    memory = tmp_path / "memory"
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 120.0)]

    first = run_postclose_learning(run_dir, memory, fills, run_id="R1", timestamp="t1")
    again = run_postclose_learning(run_dir, memory, fills, run_id="R2", timestamp="t2")
    assert first.journal_entries == 1
    assert again.journal_entries == 0
    journal = (memory / "trade_journal.md").read_text(encoding="utf-8")
    assert journal.count("## TCS") == 1
    dossier = (memory / "stock_dossiers" / "TCS.md").read_text(encoding="utf-8")
    assert dossier.count("realized_r") == 1


def test_no_closed_trades_writes_empty_stats_no_journal(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_orders(run_dir)
    memory = tmp_path / "memory"
    fills = [_fill("TCS", "BUY", 10, 100.0)]  # open, not closed
    result = run_postclose_learning(run_dir, memory, fills, run_id="R1", timestamp="t")
    assert result.journal_entries == 0
    assert "paper_trades: 0" in (memory / "strategy_performance.md").read_text(encoding="utf-8")
    assert not (memory / "trade_journal.md").exists()
