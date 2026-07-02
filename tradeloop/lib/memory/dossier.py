from pathlib import Path

from tradeloop.lib.memory.writer import append_unique


def update_dossier(memory_root: Path, ticker: str, heading: str, body: str) -> bool:
    path = memory_root / "stock_dossiers" / f"{ticker.strip().upper()}.md"
    return append_unique(path, heading, body)

