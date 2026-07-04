import json
from pathlib import Path

from tradeloop.lib.data.evidence import validate_evidence
from tradeloop.lib.data.snapshot import Snapshot


def _snap(ids):
    return Snapshot(run_dir=Path("."), snapshot_hash="x", news_ids=set(ids))


def test_all_cited_ids_present_passes(tmp_path):
    # kills a false-positive rejection when every cited news_id is legitimately in the snapshot
    (tmp_path / "20_bull.json").write_text(json.dumps(
        {"claims": [{"text": "strong", "evidence": ["aaaaaaaaaaaa"]}]}))
    res = validate_evidence(tmp_path, _snap({"aaaaaaaaaaaa", "bbbbbbbbbbbb"}))
    assert res.ok is True and res.missing == []


def test_missing_cited_id_rejected(tmp_path):
    # kills the core bug this validator exists to catch: a phantom/fabricated news_id citation
    (tmp_path / "20_bull.json").write_text(json.dumps(
        {"evidence": ["ffffffffffff"]}))
    res = validate_evidence(tmp_path, _snap({"aaaaaaaaaaaa"}))
    assert res.ok is False
    assert ("20_bull.json", "ffffffffffff") in res.missing


def test_no_evidence_arrays_is_ok(tmp_path):
    # kills a false-positive rejection of artifacts that have no evidence field at all
    (tmp_path / "10_news.json").write_text(json.dumps({"names": ["RELIANCE"]}))
    assert validate_evidence(tmp_path, _snap(set())).ok is True
