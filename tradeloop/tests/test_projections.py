from pathlib import Path

from tradeloop.lib.audit import ledger as L
from tradeloop.lib.audit.projections import MarkdownProjector


def _seed(tmp_path: Path) -> L.Ledger:
    led = L.Ledger(tmp_path / "ledger.db")
    led.append({"type": L.FETCH_OK, "source": "google_news", "count": 5})
    led.append({"type": L.RISK_VERDICT, "symbol": "TCS", "approved": True, "reasons": []})
    led.append({"type": L.ORDER_FILLED, "symbol": "TCS", "side": "BUY", "quantity": 10,
                "fill_price": 100.0, "product": "CNC", "order_id": "P1", "hard_stop": 90.0})
    return led


def test_journal_written_with_all_events(tmp_path):
    led = _seed(tmp_path)
    proj = MarkdownProjector(led, tmp_path / "memory")
    result = proj.regenerate_journal()
    assert result.changed is True
    text = result.path.read_text(encoding="utf-8")
    assert "fetch.ok" in text
    assert "risk.verdict" in text
    assert "paper.order.filled" in text
    assert "source_event_hash:" in text


def test_journal_idempotent_no_rewrite_when_unchanged(tmp_path):
    led = _seed(tmp_path)
    proj = MarkdownProjector(led, tmp_path / "memory")
    first = proj.regenerate_journal()
    mtime_1 = first.path.stat().st_mtime_ns
    second = proj.regenerate_journal()
    assert second.changed is False
    assert second.path.stat().st_mtime_ns == mtime_1  # file untouched


def test_journal_rewrites_when_new_event_appended(tmp_path):
    led = _seed(tmp_path)
    proj = MarkdownProjector(led, tmp_path / "memory")
    proj.regenerate_journal()
    led.append({"type": L.FETCH_FAIL, "source": "nse_bse", "error": "timeout"})
    result = proj.regenerate_journal()
    assert result.changed is True
    assert "fetch.fail" in result.path.read_text(encoding="utf-8")


def test_journal_embeds_source_event_hash_unconditionally_no_config_read(tmp_path, monkeypatch):
    # Patch override: config/memory.yaml does not exist and must never be read.
    # Fail loudly if projections.py tries to open it - proves no config gate
    # guards the source_event_hash embed.
    import builtins

    real_open = builtins.open

    def _guarded_open(file, *args, **kwargs):
        if "memory.yaml" in str(file):
            raise AssertionError("projections.py must not read config/memory.yaml")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _guarded_open)

    led = _seed(tmp_path)
    proj = MarkdownProjector(led, tmp_path / "memory")
    result = proj.regenerate_journal()
    assert result.changed is True
    assert "source_event_hash:" in result.path.read_text(encoding="utf-8")
