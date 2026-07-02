from dataclasses import dataclass
from typing import Dict, Optional

from tradingbot.broker.paper import PaperPortfolio


@dataclass(frozen=True)
class SignalDecision:
    symbol: str
    action: str
    strategy: str
    reason: str
    quantity: int = 0
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None


def simple_breakout_signal(
    symbol: str,
    last_price: float,
    portfolio: PaperPortfolio,
    strategy_config: Dict,
    default_quantity: int,
) -> SignalDecision:
    strategy_name = str(strategy_config.get("name", "daily_breakout_v1"))
    exit_config = strategy_config.get("exit", {})
    stop_loss_pct = float(exit_config.get("stop_loss_pct", 2))
    target_pct = float(exit_config.get("target_pct", 5))
    normalized = symbol.upper()

    if normalized in portfolio.positions:
        avg_price = portfolio.avg_prices.get(normalized, last_price)
        stop_loss = round(avg_price * (1 - stop_loss_pct / 100), 2)
        target = round(avg_price * (1 + target_pct / 100), 2)
        if last_price <= stop_loss:
            return SignalDecision(normalized, "SELL", strategy_name, "stop_loss_hit", portfolio.positions[normalized])
        if last_price >= target:
            return SignalDecision(normalized, "SELL", strategy_name, "target_hit", portfolio.positions[normalized])
        return SignalDecision(normalized, "HOLD", strategy_name, "position_within_exit_band")

    if not strategy_config.get("enabled", True):
        return SignalDecision(normalized, "HOLD", strategy_name, "strategy_disabled")

    entry_config = strategy_config.get("entry", {})
    if entry_config.get("type") != "breakout":
        return SignalDecision(normalized, "HOLD", strategy_name, "unsupported_entry_type")

    # V1 deliberately uses a conservative placeholder trigger until candle
    # history is added: the closed loop proves order/risk/memory plumbing first.
    if last_price > 0 and bool(strategy_config.get("paper_entry_enabled", False)):
        return SignalDecision(
            normalized,
            "BUY",
            strategy_name,
            "paper_entry_enabled",
            default_quantity,
            stop_loss=round(last_price * (1 - stop_loss_pct / 100), 2),
            target_price=round(last_price * (1 + target_pct / 100), 2),
        )

    return SignalDecision(normalized, "HOLD", strategy_name, "entry_trigger_not_met")
