from pathlib import Path
from typing import List


def relevant_memory(memory_root: Path, symbol: str, limit: int = 5) -> List[str]:
    normalized = symbol.strip().upper()
    candidates: List[str] = []
    for path in [
        memory_root / "lessons_learned.md",
        memory_root / "manager_feedback.md",
        memory_root / "trade_journal.md",
        memory_root / "strategy_performance.md",
        memory_root / "stock_dossiers" / f"{normalized}.md",
    ]:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for block in text.split("\n## "):
            if normalized in block.upper():
                candidates.append(block.strip())
    return candidates[:limit]
