from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from tradeloop.lib.data.ticker_master import load_master

log = logging.getLogger("tradeloop.universe")


def _cache_symbols(cache_path: Path, max_age_days: int, today: date) -> "list[str] | None":
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        fetched = date.fromisoformat(str(data["fetched"]))
        if (today - fetched).days < max_age_days:
            return [str(s).strip().upper() for s in data.get("symbols", [])]
    except (ValueError, KeyError, OSError):
        return None  # corrupt/unreadable -> treat as stale
    return None


def _yaml_symbols(yaml_path: Path) -> "list[str]":
    try:
        return [s.strip().upper() for s in load_master(yaml_path).symbols()]
    except (OSError, ValueError):
        return []


def load_universe(kite_client, cache_path: Path, yaml_path: Path,
                  max_age_days: int = 7, max_symbols: int = 2500,
                  now: "date | None" = None) -> "list[str]":
    cache_path = Path(cache_path)
    today = now or date.today()

    cached = _cache_symbols(cache_path, max_age_days, today)
    if cached:
        return cached[:max_symbols]

    if kite_client is not None:
        try:
            symbols = sorted(kite_client.instruments("NSE").keys())
            if symbols:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps({"fetched": today.isoformat(), "symbols": symbols}),
                    encoding="utf-8")
                return symbols[:max_symbols]
        except Exception as exc:  # kite/token/transport failure -> degrade to yaml
            log.warning("universe fetch failed, falling back to yaml: %s", exc)

    return _yaml_symbols(yaml_path)[:max_symbols]
