from __future__ import annotations

import json
import os
import select
import subprocess
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import IO, List, Protocol, cast


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


class KiteAuthError(RuntimeError):
    pass


def _is_auth_error(text: str) -> bool:
    lower = text.lower()
    return "tokenexception" in lower or "api_key" in lower or "access_token" in lower


class StdioTransport:
    """Minimal MCP stdio JSON-RPC: spawn `tsx src/mcp/zerodha.ts`, initialize, tools/call.
    ponytail: newline-delimited JSON-RPC by hand; adopt the official mcp python client
    only if streaming/notifications are ever needed."""

    def __init__(self, command=("npm", "run", "-s", "mcp:zerodha"), timeout_seconds: float = 45.0,
                 cwd: "Path | str | None" = None):
        repo_root = Path(cwd) if cwd is not None else Path(__file__).resolve().parents[3]
        self._proc = subprocess.Popen(
            list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0,
            cwd=str(repo_root)
        )
        self._stdin = cast(IO[bytes], self._proc.stdin)
        self._stdout = cast(IO[bytes], self._proc.stdout)
        self._stdout_buffer = b""
        self._id = 0
        self._timeout_seconds = timeout_seconds
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "tradeloop", "version": "1.0"},
        })
        self._notify("notifications/initialized", {})

    def _rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        self._stdin.write((json.dumps(msg) + "\n").encode())
        self._stdin.flush()
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            newline = self._stdout_buffer.find(b"\n")
            if newline >= 0:
                line = self._stdout_buffer[:newline]
                self._stdout_buffer = self._stdout_buffer[newline + 1:]
                if not line:
                    continue
                resp = json.loads(line.decode())
                if resp.get("id") == self._id:
                    if "error" in resp:
                        raise RuntimeError(f"kite MCP error: {resp['error']}")
                    return resp["result"]
                continue

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close()
                raise TimeoutError(
                    f"kite MCP timed out waiting for {method} after {self._timeout_seconds:g}s"
                )
            ready, _, _ = select.select([self._stdout], [], [], remaining)
            if not ready:
                self.close()
                raise TimeoutError(
                    f"kite MCP timed out waiting for {method} after {self._timeout_seconds:g}s"
                )
            chunk = os.read(self._stdout.fileno(), 4096)
            if not chunk:
                raise RuntimeError("kite MCP closed stdout")
            self._stdout_buffer += chunk

    def _notify(self, method: str, params: dict) -> None:
        self._stdin.write((json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n").encode())
        self._stdin.flush()

    def call_tool(self, name: str, arguments: dict) -> dict:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        # server returns {"content":[{"type":"text","text":"<json>"}]}
        text = str(result.get("content", [{}])[0].get("text", ""))
        if result.get("isError"):
            if _is_auth_error(text):
                raise KiteAuthError(
                    "Zerodha authentication failed: Kite rejected the api_key/access_token; "
                    "refresh with `npm run auth:zerodha -- --auto` or `npm run auth:zerodha -- --listen`"
                )
            raise RuntimeError(f"kite MCP tool {name} failed: {text}")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"kite MCP tool {name} returned non-JSON output") from exc

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
