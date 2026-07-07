import threading
import time

from tradingbot.broker.paper import PaperOrderRequest
from tradingbot.event_log import EventLog
from tradingbot.order_gate import OrderGate, set_order_gate_mode


def request() -> PaperOrderRequest:
    return PaperOrderRequest("RELIANCE", "BUY", 1, 1000, strategy="test", source="test")


def test_autopilot_order_gate_auto_approves_after_window(tmp_path) -> None:
    event_log = EventLog(tmp_path / "trading.db")
    gate = OrderGate(event_log, mode="autopilot", cancel_window_seconds=0)

    decision = gate.wait_for_decision(request(), {"symbol": "RELIANCE"})

    assert decision.approved is True
    assert decision.status == "APPROVED"
    assert event_log.latest("order_gate.pending") is not None
    assert event_log.latest("order_gate.approved") is not None


def test_order_gate_cancel_prevents_approval(tmp_path) -> None:
    event_log = EventLog(tmp_path / "trading.db")
    gate = OrderGate(event_log, mode="autopilot", cancel_window_seconds=1, poll_interval_seconds=0.05)
    result = {}

    worker = threading.Thread(
        target=lambda: result.setdefault("decision", gate.wait_for_decision(request(), {"symbol": "RELIANCE"}))
    )
    worker.start()
    while event_log.latest("order_gate.pending") is None:
        time.sleep(0.01)
    pending = event_log.latest("order_gate.pending")
    assert pending is not None
    event_log.append_event(
        "order_gate.cancelled",
        pending.aggregate_id,
        {"gate_id": pending.aggregate_id, "status": "CANCELLED_BY_USER", "reason": "test_cancel"},
    )
    worker.join(timeout=2)

    assert result["decision"].approved is False
    assert result["decision"].status == "CANCELLED_BY_USER"


def test_order_gate_mode_change_is_used_for_next_order(tmp_path) -> None:
    event_log = EventLog(tmp_path / "trading.db")
    gate = OrderGate(event_log, mode="autopilot", cancel_window_seconds=0)
    set_order_gate_mode(event_log, "paused")

    decision = gate.wait_for_decision(request(), {"symbol": "RELIANCE"})

    assert decision.approved is False
    assert decision.status == "BLOCKED"
