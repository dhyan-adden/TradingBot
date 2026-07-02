from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class MarketSession:
    is_open: bool
    phase: str
    local_time: str
    timezone: str
    reason: str


class MarketClock:
    def __init__(self, loop_config: dict):
        hours = loop_config.get("market_hours", {})
        self.timezone = str(hours.get("timezone", "Asia/Kolkata"))
        self.start = _parse_hhmm(str(hours.get("start", "09:15")))
        self.end = _parse_hhmm(str(hours.get("end", "15:30")))

    def session(self, now: datetime | None = None) -> MarketSession:
        zone = ZoneInfo(self.timezone)
        local_now = now.astimezone(zone) if now else datetime.now(zone)
        if local_now.weekday() >= 5:
            return MarketSession(False, "closed", local_now.isoformat(), self.timezone, "weekend")
        current = local_now.time()
        if current < self.start:
            return MarketSession(False, "pre_market", local_now.isoformat(), self.timezone, "before_market_open")
        if current > self.end:
            return MarketSession(False, "post_market", local_now.isoformat(), self.timezone, "after_market_close")
        return MarketSession(True, "open", local_now.isoformat(), self.timezone, "market_open")


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))
