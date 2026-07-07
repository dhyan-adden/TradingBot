from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from tradeloop.lib.audit.outcomes import Outcome, classify_outcome


@dataclass(frozen=True)
class TradeAttribution:
    symbol: str
    strategy_family: str
    expected_r: float
    realized_r: float
    outcome: Outcome


@dataclass(frozen=True)
class StrategyStat:
    strategy: str
    trades: int
    win_rate: float
    expectancy_r: float
    max_drawdown_pct: float


@dataclass(frozen=True)
class StrategyPerformance:
    trades: List[TradeAttribution]
    by_strategy: List[StrategyStat]
    paper_trades: int


def expected_r(order) -> float:
    entry = float(order.price)
    stop = order.hard_stop
    target = order.target_1
    if stop is None or target is None:
        return 0.0
    risk = entry - float(stop)
    if risk <= 0:
        return 0.0
    return round((float(target) - entry) / risk, 4)


def _plans_by_symbol(trade_plans) -> Dict[str, object]:
    return {o.ticker.strip().upper(): o for o in trade_plans.orders}


def _round_trips(fills: List[dict]) -> Dict[str, dict]:
    """Return {symbol: {entry_vwap, exit_vwap}} for symbols fully closed."""
    agg: Dict[str, dict] = {}
    for f in fills:
        # Ledger ORDER_FILLED events carry no "status" key; default FILLED so real
        # replayed fills are attributed (else paper_trades stays 0 forever).
        if str(f.get("status", "FILLED")).upper() != "FILLED":
            continue
        symbol = str(f["symbol"]).strip().upper()
        side = str(f["side"]).upper()
        qty = int(f["quantity"])
        price = float(f["fill_price"])
        a = agg.setdefault(symbol, {"buy_qty": 0, "buy_val": 0.0, "sell_qty": 0, "sell_val": 0.0})
        if side == "BUY":
            a["buy_qty"] += qty
            a["buy_val"] += qty * price
        else:
            a["sell_qty"] += qty
            a["sell_val"] += qty * price
    closed: Dict[str, dict] = {}
    for symbol, a in agg.items():
        if a["sell_qty"] > 0 and a["sell_qty"] >= a["buy_qty"] and a["buy_qty"] > 0:
            closed[symbol] = {
                "entry_vwap": round(a["buy_val"] / a["buy_qty"], 6),
                "exit_vwap": round(a["sell_val"] / a["sell_qty"], 6),
            }
    return closed


def report(trade_plans, fills: List[dict]) -> StrategyPerformance:
    plans = _plans_by_symbol(trade_plans)
    closed = _round_trips(fills)
    trades: List[TradeAttribution] = []

    for symbol, rt in sorted(closed.items()):
        plan = plans.get(symbol)
        if plan is None:
            continue
        entry, exit_price = rt["entry_vwap"], rt["exit_vwap"]
        stop = float(plan.hard_stop) if plan.hard_stop is not None else entry
        target = float(plan.target_1) if plan.target_1 is not None else None
        risk = entry - stop
        realized = round((exit_price - entry) / risk, 4) if risk > 0 else 0.0
        hit_target = target is not None and exit_price >= target
        hit_stop = exit_price <= stop
        trades.append(TradeAttribution(
            symbol=symbol,
            strategy_family=str(plan.strategy_family or "unknown"),
            expected_r=expected_r(plan),
            realized_r=realized,
            outcome=classify_outcome(realized, hit_target, hit_stop),
        ))

    return StrategyPerformance(trades=trades, by_strategy=_aggregate(trades), paper_trades=len(trades))


def _aggregate(trades: List[TradeAttribution]) -> List[StrategyStat]:
    groups: Dict[str, List[TradeAttribution]] = {}
    for t in trades:
        groups.setdefault(t.strategy_family, []).append(t)
    stats: List[StrategyStat] = []
    for strategy, group in sorted(groups.items()):
        n = len(group)
        wins = sum(1 for t in group if t.realized_r > 0)
        expectancy = round(sum(t.realized_r for t in group) / n, 4) if n else 0.0
        max_dd = round(abs(min((t.realized_r for t in group), default=0.0)), 4)
        stats.append(StrategyStat(strategy, n, round(wins / n, 4) if n else 0.0, expectancy, max_dd))
    return stats


def render_strategy_performance(perf: StrategyPerformance, live_ready: bool = False) -> str:
    # Patch C: the promotion gate (router.live_promotion_ready) reads portfolio
    # metrics via _metric's `key: <number>` regex, so emit them as top-level lines
    # BEFORE the per-strategy table (which stays as human context).
    rs = [t.realized_r for t in perf.trades]
    n = len(rs)
    win_rate = round(sum(1 for r in rs if r > 0) / n, 4) if n else 0.0
    expectancy_r = round(sum(rs) / n, 4) if n else 0.0
    # ponytail: worst single-trade LOSS in R, floored at 0 so wins never register
    #           as drawdown - a proxy, not a true equity-curve DD%. Upgrade to an
    #           equity-curve drawdown if the gate ever needs real DD.
    max_drawdown_pct = round(abs(min([0.0, *rs])), 4)
    lines = [
        "# Strategy Performance",
        "",
        f"live_ready: {'true' if live_ready else 'false'}",
        f"paper_trades: {perf.paper_trades}",
        f"win_rate: {win_rate}",
        f"expectancy_r: {expectancy_r}",
        f"max_drawdown_pct: {max_drawdown_pct}",
        "",
        "| Strategy | Trades | Win Rate | Expectancy R | Max Drawdown % | Confidence |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for s in perf.by_strategy:
        confidence = "trusted" if s.trades >= 10 else "provisional"
        lines.append(f"| {s.strategy} | {s.trades} | {s.win_rate} | {s.expectancy_r} | {s.max_drawdown_pct} | {confidence} |")
    lines.append("")
    return "\n".join(lines)
