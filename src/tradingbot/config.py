from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SystemConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: str = "paper"
    market: str = "india"
    timezone: str = "Asia/Kolkata"
    broker: str = "zerodha"

    @field_validator("mode")
    @classmethod
    def paper_only_for_day1(cls, value: str) -> str:
        if value != "paper":
            raise ValueError("Day 1 scaffold only supports paper mode")
        return value


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    paper_capital_inr: float = Field(gt=0)
    max_open_positions: int = Field(gt=0)
    max_position_allocation_pct: float = Field(gt=0, le=100)
    max_total_deployed_pct: float = Field(gt=0, le=100)
    allow_leverage: bool = False
    allow_short_selling: bool = False

    @model_validator(mode="after")
    def validate_limits(self) -> "RiskConfig":
        if self.allow_leverage:
            raise ValueError("Leverage is disabled for Day 1")
        if self.allow_short_selling:
            raise ValueError("Short selling is disabled for Day 1")
        if self.max_total_deployed_pct < self.max_position_allocation_pct:
            raise ValueError("Total deployed limit must be >= per-position limit")
        return self


class ComplianceConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    live_trading_enabled: bool = False
    max_orders_per_second: int = Field(gt=0, le=10)

    @field_validator("live_trading_enabled")
    @classmethod
    def live_disabled_for_day1(cls, value: bool) -> bool:
        if value:
            raise ValueError("Live trading must remain disabled for Day 1")
        return value


class TradingConfig(BaseModel):
    system: SystemConfig
    risk: RiskConfig
    compliance: ComplianceConfig
    raw: Dict[str, Any]


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("YAML config must be a mapping: {}".format(path))
    return data


def load_config(config_dir: Path) -> TradingConfig:
    raw = {
        "system": load_yaml(config_dir / "system.yaml"),
        "risk": load_yaml(config_dir / "risk.yaml"),
        "compliance": load_yaml(config_dir / "compliance.yaml"),
        "strategies": load_yaml(config_dir / "strategies.yaml"),
        "universe": load_yaml(config_dir / "universe.yaml"),
        "paper_broker": load_yaml(config_dir / "paper_broker.yaml"),
        "agents": load_yaml(config_dir / "agents.yaml"),
        "memory": load_yaml(config_dir / "memory.yaml"),
        "loop": load_yaml(config_dir / "loop.yaml"),
    }
    return TradingConfig(
        system=SystemConfig(**raw["system"]),
        risk=RiskConfig(**raw["risk"]),
        compliance=ComplianceConfig(**raw["compliance"]),
        raw=raw,
    )
