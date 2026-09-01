from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_settings_yaml_has_phase0_knobs() -> None:
    data = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    assert data["capital"]["max_total_deployed_pct"] == 90
    assert data["cycle_timeout_seconds"] == 3600


from tradeloop.lib.config import load_settings, risk_caps


def test_load_settings_and_risk_caps_mapping() -> None:
    settings = load_settings(ROOT / "config" / "settings.yaml")
    assert settings.paper_starting_inr == 100000
    assert settings.max_open_positions == 6
    assert settings.max_position_pct == 25
    assert settings.max_total_deployed_pct == 90
    assert settings.max_sector_pct == 50  # raised 2026-07-07: user-approved two-bank entry
    assert settings.daily_drawdown_pct == 3
    assert settings.promotion_gates["min_paper_trades"] == 40
    assert settings.cycle_timeout_seconds == 3600

    caps = risk_caps(settings, ["RELIANCE", "TCS"], capital_inr=250000.0)
    assert caps.capital_inr == 250000.0
    assert caps.max_open_positions == 6
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
                "stt_buy_cnc_pct", "stt_sell_cnc_pct", "stt_sell_mis_pct",
                "exchange_transaction_pct", "sebi_turnover_pct", "stamp_buy_cnc_pct",
                "stamp_buy_mis_pct", "gst_pct", "dp_charge_inr_per_scrip"]:
        assert params[key].default == costs[key], key


from tradeloop.lib.broker.router import live_promotion_ready


def test_promotion_gate_ignores_markdown(tmp_path) -> None:
    # Phase 6: live_promotion_ready delegates to the ledger/audit promotion
    # service; a markdown performance report is no longer authoritative.
    root = tmp_path / "tradeloop"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "strategy_performance.md").write_text(
        "live_ready: true\npaper_trades: 9999\nwin_rate: 0.9\nexpectancy_r: 5.0\n",
        encoding="utf-8",
    )
    settings = load_settings(ROOT / "config" / "settings.yaml")
    # No ledger -> not ready, markdown claims ignored.
    assert live_promotion_ready(root, settings) is False


def test_execution_mode_defaults_are_safe() -> None:
    settings = load_settings(ROOT / "config" / "settings.yaml")
    assert settings.approval_mode == "auto"
    assert settings.allow_auto_live is False
    assert settings.auto_route_min_conviction == 6.5
    assert settings.live_canary_enabled is True
    assert settings.live_canary_max_quantity == 1
    assert settings.promotion_min_closed_paper_trades == 60
    assert settings.promotion_min_win_rate == 0.45
    assert settings.promotion_min_expectancy_r == 0.3
    assert settings.promotion_max_drawdown_r == 8.0
    assert settings.promotion_require_clean_audits is True


def test_invalid_approval_mode_fails_to_load(tmp_path) -> None:
    import pytest

    root = tmp_path / "tradeloop"
    (root / "config").mkdir(parents=True)
    data = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    data["execution"] = {"approval_mode": "weird_value"}
    (root / "config" / "settings.yaml").write_text(
        yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_settings(root / "config" / "settings.yaml")


def test_live_ready_literal_cannot_enable_promotion(tmp_path) -> None:
    root = tmp_path / "tradeloop"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "strategy_performance.md").write_text(
        "live_ready: true\npaper_trades: 0\n", encoding="utf-8")
    settings = load_settings(ROOT / "config" / "settings.yaml")
    assert live_promotion_ready(root, settings) is False


def test_live_ready_literal_with_59_trades_still_fails(tmp_path) -> None:
    root = tmp_path / "tradeloop"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "strategy_performance.md").write_text(
        "live_ready: true\npaper_trades: 59\n", encoding="utf-8")
    settings = load_settings(ROOT / "config" / "settings.yaml")
    assert live_promotion_ready(root, settings) is False


def test_missing_performance_report_blocks_promotion(tmp_path) -> None:
    root = tmp_path / "tradeloop"
    (root / "memory").mkdir(parents=True)
    settings = load_settings(ROOT / "config" / "settings.yaml")
    assert live_promotion_ready(root, settings) is False


def test_passing_trades_but_failing_expectancy_blocks_promotion(tmp_path) -> None:
    root = tmp_path / "tradeloop"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "strategy_performance.md").write_text(
        "paper_trades: 60\nwin_rate: 0.9\nexpectancy_r: 0.0\nmax_drawdown_pct: 1\n",
        encoding="utf-8")
    settings = load_settings(ROOT / "config" / "settings.yaml")
    assert live_promotion_ready(root, settings) is False
