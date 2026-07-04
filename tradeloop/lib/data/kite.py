from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import date
from typing import List, Protocol


@dataclass(frozen=True)
class Candle:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class Transport(Protocol):
    def call_tool(self, name: str, arguments: dict) -> dict: ...


class StdioTransport:
    """Minimal MCP stdio JSON-RPC: spawn `tsx src/mcp/zerodha.ts`, initialize, tools/call.
    ponytail: newline-delimited JSON-RPC by hand; adopt the official mcp python client
    only if streaming/notifications are ever needed."""

    def __init__(self, command=("npm", "run", "-s", "mcp:zerodha")):
        self._proc = subprocess.Popen(
            list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1
        )
        self._id = 0
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "tradeloop", "version": "1.0"},
        })
        self._notify("notifications/initialized", {})

    def _rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError("kite MCP closed stdout")
            resp = json.loads(line)
            if resp.get("id") == self._id:
                if "error" in resp:
                    raise RuntimeError(f"kite MCP error: {resp['error']}")
                return resp["result"]

    def _notify(self, method: str, params: dict) -> None:
        self._proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
        self._proc.stdin.flush()

    def call_tool(self, name: str, arguments: dict) -> dict:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        # server returns {"content":[{"type":"text","text":"<json>"}]}
        text = result["content"][0]["text"]
        return json.loads(text)

    def close(self) -> None:
        try:
            self._proc.terminate()
        except Exception:
            pass


class KiteClient:
    def __init__(self, transport: "Transport | None" = None):
        self._transport = transport
        self._token_cache: dict = {}

    @property
    def transport(self) -> Transport:
        if self._transport is None:
            self._transport = StdioTransport()
        return self._transport

    def ltp(self, symbols: List[str]) -> dict:
        instruments = [f"NSE:{s.strip().upper()}" for s in symbols]
        raw = self.transport.call_tool("zerodha_ltp", {"instruments": instruments})
        out: dict = {}
        for s in symbols:
            key = f"NSE:{s.strip().upper()}"
            if key in raw and isinstance(raw[key], dict) and "last_price" in raw[key]:
                out[s.strip().upper()] = float(raw[key]["last_price"])
        return out

    def ohlc(self, symbol: str) -> dict:
        key = f"NSE:{symbol.strip().upper()}"
        raw = self.transport.call_tool("zerodha_ohlc", {"instruments": [key]})
        return raw.get(key, {})

    def instruments(self, exchange: str = "NSE", mainboard_only: bool = True) -> dict:
        raw = self.transport.call_tool(
            "zerodha_instruments", {"exchange": exchange, "mainboard_only": mainboard_only}
        )
        out: dict = {}
        for row in raw.get("instruments", []):
            sym = str(row["tradingsymbol"]).strip().upper()
            token = int(row["instrument_token"])
            out[sym] = token
            self._token_cache[sym] = token  # seed so historical() needs no lookup
        return out

    def _token(self, symbol: str) -> int:
        sym = symbol.strip().upper()
        if sym not in self._token_cache:
            res = self.transport.call_tool(
                "zerodha_instrument_token", {"exchange": "NSE", "tradingsymbol": sym}
            )
            self._token_cache[sym] = int(res["instrument_token"])
        return self._token_cache[sym]

    def historical(self, symbol: str, frm: date, to: date, interval: str) -> List[Candle]:
        token = self._token(symbol)
        res = self.transport.call_tool("zerodha_historical", {
            "instrument_token": token,
            "from_date": f"{frm.isoformat()} 00:00:00",
            "to_date": f"{to.isoformat()} 23:59:59",
            "interval": interval,
        })
        candles: List[Candle] = []
        for row in res.get("candles", []):
            candles.append(Candle(
                date=str(row[0]), open=float(row[1]), high=float(row[2]),
                low=float(row[3]), close=float(row[4]), volume=int(row[5]),
            ))
        return candles


_default: "KiteClient | None" = None


def _client() -> KiteClient:
    global _default
    if _default is None:
        _default = KiteClient()
    return _default


def ltp(symbols: List[str]) -> dict:
    return _client().ltp(symbols)


def ohlc(symbol: str) -> dict:
    return _client().ohlc(symbol)


def historical(symbol: str, frm: date, to: date, interval: str) -> List[Candle]:
    return _client().historical(symbol, frm, to, interval)
