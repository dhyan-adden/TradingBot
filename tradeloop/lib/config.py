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
    approval_mode: str
    allow_auto_live: bool
    live_canary_enabled: bool
    live_canary_max_quantity: int
    promotion_min_closed_paper_trades: int
    promotion_min_win_rate: float
    promotion_min_expectancy_r: float
    promotion_max_drawdown_r: float
    promotion_require_clean_audits: bool
    llm_stage_budgets: dict
    cycle_timeout_seconds: int


def load_settings(path: Path) -> Settings:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    capital = data.get("capital", {})
    gates = data.get("live_promotion_gates", {})
    execution = data.get("execution", {}) or {}
    approval_mode = str(execution.get("approval_mode", "human_in_loop"))
    if approval_mode not in {"human_in_loop", "auto"}:
        raise ValueError(f"invalid execution.approval_mode: {approval_mode}")
    canary = execution.get("live_canary", {}) or {}
    promo = execution.get("promotion", {}) or {}
    return Settings(
        raw=data,
        paper_starting_inr=float(capital.get("paper_starting_inr", 100000)),
        per_trade_risk_pct=float(capital.get("per_trade_risk_pct", 1.5)),
        max_open_positions=int(capital.get("max_concurrent_positions", 4)),
        max_position_pct=float(capital.get("max_position_pct", 25)),
        max_total_deployed_pct=float(capital.get("max_total_deployed_pct", 90)),
        max_sector_pct=float(capital.get("max_sector_exposure_pct", 50)),
        daily_drawdown_pct=float(capital.get("daily_drawdown_circuit_pct", 3)),
        max_open_risk_pct=float(capital.get("max_open_risk_pct", 4.0)),
        min_position_size_inr=float(capital.get("min_position_size_inr", 15000)),
        promotion_gates=dict(gates),
        approval_mode=approval_mode,
        allow_auto_live=bool(execution.get("allow_auto_live", False)),
        live_canary_enabled=bool(canary.get("enabled", True)),
        live_canary_max_quantity=int(canary.get("max_quantity", 1)),
        promotion_min_closed_paper_trades=int(promo.get("min_closed_paper_trades", 1)),
        promotion_min_win_rate=float(promo.get("min_win_rate", 0.45)),
        promotion_min_expectancy_r=float(promo.get("min_expectancy_r", 0.3)),
        promotion_max_drawdown_r=float(promo.get("max_drawdown_r", 8.0)),
        promotion_require_clean_audits=bool(promo.get("require_clean_audits", True)),
        llm_stage_budgets=dict(data.get("llm_stages", {}) or {}),
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
