import hashlib
from dataclasses import dataclass
from pathlib import Path

from tradeloop.lib.audit.ledger import Ledger


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProjectionResult:
    path: Path
    changed: bool


class MarkdownProjector:
    def __init__(self, ledger: Ledger, memory_root: Path):
        self.ledger = ledger
        self.memory_root = Path(memory_root)

    def regenerate_journal(self) -> ProjectionResult:
        events = self.ledger.replay()
        source_hash = content_hash("".join(e["row_hash"] for e in events))
        lines = [
            "---",
            "projection: event_log",
            f"source_event_hash: {source_hash}",
            f"event_count: {len(events)}",
            "---",
            "",
            "## Event Log",
        ]
        last_day = None
        for e in events:
            day = e.get("ts", "")[:10]
            if day != last_day:
                lines.append("")
                lines.append(f"### {day}")
                last_day = day
            lines.append(f"- `{e['row_hash'][:12]}` seq={e['seq']} {e['type']} {self._summary(e)}")
        lines.append("")
        content = "\n".join(lines)
        path = self.memory_root / "journal" / "event_log.md"
        return self._write(path, content)

    def _summary(self, e: dict) -> str:
        keys = [k for k in e if k not in {"type", "ts", "seq", "prev_hash", "row_hash"}]
        return " ".join(f"{k}={e[k]}" for k in sorted(keys))

    def _write(self, path: Path, content: str) -> ProjectionResult:
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing == content:
            return ProjectionResult(path=path, changed=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
        return ProjectionResult(path=path, changed=True)
