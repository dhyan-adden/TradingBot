import argparse
import threading
import time
from pathlib import Path

from tradingbot.agent_loop import AgentLoopRunner
from tradingbot.agents.workflow import PaperTradingWorkflow
from tradingbot.autonomous import AutonomousLoopRunner
from tradingbot.broker.paper import PaperBroker, PaperOrderRequest
from tradingbot.config import load_config
from tradingbot.dashboard import serve_dashboard
from tradingbot.data.yfinance import YFinanceMarketDataAdapter
from tradingbot.event_log import EventLog
from tradingbot.loop import ClosedLoopRunner
from tradingbot.memory.projections import MemoryProjector
from tradingbot.order_gate import OrderGate, latest_order_gate_mode, set_order_gate_mode
from tradingbot.research import GoogleNewsRSSProvider, summarize_research
from tradingbot.risk.engine import RiskEngine, RiskLimits


def config_check(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config_dir))
    print("config=OK mode={} broker={}".format(config.system.mode, config.system.broker))
    return 0


def event_smoke(args: argparse.Namespace) -> int:
    event_log = EventLog(Path(args.db))
    event = event_log.append_event(
        event_type="signal.generated",
        aggregate_id="SMOKE-AGGREGATE",
        payload={"symbol": "RELIANCE", "strategy": "daily_breakout_v1", "action": "watch"},
    )
    replayed = list(event_log.replay("SMOKE-AGGREGATE"))
    print("event_smoke=OK events={} last_hash={}".format(len(replayed), event.event_hash[:12]))
    return 0


def _event_log_from_config(config) -> EventLog:
    return EventLog(Path(config.raw["system"]["state"]["sqlite_path"]))


def _paper_broker(config, event_log: EventLog) -> PaperBroker:
    paper_config = config.raw["paper_broker"]
    return PaperBroker(
        event_log=event_log,
        starting_cash_inr=float(paper_config.get("starting_cash_inr", config.risk.paper_capital_inr)),
        order_prefix=str(paper_config.get("order_id_prefix", "PAPER")),
    )


def _risk_engine(config, broker: PaperBroker) -> RiskEngine:
    risk_config = config.raw["risk"]
    kill_event = broker.event_log.latest("system.kill_switch")
    kill_switch_active = bool(kill_event and kill_event.payload.get("active"))
    return RiskEngine(
        RiskLimits(
            paper_capital_inr=config.risk.paper_capital_inr,
            max_open_positions=config.risk.max_open_positions,
            max_position_allocation_pct=config.risk.max_position_allocation_pct,
            max_total_deployed_pct=config.risk.max_total_deployed_pct,
            allow_short_selling=config.risk.allow_short_selling,
            kill_switch_enabled=bool(risk_config.get("kill_switch", {}).get("enabled", True)),
        ),
        universe=config.raw["universe"].get("symbols", []),
        kill_switch_active=kill_switch_active,
    )


def paper_status(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config_dir))
    event_log = _event_log_from_config(config)
    broker = _paper_broker(config, event_log)
    portfolio = broker.portfolio()
    print(
        "paper_status cash_inr={} open_positions={} realized_pnl_inr={}".format(
            portfolio.cash_inr,
            len(portfolio.positions),
            portfolio.realized_pnl_inr,
        )
    )
    for symbol, quantity in sorted(portfolio.positions.items()):
        print(
            "position symbol={} quantity={} avg_price={}".format(
                symbol,
                quantity,
                portfolio.avg_prices.get(symbol, 0),
            )
        )
    return 0


def paper_order(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config_dir))
    event_log = _event_log_from_config(config)
    broker = _paper_broker(config, event_log)
    request = PaperOrderRequest(
        symbol=args.symbol,
        side=args.side,
        quantity=args.quantity,
        price=args.price,
        strategy=args.strategy,
        source="manual",
    )
    decision = _risk_engine(config, broker).evaluate(request, broker.portfolio())
    event_log.append_event(
        "risk.approved" if decision.approved else "risk.rejected",
        f"RISK-{args.symbol.upper()}",
        {"symbol": args.symbol.upper(), "approved": decision.approved, "reasons": decision.reasons},
    )
    if not decision.approved:
        print("paper_order=REJECTED reasons={}".format(",".join(decision.reasons)))
        return 2
    event = broker.place_order(request)
    print("paper_order={} order_id={}".format(event.event_type, event.aggregate_id))
    return 0


