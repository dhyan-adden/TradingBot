import os
from typing import Any, Dict, List, Optional

import httpx


class ZerodhaDataClient:
    def __init__(self, api_key: Optional[str] = None, access_token: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ZERODHA_API_KEY")
        self.access_token = access_token or os.environ.get("ZERODHA_ACCESS_TOKEN")
        if not self.api_key or not self.access_token:
            raise ValueError("Zerodha credentials are not configured")
        self.base_url = "https://api.kite.trade"

    def headers(self) -> Dict[str, str]:
        return {
            "X-Kite-Version": "3",
            "Authorization": "token {}:{}".format(self.api_key, self.access_token),
        }

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        with httpx.Client(base_url=self.base_url, timeout=30) as client:
            response = client.get(path, headers=self.headers(), params=params)
            response.raise_for_status()
            payload = response.json()
        return payload.get("data")

    def ltp(self, instruments: List[str]) -> Dict[str, Any]:
        return self.get_json("/quote/ltp", params={"i": instruments})

    def historical_daily(
        self,
        instrument_token: int,
        from_date: str,
        to_date: str,
    ) -> List[Dict[str, Any]]:
        data = self.get_json(
            "/instruments/historical/{}/day".format(instrument_token),
            params={"from": from_date, "to": to_date},
        )
        candles = []
        for row in data.get("candles", []) if isinstance(data, dict) else []:
            candles.append(
                {
                    "timestamp": row[0],
                    "open": row[1],
                    "high": row[2],
                    "low": row[3],
                    "close": row[4],
                    "volume": row[5],
                }
            )
        return candles
