from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from tradeloop.dashboard.render import render_decision, render_stage

STAGE_ORDER = [
    "10_news", "11_sentiment", "12_fundamentals", "13_technical", "14_shortlist",
    "20_bull", "21_bear", "22_debate", "30_trade_plan", "40_risk_report",
]

IN_FLIGHT = "Still running - no decision yet."


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


def _stage_models(run_dir: Path) -> dict[str, str]:
    """role -> model slug that ACTUALLY ran it, from the audit log. A successful
    call overrides a prior failed attempt; on a fallback chain the last used model
    wins. Empty when the run predates the audit log or it's unreadable."""
    path = run_dir / "llm_calls.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    models: dict[str, str] = {}
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        role, model = rec.get("role"), rec.get("model")
        if not role or not model:
            continue
        if role not in models or rec.get("used_model"):
            models[role] = model
    return models


def list_runs(runs_dir: Path) -> list[RunSummary]:
    runs_dir = Path(runs_dir)
    if not runs_dir.exists():
        return []
    out = []
    for d in sorted((p for p in runs_dir.iterdir() if p.is_dir()),
                    key=lambda p: p.name, reverse=True):
        # same truthfulness rules as read_run: an unfinished run is not a "hold"
        orders = _load(d / "orders.json") or {}
        if (d / "reasoning_error.txt").exists():
            summary = "This run did not finish."
        elif not orders:
            summary = IN_FLIGHT
        else:
            summary = render_decision(orders).summary
        out.append(RunSummary(dir_name=d.name, mode=_mode(d.name), decision=summary))
    return out


def read_run(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    models = _stage_models(run_dir)
    stages = []
    for stage in STAGE_ORDER:
        raw = _load(run_dir / f"{stage}.json")
        if raw is None:
            continue  # not written yet
        stages.append(asdict(render_stage(stage, raw, models.get(stage, ""))))
    orders = _load(run_dir / "orders.json") or {}
    decision = asdict(render_decision(orders, models.get("41_pm_decision", "")))
    err_path = run_dir / "reasoning_error.txt"
    error = err_path.read_text(encoding="utf-8").strip() if err_path.exists() else ""
    if error:
        # a crashed run must NOT read as a clean "hold" - say so plainly
        decision["summary"] = "This run did not finish - " + error.splitlines()[0]
    # end-of-run marker = the orders.json DICT _run_reasoning writes for every mode
    # (intraday/postclose skip the PM stage, so 41_pm_decision.json can't mark it;
    # prepare's placeholder is the list [], which _load-or-{} leaves falsy)
    live = not orders and not error
    if live:
        # regression (2026-07-08): the empty orders.json placeholder rendered a
        # confident "Holding today" while the run was still scanning/reasoning
        decision["summary"] = IN_FLIGHT
    return {"dir": run_dir.name, "live": live, "stages": stages,
            "decision": decision, "error": error}
