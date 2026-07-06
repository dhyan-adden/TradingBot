from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from tradeloop.lib.data.ticker_master import load_master

log = logging.getLogger("tradeloop.universe")


def _read_cache(cache_path: Path, max_age_days: int, today: date) -> "dict | None":
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        fetched = date.fromisoformat(str(data["fetched"]))
        if (today - fetched).days < max_age_days:
            return data
    except (ValueError, KeyError, OSError):
        return None  # corrupt/unreadable -> treat as stale
    return None


def _seed_tokens(kite_client, tokens: dict) -> None:
    # re-populate the client's token cache from the persisted map so a cache hit does
    # NOT force a per-symbol instrument lookup (each of which re-downloads the full CSV).
    cache = getattr(kite_client, "_token_cache", None)
    if isinstance(cache, dict) and tokens:
        cache.update({str(s).strip().upper(): int(t) for s, t in tokens.items()})


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

    cached = _read_cache(cache_path, max_age_days, today)
    if cached and cached.get("symbols"):
        if kite_client is not None:
            _seed_tokens(kite_client, cached.get("tokens") or {})
        return [str(s).strip().upper() for s in cached["symbols"]][:max_symbols]

    if kite_client is not None:
        try:
            tokens = kite_client.instruments("NSE")  # {SYMBOL: token}, also seeds the client cache
            symbols = sorted(tokens.keys())
            if symbols:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps({"fetched": today.isoformat(), "symbols": symbols, "tokens": tokens}),
                    encoding="utf-8")
                return symbols[:max_symbols]
        except Exception as exc:  # kite/token/transport failure -> degrade to yaml
            log.warning("universe fetch failed, falling back to yaml: %s", exc)

    return _yaml_symbols(yaml_path)[:max_symbols]
