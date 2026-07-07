from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

import yaml


@dataclass(frozen=True)
class PortfolioState:
    cash_inr: float
    positions: Dict[str, int] = field(default_factory=dict)
    avg_prices: Dict[str, float] = field(default_factory=dict)
    hard_stops: Dict[str, float] = field(default_factory=dict)
    equity_inr: float = 0.0
    daily_pnl_inr: float = 0.0


def empty_state_from_settings(settings_path: Path) -> PortfolioState:
    data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    cash = float(data.get("capital", {}).get("paper_starting_inr", 100000))
    return PortfolioState(cash_inr=cash, equity_inr=cash)


def render_context(state: PortfolioState, mode: str, macro: str = "") -> str:
    lines = [
        "# Context",
        "",
        f"Mode: {mode}",
        f"Cash INR: {state.cash_inr}",
        f"Equity INR: {state.equity_inr or state.cash_inr}",
        f"Daily P&L INR: {state.daily_pnl_inr}",
        "",
        "## Positions",
    ]
    if not state.positions:
        lines.append("- None")
    for symbol, quantity in sorted(state.positions.items()):
        line = f"- {symbol}: quantity={quantity}, avg_price={state.avg_prices.get(symbol, 0)}"
        if state.hard_stops.get(symbol):
            line += f", hard_stop={state.hard_stops[symbol]}"
        lines.append(line)
    lines.extend(["", "## Macro Snapshot", macro.strip() or "No macro snapshot yet.", ""])
    return "\n".join(lines)

