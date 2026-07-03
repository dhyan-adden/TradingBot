import json
from pathlib import Path

import pytest

from tradeloop.lib.audit import ledger as L


def _ledger(tmp_path: Path) -> L.Ledger:
    return L.Ledger(tmp_path / "ledger.db")


def test_append_returns_hash_and_replay_roundtrips(tmp_path):
    led = _ledger(tmp_path)
    h1 = led.append({"type": "fetch.ok", "source": "google_news", "count": 3})
    h2 = led.append({"type": "model.call", "role": "news", "model": "x", "tokens": 42})
    assert isinstance(h1, str) and len(h1) == 64
    rows = led.replay()
    assert [r["type"] for r in rows] == ["fetch.ok", "model.call"]
    assert rows[0]["seq"] == 1 and rows[1]["seq"] == 2
    assert rows[0]["prev_hash"] == L.GENESIS_HASH
    assert rows[1]["prev_hash"] == h1
    assert rows[1]["row_hash"] == h2
    # payload fields survive the round trip
    assert rows[0]["source"] == "google_news"
    assert rows[0]["count"] == 3


def test_replay_filters_by_type(tmp_path):
    led = _ledger(tmp_path)
    led.append({"type": "fetch.ok", "source": "rss"})
    led.append({"type": "model.call", "role": "bull"})
    led.append({"type": "fetch.fail", "source": "nse"})
    fetches = led.replay(["fetch.ok", "fetch.fail"])
    assert [r["type"] for r in fetches] == ["fetch.ok", "fetch.fail"]


def test_chain_links_each_row_to_previous(tmp_path):
    led = _ledger(tmp_path)
    led.append({"type": "a"})
    led.append({"type": "b"})
    led.append({"type": "c"})
    rows = led.replay()
    for i in range(1, len(rows)):
        assert rows[i]["prev_hash"] == rows[i - 1]["row_hash"]


def test_append_requires_type(tmp_path):
    led = _ledger(tmp_path)
    with pytest.raises(KeyError):
        led.append({"source": "no_type"})


def test_canonical_is_deterministic_regardless_of_key_order():
    a = {"b": 1, "a": {"z": [3, 2, 1], "y": 2}}
    b = {"a": {"y": 2, "z": [3, 2, 1]}, "b": 1}
    assert L.canonical(a) == L.canonical(b)


def test_nested_payload_roundtrips_through_append_and_replay(tmp_path):
    led = _ledger(tmp_path)
    payload = {
        "type": "fetch.ok",
        "source": "rss",
        "meta": {"tags": ["a", "b"], "nested": {"count": 2, "items": [1, 2, 3]}},
    }
    h = led.append(payload)
    rows = led.replay()
    assert rows[0]["meta"] == payload["meta"]
    # replay's recomputed material must match what append hashed: canonical() is
    # order-independent, so a payload rebuilt with different key order still
    # reproduces the same row_hash.
    reordered = {
        "meta": {"nested": {"items": [1, 2, 3], "count": 2}, "tags": ["a", "b"]},
        "source": "rss",
        "type": "fetch.ok",
        "ts": rows[0]["ts"],
    }
    assert L.row_hash(L.GENESIS_HASH, 1, reordered) == h
