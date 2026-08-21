"""OpenCode stage transport for mixed OpenAI subscription + OpenRouter routing.

This mirrors the ``LLMClient`` contract but delegates model execution to the
local ``opencode`` CLI so stages can use OpenAI subscription models for senior
decisions and OpenRouter API models for cheap research.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from tradeloop.lib.llm import routing
from tradeloop.lib.llm.client import (
    CallRecord, LLMValidationError, _failed_record, _parse_json_object,
    build_system_content,
)

_NO_TOOLS_PREAMBLE = (
    "CRITICAL: You are a bounded JSON-only TradeLoop stage. Do NOT use tools, "
    "do NOT inspect files beyond the attached prompt, and do NOT ask follow-up "
    "questions. Output ONLY the JSON object specified by the prompt.\n\n"
)


class OpenCodeStageClient:
    def __init__(
        self,
        audit_path: Path,
        cli: str = "opencode",
        agent: str = "tradeloop-stage",
        fallback_models: tuple[str, ...] | None = None,
        max_retries: int = 2,
        backoff_base: float = 0.5,
        per_call_timeout: float = 420.0,
        cwd: Path | None = None,
    ) -> None:
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.cli = cli
        self.agent = agent
        self.fallback_models = tuple(fallback_models) if fallback_models is not None else None
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.per_call_timeout = per_call_timeout
        self.cwd = Path(cwd) if cwd is not None else _discover_project_root(self.audit_path)

    def call_json(
        self,
        role: str,
        system: str,
        user: str,
        schema: type[BaseModel],
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> BaseModel:
        primary = model or routing.opencode_model_for(role)
        fallbacks = self.fallback_models if self.fallback_models is not None else routing.opencode_fallbacks_for(role)
        models = [primary]
        for fb in fallbacks:
            if fb not in models:
                models.append(fb)

        prompt = f"{system}\n\n{user}"
        system_content = build_system_content(system, schema)
        budget_note = (
            f"Keep the JSON response within roughly {max_tokens} output tokens.\n\n"
            if max_tokens is not None else ""
        )
        stage_prompt = f"{_NO_TOOLS_PREAMBLE}{budget_note}{system_content}\n\n{user}"
        last_exc: Exception | None = None

        for m in models:
            for attempt in range(self.max_retries):
                try:
                    text, envelope = self._run_opencode(m, stage_prompt)
                    obj = _parse_json_object(text)
                    validated = schema.model_validate(obj)
                except (subprocess.TimeoutExpired, subprocess.SubprocessError,
                        RuntimeError, ValueError, ValidationError) as exc:
                    last_exc = exc
                    self._record(_failed_record(role, f"opencode:{m}", prompt, str(exc)))
                    if attempt < self.max_retries - 1:
                        time.sleep(self.backoff_base * (2 ** attempt))
                    continue
                usage = _usage_from_envelope(envelope)
                reported_cost = _cost_from_envelope(envelope)
                self._record(CallRecord(
                    role=role,
                    model=f"opencode:{m}",
                    model_version=str(envelope.get("model", m)),
                    response_id=str(envelope.get("id", envelope.get("sessionID", ""))),
                    prompt=prompt,
                    response=text,
                    prompt_tokens=usage[0],
                    completion_tokens=usage[1],
                    total_tokens=usage[2],
                    used_model=True,
                    estimated_input_chars=len(prompt),
                    cost_usd=reported_cost or 0.0,
                    cost_known=reported_cost is not None,
                ))
                return validated

        raise LLMValidationError(
            f"{role} failed on opencode models {models} after {self.max_retries} tries each: {last_exc}")

    def _run_opencode(self, model: str, stage_prompt: str) -> tuple[str, dict[str, Any]]:
        import os
        import dotenv

        env = os.environ.copy()
        dotenv_path = self.cwd / ".env"
        if dotenv_path.exists():
            dotenv.load_dotenv(dotenv_path, override=True)
            env = os.environ.copy()

        proc = subprocess.run(
            [
                self.cli, "run", "--model", model, "--agent", self.agent,
                "--format", "json", "--dir", str(self.cwd), stage_prompt,
            ],
            capture_output=True,
            text=True,
            timeout=self.per_call_timeout,
            cwd=self.cwd,
            env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"opencode exit {proc.returncode}: {(proc.stderr or proc.stdout)[:300]}")
        envelope = _last_json_event(proc.stdout)
        return _extract_opencode_text(proc.stdout), envelope

    def _record(self, record: CallRecord) -> None:
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record)) + "\n")


def _discover_project_root(path: Path) -> Path:
    for parent in Path(path).resolve().parents:
        if any((parent / name).exists() for name in ("opencode.jsonc", "opencode.json", ".git")):
            return parent
    return Path.cwd()


def _last_json_event(stdout: str) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for raw in stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            last = parsed
    if last:
        return last
    try:
        parsed = json.loads(stdout)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_opencode_text(stdout: str) -> str:
    candidates: list[str] = []
    for raw in stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except ValueError:
            continue
        _collect_text(parsed, candidates)
    if not candidates:
        try:
            parsed = json.loads(stdout)
        except ValueError:
            return stdout
        _collect_text(parsed, candidates)
    for candidate in reversed(candidates):
        if "{" in candidate and "}" in candidate:
            return candidate
    return stdout


def _collect_text(value: Any, candidates: list[str]) -> None:
    if isinstance(value, str):
        text = value.strip()
        if text:
            candidates.append(text)
        return
    if isinstance(value, list):
        for item in value:
            _collect_text(item, candidates)
        return
    if not isinstance(value, dict):
        return
    for key in ("result", "text", "content", "output"):
        if key in value:
            _collect_text(value[key], candidates)
    for key in ("message", "part", "parts", "data"):
        child = value.get(key)
        if isinstance(child, (dict, list)):
            _collect_text(child, candidates)


def _usage_from_envelope(envelope: dict[str, Any]) -> tuple[int, int, int]:
    if not isinstance(envelope, dict):
        return 0, 0, 0
    part = envelope.get("part", {})
    if not isinstance(part, dict):
        part = {}
    tokens = part.get("tokens", {}) if isinstance(part, dict) else {}
    usage = envelope.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    if not isinstance(tokens, dict):
        tokens = {}
    prompt = int(tokens.get("input", usage.get("prompt_tokens", usage.get("input_tokens", 0))) or 0)
    completion = int(tokens.get("output", usage.get("completion_tokens", usage.get("output_tokens", 0))) or 0)
    total = int(tokens.get("total", usage.get("total_tokens", prompt + completion)) or 0)
    return prompt, completion, total


def _cost_from_envelope(envelope: dict[str, Any]) -> float | None:
    if not isinstance(envelope, dict):
        return None
    part = envelope.get("part", {})
    cost = envelope.get("cost")
    if isinstance(part, dict) and cost is None:
        cost = part.get("cost")
    if cost is None:
        return None
    try:
        return float(cost)
    except (TypeError, ValueError):
        return None
