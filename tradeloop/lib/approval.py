"""Phase 8: explicit human approval bound to the exact orders.json.

A live human-in-loop route is refused unless an approval artifact exists whose
orders_sha256 matches the current orders.json. Auto mode does not consult the
human artifact (it must satisfy the stricter policy gate elsewhere).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from tradeloop.lib.config import Settings


@dataclass(frozen=True)
class ApprovalStatus:
    ok: bool
    reasons: List[str]
    approved_live: bool = False


def orders_sha256(orders_path: Path) -> str:
    return hashlib.sha256(Path(orders_path).read_bytes()).hexdigest()


def requires_live_human_approval(settings: Settings) -> bool:
    return str(settings.approval_mode).strip().lower() == "human_in_loop"


def validate_approval(run_dir: Path, orders_path: Path) -> ApprovalStatus:
    run_dir = Path(run_dir)
    orders_path = Path(orders_path)
    approval_path = run_dir / "approval.json"
    if not approval_path.exists():
        return ApprovalStatus(False, ["no approval.json present"])
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return ApprovalStatus(False, ["approval.json malformed"])
    if not approval.get("approved_live"):
        return ApprovalStatus(False, ["approval.approved_live is not true"])
    expected = orders_sha256(orders_path)
    if approval.get("orders_sha256") != expected:
        return ApprovalStatus(
            False, ["orders_sha256 mismatch: approval bound to a different orders.json"])
    return ApprovalStatus(True, [], approved_live=True)
