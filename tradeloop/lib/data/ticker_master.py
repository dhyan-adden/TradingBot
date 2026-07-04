from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

import yaml


@dataclass(frozen=True)
class TickerRecord:
    symbol: str
    name: str
    sector: str = ""
    industry: str = ""
    isin: str = ""
    bucket: str = "other"
    aliases: tuple[str, ...] = ()
    avg_daily_turnover_cr: float = 0.0


def load_ticker_master(path: Path) -> List[TickerRecord]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    records: List[TickerRecord] = []
    for row in data.get("symbols", []) + data.get("watchlist", []):
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        aliases = tuple(str(item).upper() for item in row.get("aliases", []))
        records.append(
            TickerRecord(
                symbol=symbol,
                name=str(row.get("name", symbol)),
                sector=str(row.get("sector", "")),
                industry=str(row.get("industry", "")),
                isin=str(row.get("isin", "")),
                bucket=str(row.get("bucket", "other")),
                aliases=aliases,
                avg_daily_turnover_cr=float(row.get("avg_daily_turnover_cr", 0.0)),
            )
        )
    return records


def alias_index(records: Iterable[TickerRecord]) -> Dict[str, TickerRecord]:
    index: Dict[str, TickerRecord] = {}
    for record in records:
        index[record.symbol.upper()] = record
        index[record.name.upper()] = record
        for alias in record.aliases:
            index[alias.upper()] = record
    return index


class TickerMaster:
    def __init__(self, records: List[TickerRecord]):
        self.records = records
        self._by_symbol = {r.symbol.upper(): r for r in records}
        self._by_isin = {r.isin.upper(): r for r in records if r.isin}

    def symbols(self) -> List[str]:
        return [r.symbol for r in self.records]

    def record_for(self, symbol: str) -> "TickerRecord | None":
        return self._by_symbol.get(symbol.strip().upper())

    def sector_of(self, symbol: str) -> str:
        rec = self.record_for(symbol)
        return rec.sector if rec else ""

    def by_isin(self, isin: str) -> "TickerRecord | None":
        return self._by_isin.get(isin.strip().upper())

    def alias_map(self) -> Dict[str, TickerRecord]:
        # symbols first (never shadowed), then names, then aliases; first writer wins.
        index: Dict[str, TickerRecord] = {}
        for record in self.records:
            index.setdefault(record.symbol.upper(), record)
        for record in self.records:
            index.setdefault(record.name.upper(), record)
        for record in self.records:
            for alias in record.aliases:
                index.setdefault(alias.upper(), record)
        return index


def load_master(path: Path) -> TickerMaster:
    return TickerMaster(load_ticker_master(path))

