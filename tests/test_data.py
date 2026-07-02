from typing import Any, Dict, List

import pytest

from tradingbot.data.quality import require_non_empty_candles, require_quote_ltp
from tradingbot.data.zerodha import ZerodhaDataClient


def test_quality_rejects_missing_candles() -> None:
    with pytest.raises(ValueError, match="No candles"):
        require_non_empty_candles([])


def test_quality_rejects_missing_ltp() -> None:
    with pytest.raises(ValueError, match="last_price"):
        require_quote_ltp({"instrument_token": 1})


def test_historical_daily_maps_candles(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ZerodhaDataClient(api_key="key", access_token="token")

    def fake_get_json(path: str, params: Dict[str, Any]) -> Dict[str, List[List[Any]]]:
        assert path == "/instruments/historical/123/day"
        return {"candles": [["2026-05-16T00:00:00+0530", 1, 2, 0.5, 1.5, 1000]]}

    monkeypatch.setattr(client, "get_json", fake_get_json)

    candles = client.historical_daily(123, "2026-05-01", "2026-05-16")

    assert candles == [
        {
            "timestamp": "2026-05-16T00:00:00+0530",
            "open": 1,
            "high": 2,
            "low": 0.5,
            "close": 1.5,
            "volume": 1000,
        }
    ]
