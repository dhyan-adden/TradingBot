from pathlib import Path

import pytest
import yaml

from tradingbot.config import load_config


def test_default_config_loads() -> None:
    config = load_config(Path("config"))

    assert config.system.mode == "paper"
    assert config.system.market == "india"
    assert config.system.timezone == "Asia/Kolkata"
    assert config.raw["system"]["currency"] == "INR"
    assert config.raw["system"]["data"]["benchmarks"]["NSE"] == "^NSEI"
    assert config.raw["system"]["data"]["symbol_suffixes"]["BSE"] == ".BO"
    assert config.risk.max_open_positions == 5
    assert config.compliance.live_trading_enabled is False


def test_live_mode_is_rejected(tmp_path: Path) -> None:
    for source in Path("config").glob("*.yaml"):
        target = tmp_path / source.name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    system = yaml.safe_load((tmp_path / "system.yaml").read_text(encoding="utf-8"))
    system["mode"] = "live"
    (tmp_path / "system.yaml").write_text(yaml.safe_dump(system), encoding="utf-8")

    with pytest.raises(ValueError, match="paper mode"):
        load_config(tmp_path)


def test_invalid_risk_limits_are_rejected(tmp_path: Path) -> None:
    for source in Path("config").glob("*.yaml"):
        target = tmp_path / source.name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    risk = yaml.safe_load((tmp_path / "risk.yaml").read_text(encoding="utf-8"))
    risk["max_total_deployed_pct"] = 10
    risk["max_position_allocation_pct"] = 20
    (tmp_path / "risk.yaml").write_text(yaml.safe_dump(risk), encoding="utf-8")

    with pytest.raises(ValueError, match="Total deployed"):
        load_config(tmp_path)
