from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class MarketRegime:
    regime: str
    cycle: str
    risk_posture: str
    setup_count: int
    strong_setup_count: int
    average_score: float
    strategy_bias: dict[str, str]
    reasons: list[str]


_RISK_TERMS = (
    "crash", "selloff", "war", "oil", "inflation", "fed", "rupee", "inr",
    "tariff", "rate hike", "recession",
)


def classify_market_regime(setups: Iterable[object], macro_items: Iterable[object]) -> MarketRegime:
    rows = list(setups)
    scores = [float(getattr(s, "cleanliness_score", 0.0) or 0.0) for s in rows]
    setup_types = [str(getattr(s, "setup_type", "")).lower() for s in rows]
    setup_count = len(rows)
    strong = sum(1 for score in scores if score >= 7.0)
    average = round(sum(scores) / setup_count, 2) if setup_count else 0.0
    breakout = sum(1 for item in setup_types if "breakout" in item)
    pullback = sum(1 for item in setup_types if "pullback" in item)
    macro_titles = " ".join(str(getattr(item, "title", "")) for item in macro_items).lower()
    macro_risk = sum(1 for term in _RISK_TERMS if term in macro_titles)

    reasons: list[str] = []
    if setup_count == 0:
        reasons.append("no tradeable technical setups found")
        return MarketRegime(
            regime="data_sparse", cycle="unknown", risk_posture="no_new_entries",
            setup_count=0, strong_setup_count=0, average_score=0.0,
            strategy_bias=_bias("avoid", "avoid", "avoid", "avoid"), reasons=reasons)

    reasons.append(f"{setup_count} tradeable setups, {strong} strong setups, average score {average}")
    if macro_risk:
        reasons.append(f"{macro_risk} macro risk terms detected")

    if macro_risk >= 3 and strong < 5:
        regime, cycle, posture = "risk_off", "contraction", "reduced"
        bias = _bias("avoid", "favor", "avoid", "avoid")
    elif strong >= 25 and breakout >= pullback:
        regime, cycle, posture = "trend_up", "expansion", "normal"
        bias = _bias("favor", "neutral", "favor", "favor")
    elif strong >= 10 and pullback > breakout:
        regime, cycle, posture = "pullback_in_uptrend", "pullback", "normal"
        bias = _bias("neutral", "favor", "neutral", "favor")
    elif average < 5.5 or strong < 5:
        regime, cycle, posture = "choppy", "range", "reduced"
        bias = _bias("avoid", "neutral", "avoid", "neutral")
    else:
        regime, cycle, posture = "range_bound", "range", "reduced"
        bias = _bias("neutral", "favor", "avoid", "neutral")

    return MarketRegime(
        regime=regime, cycle=cycle, risk_posture=posture,
        setup_count=setup_count, strong_setup_count=strong, average_score=average,
        strategy_bias=bias, reasons=reasons)


def _bias(trend: str, mean_reversion: str, breakout: str, momentum_pullback: str) -> dict[str, str]:
    return {
        "trend_following": trend,
        "mean_reversion": mean_reversion,
        "breakout_continuation": breakout,
        "momentum_pullback": momentum_pullback,
        "news_catalyst": "confirm_only",
        "position_management": "always_on",
    }


def render_market_regime(regime: MarketRegime) -> str:
    lines = [
        "# Market Regime",
        "",
        f"- regime: {regime.regime}",
        f"- cycle: {regime.cycle}",
        f"- risk_posture: {regime.risk_posture}",
        f"- setup_count: {regime.setup_count}",
        f"- strong_setup_count: {regime.strong_setup_count}",
        f"- average_score: {regime.average_score}",
        "",
        "## Strategy Bias",
    ]
    for strategy, bias in regime.strategy_bias.items():
        lines.append(f"- {strategy}: {bias}")
    lines += ["", "## Reasons"]
    lines.extend(f"- {reason}" for reason in regime.reasons)
    lines.append("")
    return "\n".join(lines)


def dump_market_regime(regime: MarketRegime) -> str:
    return json.dumps(asdict(regime), indent=2, sort_keys=True)
