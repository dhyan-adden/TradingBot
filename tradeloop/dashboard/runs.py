from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from tradeloop.dashboard.render import (
    render_debate, render_decision, render_markdown_stage, render_stage,
)

STAGE_ORDER = [
    "10_news", "11_sentiment", "12_fundamentals", "13_technical", "14_shortlist",
    "15_holdings_review", "20_bull", "21_bear", "22_debate", "30_trade_plan",
    "40_risk_report",
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


def _orders_dict(orders) -> dict:
    """Normalize orders.json for render_decision.

    The deterministic router writes a dict {"orders": [...], "held": [...]} while
    the Codex/OpenRouter path writes a bare list of orders. render_decision expects
    the dict shape, so a list is wrapped rather than crashing on .get().
    """
    if isinstance(orders, dict):
        return orders
    if isinstance(orders, list):
        return {"orders": orders, "held": []}
    return {}


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


def _usage_summary(run_dir: Path) -> dict:
    path = run_dir / "llm_calls.jsonl"
    summary = {
        "calls": 0,
        "successful_calls": 0,
        "failed_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "cost_known": False,
        "cost_source": "",
        "by_stage": {},
    }
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        summary["calls"] += 1
        successful = bool(record.get("used_model"))
        summary["successful_calls"] += int(successful)
        summary["failed_calls"] += int(not successful)
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            summary[field] += int(record.get(field) or 0)
        if record.get("cost_known"):
            summary["cost_known"] = True
        summary["cost_usd"] += float(record.get("cost_usd") or 0.0)
        stage = str(record.get("role") or "unknown")
        stage_usage = summary["by_stage"].setdefault(stage, {"calls": 0, "total_tokens": 0, "cost_usd": 0.0})
        stage_usage["calls"] += 1
        stage_usage["total_tokens"] += int(record.get("total_tokens") or 0)
        stage_usage["cost_usd"] += float(record.get("cost_usd") or 0.0)
        if record.get("cost_known"):
            summary["cost_source"] = "provider_reported"
    codex_path = run_dir / "codex_usage.json"
    try:
        codex = json.loads(codex_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        codex = None
    if isinstance(codex, dict):
        summary["calls"] += int(codex.get("calls") or 0)
        summary["successful_calls"] += int(codex.get("successful_calls") or 0)
        summary["failed_calls"] += int(codex.get("failed_calls") or 0)
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            summary[field] += int(codex.get(field) or 0)
        summary["cost_usd"] += float(codex.get("cost_usd") or 0.0)
        if codex.get("cost_known"):
            summary["cost_known"] = True
            summary["cost_source"] = codex.get("cost_source", "")
        stage = "codex_orchestrator"
        summary["by_stage"][stage] = {
            "calls": int(codex.get("calls") or 0),
            "total_tokens": int(codex.get("total_tokens") or 0),
            "cost_usd": round(float(codex.get("cost_usd") or 0.0), 8),
        }
    if not summary["calls"]:
        legacy = _legacy_codex_usage(run_dir)
        if legacy:
            summary.update(legacy)
    summary["cost_usd"] = round(summary["cost_usd"], 8)
    for stage_usage in summary["by_stage"].values():
        stage_usage["cost_usd"] = round(stage_usage["cost_usd"], 8)
    return summary


def _legacy_codex_usage(run_dir: Path) -> dict | None:
    """Recover aggregate Codex tokens from pre-JSON cycle logs.

    Older Codex runs emitted only a final ``tokens used`` total. The input/output
    split and provider cost are unavailable, so this deliberately reports tokens
    without inventing a cost or per-expert allocation.
    """
    logs_dir = run_dir.parents[1] / "reports" / "cycle_logs"
    if not logs_dir.exists():
        return None
    marker = str(run_dir)
    for path in sorted(logs_dir.glob("*.log"), reverse=True):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if marker not in text:
            continue
        match = re.search(r"tokens used\s*\n\s*([\d,]+)", text, re.IGNORECASE)
        if not match:
            continue
        model_match = re.search(r"^model:\s*(\S+)", text, re.MULTILINE)
        total_tokens = int(match.group(1).replace(",", ""))
        stage_count = sum(1 for stage in STAGE_ORDER
                          if (run_dir / f"{stage}.md").exists())
        return {
            "calls": 1,
            "successful_calls": 1,
            "failed_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": total_tokens,
            "cost_usd": 0.0,
            "cost_known": False,
            "cost_source": "legacy_codex_log_total_tokens",
            "model": model_match.group(1) if model_match else "",
            "by_stage": {
                "codex_orchestrator": {
                    "calls": 1,
                    "handoffs": stage_count,
                    "total_tokens": total_tokens,
                    "cost_usd": 0.0,
                }
            },
        }
    return None


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
            summary = render_decision(_orders_dict(orders)).summary
        out.append(RunSummary(dir_name=d.name, mode=_mode(d.name), decision=summary))
    return out


def read_run(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    models = _stage_models(run_dir)
    if not models:
        try:
            codex = json.loads((run_dir / "codex_usage.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            codex = None
        codex_model = codex.get("model") if isinstance(codex, dict) else ""
        if not codex_model:
            legacy = _legacy_codex_usage(run_dir)
            codex_model = legacy.get("model") if legacy else ""
        if codex_model:
            models = {stage: f"codex:{codex_model}" for stage in STAGE_ORDER}
    stages = []
    raws: dict[str, dict] = {}
    for stage in STAGE_ORDER:
        raw = _load(run_dir / f"{stage}.json")
        if raw is None:
            markdown_path = run_dir / f"{stage}.md"
            try:
                markdown = markdown_path.read_text(encoding="utf-8")
            except OSError:
                continue  # not written yet
            stages.append(asdict(render_markdown_stage(stage, markdown,
                                                       models.get(stage, ""))))
            continue
        raws[stage] = raw
        if stage == "22_debate":  # the Judge's card carries the full exchange
            view = render_debate(raw, raws.get("20_bull"), raws.get("21_bear"),
                                 models.get(stage, ""))
        else:
            view = render_stage(stage, raw, models.get(stage, ""))
        stages.append(asdict(view))
    orders = _load(run_dir / "orders.json") or {}
    decision = asdict(render_decision(_orders_dict(orders), models.get("41_pm_decision", "")))
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
            "decision": decision, "error": error, "usage": _usage_summary(run_dir)}
