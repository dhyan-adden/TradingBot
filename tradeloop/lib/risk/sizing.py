def atr_position_size(
    capital_inr: float,
    entry_price: float,
    atr_value: float,
    risk_per_trade_pct: float,
    atr_stop_multiple: float = 2.0,
) -> int:
    if capital_inr <= 0:
        raise ValueError("capital must be positive")
    if entry_price <= 0:
        raise ValueError("entry price must be positive")
    if atr_value <= 0:
        return 0
    risk_budget = capital_inr * (risk_per_trade_pct / 100)
    per_share_risk = atr_value * atr_stop_multiple
    quantity = int(risk_budget // per_share_risk)
    affordable = int(capital_inr // entry_price)
    return max(0, min(quantity, affordable))


def capped_quantity(quantity: int, entry_price: float, capital_inr: float, max_allocation_pct: float) -> int:
    if quantity <= 0:
        return 0
    max_notional = capital_inr * (max_allocation_pct / 100)
    return max(0, min(quantity, int(max_notional // entry_price)))


def position_size_from_stop(
    equity_inr: float,
    entry_price: float,
    hard_stop: float,
    atr_value: float,
    per_trade_risk_pct: float = 1.5,
    atr_stop_multiple: float = 1.5,
) -> int:
    if equity_inr <= 0 or entry_price <= 0:
        raise ValueError("equity and entry must be positive")
    stop_distance = max(entry_price - hard_stop, atr_stop_multiple * atr_value)
    if stop_distance <= 0:
        return 0
    risk_budget = equity_inr * (per_trade_risk_pct / 100)
    return max(0, int(risk_budget // stop_distance))


def apply_guardrails(
    shares: int,
    entry_price: float,
    equity_inr: float,
    max_position_pct: float,
    adv20_inr: float | None = None,
    min_position_size_inr: float = 15000,
) -> int:
    if shares <= 0:
        return 0
    max_by_position = int((equity_inr * (max_position_pct / 100)) // entry_price)
    capped = min(shares, max_by_position)
    if adv20_inr is not None and adv20_inr > 0:
        capped = min(capped, int((adv20_inr * 0.01) // entry_price))
    if capped * entry_price < min_position_size_inr:
        return 0
    return max(0, capped)
