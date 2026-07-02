from pathlib import Path


def kill_switch_active(root: Path) -> bool:
    return (root / "kill_switch.md").exists()


def drawdown_circuit_active(daily_pnl_inr: float, equity_inr: float, max_drawdown_pct: float) -> bool:
    if equity_inr <= 0:
        return True
    return daily_pnl_inr <= -(equity_inr * (max_drawdown_pct / 100))

