"""
nlu/context.py
--------------
Builds the Context Pack that is sent to the LLM alongside a user instruction.

The context pack tells the LLM:
  - How long the current edited video is (current_duration_s)
  - How long the original source is (source_duration_s)
  - Which speakers exist and how many segments they have
  - The current list of chapters/topics (from analysis.json)
  - A compact history of recent edits (last 5 groups)
  - Whether there's a pending clarification

This is a compact, token-efficient text block that fits in a few hundred tokens.
"""
from __future__ import annotations

import json
from typing import Optional, List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from engine.session import Session


def build_context_pack(
    session,  # engine.session.Session
    analysis: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build a compact context string for the LLM.

    Args:
        session:  The current editing session.
        analysis: Optional analysis.json dict (from perception pipeline).

    Returns:
        A plain-text context block (typically 200-400 tokens).
    """
    lines = []

    # ── Video duration ────────────────────────────────────────────────────────
    src_dur_s = session.transcript.duration_us / 1_000_000.0
    edited_dur_s = session.get_duration_s()
    lines.append(f"SOURCE_DURATION: {src_dur_s:.1f}s")
    lines.append(f"CURRENT_DURATION: {edited_dur_s:.1f}s")

    # ── Speakers ──────────────────────────────────────────────────────────────
    if analysis and analysis.get("speakers"):
        speakers = analysis["speakers"]
        lines.append(f"SPEAKERS: {', '.join(speakers)}")
    else:
        # Infer from transcript
        speakers = _infer_speakers(session.transcript.words)
        if speakers:
            lines.append(f"SPEAKERS: {', '.join(speakers)}")

    # ── Chapters / topics ─────────────────────────────────────────────────────
    if analysis and analysis.get("chapters"):
        lines.append("CHAPTERS:")
        for ch in analysis["chapters"][:8]:  # cap at 8
            t_start = _format_time(ch["start_us"])
            t_end = _format_time(ch["end_us"])
            title = ch.get("title") or f"Chapter {ch['chapter_id'] + 1}"
            kw = ", ".join(ch.get("keywords", [])[:3])
            lines.append(f"  [{ch['chapter_id']}] {t_start}-{t_end} '{title}' ({kw})")

    # ── Recent edit history ────────────────────────────────────────────────────
    all_ops = session.history.all_ops()
    active_groups = sorted({op.group_id for op in all_ops if not op.revoked})
    if active_groups:
        lines.append("RECENT_EDITS (last 5, newest first):")
        for gid in reversed(active_groups[-5:]):
            instr = session.history.get_group_instruction(gid)
            ops_in_group = session.history.ops_in_group(gid)
            op_types = ", ".join(op.op_type for op in ops_in_group[:3])
            lines.append(f"  group={gid}: '{instr}' [{op_types}]")

    # ── Pending clarification ─────────────────────────────────────────────────
    if session._pending_clarification is not None:
        pending_intent = session._pending_clarification.get("intent", "unknown")
        lines.append(f"PENDING_CLARIFICATION: {pending_intent} (awaiting user reply)")

    # ── Timeline hash (for debugging determinism) ─────────────────────────────
    lines.append(f"TIMELINE_HASH: {session.get_timeline_hash()[:12]}")

    return "\n".join(lines)


def _format_time(us: int) -> str:
    s = int(us / 1_000_000)
    return f"{s // 60}:{s % 60:02d}"


def _infer_speakers(words) -> List[str]:
    seen = []
    for w in words:
        if w.speaker and w.speaker not in seen:
            seen.append(w.speaker)
    return seen