def paper_loop(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config_dir))
    event_log = _event_log_from_config(config)
    broker = _paper_broker(config, event_log)
    projector = MemoryProjector(event_log, Path(config.raw["system"]["state"]["memory_root"]))
    workflow = PaperTradingWorkflow(
        market_data=YFinanceMarketDataAdapter(),
        risk_engine=_risk_engine(config, broker),
        broker=broker,
        projector=projector,
        event_log=event_log,
    )
    symbols = args.symbols or config.raw["universe"].get("symbols", [])[:1]
    poll_interval = args.poll_interval_seconds
    if poll_interval is None:
        poll_interval = int(config.raw["system"].get("data", {}).get("poll_interval_seconds", 60))
    for iteration in range(args.iterations):
        for symbol in symbols:
            state = workflow.run_once(
                symbol=symbol,
                quantity=args.quantity,
                strategy=args.strategy,
                side="BUY" if args.buy else None,
            )
            print(
                "paper_loop iteration={} symbol={} price={} risk_reasons={} order_id={}".format(
                    iteration + 1,
                    state.symbol,
                    state.quote["last_price"] if state.quote else "NA",
                    ",".join(state.risk_reasons or []),
                    state.order_id or "NONE",
                )
            )
        if iteration + 1 < args.iterations and poll_interval > 0:
            time.sleep(poll_interval)
    return 0


def memory_regenerate(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config_dir))
    event_log = _event_log_from_config(config)
    broker = _paper_broker(config, event_log)
    projector = MemoryProjector(event_log, Path(config.raw["system"]["state"]["memory_root"]))
    results = projector.regenerate_daily(dry_run=args.dry_run)
    results.append(projector.regenerate_scorecard(broker, dry_run=args.dry_run))
    changed = [result for result in results if result.changed]
    print("memory_regenerate dry_run={} changed={}".format(args.dry_run, len(changed)))
    for result in changed:
        print(str(result.path))
    return 0


def kill_switch(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config_dir))
    event_log = _event_log_from_config(config)
    active = args.state == "on"
    event_log.append_event("system.kill_switch", "SYSTEM", {"active": active})
    print("kill_switch={}".format("ON" if active else "OFF"))
    return 0


def dashboard(args: argparse.Namespace) -> int:
    serve_dashboard(args.host, args.port, Path(args.config_dir))
    return 0


def closed_loop(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config_dir))
    event_log = _event_log_from_config(config)
    broker = _paper_broker(config, event_log)
    runner = ClosedLoopRunner(
        config=config,
        event_log=event_log,
        market_data=YFinanceMarketDataAdapter(),
        broker=broker,
        risk_engine=_risk_engine(config, broker),
        memory_projector=MemoryProjector(event_log, Path(config.raw["system"]["state"]["memory_root"])),
    )
    loop_config = config.raw["loop"]
    symbols = args.symbols or config.raw["universe"].get("symbols", [])[: int(loop_config.get("max_symbols_per_cycle", 10))]
    cycles = 1 if args.once else int(args.cycles or loop_config.get("max_cycles") or 1)
    poll_interval = args.poll_interval_seconds
    if poll_interval is None:
        poll_interval = int(loop_config.get("poll_interval_seconds", 60))
    dry_run = bool(args.dry_run or loop_config.get("dry_run_default", False))
    result = runner.run(symbols=symbols, cycles=cycles, poll_interval_seconds=poll_interval, dry_run=dry_run)
    print(
        "closed_loop cycles={} symbols={} signals={} orders={} dry_run={}".format(
            result.cycles,
            ",".join(result.symbols),
            result.signals_generated,
            result.orders_created,
            result.dry_run,
        )
    )
    return 0


def _agent_loop_runner(config, event_log: EventLog, broker: PaperBroker, order_gate: OrderGate | None = None) -> AgentLoopRunner:
    return AgentLoopRunner(
        config=config,
        event_log=event_log,
        market_data=YFinanceMarketDataAdapter(),
        research_provider=GoogleNewsRSSProvider(),
        broker=broker,
        risk_engine=_risk_engine(config, broker),
        memory_projector=MemoryProjector(event_log, Path(config.raw["system"]["state"]["memory_root"])),
        order_gate=order_gate,
    )


