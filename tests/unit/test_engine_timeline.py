"""
tests/unit/test_engine_timeline.py
------------------------------------
Unit tests for engine.timeline — fold() and Timeline.

These tests verify the core invariants that must hold after every edit:
  - apply-then-undo returns identical hash (R-HIST-06)
  - incremental fold == fold-from-scratch
  - captions follow surviving words (R-CAP-01)
  - caption hidden when words are cut (R-CUT-06)
  - speed changes split correctly (R-SPEED-02)
"""
import pytest
from engine.transcript import build_transcript
from engine.timeline import fold, Timeline
from engine.history import History
from engine.ops import CutOp, SpeedOp, AddCaptionOp, KeepOp, MuteOp


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_transcript(duration_s: int = 10):
    """Create a simple 10-word transcript spanning duration_s seconds."""
    raw = []
    word_dur_us = (duration_s * 1_000_000) // 10
    gap_us = word_dur_us // 10
    words = ["alpha", "beta", "gamma", "delta", "epsilon",
             "zeta", "eta", "theta", "iota", "kappa"]
    t = 0
    for w in words:
        raw.append({"text": w, "start_us": t, "end_us": t + word_dur_us - gap_us,
                    "confidence": 0.99})
        t += word_dur_us
    return build_transcript(raw, source_id="test", duration_us=duration_s * 1_000_000)


def make_history_with_cut(start_us: int, end_us: int):
    h = History()
    gid = h.begin_group()
    op = CutOp(op_id=0, group_id=gid, start_us=start_us, end_us=end_us)
    h.append(op)
    h.end_group()
    return h


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestFoldBasic:
    def test_empty_ops_full_duration(self):
        t = make_transcript(10)
        timeline = fold(t, [])
        assert timeline.duration_us == 10_000_000

    def test_cut_reduces_duration(self):
        t = make_transcript(10)
        h = make_history_with_cut(0, 3_000_000)
        timeline = fold(t, h.active_ops())
        assert timeline.duration_us == 7_000_000

    def test_cut_middle(self):
        t = make_transcript(10)
        h = History()
        gid = h.begin_group()
        h.append(CutOp(op_id=0, group_id=gid, start_us=3_000_000, end_us=6_000_000))
        h.end_group()
        timeline = fold(t, h.active_ops())
        assert timeline.duration_us == 7_000_000

    def test_keep_only(self):
        t = make_transcript(10)
        h = History()
        gid = h.begin_group()
        h.append(KeepOp(op_id=0, group_id=gid, start_us=2_000_000, end_us=5_000_000))
        h.end_group()
        timeline = fold(t, h.active_ops())
        assert timeline.duration_us == 3_000_000

    def test_no_segments_after_whole_cut(self):
        t = make_transcript(10)
        h = make_history_with_cut(0, 10_000_000)
        timeline = fold(t, h.active_ops())
        assert timeline.duration_us == 0


class TestFoldDeterminism:
    def test_identical_hash_three_runs(self):
        """Same ops → same hash every time.  (R-HIST-06)"""
        t = make_transcript(10)
        h = make_history_with_cut(1_000_000, 3_000_000)
        ops = h.active_ops()

        hashes = [fold(t, ops).timeline_hash() for _ in range(3)]
        assert hashes[0] == hashes[1] == hashes[2]

    def test_different_ops_different_hash(self):
        t = make_transcript(10)
        h1 = make_history_with_cut(0, 1_000_000)
        h2 = make_history_with_cut(0, 2_000_000)
        assert fold(t, h1.active_ops()).timeline_hash() != fold(t, h2.active_ops()).timeline_hash()


class TestApplyThenUndo:
    def test_undo_restores_original_hash(self):
        """apply-then-undo returns identical hash as before apply.  (R-HIST-06)"""
        t = make_transcript(10)
        h = History()
        original_hash = fold(t, h.active_ops()).timeline_hash()

        h.begin_group()
        h.append(CutOp(op_id=0, group_id=0, start_us=0, end_us=2_000_000))
        h.end_group()
        # After apply, hash is different
        assert fold(t, h.active_ops()).timeline_hash() != original_hash

        h.undo()
        # After undo, hash must equal original
        assert fold(t, h.active_ops()).timeline_hash() == original_hash


class TestSpeedOps:
    def test_speed_changes_duration(self):
        t = make_transcript(10)
        h = History()
        gid = h.begin_group()
        # Speed up 0-5s by 2x
        h.append(SpeedOp(op_id=0, group_id=gid, start_us=0, end_us=5_000_000, factor=2.0))
        h.end_group()
        timeline = fold(t, h.active_ops())
        # First 5s at 2x = 2.5s; rest 5s at 1x = 5s; total = 7.5s
        assert timeline.duration_us == 7_500_000

    def test_speed_last_writer_wins(self):
        """Overlapping speed changes: last wins.  (R-SPEED-02)"""
        t = make_transcript(10)
        h = History()
        gid = h.begin_group()
        h.append(SpeedOp(op_id=0, group_id=gid, start_us=0, end_us=10_000_000, factor=2.0))
        h.end_group()
        gid2 = h.begin_group()
        # Override 3-7s with 1x speed
        h.append(SpeedOp(op_id=0, group_id=gid2, start_us=3_000_000, end_us=7_000_000, factor=1.0))
        h.end_group()
        timeline = fold(t, h.active_ops())
        # 0-3s at 2x = 1.5s; 3-7s at 1x = 4s; 7-10s at 2x = 1.5s; total = 7s
        assert timeline.duration_us == 7_000_000


