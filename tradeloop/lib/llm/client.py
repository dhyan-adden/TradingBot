"""In-process OpenRouter chat-completions client.

Transport reuses the proven pattern in src/tradingbot/llm.py (JSON-only system
prompt, brace-balanced JSON extraction, tolerant content parsing) and adds:
retry/backoff, response_format=json_schema, pydantic validation with retry on
invalid output, and a full provenance CallRecord (model_version / response_id /
prompt / response / token usage) appended to an audit JSONL - the
input-reproducibility half of DoD #3.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError


class LLMConfigError(RuntimeError):
    """Provider disabled or API key missing."""


class LLMValidationError(RuntimeError):
    """Model output could not be parsed/validated against the schema after retries."""


@dataclass(frozen=True)
class CallRecord:
    role: str
    model: str
    model_version: str
    response_id: str
    prompt: str
    response: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    used_model: bool
    reason: str = ""


class LLMClient:
    def __init__(
        self,
        audit_path: Path,
        api_key_env: str = "OPENROUTER_API_KEY",
        base_url: str = "https://openrouter.ai/api/v1",
        default_model: str = "xiaomi/mimo-v2.5",
        fallback_models: tuple[str, ...] = ("minimax/minimax-m3", "xiaomi/mimo-v2.5"),
        max_tokens: int = 4000,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.api_key_env = api_key_env
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.fallback_models = tuple(fallback_models)
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout_seconds = timeout_seconds

    def call_json(
        self, role: str, system: str, user: str, schema: type[BaseModel], model: str | None = None
    ) -> BaseModel:
        model = model or self.default_model
        api_key = os.getenv(self.api_key_env)  # only sanctioned secret read; never logged
        if not api_key:
            raise LLMConfigError(f"{self.api_key_env} not set")

        prompt = f"{system}\n\n{user}"
        # Give the model the exact output shape. Without this it invents prose
        # keys ("Names in play today") that never match the pydantic fields, so
        # extra="ignore" silently defaults every field and the object comes back
        # hollow. The JSON Schema pins field names/types/required + enums.
        schema_hint = json.dumps(schema.model_json_schema(), separators=(",", ":"))
        system_content = (
            f"{system}\n\n"
            "You are one bounded agent inside an Indian-market paper trading "
            "system. India cash equities only, long-only. Return ONE compact JSON "
            "object and nothing else, conforming to this JSON Schema - use these "
            "EXACT field names (not prose labels), correct types, and every required "
            f"field:\n{schema_hint}\n"
            "When a claim rests on a news item, cite it by copying the bracketed "
            "[news_id] tokens from the input verbatim into the nearest 'evidence' "
            "array. Do not request order execution; risk, gate and broker controls "
            "are deterministic and final."
        )

        # Try the assigned model, then a chain of DISTINCT fallbacks. A single flaky
        # provider (deepseek-v4-flash OR mimo returning empty content) must not kill
        # the cycle - a completed run on a fallback beats a dead run, and the senior
        # judge reviews everything downstream anyway. Distinct is the point: the
        # assigned model is skipped from the chain so a mimo-primary stage still gets
        # a genuinely different model (minimax) to fall to.
        models = [model]
        for fb in self.fallback_models:
            if fb not in models:
                models.append(fb)

        last_exc: Exception | None = None
        for m in models:
            payload = {
                "model": m,
                "max_tokens": self.max_tokens,
                # Best-effort structured-output nudge only. Correctness is guaranteed
                # by our own brace-balanced extraction + pydantic validation below, so
                # this stays broadly-supported (json_object, not strict json_schema
                # which some providers 400 on) and is dropped on a 400 downgrade.
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user},
                ],
            }
            for attempt in range(self.max_retries):
                try:
                    response = httpx.post(
                        f"{self.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}",
                                 "Content-Type": "application/json"},
                        json=payload,
                        timeout=self.timeout_seconds,
                    )
                    response.raise_for_status()
                    body = response.json()
                    text = _extract_output_text(body)
                    obj = _parse_json_object(text)
                    validated = schema.model_validate(obj)
                except (httpx.HTTPError, ValueError, ValidationError) as exc:
                    last_exc = exc
                    # Graceful downgrade: some providers reject response_format with a
                    # 400. Drop it so the next attempt relies on the prompt + our
                    # extraction instead of hard-failing the whole cycle.
                    if (isinstance(exc, httpx.HTTPStatusError)
                            and exc.response.status_code == 400
                            and "response_format" in payload):
                        payload.pop("response_format", None)
                    self._record(_failed_record(role, m, prompt, str(exc)))
                    if attempt < self.max_retries - 1:
                        time.sleep(self.backoff_base * (2 ** attempt))
                    continue
                self._record(CallRecord(
                    role=role, model=m,
                    model_version=str(body.get("model", m)),
                    response_id=str(body.get("id", "")),
                    prompt=prompt, response=text,
                    prompt_tokens=int(body.get("usage", {}).get("prompt_tokens", 0)),
                    completion_tokens=int(body.get("usage", {}).get("completion_tokens", 0)),
                    total_tokens=int(body.get("usage", {}).get("total_tokens", 0)),
                    used_model=True,
                ))
                return validated

        raise LLMValidationError(
            f"{role} failed on {models} after {self.max_retries} tries each: {last_exc}")

    def _record(self, record: CallRecord) -> None:
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record)) + "\n")


def _failed_record(role: str, model: str, prompt: str, reason: str) -> CallRecord:
    return CallRecord(role, model, model, "", prompt, "", 0, 0, 0, False, reason)


def _extract_output_text(body: dict[str, Any]) -> str:
    choices = body.get("choices", [])
    if choices:
        message = choices[0].get("message", {}) or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    raise ValueError("model returned empty content")


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    cleaned = _first_json_object(cleaned)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("model output must be a JSON object")
    return parsed


def _first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]
