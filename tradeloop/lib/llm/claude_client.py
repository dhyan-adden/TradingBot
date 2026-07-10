"""Claude-subscription stage transport: one `claude -p` per DAG stage.

Mirrors LLMClient's SupportsCallJson contract but reaches Claude models on the
local subscription through the `claude` CLI instead of OpenRouter over httpx.
The prompt is delivered on stdin (no ARG_MAX ceiling for large setup blocks),
and output handling reuses client.py's schema-pinned system prompt, brace
extraction, hollow-{} rejection, pydantic validation, and CallRecord provenance
so the audit log is byte-compatible with the OpenRouter path.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

from pydantic import BaseModel, ValidationError

from tradeloop.lib.llm import routing
from tradeloop.lib.llm.client import (
    CallRecord, LLMValidationError, _failed_record, _parse_json_object,
    build_system_content,
)


class ClaudeStageClient:
    def __init__(self, audit_path: Path, cli: str = "claude",
                 max_retries: int = 3, per_call_timeout: float = 120.0) -> None:
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.cli = cli
        self.max_retries = max_retries
        self.per_call_timeout = per_call_timeout

    def call_json(self, role: str, system: str, user: str,
                  schema: type[BaseModel], model: str | None = None) -> BaseModel:
        model = model or routing.claude_model_for(role)
        system_content = build_system_content(system, schema)
        stdin_prompt = f"{system_content}\n\n{user}"   # to claude on stdin; no ARG_MAX
        prompt = f"{system}\n\n{user}"                 # recorded for provenance parity
        argv = [self.cli, "-p", "--model", model,
                "--output-format", "json", "--max-turns", "1"]
        # Force the subscription: strip any Anthropic API credentials so claude -p
        # can never silently bill the metered API. Subscription, or a loud failure.
        env = {k: v for k, v in os.environ.items()
               if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}

        last_exc: Exception | None = None
        for _ in range(self.max_retries):
            try:
                proc = subprocess.run(argv, input=stdin_prompt, capture_output=True,
                                      text=True, timeout=self.per_call_timeout, env=env)
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"claude -p exit {proc.returncode}: {(proc.stderr or '')[:200]}")
                envelope = json.loads(proc.stdout)
                text = str(envelope.get("result", ""))
                obj = _parse_json_object(text)         # fence strip + brace extract + reject {}
                validated = schema.model_validate(obj)
            except (subprocess.TimeoutExpired, subprocess.SubprocessError,
                    RuntimeError, ValueError, ValidationError) as exc:
                last_exc = exc
                self._record(_failed_record(role, f"claude:{model}", prompt, str(exc)))
                continue
            usage = envelope.get("usage", {}) or {}
            in_tok = int(usage.get("input_tokens", 0))
            out_tok = int(usage.get("output_tokens", 0))
            self._record(CallRecord(
                role=role, model=f"claude:{model}",
                model_version=str(next(iter(envelope.get("modelUsage", {})), model)),
                response_id=str(envelope.get("session_id", "")),
                prompt=prompt, response=text,
                prompt_tokens=in_tok, completion_tokens=out_tok,
                total_tokens=in_tok + out_tok, used_model=True))
            return validated
        raise LLMValidationError(
            f"{role} failed on claude:{model} after {self.max_retries} tries: {last_exc}")

    def _record(self, record: CallRecord) -> None:
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record)) + "\n")
