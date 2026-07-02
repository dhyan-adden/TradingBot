from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from tradingbot.agent_loop import AgentLoopRunner
from tradingbot.autonomous import AutonomousLoopRunner
from tradingbot.broker.paper import PaperBroker
from tradingbot.config import load_config
from tradingbot.data.market import MarketQuote
from tradingbot.event_log import EventLog
from tradingbot.memory.projections import MemoryProjector
from tradingbot.order_gate import OrderGate
from tradingbot.research import ResearchItem, StaticResearchProvider
from tradingbot.risk.engine import RiskEngine, RiskLimits


class StaticMarketData:
    source = "test"

    def quote(self, symbol: str) -> MarketQuote:
        return MarketQuote(
            symbol=symbol.upper(),
            source_symbol=f"{symbol.upper()}.NS",
            last_price=1000,
            timestamp="2026-05-16T09:15:00+05:30",
            source=self.source,
        )


def copy_configs(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for source in Path("config").glob("*.yaml"):
        text = source.read_text(encoding="utf-8")
        text = text.replace("state/trading.db", str(tmp_path / "state" / "trading.db"))
        text = text.replace("memory_root: memory", f"memory_root: {tmp_path / 'memory'}")
        text = text.replace("cancel_window_seconds: 30", "cancel_window_seconds: 0")
        (config_dir / source.name).write_text(text, encoding="utf-8")
    return config_dir


def item(symbol: str, title: str) -> ResearchItem:
    return ResearchItem(
        symbol=symbol,
        title=title,
        url=f"https://example.com/{symbol.lower()}",
        source="test",
        published_at="2026-05-16T09:15:00+05:30",
    )


def build_autonomous_runner(tmp_path: Path) -> tuple[AutonomousLoopRunner, EventLog, PaperBroker]:
    config = load_config(copy_configs(tmp_path))
    event_log = EventLog(tmp_path / "state" / "trading.db")
    broker = PaperBroker(event_log, starting_cash_inr=100000)
    risk = RiskEngine(
        RiskLimits(
            paper_capital_inr=100000,
            max_open_positions=5,
            max_position_allocation_pct=20,
            max_total_deployed_pct=60,
        ),
        universe=["RELIANCE", "TCS"],
    )
    research = StaticResearchProvider(
        [
            item("RELIANCE", "Reliance wins strong growth deal"),
            item("TCS", "TCS shares fall after weak outlook"),
        ]
    )
    agent_runner = AgentLoopRunner(
        config=config,
        event_log=event_log,
        market_data=StaticMarketData(),
        research_provider=research,
        broker=broker,
        risk_engine=risk,
        memory_projector=MemoryProjector(event_log, tmp_path / "memory"),
        order_gate=OrderGate(event_log, mode="autopilot", cancel_window_seconds=0),
    )
    runner = AutonomousLoopRunner(
        event_log=event_log,
        agent_runner=agent_runner,
        research_provider=research,
        universe=["RELIANCE", "TCS"],
        loop_config=config.raw["loop"],
    )
    return runner, event_log, broker


def test_autonomous_loop_shortlists_and_runs_agent_cycle(tmp_path: Path) -> None:
    runner, event_log, broker = build_autonomous_runner(tmp_path)
    runner.market_clock.session = lambda now=None: type(
        "Session",
        (),
        {
            "is_open": True,
            "phase": "open",
            "reason": "market_open",
            "local_time": "2026-05-18T10:00:00+05:30",
            "timezone": "Asia/Kolkata",
        },
    )()

    result = runner.run(cycles=1, poll_interval_seconds=0, dry_run=False)

    assert result.shortlisted_symbols[:1] == ["RELIANCE"]
    assert result.signals_generated >= 1
    assert "RELIANCE" in broker.portfolio().positions
    assert event_log.latest("research.shortlist_generated") is not None
    assert event_log.latest("order_gate.pending") is not None
    assert event_log.latest("execution.order_gate_decision").payload["approved"] is True


def test_autonomous_loop_forces_dry_run_when_market_closed(tmp_path: Path) -> None:
    runner, event_log, broker = build_autonomous_runner(tmp_path)
    runner.market_clock.session = lambda now=None: type(
        "Session",
        (),
        {
            "is_open": False,
            "phase": "closed",
            "reason": "weekend",
            "local_time": datetime(2026, 5, 16, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")).isoformat(),
            "timezone": "Asia/Kolkata",
        },
    )()

    result = runner.run(cycles=1, poll_interval_seconds=0, dry_run=False)

    assert result.signals_generated >= 1
    assert result.orders_created == 0
    assert broker.portfolio().positions == {}
    assert event_log.latest("market.session_checked").payload["execution_dry_run"] is True
    assert event_log.latest("paper.order.filled") is None
