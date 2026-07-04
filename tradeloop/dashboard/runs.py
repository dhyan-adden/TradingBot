from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from tradeloop.dashboard.render import render_decision, render_stage

STAGE_ORDER = [
    "10_news", "11_sentiment", "12_fundamentals", "13_technical", "14_shortlist",
    "20_bull", "21_bear", "22_debate", "30_trade_plan", "40_risk_report",
]


@dataclass
class RunSummary:
    dir_name: str
    mode: str
    decision: str


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}  # malformed -> empty, never crash


def _mode(dir_name: str) -> str:
    return dir_name.rsplit("_", 1)[-1] if "_" in dir_name else ""


def list_runs(runs_dir: Path) -> list[RunSummary]:
    runs_dir = Path(runs_dir)
    if not runs_dir.exists():
        return []
    out = []
    for d in sorted((p for p in runs_dir.iterdir() if p.is_dir()),
                    key=lambda p: p.name, reverse=True):
        orders = _load(d / "orders.json") or {}
        dec = render_decision(orders)
        out.append(RunSummary(dir_name=d.name, mode=_mode(d.name), decision=dec.summary))
    return out


def read_run(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    stages = []
    for stage in STAGE_ORDER:
        raw = _load(run_dir / f"{stage}.json")
        if raw is None:
            continue  # not written yet
        stages.append(asdict(render_stage(stage, raw)))
    decision_raw = _load(run_dir / "41_pm_decision.json")
    live = decision_raw is None
    orders = _load(run_dir / "orders.json") or {}
    decision = asdict(render_decision(orders))
    return {"dir": run_dir.name, "live": live, "stages": stages, "decision": decision}