def agent_loop(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config_dir))
    event_log = _event_log_from_config(config)
    broker = _paper_broker(config, event_log)
    runner = _agent_loop_runner(config, event_log, broker)
    loop_config = config.raw["loop"]
    symbols = args.symbols or config.raw["universe"].get("symbols", [])[: int(loop_config.get("max_symbols_per_cycle", 10))]
    cycles = 1 if args.once else int(args.cycles or loop_config.get("max_cycles") or 1)
    poll_interval = args.poll_interval_seconds
    if poll_interval is None:
        poll_interval = int(loop_config.get("poll_interval_seconds", 60))
    dry_run = bool(args.dry_run or loop_config.get("dry_run_default", False))
    result = runner.run(symbols=symbols, cycles=cycles, poll_interval_seconds=poll_interval, dry_run=dry_run)
    print(
        "agent_loop cycles={} symbols={} research_items={} signals={} vetoes={} orders={} dry_run={}".format(
            result.cycles,
            ",".join(result.symbols),
            result.research_items,
            result.signals_generated,
            result.vetoes,
            result.orders_created,
            result.dry_run,
        )
    )
    return 0


def autonomous_server(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config_dir))
    event_log = _event_log_from_config(config)
    broker = _paper_broker(config, event_log)
    loop_config = config.raw["loop"]
    gate_config = loop_config.get("execution", {}).get("order_gate", {})
    configured_mode = str(args.order_gate_mode or gate_config.get("mode", "autopilot"))
    set_order_gate_mode(event_log, configured_mode)
    active_mode = latest_order_gate_mode(event_log, configured_mode)
    order_gate = OrderGate(
        event_log=event_log,
        mode=active_mode,
        cancel_window_seconds=float(args.cancel_window_seconds if args.cancel_window_seconds is not None else gate_config.get("cancel_window_seconds", 30)),
    )
    research_provider = GoogleNewsRSSProvider()
    agent_runner = AgentLoopRunner(
        config=config,
        event_log=event_log,
        market_data=YFinanceMarketDataAdapter(),
        research_provider=research_provider,
        broker=broker,
        risk_engine=_risk_engine(config, broker),
        memory_projector=MemoryProjector(event_log, Path(config.raw["system"]["state"]["memory_root"])),
        order_gate=order_gate,
    )
    runner = AutonomousLoopRunner(
        event_log=event_log,
        agent_runner=agent_runner,
        research_provider=research_provider,
        universe=config.raw["universe"].get("symbols", []),
        loop_config=loop_config,
    )
    cycles = 1 if args.once else int(args.cycles or loop_config.get("max_cycles") or 1_000_000)
    poll_interval = args.poll_interval_seconds
    if poll_interval is None:
        poll_interval = int(loop_config.get("poll_interval_seconds", 60))
    dry_run = bool(args.dry_run or loop_config.get("dry_run_default", False))

    event_log.append_event(
        "autonomous_server.started",
        "AUTONOMOUS_SERVER",
        {
            "host": args.host,
            "port": args.port,
            "cycles": cycles,
            "dry_run": dry_run,
            "order_gate_mode": active_mode,
        },
    )
    dashboard_thread = threading.Thread(
        target=serve_dashboard,
        args=(args.host, args.port, Path(args.config_dir)),
        daemon=True,
    )
    dashboard_thread.start()
    print(f"autonomous_dashboard=http://{args.host}:{args.port}")
    try:
        result = runner.run(cycles=cycles, poll_interval_seconds=poll_interval, dry_run=dry_run)
    except KeyboardInterrupt:
        event_log.append_event("autonomous_server.stopped", "AUTONOMOUS_SERVER", {"reason": "keyboard_interrupt"})
        print("autonomous_server=STOPPED")
        return 130
    print(
        "autonomous_server cycles={} shortlist={} research_items={} signals={} vetoes={} orders={} dry_run={}".format(
            result.cycles,
            ",".join(result.shortlisted_symbols),
            result.research_items,
            result.signals_generated,
            result.vetoes,
            result.orders_created,
            result.dry_run,
        )
    )
    return 0


