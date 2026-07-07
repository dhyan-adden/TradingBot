from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List


def require_non_empty_candles(candles: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = list(candles)
    if not result:
        raise ValueError("No candles returned")
    return result


def require_quote_ltp(quote: Dict[str, Any]) -> Dict[str, Any]:
    last_price = quote.get("last_price")
    if last_price is None or float(last_price) <= 0:
        raise ValueError("Quote is missing a positive last_price")
    return quote


def require_fresh_timestamp(timestamp: str, max_age_seconds: int) -> None:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    age = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    if age.total_seconds() > max_age_seconds:
        raise ValueError("Timestamp is stale")
