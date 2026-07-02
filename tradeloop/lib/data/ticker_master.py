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

