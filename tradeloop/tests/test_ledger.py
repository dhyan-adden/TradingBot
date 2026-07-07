from pathlib import Path

import pytest

from tradeloop.lib.audit import ledger as L
from tradeloop.lib.broker.paper_broker import PaperBroker


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


def test_verify_chain_passes_on_untouched_ledger(tmp_path):
    led = _ledger(tmp_path)
    led.append({"type": "a", "v": 1})
    led.append({"type": "b", "v": 2})
    led.verify_chain()  # must not raise


def test_mutating_a_row_breaks_the_chain(tmp_path):
    led = _ledger(tmp_path)
    led.append({"type": "a", "v": 1})
    led.append({"type": "b", "v": 2})
    led.append({"type": "c", "v": 3})
    # tamper: rewrite row 2's payload directly, bypassing append
    import sqlite3
    conn = sqlite3.connect(str(led.db_path))
    tampered = L.canonical({"type": "b", "v": 999, "ts": "2026-07-02T00:00:00+00:00"})
    conn.execute("UPDATE events SET payload_json = ? WHERE seq = 2", (tampered,))
    conn.commit()
    conn.close()
    with pytest.raises(L.LedgerTamperError):
        led.verify_chain()


def test_deleting_a_row_breaks_the_chain(tmp_path):
    led = _ledger(tmp_path)
    led.append({"type": "a"})
    led.append({"type": "b"})
    led.append({"type": "c"})
    import sqlite3
    conn = sqlite3.connect(str(led.db_path))
    conn.execute("DELETE FROM events WHERE seq = 2")
    conn.commit()
    conn.close()
    with pytest.raises(L.LedgerTamperError):
        led.verify_chain()


def test_mutating_the_genesis_linked_row_is_caught(tmp_path):
    # row 1 (seq=1) links to GENESIS_HASH, not a prior row's hash. Its own
    # verification path (recomputed row_hash) differs from a middle row's
    # (which also checks prev_hash linkage), so it needs its own test.
    led = _ledger(tmp_path)
    led.append({"type": "a", "v": 1})
    led.append({"type": "b", "v": 2})
    import sqlite3
    conn = sqlite3.connect(str(led.db_path))
    tampered = L.canonical({"type": "a", "v": 999, "ts": "2026-07-02T00:00:00+00:00"})
    conn.execute("UPDATE events SET payload_json = ? WHERE seq = 1", (tampered,))
    conn.commit()
    conn.close()
    with pytest.raises(L.LedgerTamperError):
        led.verify_chain()


def test_project_positions_matches_known_fill_sequence(tmp_path):
    led = _ledger(tmp_path)
    # BUY 10 @ 100, BUY 10 @ 120  -> qty 20, avg 110 ; SELL 5 @ 130 -> qty 15
    for ev in [
        {"type": L.ORDER_FILLED, "symbol": "TCS", "side": "BUY", "quantity": 10,
         "fill_price": 100.0, "product": "CNC", "order_id": "P1", "hard_stop": 90.0},
        {"type": L.ORDER_FILLED, "symbol": "TCS", "side": "BUY", "quantity": 10,
         "fill_price": 120.0, "product": "CNC", "order_id": "P2", "hard_stop": 95.0},
        {"type": L.ORDER_FILLED, "symbol": "TCS", "side": "SELL", "quantity": 5,
         "fill_price": 130.0, "product": "CNC", "order_id": "P3", "hard_stop": 0.0},
    ]:
        led.append(ev)

    broker = led.project_positions(starting_cash_inr=1_000_000.0)

    assert isinstance(broker, PaperBroker)
    assert broker.positions["TCS"] == 15
    assert broker.avg_prices["TCS"] == pytest.approx(110.0)


def test_project_positions_ignores_non_fill_events(tmp_path):
    led = _ledger(tmp_path)
    led.append({"type": L.FETCH_OK, "source": "rss"})
    led.append({"type": L.MODEL_CALL, "role": "news"})
    led.append({"type": L.ORDER_FILLED, "symbol": "INFY", "side": "BUY", "quantity": 4,
                "fill_price": 50.0, "product": "CNC", "order_id": "P9", "hard_stop": 45.0})
    broker = led.project_positions(starting_cash_inr=500_000.0)
    assert broker.positions == {"INFY": 4}


def test_project_positions_full_sell_removes_symbol_from_positions(tmp_path):
    # BUY then a full SELL of the same symbol must leave it ABSENT from
    # positions (paper_broker._apply_fill pops a zeroed position), not present
    # with qty 0 - a qty-0 check would pass even if the pop logic broke.
    led = _ledger(tmp_path)
    led.append({"type": L.ORDER_FILLED, "symbol": "TCS", "side": "BUY", "quantity": 10,
                "fill_price": 100.0, "product": "CNC", "order_id": "P1", "hard_stop": 90.0})
    led.append({"type": L.ORDER_FILLED, "symbol": "TCS", "side": "SELL", "quantity": 10,
                "fill_price": 110.0, "product": "CNC", "order_id": "P2", "hard_stop": 0.0})
    broker = led.project_positions(starting_cash_inr=1_000_000.0)
    assert "TCS" not in broker.positions
    assert "TCS" not in broker.avg_prices


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


def test_fetch_and_model_loggers(tmp_path):
    led = _ledger(tmp_path)
    led.log_fetch_ok("google_news", count=7, url="https://news.example/rss")
    led.log_fetch_fail("nse_bse", error="HTTP 503")
    led.log_model_call("bull", "anthropic/claude", prompt_tokens=800,
                        completion_tokens=200, latency_ms=1420)
    rows = led.replay()
    assert [r["type"] for r in rows] == [L.FETCH_OK, L.FETCH_FAIL, L.MODEL_CALL]
    assert rows[0]["count"] == 7 and rows[0]["source"] == "google_news"
    assert rows[1]["error"] == "HTTP 503"
    assert rows[2]["prompt_tokens"] == 800 and rows[2]["latency_ms"] == 1420
    # no secret-like keys leaked into the model-call event
    assert not any(k.lower().endswith(("key", "secret", "token")) for k in rows[2])
    led.verify_chain()
