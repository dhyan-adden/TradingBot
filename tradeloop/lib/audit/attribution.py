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
    # stable identity of the closing fill - journal/dossier entries key on this so
    # re-running attribution over the full ledger never duplicates them
    close_ref: str = ""


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


def _episodes(fills: List[dict]) -> List[dict]:
    """Chronological per-symbol round trips: an episode opens on a BUY from flat and
    closes when the position returns to zero. Re-entries form NEW episodes instead
    of merging into one VWAP blob, and each episode keeps its ENTRY fill (which
    carries the plan's hard_stop/target_1/strategy_family, stamped at route time)."""
    open_eps: Dict[str, dict] = {}
    counts: Dict[str, int] = {}
    closed: List[dict] = []
    for f in fills:
        # Ledger ORDER_FILLED events carry no "status" key; default FILLED so real
        # replayed fills are attributed (else paper_trades stays 0 forever).
        if str(f.get("status", "FILLED")).upper() != "FILLED":
            continue
        symbol = str(f["symbol"]).strip().upper()
        side = str(f["side"]).upper()
        qty = int(f["quantity"])
        price = float(f["fill_price"])
        ep = open_eps.get(symbol)
        if ep is None:
            if side != "BUY":
                continue  # exit with no tracked entry (pre-ledger history)
            counts[symbol] = counts.get(symbol, 0) + 1
            ep = open_eps[symbol] = {
                "symbol": symbol, "n": counts[symbol], "net": 0, "entry_fill": f,
                "buy_qty": 0, "buy_val": 0.0, "sell_qty": 0, "sell_val": 0.0,
            }
        if side == "BUY":
            ep["net"] += qty
            ep["buy_qty"] += qty
            ep["buy_val"] += qty * price
        else:
            ep["net"] -= qty
            ep["sell_qty"] += qty
            ep["sell_val"] += qty * price
        if ep["net"] <= 0:
            ep["close_ref"] = str(f.get("order_id") or f"trade-{ep['n']}")
            closed.append(open_eps.pop(symbol))
    return closed


def report(trade_plans, fills: List[dict]) -> StrategyPerformance:
    plans = _plans_by_symbol(trade_plans)
    trades: List[TradeAttribution] = []

    for ep in _episodes(fills):
        symbol = ep["symbol"]
        entry = round(ep["buy_val"] / ep["buy_qty"], 6)
        exit_price = round(ep["sell_val"] / ep["sell_qty"], 6)
        # Plan data comes from the episode's own entry fill; the run's orders.json
        # is only a fallback for fills recorded before route-time stamping existed.
        entry_fill, plan = ep["entry_fill"], plans.get(symbol)
        stop = float(entry_fill.get("hard_stop") or 0.0)
        if stop <= 0 and plan is not None and plan.hard_stop is not None:
            stop = float(plan.hard_stop)
        risk = entry - stop
        if stop <= 0 or risk <= 0:
            continue  # R is undefined without a recorded stop - never fabricate a 0R trade
        target = entry_fill.get("target_1")
        if target is None and plan is not None:
            target = plan.target_1
        target = float(target) if target is not None else None
        strategy = str(entry_fill.get("strategy_family")
                       or (plan.strategy_family if plan is not None else None) or "unknown")
        realized = round((exit_price - entry) / risk, 4)
        hit_target = target is not None and exit_price >= target
        hit_stop = exit_price <= stop
        trades.append(TradeAttribution(
            symbol=symbol,
            strategy_family=strategy,
            expected_r=round((target - entry) / risk, 4) if target is not None else 0.0,
            realized_r=realized,
            outcome=classify_outcome(realized, hit_target, hit_stop),
            close_ref=ep["close_ref"],
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
