from typing import Any

from tradingbot.event_log import EventLog


def log_step(event_log: EventLog, scope: str, step: str, **payload: Any) -> None:
    material = {
        "scope": scope,
        "step": step,
        **payload,
    }
    event_log.append_event("runtime.step", f"STEP-{scope.upper()}", material)
    detail = _format_payload(payload)
    print(f"[tradingbot] {scope}.{step}{detail}")


def _format_payload(payload: dict[str, Any]) -> str:
    if not payload:
        return ""
    parts: list[str] = []
    for key, value in payload.items():
        if isinstance(value, list):
            if len(value) <= 5 and all(isinstance(item, str) for item in value):
                rendered = ",".join(value)
            else:
                rendered = f"{len(value)} items"
        elif isinstance(value, dict):
            rendered = f"{len(value)} keys"
        else:
            rendered = str(value)
        if len(rendered) > 80:
            rendered = rendered[:77] + "..."
        parts.append(f"{key}={rendered}")
    return " " + " ".join(parts)
