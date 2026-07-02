import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from tradingbot.event_log import EventLog


@dataclass(frozen=True)
class ModelCallResult:
    role: str
    model: str
    content: dict[str, Any]
    used_model: bool
    reason: str = ""


class ModelRouter:
    def __init__(self, config: dict, event_log: EventLog, timeout_seconds: float = 30):
        self.config = config
        self.event_log = event_log
        self.timeout_seconds = timeout_seconds
        provider_config = config.get("model_provider", {})
        self.enabled = bool(provider_config.get("enabled", False))
        self.base_url = str(provider_config.get("base_url", "https://openrouter.ai/api/v1"))
        self.api_key_env = str(provider_config.get("api_key_env", "OPENROUTER_API_KEY"))
        self.default_model = str(provider_config.get("default_model", "deepseek/deepseek-v4-flash"))
        # Reasoning models (DeepSeek/MiniMax/Hy3/MiMo) spend tokens thinking before
        # emitting content, so the budget must clear the reasoning span. ponytail:
        # single global cap; per-role override only if a stage truncates.
        self.max_tokens = int(provider_config.get("max_tokens", 2000))
        self.role_models = {
            role: str(settings.get("model", self.default_model))
            for role, settings in config.get("agents", {}).items()
            if isinstance(settings, dict)
        }

    def call_json(self, role: str, prompt: str, fallback: dict[str, Any]) -> ModelCallResult:
        model = self.role_models.get(role, self.default_model)
        if not self.enabled:
            self._log("model.skipped", role, model, "model_provider_disabled")
            return ModelCallResult(role, model, fallback, False, "model_provider_disabled")

        api_key = os.getenv(self.api_key_env)
        if not api_key:
            self._log("model.skipped", role, model, "api_key_missing")
            return ModelCallResult(role, model, fallback, False, "api_key_missing")

        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "max_tokens": self.max_tokens,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are one bounded agent inside an Indian-market paper trading system. "
                                "Return compact JSON only. Do not request order execution. "
                                "Risk, order gate, and broker controls are deterministic and final."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            text = _extract_output_text(body)
            parsed = _parse_json_object(text)
            self.event_log.append_event(
                "model.response_written",
                f"MODEL-{role.upper()}",
                {"role": role, "model": model, "used_model": True, "content": parsed},
            )
            return ModelCallResult(role, model, parsed, True)
        except Exception as exc:
            self._log("model.failed", role, model, str(exc))
            return ModelCallResult(role, model, fallback, False, str(exc))

    def _log(self, event_type: str, role: str, model: str, reason: str) -> None:
        self.event_log.append_event(
            event_type,
            f"MODEL-{role.upper()}",
            {"role": role, "model": model, "reason": reason},
        )


def _extract_output_text(body: dict[str, Any]) -> str:
    # OpenRouter / OpenAI chat-completions shape.
    choices = body.get("choices", [])
    if choices:
        message = choices[0].get("message", {}) or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        # Some providers stream parts as a list of {type,text} blocks.
        if isinstance(content, list):
            return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    raise ValueError("model returned empty content (raise max_tokens for reasoning models)")


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
    """Return the first brace-balanced JSON object. Reasoning models (e.g. MiniMax M3)
    sometimes emit the object twice; rfind('}') would span both and break json.loads."""
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
