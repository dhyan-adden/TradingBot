from pathlib import Path

from tradingbot.agent_loop import AgentLoopRunner
from tradingbot.broker.paper import PaperBroker
from tradingbot.config import load_config
from tradingbot.data.market import MarketQuote
from tradingbot.event_log import EventLog
from tradingbot.memory.projections import MemoryProjector
from tradingbot.research import ResearchItem, StaticResearchProvider
from tradingbot.risk.engine import RiskEngine, RiskLimits


class StaticMarketData:
    source = "test"

    def __init__(self, price: float = 1000):
        self.price = price

    def quote(self, symbol: str) -> MarketQuote:
        return MarketQuote(
            symbol=symbol.upper(),
            source_symbol=f"{symbol.upper()}.NS",
            last_price=self.price,
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
        (config_dir / source.name).write_text(text, encoding="utf-8")
    return config_dir


def build_runner(tmp_path: Path, research_items: list[ResearchItem]) -> tuple[AgentLoopRunner, EventLog, PaperBroker]:
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
        universe=["RELIANCE"],
    )
    runner = AgentLoopRunner(
        config=config,
        event_log=event_log,
        market_data=StaticMarketData(),
        research_provider=StaticResearchProvider(research_items),
        broker=broker,
        risk_engine=risk,
        memory_projector=MemoryProjector(event_log, tmp_path / "memory"),
    )
    return runner, event_log, broker


def item(title: str) -> ResearchItem:
    return ResearchItem(
        symbol="RELIANCE",
        title=title,
        url="https://example.com/news",
        source="test",
        published_at="2026-05-16T09:15:00+05:30",
    )


def test_agent_loop_dry_run_writes_research_and_no_order(tmp_path: Path) -> None:
    runner, event_log, broker = build_runner(tmp_path, [item("Reliance profit growth strong")])

    result = runner.run(["RELIANCE"], cycles=1, poll_interval_seconds=0, dry_run=True)

    assert result.research_items == 1
    assert result.signals_generated == 1
    assert result.orders_created == 0
    assert broker.portfolio().positions == {}
    assert event_log.latest("research.trend_summary_written") is not None
    assert event_log.latest("agent.portfolio_decision_written").payload["allow_trade"] is True
    assert event_log.latest("paper.order.filled") is None


def test_agent_loop_negative_news_vetoes_signal(tmp_path: Path) -> None:
    runner, event_log, broker = build_runner(tmp_path, [item("Reliance shares fall after weak results")])

    result = runner.run(["RELIANCE"], cycles=1, poll_interval_seconds=0, dry_run=False)

    assert result.vetoes == 1
    assert result.orders_created == 0
    assert broker.portfolio().positions == {}
    assert event_log.latest("agent.vetoed") is not None


def test_agent_loop_places_paper_order_when_research_allows(tmp_path: Path) -> None:
    runner, event_log, broker = build_runner(tmp_path, [item("Reliance wins strong growth deal")])

    result = runner.run(["RELIANCE"], cycles=1, poll_interval_seconds=0, dry_run=False)

    assert result.orders_created == 1
    assert broker.portfolio().positions == {"RELIANCE": 1}
    assert event_log.latest("risk.approved") is not None
    assert event_log.latest("paper.order.filled") is not None
