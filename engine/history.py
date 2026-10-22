"""
engine/history.py
-----------------
Event-sourced edit history.

The History is a linear append-only log of operations.  (R-HIST-01)
Undo/redo move a group pointer, not a list pointer, so multi-op groups
work correctly.  (R-HIST-02, R-HIST-04)

Key design choice: op IDs are global counters that never reset, so they are
stable across undo/redo. This is required for restore-specific-edit (R-HIST-05)
and for deterministic hashing (R-HIST-06).
"""
from __future__ import annotations

import json
from typing import List, Optional, Tuple
from .ops import BaseOp, RevokeOp


class History:
    """
    Append-only log of BaseOp instances with undo/redo pointer.

    Internal state
    --------------
    _ops            : list of ALL ops ever appended (never removed)
    _next_op_id     : monotonically increasing op ID counter
    _next_group_id  : monotonically increasing undo-group counter
    _head_group     : the group_id of the most recently applied group
                      (i.e. the undo pointer).  None = before any edit.
    _current_group  : the group currently being built (or None)
    """

    def __init__(self) -> None:
        self._ops: List[BaseOp] = []
        self._next_op_id: int = 0
        self._next_group_id: int = 0
        self._head_group: Optional[int] = None   # highest active group_id
        self._current_group: Optional[int] = None
        self._group_instructions: Dict[int, str] = {}

    # ── Writing ops ───────────────────────────────────────────────────────────

    def begin_group(self, instruction: Optional[str] = None) -> int:
        """
        Open a new undo group.  Returns the new group_id.
        Must be followed by end_group() or commit_group().  (R-HIST-02)

        A new edit always clears the redo stack (R-HIST-04): any op whose
        group_id > _head_group is revoked before we begin.
        """
        self._clear_redo()
        self._current_group = self._next_group_id
        if instruction is not None:
            self._group_instructions[self._current_group] = instruction
        self._next_group_id += 1
        return self._current_group

    def append(self, op: BaseOp) -> BaseOp:
        """
        Append an op to the current group.  Returns the op with its assigned ID.
        Must be called between begin_group() / end_group().
        """
        if self._current_group is None:
            raise RuntimeError("append() called outside of begin_group/end_group")
        import dataclasses
        op = dataclasses.replace(
            op,
            op_id=self._next_op_id,
            group_id=self._current_group,
            revoked=False,
        )
        self._ops.append(op)
        self._next_op_id += 1
        return op

    def append_op(self, op: BaseOp) -> BaseOp:
        """Alias for append()."""
        return self.append(op)

    def end_group(self) -> int:
        """Close the current undo group and advance the head pointer."""
        if self._current_group is None:
            raise RuntimeError("end_group() called without begin_group()")
        grp = self._current_group
        self._head_group = self._current_group
        self._current_group = None
        return grp

    def commit_group(self) -> int:
        """Alias for end_group()."""
        return self.end_group()

    def get_active_ops(self) -> List[BaseOp]:
        """Alias for active_ops()."""
        return self.active_ops()

    def get_group_instruction(self, group_id: int) -> str:
        return self._group_instructions.get(group_id, f"Group #{group_id}")

    # ── Undo / Redo ───────────────────────────────────────────────────────────

    def undo(self) -> Optional[int]:
        """
        Revoke the most recently applied group.  (R-HIST-04)
        Returns the revoked group_id, or None if nothing to undo.
        """
        if self._head_group is None:
            return None
        # Mark all ops in this group as revoked
        target = self._head_group
        self._set_group_revoked(target, revoked=True)
        # Move head to the previous active group
        self._head_group = self._prev_active_group(target)
        return target

    def redo(self) -> Optional[int]:
        """
        Re-apply the next revoked group.  (R-HIST-04)
        Returns the restored group_id, or None if nothing to redo.
        """
        next_group = self._next_revoked_group()
        if next_group is None:
            return None
        self._set_group_revoked(next_group, revoked=False)
        self._head_group = next_group
        return next_group

    def has_undo(self) -> bool:
        return self._head_group is not None

    def has_redo(self) -> bool:
        return self._next_revoked_group() is not None

    # ── Restore specific edit ─────────────────────────────────────────────────

    def revoke_op(self, op_id: int) -> Optional[BaseOp]:
        """
        Revoke a specific op by ID.  (R-HIST-05)
        This is different from undo: it removes only that op, leaving others.
        Returns the revoked op, or None if not found.
        """
        for i, op in enumerate(self._ops):
            if op.op_id == op_id and not op.revoked:
                import dataclasses
                self._ops[i] = dataclasses.replace(op, revoked=True)
                return self._ops[i]
        return None

    def restore_op(self, op_id: int) -> Optional[BaseOp]:
        """Un-revoke a specific op. Used to undo a RevokeOp."""
        for i, op in enumerate(self._ops):
            if op.op_id == op_id and op.revoked:
                import dataclasses
                self._ops[i] = dataclasses.replace(op, revoked=False)
                return self._ops[i]
        return None

    # ── Query ─────────────────────────────────────────────────────────────────

    def active_ops(self) -> List[BaseOp]:
        """
        Return all non-revoked ops in order.  (R-HIST-03)
        This is the input to fold().
        """
        return [op for op in self._ops if not op.revoked]

    def all_ops(self) -> List[BaseOp]:
        """Return every op (including revoked) in order."""
        return list(self._ops)

    def op_by_id(self, op_id: int) -> Optional[BaseOp]:
        for op in self._ops:
            if op.op_id == op_id:
                return op
        return None

    def group_ids(self) -> List[int]:
        """Return sorted list of unique group IDs."""
        return sorted({op.group_id for op in self._ops})

    def ops_in_group(self, group_id: int) -> List[BaseOp]:
        return [op for op in self._ops if op.group_id == group_id]

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "next_op_id": self._next_op_id,
            "next_group_id": self._next_group_id,
            "head_group": self._head_group,
            "ops": [op.to_dict() for op in self._ops],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @staticmethod
    def from_dict(d: dict) -> "History":
        h = History()
        h._next_op_id = d["next_op_id"]
        h._next_group_id = d["next_group_id"]
        h._head_group = d["head_group"]
        h._ops = [BaseOp.from_dict(op) for op in d["ops"]]
        return h

    # ── Private helpers ───────────────────────────────────────────────────────

    def _clear_redo(self) -> None:
        """
        Mark all ops with group_id > _head_group as revoked.  (R-HIST-04)
        This implements the "new edit clears redo stack" rule.
        """
        import dataclasses
        head = self._head_group if self._head_group is not None else -1
        for i, op in enumerate(self._ops):
            if op.group_id > head and not op.revoked:
                self._ops[i] = dataclasses.replace(op, revoked=True)
        # Reset next_group_id to just after head to keep counters tight.
        # We do NOT reset next_op_id — op IDs must never be reused.
        if self._head_group is not None:
            self._next_group_id = self._head_group + 1
        else:
            self._next_group_id = 0

    def _set_group_revoked(self, group_id: int, *, revoked: bool) -> None:
        import dataclasses
        for i, op in enumerate(self._ops):
            if op.group_id == group_id:
                self._ops[i] = dataclasses.replace(op, revoked=revoked)

    def _prev_active_group(self, group_id: int) -> Optional[int]:
        """Return the highest active group_id strictly below group_id."""
        candidates = [
            op.group_id for op in self._ops
            if op.group_id < group_id and not op.revoked
        ]
        return max(candidates) if candidates else None

    def _next_revoked_group(self) -> Optional[int]:
        """Return the lowest revoked group_id strictly above _head_group."""
        head = self._head_group if self._head_group is not None else -1
        candidates = [
            op.group_id for op in self._ops
            if op.group_id > head and op.revoked
        ]
        return min(candidates) if candidates else None
