from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from tradeloop.lib.risk.checks import RiskCaps


@dataclass(frozen=True)
class Settings:
    raw: dict
    paper_starting_inr: float
    per_trade_risk_pct: float
    max_open_positions: int
    max_position_pct: float
    max_total_deployed_pct: float
    max_sector_pct: float
    daily_drawdown_pct: float
    max_open_risk_pct: float
    min_position_size_inr: float
    promotion_gates: dict
    cycle_timeout_seconds: int


def load_settings(path: Path) -> Settings:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    capital = data.get("capital", {})
    gates = data.get("live_promotion_gates", {})
    return Settings(
        raw=data,
        paper_starting_inr=float(capital.get("paper_starting_inr", 100000)),
        per_trade_risk_pct=float(capital.get("per_trade_risk_pct", 1.5)),
        max_open_positions=int(capital.get("max_concurrent_positions", 4)),
        max_position_pct=float(capital.get("max_position_pct", 25)),
        max_total_deployed_pct=float(capital.get("max_total_deployed_pct", 90)),
        max_sector_pct=float(capital.get("max_sector_exposure_pct", 40)),
        daily_drawdown_pct=float(capital.get("daily_drawdown_circuit_pct", 3)),
        max_open_risk_pct=float(capital.get("max_open_risk_pct", 4.0)),
        min_position_size_inr=float(capital.get("min_position_size_inr", 15000)),
        promotion_gates=dict(gates),
        cycle_timeout_seconds=int(data.get("cycle_timeout_seconds", 1200)),
    )


def risk_caps(settings: Settings, universe: Iterable[str], capital_inr: float) -> RiskCaps:
    return RiskCaps(
        capital_inr=float(capital_inr),
        max_open_positions=settings.max_open_positions,
        max_position_allocation_pct=settings.max_position_pct,
        max_total_deployed_pct=settings.max_total_deployed_pct,
        max_sector_allocation_pct=settings.max_sector_pct,
        max_daily_drawdown_pct=settings.daily_drawdown_pct,
        universe=[str(s).strip().upper() for s in universe],
        max_open_risk_pct=settings.max_open_risk_pct,
        min_position_size_inr=settings.min_position_size_inr,
    )
