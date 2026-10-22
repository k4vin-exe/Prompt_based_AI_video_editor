"""
tests/unit/test_engine_history.py
----------------------------------
Unit tests for engine.history — event-sourced edit history.
"""
import pytest
from engine.history import History
from engine.ops import CutOp, SpeedOp


def _make_cut(history: History, start: int, end: int) -> CutOp:
    """Helper: open group, append CutOp, close group."""
    gid = history.begin_group()
    op = CutOp(op_id=0, group_id=gid, start_us=start, end_us=end)
    op = history.append(op)
    history.end_group()
    return op


class TestHistoryBasics:
    def test_empty_history(self):
        h = History()
        assert h.active_ops() == []
        assert not h.has_undo()
        assert not h.has_redo()

    def test_append_op(self):
        h = History()
        op = _make_cut(h, 0, 10_000_000)
        assert op.op_id == 0
        assert not op.revoked
        assert len(h.active_ops()) == 1

    def test_op_ids_sequential(self):
        h = History()
        op1 = _make_cut(h, 0, 1_000_000)
        op2 = _make_cut(h, 2_000_000, 3_000_000)
        assert op1.op_id == 0
        assert op2.op_id == 1

    def test_append_outside_group_raises(self):
        h = History()
        with pytest.raises(RuntimeError):
            h.append(CutOp(op_id=0, group_id=0, start_us=0, end_us=1_000_000))


class TestUndo:
    def test_undo_revokes_last_group(self):
        h = History()
        op = _make_cut(h, 0, 10_000_000)
        assert h.has_undo()
        revoked_gid = h.undo()
        assert revoked_gid == op.group_id
        assert h.active_ops() == []
        assert not h.has_undo()

    def test_undo_nothing(self):
        h = History()
        result = h.undo()
        assert result is None

    def test_undo_undo_two_groups(self):
        h = History()
        op1 = _make_cut(h, 0, 1_000_000)
        op2 = _make_cut(h, 2_000_000, 3_000_000)
        h.undo()
        # op2 revoked; op1 still active
        active = h.active_ops()
        assert len(active) == 1
        assert active[0].op_id == op1.op_id
        h.undo()
        assert h.active_ops() == []


class TestRedo:
    def test_redo_after_undo(self):
        h = History()
        op = _make_cut(h, 0, 10_000_000)
        h.undo()
        assert h.has_redo()
        restored = h.redo()
        assert restored == op.group_id
        assert len(h.active_ops()) == 1

    def test_redo_cleared_by_new_edit(self):
        h = History()
        _make_cut(h, 0, 1_000_000)
        h.undo()
        # New edit clears redo
        _make_cut(h, 2_000_000, 3_000_000)
        assert not h.has_redo()

    def test_redo_nothing(self):
        h = History()
        result = h.redo()
        assert result is None


class TestRevokeOp:
    def test_revoke_specific_op(self):
        h = History()
        op1 = _make_cut(h, 0, 1_000_000)
        op2 = _make_cut(h, 2_000_000, 3_000_000)
        # Revoke op1 specifically (like "restore to before that edit")
        revoked = h.revoke_op(op1.op_id)
        assert revoked is not None
        active = h.active_ops()
        assert len(active) == 1
        assert active[0].op_id == op2.op_id

    def test_revoke_nonexistent_op(self):
        h = History()
        result = h.revoke_op(999)
        assert result is None


class TestMultiOpGroup:
    def test_multi_op_undo_group(self):
        """One instruction = one undo group, even with multiple ops."""
        h = History()
        gid = h.begin_group()
        op1 = CutOp(op_id=0, group_id=gid, start_us=0, end_us=1_000_000)
        op2 = CutOp(op_id=0, group_id=gid, start_us=2_000_000, end_us=3_000_000)
        op1 = h.append(op1)
        op2 = h.append(op2)
        h.end_group()

        assert len(h.active_ops()) == 2
        h.undo()
        assert len(h.active_ops()) == 0  # both revoked together


class TestSerialization:
    def test_roundtrip(self):
        h = History()
        _make_cut(h, 0, 1_000_000)
        _make_cut(h, 5_000_000, 6_000_000)
        h.undo()

        d = h.to_dict()
        h2 = History.from_dict(d)
        assert len(h2.active_ops()) == len(h.active_ops())
        assert h2.has_undo() == h.has_undo()
        assert h2.has_redo() == h.has_redo()
