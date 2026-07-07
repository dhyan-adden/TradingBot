from tradeloop.lib.memory.writer import append_provenanced


def test_provenance_header_written(tmp_path):
    path = tmp_path / "trade_journal.md"
    assert append_provenanced(path, "TCS 2026-07-02", "Exited at target.", run_id="R1", timestamp="2026-07-02T16:00")
    text = path.read_text(encoding="utf-8")
    assert "run_id: R1" in text
    assert "2026-07-02T16:00" in text
    assert "hash:" in text
    assert "Exited at target." in text


def test_provenance_dedup(tmp_path):
    path = tmp_path / "trade_journal.md"
    assert append_provenanced(path, "TCS", "same body", run_id="R1", timestamp="t1")
    assert not append_provenanced(path, "TCS", "same body", run_id="R1", timestamp="t1")
