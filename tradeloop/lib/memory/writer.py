import hashlib
from pathlib import Path


def append_unique(path: Path, heading: str, body: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = "\n".join(["", f"## {heading.strip()}", "", body.strip(), ""])
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if entry.strip() in existing:
        return False
    with path.open("a", encoding="utf-8") as handle:
        if not existing:
            handle.write(f"# {path.stem.replace('_', ' ').title()}\n")
        handle.write(entry)
    return True


def append_provenanced(path: Path, heading: str, body: str, run_id: str, timestamp: str) -> bool:
    digest = hashlib.sha256(body.strip().encode("utf-8")).hexdigest()[:12]
    stamped = "\n".join([f"_run_id: {run_id} · {timestamp} · hash: {digest}_", "", body.strip()])
    return append_unique(path, heading, stamped)


def append_trade_journal(memory_root: Path, heading: str, body: str) -> bool:
    return append_unique(memory_root / "trade_journal.md", heading, body)


def append_lesson(memory_root: Path, heading: str, body: str) -> bool:
    return append_unique(memory_root / "lessons_learned.md", heading, body)

