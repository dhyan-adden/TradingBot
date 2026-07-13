from dataclasses import dataclass
from typing import Dict, Iterable, List

from tradeloop.lib.broker.paper_broker import OrderTicket


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: List[str]


@dataclass(frozen=True)
class RiskState:
    cash_inr: float
    positions: Dict[str, int]
    avg_prices: Dict[str, float]
    sectors: Dict[str, str]
    open_risk_inr: float = 0.0
    daily_pnl_inr: float = 0.0


@dataclass(frozen=True)
class RiskCaps:
    capital_inr: float
    max_open_positions: int
    max_position_allocation_pct: float
    max_total_deployed_pct: float
    max_sector_allocation_pct: float
    max_daily_drawdown_pct: float
    universe: Iterable[str]
    max_open_risk_pct: float = 4.0
    min_position_size_inr: float = 15000
    max_adv_participation_pct: float = 1.0


def evaluate(ticket: OrderTicket, state: RiskState, caps: RiskCaps) -> RiskDecision:
    reasons: List[str] = []
    symbol = ticket.symbol.strip().upper()
    universe = {item.strip().upper() for item in caps.universe}
    notional = ticket.quantity * ticket.price
    deployed = sum(quantity * state.avg_prices.get(pos_symbol, 0.0) for pos_symbol, quantity in state.positions.items())

    if symbol not in universe:
        reasons.append("symbol_not_in_universe")
    if ticket.side not in {"BUY", "SELL"}:
        reasons.append("unsupported_side")
    if ticket.side == "SELL" and ticket.quantity > state.positions.get(symbol, 0):
        reasons.append("long_only_sell_exceeds_position")
    if ticket.quantity <= 0:
        reasons.append("quantity_must_be_positive")
    if ticket.price <= 0:
        reasons.append("price_must_be_positive")
    if ticket.product not in {"CNC", "MIS"}:
        reasons.append("unsupported_product")
    if notional < caps.min_position_size_inr and ticket.side == "BUY":
        reasons.append("below_min_position_size")
    # BUY-only: an appreciated position's exit notional can exceed the entry
    # cap; the gate must never trap capital in a winner.
    if notional > caps.capital_inr * (caps.max_position_allocation_pct / 100) and ticket.side == "BUY":
        reasons.append("max_position_allocation_exceeded")
    if state.open_risk_inr > caps.capital_inr * (caps.max_open_risk_pct / 100):
        reasons.append("max_open_risk_exceeded")
    if ticket.side == "BUY":
        if symbol not in state.positions and len(state.positions) >= caps.max_open_positions:
            reasons.append("max_open_positions_exceeded")
        if deployed + notional > caps.capital_inr * (caps.max_total_deployed_pct / 100):
            reasons.append("max_total_deployed_exceeded")
        sector_reason = _sector_reason(symbol, notional, state, caps)
        if sector_reason:
            reasons.append(sector_reason)
    if state.daily_pnl_inr < 0 and abs(state.daily_pnl_inr) > caps.capital_inr * (caps.max_daily_drawdown_pct / 100):
        reasons.append("daily_drawdown_circuit")
    return RiskDecision(approved=not reasons, reasons=reasons)


def liquidity_ok(position_value_inr: float, adv20_inr: float, max_participation_pct: float = 1.0) -> bool:
    if adv20_inr <= 0:
        return False
    return position_value_inr <= adv20_inr * (max_participation_pct / 100)


def _sector_reason(symbol: str, next_notional: float, state: RiskState, caps: RiskCaps) -> str:
    sector = state.sectors.get(symbol)
    if not sector:
        return ""
    sector_deployed = next_notional
    for pos_symbol, quantity in state.positions.items():
        if state.sectors.get(pos_symbol) == sector:
            sector_deployed += quantity * state.avg_prices.get(pos_symbol, 0.0)
    if sector_deployed > caps.capital_inr * (caps.max_sector_allocation_pct / 100):
        return "max_sector_allocation_exceeded"
    return ""
