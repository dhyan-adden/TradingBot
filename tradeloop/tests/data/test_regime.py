from tradeloop.lib.data.regime import classify_market_regime, render_market_regime
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.ta.scanner import SetupScan


def _scan(symbol: str, setup_type: str, score: float) -> SetupScan:
    return SetupScan(
        ticker=symbol, setup_type=setup_type, cleanliness_score=score,
        entry_zone="100", stop_zone="95", target_zone="110/115", volume_context="ok")


def test_regime_is_data_sparse_without_setups():
    regime = classify_market_regime([], [])
    assert regime.regime == "data_sparse"
    assert regime.risk_posture == "no_new_entries"
    assert regime.strategy_bias["trend_following"] == "avoid"


def test_regime_favors_trend_when_many_breakouts_are_strong():
    setups = [_scan(f"S{i}", "20d_breakout", 8.0) for i in range(25)]
    regime = classify_market_regime(setups, [])
    assert regime.regime == "trend_up"
    assert regime.cycle == "expansion"
    assert regime.strategy_bias["trend_following"] == "favor"


def test_regime_reduces_risk_when_macro_risk_dominates_weak_scan():
    macro = [RawItem("n1", "Oil inflation Fed rupee selloff", "u", "s", "tier_A", "t")]
    setups = [_scan("S1", "ema20_pullback", 6.0)]
    regime = classify_market_regime(setups, macro)
    assert regime.regime == "risk_off"
    assert regime.risk_posture == "reduced"
    assert regime.strategy_bias["breakout_continuation"] == "avoid"


def test_render_market_regime_is_expert_readable():
    regime = classify_market_regime([_scan("S1", "ema20_pullback", 8.0) for _ in range(10)], [])
    text = render_market_regime(regime)
    assert "# Market Regime" in text
    assert "mean_reversion" in text
    assert "risk_posture" in text
