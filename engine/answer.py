"""
engine/answer.py
----------------
Response types returned to the user for every instruction.  (Brief §3-way answers)

Every instruction returns exactly ONE of:
  AppliedAnswer       — operations performed, before/after summary
  ClarificationAnswer — specific question with options
  RejectedAnswer      — reason + which earlier op it contradicts

Design note: these are pure data containers; the engine produces them,
the API layer serialises them. No I/O here.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


@dataclass
class OperationSummary:
    """Summary of one applied atomic operation."""
    op_id: int
    op_type: str
    description: str          # human-readable one-liner


@dataclass
class BeforeAfter:
    """Before/after snapshot for an applied instruction."""
    duration_us_before: int
    duration_us_after: int
    timeline_hash_before: str
    timeline_hash_after: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AppliedAnswer:
    """
    Returned when an instruction was successfully applied.

    operations  : list of all atomic ops in this undo group
    summary     : human-readable description of what changed
    before_after: before/after metrics
    time_policy : which time policy was used (R-TIME-02)
    warnings    : non-fatal issues (e.g. caption hidden, pause preserved)
    """
    status: str = "applied"
    operations: List[OperationSummary] = field(default_factory=list)
    summary: str = ""
    before_after: Optional[BeforeAfter] = None
    time_policy: str = "current_edited"
    warnings: List[str] = field(default_factory=list)
    group_id: int = 0

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "operations": [asdict(op) for op in self.operations],
            "summary": self.summary,
            "before_after": self.before_after.to_dict() if self.before_after else None,
            "time_policy": self.time_policy,
            "warnings": self.warnings,
            "group_id": self.group_id,
        }


@dataclass
class ClarificationAnswer:
    """
    Returned when the instruction is ambiguous and we must not guess.

    question : a specific question (e.g. "Pricing mentioned at 1:05, 2:40, 3:15 — which?")
    options  : list of options for the user to choose from
    context  : optional dict of additional context (e.g. matched spans)
    """
    status: str = "needs_clarification"
    question: str = ""
    options: List[str] = field(default_factory=list)
    context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "question": self.question,
            "options": self.options,
            "context": self.context,
        }


@dataclass
class RejectedAnswer:
    """
    Returned when an instruction is impossible or contradicts an earlier edit.

    reason          : human-readable explanation
    error_code      : UPPER_SNAKE_CASE code (see RULES.md R-REJECT)
    conflicting_op  : op_id of the earlier op it conflicts with (or None)
    """
    status: str = "rejected"
    reason: str = ""
    error_code: str = ""
    conflicting_op: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "error_code": self.error_code,
            "conflicting_op": self.conflicting_op,
        }


# ── Composite answer for multi-part instructions  (R-CL-05) ──────────────────

@dataclass
class PartResult:
    """Result for one part of a multi-part instruction."""
    part_text: str
    result: Any   # AppliedAnswer | ClarificationAnswer | RejectedAnswer

    def to_dict(self) -> dict:
        return {
            "part_text": self.part_text,
            "result": self.result.to_dict(),
        }


@dataclass
class MultiPartAnswer:
    """
    Returned for multi-part instructions.
    All applied parts form ONE undo group.  (R-CL-05)
    """
    status: str = "multi_part"
    parts: List[PartResult] = field(default_factory=list)
    group_id: Optional[int] = None
    timeline_hash_after: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "parts": [p.to_dict() for p in self.parts],
            "group_id": self.group_id,
            "timeline_hash_after": self.timeline_hash_after,
        }

    @property
    def overall_status(self) -> str:
        """
        Summarise: 'applied' if all applied, 'partial' if mixed,
        'needs_clarification' / 'rejected' if nothing applied.
        """
        statuses = {p.result.status for p in self.parts}
        if statuses == {"applied"}:
            return "applied"
        if "applied" in statuses:
            return "partial"
        return list(statuses)[0]
