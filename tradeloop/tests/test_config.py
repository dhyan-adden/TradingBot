from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_settings_yaml_has_phase0_knobs() -> None:
    data = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    assert data["capital"]["max_total_deployed_pct"] == 90
    assert data["cycle_timeout_seconds"] == 1800


from tradeloop.lib.config import load_settings, risk_caps


def test_load_settings_and_risk_caps_mapping() -> None:
    settings = load_settings(ROOT / "config" / "settings.yaml")
    assert settings.paper_starting_inr == 100000
    assert settings.max_open_positions == 4
    assert settings.max_position_pct == 25
    assert settings.max_total_deployed_pct == 90
    assert settings.max_sector_pct == 50  # raised 2026-07-07: user-approved two-bank entry
    assert settings.daily_drawdown_pct == 3
    assert settings.promotion_gates["min_paper_trades"] == 40
    assert settings.cycle_timeout_seconds == 1800

    caps = risk_caps(settings, ["RELIANCE", "TCS"], capital_inr=250000.0)
    assert caps.capital_inr == 250000.0
    assert caps.max_open_positions == 4
    assert caps.max_position_allocation_pct == 25
    assert caps.max_total_deployed_pct == 90
    assert caps.max_sector_allocation_pct == 50
    assert caps.max_daily_drawdown_pct == 3
    assert caps.max_open_risk_pct == 4.0
    assert caps.min_position_size_inr == 15000
    assert set(caps.universe) == {"RELIANCE", "TCS"}


def test_cost_model_defaults_match_settings_costs() -> None:
    # ponytail: cost_model keeps its hardcoded defaults in P0 (spec §5.1 refactor
    # deferred); this tripwire fails the suite if they ever drift from settings.yaml.
    import inspect

    from tradeloop.lib.broker.cost_model import estimate_cost

    params = inspect.signature(estimate_cost).parameters
    costs = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))["costs"]
    for key in ["cnc_brokerage_inr", "mis_brokerage_inr_max", "mis_brokerage_pct",
                "stt_sell_cnc_pct", "stt_sell_mis_pct", "stamp_buy_cnc_pct",
                "stamp_buy_mis_pct", "gst_pct", "dp_charge_inr_per_scrip"]:
        assert params[key].default == costs[key], key


from tradeloop.lib.broker.router import live_promotion_ready


def test_promotion_gate_reads_thresholds_from_settings(tmp_path) -> None:
    root = tmp_path / "tradeloop"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "strategy_performance.md").write_text(
        "paper_trades: 5\nwin_rate: 0.9\nexpectancy_r: 1.0\nmax_drawdown_pct: 1\n",
        encoding="utf-8",
    )
    settings = load_settings(ROOT / "config" / "settings.yaml")
    # 5 paper trades < 40 required by settings -> not ready.
    assert live_promotion_ready(root, settings) is False

    class LooseSettings:
        promotion_gates = {"min_paper_trades": 1, "min_win_rate": 0.1,
                           "min_expectancy_r": 0.1, "max_drawdown_pct": 50}
    assert live_promotion_ready(root, LooseSettings()) is True
