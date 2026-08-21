from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def record_alert(root: Path, kind: str, message: str, details: dict | None = None,
                 now: datetime | None = None) -> Path:
    root = Path(root)
    path = root / "reports" / "alerts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = now or datetime.now(timezone.utc)
    record = {
        "ts": ts.isoformat(),
        "kind": kind,
        "message": message,
        "details": details or {},
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return path
