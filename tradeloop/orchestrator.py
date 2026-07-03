"""TradeLoop desk manager: gates -> lock -> prepare -> reason -> order path."""
import os
import subprocess
from datetime import date
from pathlib import Path

from tradeloop.lib.risk.circuit_breaker import kill_switch_active
from tradeloop.lib.util.holidays import is_nse_holiday

ROOT = Path(__file__).resolve().parent


def _gate_holiday(today: date) -> str | None:
    return "nse_holiday" if is_nse_holiday(today) else None


def _gate_kill_switch(root: Path) -> str | None:
    return "kill_switch" if kill_switch_active(root) else None


def _run_reasoning(run_dir: Path, mode: str, agent: str) -> int:
    """Phase-0 seam: run the unchanged external reasoning backend as a
    subprocess. Phase 1 replaces this body with in-process OpenRouter calls
    without touching the order path. Sources no secrets in Python — the child
    reads OPENROUTER_API_KEY from the already-exported env (AGENTS.md safe)."""
    script = ROOT / "scripts" / "run_cycle.sh"
    env = dict(os.environ, TRADELOOP_AGENT=agent)
    proc = subprocess.run(["bash", str(script), mode], env=env, cwd=str(ROOT.parent))
    return proc.returncode
