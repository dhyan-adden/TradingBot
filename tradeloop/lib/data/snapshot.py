from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List

from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.tickers import TaggedStory


def news_id(guid: str, url: str, title: str) -> str:
    return hashlib.sha256(f"{guid}|{url}|{title}".encode("utf-8")).hexdigest()[:12]


@dataclass
class Snapshot:
    run_dir: Path
    snapshot_hash: str
    news_ids: set
    stories: List[TaggedStory] = field(default_factory=list)
    macro: List[RawItem] = field(default_factory=list)
    setups: list = field(default_factory=list)
    news_available: bool = True


def freeze(stories, macro, setups, run_dir: Path):
    snap_dir = Path(run_dir) / "snapshot"
    snap_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for s in stories:
        records.append({"kind": "story", **asdict(s)})
    for m in macro:
        records.append({"kind": "macro", **asdict(m)})
    for c in setups:
        records.append({"kind": "setup", **asdict(c)})
    # deterministic order so the hash is reproducible regardless of fetch order.
    records.sort(key=lambda r: (r["kind"], r.get("news_id", ""), r.get("ticker", "")))
    lines = [json.dumps(r, sort_keys=True, default=str) for r in records]
    blob = "\n".join(lines).encode("utf-8")
    snapshot_hash = hashlib.sha256(blob).hexdigest()
    (snap_dir / "items.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    (snap_dir / "snapshot_hash.txt").write_text(snapshot_hash + "\n", encoding="utf-8")
    return snap_dir, snapshot_hash


def render_news_raw(stories, macro, news_available: bool) -> str:
    if not news_available:
        return "# Raw News\n\n> NO NEWS DATA - every news source failed this cycle. Decisions must not rely on news catalysts.\n"
    lines = ["# Raw News", "", "## Macro Stories"]
    for item in macro:
        lines.append(f"- [{item.news_id}] {item.title} ({item.source}) {item.url}")
    lines.extend(["", "## Ticker Stories"])
    by_ticker: dict = {}
    for s in stories:
        by_ticker.setdefault(s.ticker, []).append(s)
    for ticker, items in sorted(by_ticker.items()):
        lines.append(f"### {ticker}")
        for s in items:
            lines.append(f"- [{s.news_id}] [{s.tier}] {s.category}: {s.title} ({s.source}) {s.url}")
    lines.append("")
    return "\n".join(lines)


def render_setups(setups) -> str:
    lines = ["# Raw Technical Setups", ""]
    for scan in setups:
        family = getattr(scan, "strategy_family", "") or scan.setup_type
        exit_r = getattr(scan, "exit_rule", "")
        base = (
            f"- {scan.ticker}: {scan.setup_type} [{family}], score={scan.cleanliness_score}, "
            f"entry={scan.entry_zone}, stop={scan.stop_zone}, targets={scan.target_zone}, "
            f"volume={scan.volume_context}"
        )
        if exit_r:
            base += f", exit_rule=({exit_r})"
        lines.append(base)
    lines.append("")
    return "\n".join(lines)


def load_snapshot(run_dir: Path):
    """Rehydrate a frozen snapshot's news_ids for the post-reason evidence check.
    Returns None when this run has no frozen snapshot (e.g. a monkeypatched prepare),
    so legacy/unit cycles skip the check instead of failing."""
    items = Path(run_dir) / "snapshot" / "items.jsonl"
    if not items.exists():
        return None
    news_ids = set()
    for line in items.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("kind") in ("story", "macro") and rec.get("news_id"):
            news_ids.add(rec["news_id"])
    hash_file = Path(run_dir) / "snapshot" / "snapshot_hash.txt"
    snap_hash = hash_file.read_text().strip() if hash_file.exists() else ""
    return Snapshot(run_dir=Path(run_dir), snapshot_hash=snap_hash, news_ids=news_ids)
