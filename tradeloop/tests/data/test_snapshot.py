import hashlib

from tradeloop.lib.data.snapshot import news_id, freeze, render_news_raw, load_snapshot
from tradeloop.lib.data.tickers import TaggedStory


def _story(nid):
    return TaggedStory("RELIANCE", "Reliance profit", "http://x", "google_news_generic",
                       "tier_C", "earnings", nid, 1.0)


def test_news_id_deterministic_and_12():
    a = news_id("g", "u", "t")
    assert a == hashlib.sha256("g|u|t".encode()).hexdigest()[:12]
    assert len(a) == 12
    assert news_id("g", "u", "t") == a


def test_freeze_writes_and_hashes(tmp_path):
    stories = [_story("abc123abc123")]
    snap_dir, snap_hash = freeze(stories, [], [], tmp_path)
    assert (snap_dir / "items.jsonl").exists()
    assert (snap_dir / "snapshot_hash.txt").read_text().strip() == snap_hash
    assert len(snap_hash) == 64  # full sha256 over frozen bytes


def test_render_marks_no_news_loudly():
    out = render_news_raw([], [], news_available=False)
    assert "NO NEWS DATA" in out


def test_load_snapshot_rehydrates_news_ids(tmp_path):
    # kills a bug where load_snapshot fails to surface a frozen story's news_id
    stories = [_story("abc123abc123")]
    freeze(stories, [], [], tmp_path)
    snap = load_snapshot(tmp_path)
    assert snap is not None
    assert "abc123abc123" in snap.news_ids


def test_load_snapshot_missing_dir_returns_none(tmp_path):
    # kills a bug where a run_dir with no snapshot/ crashes instead of degrading to None
    assert load_snapshot(tmp_path) is None
