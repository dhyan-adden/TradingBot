from pathlib import Path

from tradingbot.event_log import EventLog, stable_event_hash


def test_append_and_replay_event(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "trading.db")
    event = log.append_event(
        "signal.generated",
        "PAPER-TEST",
        {"symbol": "RELIANCE", "confidence": 0.5},
        event_id="event-1",
        created_at="2026-05-16T00:00:00+00:00",
    )

    events = list(log.replay("PAPER-TEST"))

    assert len(events) == 1
    assert events[0] == event
    assert events[0].payload["symbol"] == "RELIANCE"


def test_event_hash_is_stable() -> None:
    left = stable_event_hash("x", "a", {"b": 2, "a": 1})
    right = stable_event_hash("x", "a", {"a": 1, "b": 2})

    assert left == right
