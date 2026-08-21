"""Phase 10: credential hygiene.

No shell script may read the env file (project .env) or grep for a key-named
variable. A status helper prints only SET/MISSING, never the value.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

# Key-named variables we must never grep for in a shell script.
KEY_TOKENS = ("API_KEY", "SECRET", "PASSWORD", "CREDENTIAL", "TOKEN", "AUTH_KEY")


def _sh_scripts() -> list[Path]:
    return sorted(SCRIPTS.glob("*.sh"))


def test_no_shell_script_reads_env_file():
    for sh in _sh_scripts():
        text = sh.read_text(encoding="utf-8", errors="ignore")
        # Word-boundary ".env" matches a path reference like "$ROOT/.env" or
        # ".env", but not ".env_key" (legitimate provider config).
        assert re.search(r"\b\.env\b", text) is None, f"{sh.name} references the env file"


def test_no_shell_script_greps_for_key_variable():
    for sh in _sh_scripts():
        text = sh.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            low = line.lower()
            if "grep" in low and any(tok.lower() in low for tok in KEY_TOKENS):
                pytest.fail(f"{sh.name} greps for a key-named variable: {line.strip()}")


def test_env_status_prints_set_not_value(monkeypatch):
    helper = SCRIPTS / "env_status.py"
    monkeypatch.setenv("PH10_SECRET_X", "super-secret-value")
    out = subprocess.run(
        [sys.executable, str(helper), "PH10_SECRET_X"],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "PH10_SECRET_X=SET"
    assert "super-secret-value" not in out.stdout
    assert out.stderr == ""


def test_env_status_prints_missing():
    helper = SCRIPTS / "env_status.py"
    out = subprocess.run(
        [sys.executable, str(helper), "PH10_DEFINITELY_MISSING_X"],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "PH10_DEFINITELY_MISSING_X=MISSING"
