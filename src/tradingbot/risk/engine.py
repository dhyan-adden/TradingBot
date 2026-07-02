from dataclasses import dataclass
from typing import List, Sequence

from tradingbot.broker.paper import PaperOrderRequest, PaperPortfolio


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: List[str]


@dataclass(frozen=True)
class RiskLimits:
    paper_capital_inr: float
    max_open_positions: int
    max_position_allocation_pct: float
    max_total_deployed_pct: float
    allow_short_selling: bool = False
    kill_switch_enabled: bool = True


class RiskEngine:
    def __init__(self, limits: RiskLimits, universe: Sequence[str], kill_switch_active: bool = False):
        self.limits = limits
        self.universe = {symbol.upper() for symbol in universe}
        self.kill_switch_active = kill_switch_active

    def evaluate(self, request: PaperOrderRequest, portfolio: PaperPortfolio) -> RiskDecision:
        reasons: List[str] = []
        symbol = request.symbol.upper()
        side = request.side.upper()
        notional = request.quantity * request.price
        deployed = sum(
            quantity * portfolio.avg_prices.get(pos_symbol, 0.0)
            for pos_symbol, quantity in portfolio.positions.items()
        )

        if self.kill_switch_active and self.limits.kill_switch_enabled:
            reasons.append("kill_switch_active")
        if symbol not in self.universe:
            reasons.append("symbol_not_in_universe")
        if side == "SELL" and not self.limits.allow_short_selling:
            if request.quantity > portfolio.positions.get(symbol, 0):
                reasons.append("short_selling_disabled")
        if side == "BUY" and symbol not in portfolio.positions:
            if len(portfolio.positions) >= self.limits.max_open_positions:
                reasons.append("max_open_positions_exceeded")
        if notional > self.limits.paper_capital_inr * (self.limits.max_position_allocation_pct / 100):
            reasons.append("max_position_allocation_exceeded")
        if side == "BUY":
            next_deployed = deployed + notional
            if next_deployed > self.limits.paper_capital_inr * (self.limits.max_total_deployed_pct / 100):
                reasons.append("max_total_deployed_exceeded")
        if request.quantity <= 0:
            reasons.append("quantity_must_be_positive")
        if request.price <= 0:
            reasons.append("price_must_be_positive")

        return RiskDecision(approved=not reasons, reasons=reasons)