def research_smoke(args: argparse.Namespace) -> int:
    provider = GoogleNewsRSSProvider()
    items = provider.fetch(args.symbol)
    summary = summarize_research(args.symbol, items)
    print(
        "research_smoke symbol={} items={} sentiment={}".format(
            args.symbol.upper(),
            len(items),
            summary.sentiment,
        )
    )
    for item in items[:5]:
        print("{} | {}".format(item.title, item.url))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tradingbot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("config-check")
    check.add_argument("--config-dir", default="config")
    check.set_defaults(func=config_check)

    smoke = subparsers.add_parser("event-smoke")
    smoke.add_argument("--db", default="state/trading.db")
    smoke.set_defaults(func=event_smoke)

    status = subparsers.add_parser("paper-status")
    status.add_argument("--config-dir", default="config")
    status.set_defaults(func=paper_status)

    order = subparsers.add_parser("paper-order")
    order.add_argument("symbol")
    order.add_argument("side", choices=["BUY", "SELL"])
    order.add_argument("quantity", type=int)
    order.add_argument("price", type=float)
    order.add_argument("--strategy", default="manual")
    order.add_argument("--config-dir", default="config")
    order.set_defaults(func=paper_order)

    loop = subparsers.add_parser("paper-loop")
    loop.add_argument("--symbols", nargs="*")
    loop.add_argument("--quantity", type=int, default=1)
    loop.add_argument("--iterations", type=int, default=1)
    loop.add_argument("--poll-interval-seconds", type=int)
    loop.add_argument("--strategy", default="paper_poll")
    loop.add_argument("--buy", action="store_true")
    loop.add_argument("--config-dir", default="config")
    loop.set_defaults(func=paper_loop)

    memory = subparsers.add_parser("memory-regenerate")
    memory.add_argument("--dry-run", action="store_true")
    memory.add_argument("--config-dir", default="config")
    memory.set_defaults(func=memory_regenerate)

    kill = subparsers.add_parser("kill-switch")
    kill.add_argument("state", choices=["on", "off"])
    kill.add_argument("--config-dir", default="config")
    kill.set_defaults(func=kill_switch)

    dash = subparsers.add_parser("dashboard")
    dash.add_argument("--host", default="127.0.0.1")
    dash.add_argument("--port", type=int, default=8765)
    dash.add_argument("--config-dir", default="config")
    dash.set_defaults(func=dashboard)

    loop_cmd = subparsers.add_parser("closed-loop")
    loop_cmd.add_argument("--symbols", nargs="*")
    loop_cmd.add_argument("--cycles", type=int)
    loop_cmd.add_argument("--once", action="store_true")
    loop_cmd.add_argument("--dry-run", action="store_true")
    loop_cmd.add_argument("--poll-interval-seconds", type=int)
    loop_cmd.add_argument("--config-dir", default="config")
    loop_cmd.set_defaults(func=closed_loop)

    agent = subparsers.add_parser("agent-loop")
    agent.add_argument("--symbols", nargs="*")
    agent.add_argument("--cycles", type=int)
    agent.add_argument("--once", action="store_true")
    agent.add_argument("--dry-run", action="store_true")
    agent.add_argument("--poll-interval-seconds", type=int)
    agent.add_argument("--config-dir", default="config")
    agent.set_defaults(func=agent_loop)

    autonomous = subparsers.add_parser("autonomous-server")
    autonomous.add_argument("--host", default="127.0.0.1")
    autonomous.add_argument("--port", type=int, default=8765)
    autonomous.add_argument("--cycles", type=int)
    autonomous.add_argument("--once", action="store_true")
    autonomous.add_argument("--dry-run", action="store_true")
    autonomous.add_argument("--poll-interval-seconds", type=int)
    autonomous.add_argument("--order-gate-mode", choices=["autopilot", "confirm_each_order", "paused"])
    autonomous.add_argument("--cancel-window-seconds", type=float)
    autonomous.add_argument("--config-dir", default="config")
    autonomous.set_defaults(func=autonomous_server)

    research = subparsers.add_parser("research-smoke")
    research.add_argument("--symbol", required=True)
    research.set_defaults(func=research_smoke)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