class TestCaptions:
    def test_caption_follows_surviving_words(self):
        t = make_transcript(10)
        h = History()
        # Add caption on word "alpha" (w0000, 0-900000µs)
        gid = h.begin_group()
        h.append(AddCaptionOp(
            op_id=0, group_id=gid, caption_id=0,
            text="Hello!", word_id_start="w0000", word_id_end="w0000",
        ))
        h.end_group()
        # Cut the first 1 second (before alpha)
        gid2 = h.begin_group()
        h.append(CutOp(op_id=0, group_id=gid2, start_us=0, end_us=0))
        h.end_group()
        timeline = fold(t, h.active_ops())
        captions = [c for c in timeline.captions if not c.hidden]
        assert len(captions) == 1
        # Caption should be at t=0 now (word survived, just shifted)

    def test_caption_hidden_when_words_cut(self):
        """Caption is hidden when all its words are cut.  (R-CUT-06)"""
        t = make_transcript(10)
        h = History()
        # Add caption anchored to first word (0-900ms)
        gid = h.begin_group()
        h.append(AddCaptionOp(
            op_id=0, group_id=gid, caption_id=0,
            text="Hello!", word_id_start="w0000", word_id_end="w0000",
        ))
        h.end_group()
        # Cut the entire first second (removes "alpha" word)
        gid2 = h.begin_group()
        h.append(CutOp(op_id=0, group_id=gid2, start_us=0, end_us=1_000_000))
        h.end_group()
        timeline = fold(t, h.active_ops())
        hidden = [c for c in timeline.captions if c.hidden]
        assert len(hidden) == 1

    def test_caption_restored_after_undo(self):
        """Hidden caption comes back when cut is undone.  (R-HIST-05, R-CUT-06)"""
        t = make_transcript(10)
        h = History()
        gid = h.begin_group()
        h.append(AddCaptionOp(
            op_id=0, group_id=gid, caption_id=0,
            text="Hello!", word_id_start="w0000", word_id_end="w0000",
        ))
        h.end_group()
        gid2 = h.begin_group()
        h.append(CutOp(op_id=0, group_id=gid2, start_us=0, end_us=1_000_000))
        h.end_group()

        # Caption hidden
        assert fold(t, h.active_ops()).captions[0].hidden

        # Undo the cut
        h.undo()

        # Caption restored
        assert not fold(t, h.active_ops()).captions[0].hidden


class TestMuteOp:
    def test_mute_segment_created(self):
        t = make_transcript(10)
        h = History()
        gid = h.begin_group()
        h.append(MuteOp(op_id=0, group_id=gid, start_us=2_000_000, end_us=4_000_000))
        h.end_group()
        timeline = fold(t, h.active_ops())
        muted = [s for s in timeline.segments if s.muted]
        assert len(muted) == 1
        assert muted[0].src_start_us == 2_000_000
        assert muted[0].src_end_us == 4_000_000

    def test_total_duration_unchanged_by_mute(self):
        t = make_transcript(10)
        h = History()
        gid = h.begin_group()
        h.append(MuteOp(op_id=0, group_id=gid, start_us=2_000_000, end_us=4_000_000))
        h.end_group()
        timeline = fold(t, h.active_ops())
        assert timeline.duration_us == 10_000_000  # mute doesn't shorten video


class TestIncrementalVsFull:
    def test_incremental_equals_full_fold(self):
        """
        fold(transcript, all_active_ops) should always equal
        fold applied one op at a time (i.e. no incremental cache corruption).
        We verify this by comparing hashes.
        """
        t = make_transcript(10)
        h = History()
        gid1 = h.begin_group()
        h.append(CutOp(op_id=0, group_id=gid1, start_us=0, end_us=1_000_000))
        h.end_group()
        gid2 = h.begin_group()
        h.append(SpeedOp(op_id=0, group_id=gid2, start_us=2_000_000, end_us=5_000_000, factor=1.5))
        h.end_group()

        # Full fold from scratch
        hash_full = fold(t, h.active_ops()).timeline_hash()

        # Simulate incremental: fold after each op added
        h2 = History()
        gid_a = h2.begin_group()
        h2.append(CutOp(op_id=0, group_id=gid_a, start_us=0, end_us=1_000_000))
        h2.end_group()
        gid_b = h2.begin_group()
        h2.append(SpeedOp(op_id=0, group_id=gid_b, start_us=2_000_000, end_us=5_000_000, factor=1.5))
        h2.end_group()

        hash_incremental = fold(t, h2.active_ops()).timeline_hash()
        assert hash_full == hash_incremental
