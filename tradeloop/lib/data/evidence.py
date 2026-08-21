from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from tradeloop.lib.data.snapshot import Snapshot


_NEWS_ID_RE = re.compile(r"^[0-9a-f]{12}$")


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


def canonicalize_evidence_ids(
    node: Any,
    valid_ids: set[str],
    max_distance: int = 3,
) -> tuple[Any, list[dict[str, str]]]:
    """Correct obvious one-off copied news_id typos against the frozen snapshot.

    This is intentionally narrow: only 12-char hex tokens inside an ``evidence``
    array are eligible, and only when exactly one snapshot id is within the
    distance threshold. Ambiguous or fabricated ids are preserved so the evidence
    gate still blocks them.
    """
    corrections: list[dict[str, str]] = []
    valid_ids = {str(v) for v in valid_ids}

    def repair_id(news_id: str) -> str:
        if news_id in valid_ids or not _NEWS_ID_RE.match(news_id):
            return news_id
        matches = [candidate for candidate in valid_ids
                   if _hamming(news_id, candidate) <= max_distance]
        if len(matches) != 1:
            return news_id
        corrected = matches[0]
        corrections.append({"from": news_id, "to": corrected})
        return corrected

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            out = {}
            for key, child in value.items():
                if key == "evidence" and isinstance(child, list):
                    out[key] = [repair_id(item) if isinstance(item, str) else item
                                for item in child]
                else:
                    out[key] = walk(child)
            return out
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(node), corrections


def _hamming(a: str, b: str) -> int:
    if len(a) != len(b):
        return max(len(a), len(b))
    return sum(left != right for left, right in zip(a, b))


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
