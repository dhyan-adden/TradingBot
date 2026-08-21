#!/usr/bin/env python
"""Record Codex/OpenRouter usage in the run directory for dashboard display."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


# OpenRouter rates as USD per token. Used only when Codex reports tokens but not
# the provider's computed cost; provider-reported cost always takes precedence.
MODEL_RATES = {
    "minimax/minimax-m3": (0.00000030, 0.00000120),
    "xiaomi/mimo-v2.5": (0.00000014, 0.00000028),
    "deepseek/deepseek-v4-flash-0731": (0.00000014, 0.00000028),
}


def _usage(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    usage = value.get("usage")
    if not isinstance(usage, dict):
        usage = value
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    total_tokens = usage.get("total_tokens")
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    input_tokens = int(input_tokens or 0)
    output_tokens = int(output_tokens or 0)
    total_tokens = int(total_tokens or input_tokens + output_tokens)
    cost = usage.get("cost", usage.get("total_cost", value.get("cost")))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": float(cost) if cost is not None else None,
    }


def _find_usage(value: object) -> dict | None:
    direct = _usage(value)
    if direct:
        return direct
    if isinstance(value, dict):
        for child in value.values():
            found = _find_usage(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_usage(child)
            if found:
                return found
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--model", default="minimax/minimax-m3")
    args = parser.parse_args()

    usages = []
    for line in args.events.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        found = _find_usage(event)
        if found:
            usages.append(found)
    if not usages:
        return 0

    # Codex normally emits one turn-level usage event. Keep the final event to
    # avoid double-counting nested item and turn summaries.
    found = usages[-1]
    cost = found["cost_usd"]
    cost_known = cost is not None
    if cost is None and args.model in MODEL_RATES:
        input_rate, output_rate = MODEL_RATES[args.model]
        cost = found["input_tokens"] * input_rate + found["output_tokens"] * output_rate
        cost_known = True
        cost_source = "estimated_openrouter_pricing"
    else:
        cost_source = "provider_reported"
    output = {
        "calls": 1,
        "successful_calls": 1,
        "failed_calls": 0,
        "prompt_tokens": found["input_tokens"],
        "completion_tokens": found["output_tokens"],
        "total_tokens": found["total_tokens"],
        "cost_usd": round(cost or 0.0, 8),
        "cost_known": cost_known,
        "cost_source": cost_source,
        "model": args.model,
    }
    (args.run_dir / "codex_usage.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
