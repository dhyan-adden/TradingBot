from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from tradeloop.lib.data.snapshot import Snapshot


@dataclass
class EvidenceResult:
    ok: bool
    missing: List[Tuple[str, str]] = field(default_factory=list)


def _walk_evidence(node) -> List[str]:
    found: List[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "evidence" and isinstance(value, list):
                found += [v for v in value if isinstance(v, str)]
            else:
                found += _walk_evidence(value)
    elif isinstance(node, list):
        for item in node:
            found += _walk_evidence(item)
    return found


def collect_cited_ids(run_dir: Path) -> Dict[str, List[str]]:
    cited: Dict[str, List[str]] = {}
    for path in sorted(Path(run_dir).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        ids = _walk_evidence(data)
        if ids:
            cited[path.name] = ids
    return cited


def uncited_news_candidates(run_dir: Path) -> List[str]:
    """Tripwire for the evidence gate's blind spot: validate_evidence catches a
    fabricated citation but not a model that silently stopped citing. The one
    suspicious shape is news-track shortlist candidates with ZERO citations
    anywhere in the run - a fully quiet-track day legitimately cites nothing
    (observed live 2026-07-13). Returns the suspect tickers; heuristic, so the
    caller warns and never blocks."""
    try:
        shortlist = json.loads((Path(run_dir) / "14_shortlist.json").read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    news_track = [c.get("ticker", "?") for c in (shortlist.get("candidates") or [])
                  if c.get("source_track") != "quiet"]
    if not news_track or collect_cited_ids(run_dir):
        return []
    return news_track


def validate_evidence(run_dir: Path, snapshot: Snapshot) -> EvidenceResult:
    missing: List[Tuple[str, str]] = []
    for artifact, ids in collect_cited_ids(run_dir).items():
        for nid in ids:
            if nid not in snapshot.news_ids:
                missing.append((artifact, nid))
    return EvidenceResult(ok=not missing, missing=missing)
