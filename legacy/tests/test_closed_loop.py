from pathlib import Path

from tradingbot.broker.paper import PaperBroker
from tradingbot.config import load_config
from tradingbot.data.market import MarketQuote
from tradingbot.event_log import EventLog
from tradingbot.loop import ClosedLoopRunner
from tradingbot.memory.projections import MemoryProjector
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


def build_runner(tmp_path: Path) -> tuple[ClosedLoopRunner, EventLog, PaperBroker]:
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
    runner = ClosedLoopRunner(
        config=config,
        event_log=event_log,
        market_data=StaticMarketData(),
        broker=broker,
        risk_engine=risk,
        memory_projector=MemoryProjector(event_log, tmp_path / "memory"),
    )
    return runner, event_log, broker


def test_closed_loop_dry_run_generates_signal_without_order(tmp_path: Path) -> None:
    runner, event_log, broker = build_runner(tmp_path)

    result = runner.run(["RELIANCE"], cycles=1, poll_interval_seconds=0, dry_run=True)

    assert result.signals_generated == 1
    assert result.orders_created == 0
    assert broker.portfolio().positions == {}
    assert event_log.latest("signal.generated") is not None
    assert event_log.latest("paper.order.filled") is None


def test_closed_loop_places_paper_order_after_risk_approval(tmp_path: Path) -> None:
    runner, event_log, broker = build_runner(tmp_path)

    result = runner.run(["RELIANCE"], cycles=1, poll_interval_seconds=0, dry_run=False)

    assert result.signals_generated == 1
    assert result.orders_created == 1
    assert broker.portfolio().positions == {"RELIANCE": 1}
    assert event_log.latest("risk.approved") is not None
    assert event_log.latest("paper.order.filled") is not None
