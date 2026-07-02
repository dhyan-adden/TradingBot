import time
import uuid
from dataclasses import asdict, dataclass
from typing import Literal

from tradingbot.broker.paper import PaperOrderRequest
from tradingbot.event_log import EventLog


OrderGateMode = Literal["autopilot", "confirm_each_order", "paused"]


@dataclass(frozen=True)
class OrderGateDecision:
    approved: bool
    gate_id: str
    status: str
    reason: str


class OrderGate:
    def __init__(
        self,
        event_log: EventLog,
        mode: str = "autopilot",
        cancel_window_seconds: float = 30,
        poll_interval_seconds: float = 0.5,
    ):
        self.event_log = event_log
        self.mode = normalize_order_gate_mode(mode)
        self.cancel_window_seconds = max(0.0, float(cancel_window_seconds))
        self.poll_interval_seconds = max(0.05, float(poll_interval_seconds))

    @classmethod
    def from_config(cls, event_log: EventLog, loop_config: dict) -> "OrderGate":
        gate_config = loop_config.get("execution", {}).get("order_gate", {})
        return cls(
            event_log=event_log,
            mode=str(gate_config.get("mode", "autopilot")),
            cancel_window_seconds=float(gate_config.get("cancel_window_seconds", 30)),
        )

    def wait_for_decision(self, request: PaperOrderRequest, context: dict) -> OrderGateDecision:
        self.mode = latest_order_gate_mode(self.event_log, self.mode)
        gate_id = f"GATE-{uuid.uuid4().hex[:12].upper()}"
        payload = {
            "gate_id": gate_id,
            "status": "PENDING_GATE",
            "mode": self.mode,
            "cancel_window_seconds": self.cancel_window_seconds,
            "request": asdict(request),
            "context": context,
        }
        self.event_log.append_event("order_gate.pending", gate_id, payload)

        if self.mode == "paused":
            return self._finish(gate_id, "BLOCKED", "order_gate_paused", approved=False)

        if self.mode == "confirm_each_order":
            return self._wait_for_manual_decision(gate_id)

        return self._wait_for_autopilot_decision(gate_id)

    def _wait_for_autopilot_decision(self, gate_id: str) -> OrderGateDecision:
        deadline = time.monotonic() + self.cancel_window_seconds
        while time.monotonic() < deadline:
            manual = self._manual_decision(gate_id)
            if manual is not None:
                return manual
            time.sleep(min(self.poll_interval_seconds, max(0.0, deadline - time.monotonic())))
        manual = self._manual_decision(gate_id)
        if manual is not None:
            return manual
        return self._finish(gate_id, "APPROVED", "autopilot_cancel_window_elapsed", approved=True)

    def _wait_for_manual_decision(self, gate_id: str) -> OrderGateDecision:
        while True:
            manual = self._manual_decision(gate_id)
            if manual is not None:
                return manual
            time.sleep(self.poll_interval_seconds)

    def _manual_decision(self, gate_id: str) -> OrderGateDecision | None:
        latest_cancel = self.event_log.latest("order_gate.cancelled", gate_id)
        if latest_cancel:
            return OrderGateDecision(False, gate_id, "CANCELLED_BY_USER", str(latest_cancel.payload.get("reason", "user_cancelled")))
        latest_approval = self.event_log.latest("order_gate.approved", gate_id)
        if latest_approval:
            return OrderGateDecision(True, gate_id, "APPROVED", str(latest_approval.payload.get("reason", "user_approved")))
        return None

    def _finish(self, gate_id: str, status: str, reason: str, approved: bool) -> OrderGateDecision:
        event_type = "order_gate.approved" if approved else "order_gate.blocked"
        self.event_log.append_event(event_type, gate_id, {"gate_id": gate_id, "status": status, "reason": reason})
        return OrderGateDecision(approved=approved, gate_id=gate_id, status=status, reason=reason)


def normalize_order_gate_mode(mode: str) -> OrderGateMode:
    normalized = mode.strip().lower()
    if normalized not in {"autopilot", "confirm_each_order", "paused"}:
        raise ValueError("order gate mode must be autopilot, confirm_each_order, or paused")
    return normalized  # type: ignore[return-value]


def set_order_gate_mode(event_log: EventLog, mode: str) -> None:
    normalized = normalize_order_gate_mode(mode)
    event_log.append_event("order_gate.mode_changed", "ORDER_GATE", {"mode": normalized})


def latest_order_gate_mode(event_log: EventLog, configured_mode: str) -> OrderGateMode:
    latest = event_log.latest("order_gate.mode_changed", "ORDER_GATE")
    if latest:
        return normalize_order_gate_mode(str(latest.payload.get("mode", configured_mode)))
    return normalize_order_gate_mode(configured_mode)
