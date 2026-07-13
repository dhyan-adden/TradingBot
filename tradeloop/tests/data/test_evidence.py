import json
from pathlib import Path

from tradeloop.lib.data.evidence import uncited_news_candidates, validate_evidence
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


def _shortlist(tmp_path, tracks):
    (tmp_path / "14_shortlist.json").write_text(json.dumps({
        "evidence": [],
        "candidates": [{"ticker": f"T{i}", "source_track": t} for i, t in enumerate(tracks)],
    }))


def test_uncited_news_candidates_warns_on_news_track_with_zero_citations(tmp_path):
    # the gate's blind spot: a model that silently stops citing passes
    # validate_evidence; news-track candidates with NO citations anywhere is
    # the one suspicious shape this tripwire exists to flag
    _shortlist(tmp_path, ["tier_a", "quiet"])
    assert uncited_news_candidates(tmp_path) == ["T0"]


def test_uncited_news_candidates_quiet_day_is_healthy(tmp_path):
    # 2026-07-13 live case: all-quiet technical shortlist legitimately cites nothing
    _shortlist(tmp_path, ["quiet", "quiet"])
    assert uncited_news_candidates(tmp_path) == []


def test_uncited_news_candidates_ok_when_anything_cites(tmp_path):
    # citations anywhere in the run mean the chain is alive - no warning
    _shortlist(tmp_path, ["tier_b"])
    (tmp_path / "10_news.json").write_text(json.dumps({"evidence": ["a1b2c3d4e5f6"]}))
    assert uncited_news_candidates(tmp_path) == []


def test_uncited_news_candidates_degrades_on_missing_or_malformed_shortlist(tmp_path):
    assert uncited_news_candidates(tmp_path) == []
    (tmp_path / "14_shortlist.json").write_text("{not json")
    assert uncited_news_candidates(tmp_path) == []
