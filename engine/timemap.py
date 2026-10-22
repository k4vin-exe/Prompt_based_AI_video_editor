"""
engine/timemap.py
-----------------
Bidirectional mapping between current-edited time and source time.

This is the implementation of the time policy (R-TIME-02):
  "current edited time" -> source position -> word anchor

The function map_edited_to_source() is a pure function of the Timeline.
It does no I/O and has no side effects.

Design: we walk the segment list linearly. For a 60-minute video the
segment list is O(#edits) long — typically < 100 items — so O(n) is fine.
"""
from __future__ import annotations

from typing import Optional, Tuple, List
from .timeline import Timeline, Segment


def edited_to_source(
    timeline: Timeline, edited_us: int
) -> Tuple[Optional[int], Optional[Segment]]:
    """
    Map a position in the edited timeline (µs) to a source position (µs).

    Returns (src_us, segment) where segment is the Segment that contains
    the position, or (None, None) if the position is out of range.

    The source position is clipped to [segment.src_start_us, segment.src_end_us).
    """
    if not timeline.segments:
        return None, None
    if edited_us < 0:
        return None, None
    if edited_us >= timeline.duration_us:
        # Return the very last position (end of last segment)
        seg = timeline.segments[-1]
        return seg.src_end_us, seg

    for seg in timeline.segments:
        if seg.edited_start_us <= edited_us < seg.edited_end_us:
            offset_in_seg_edited = edited_us - seg.edited_start_us
            # Reverse the speed: edited time / (1/speed) = edited * speed
            offset_in_seg_src = int(offset_in_seg_edited * seg.speed)
            src_us = seg.src_start_us + offset_in_seg_src
            return src_us, seg

    return None, None


def source_to_edited(
    timeline: Timeline, src_us: int
) -> Optional[int]:
    """
    Map a source position (µs) to an edited-timeline position (µs).
    Returns None if the source position has been cut.

    If the source position falls within a cut (i.e. between segments),
    returns None.
    """
    for seg in timeline.segments:
        if seg.src_start_us <= src_us < seg.src_end_us:
            offset_src = src_us - seg.src_start_us
            offset_edited = int(offset_src / seg.speed)
            return seg.edited_start_us + offset_edited
    return None


def nearest_word_boundary(
    transcript, src_us: int, direction: str = "nearest"
) -> int:
    """
    Snap a source position to the nearest inter-word gap.  (R-ANCHOR-03)

    direction : "nearest" | "left" | "right"

    Returns the snapped source position (µs).
    If src_us is already inside a gap, return it unchanged.
    If it falls inside a word, snap to the nearest edge of that word.
    """
    words = transcript.words
    if not words:
        return src_us

    # Find which word the position falls inside (if any)
    for i, w in enumerate(words):
        if w.start_us <= src_us <= w.end_us:
            # Inside a word — snap to start or end
            left_dist = src_us - w.start_us
            right_dist = w.end_us - src_us
            if direction == "left":
                return w.start_us
            elif direction == "right":
                return w.end_us
            else:  # nearest
                return w.start_us if left_dist <= right_dist else w.end_us

    # Position is in a gap — return as-is (already in inter-word gap)
    return src_us


def find_cut_boundary(
    transcript, src_us: int
) -> Tuple[int, bool]:
    """
    Find the best cut boundary near src_us.  (R-ANCHOR-03, R-CUT-05)

    Returns (snapped_src_us, was_snapped).
    Prefers the midpoint of the closest gap.
    """
    words = transcript.words
    if not words:
        return src_us, False

    # Check if we're already in a gap
    for i, w in enumerate(words):
        if i + 1 < len(words):
            next_w = words[i + 1]
            gap_start = w.end_us
            gap_end = next_w.start_us
            if gap_start <= src_us <= gap_end:
                return src_us, False  # already in gap

    # Find the nearest gap
    best_dist = float("inf")
    best_pos = src_us

    for i, w in enumerate(words):
        # Check gap before this word
        if i > 0:
            prev_w = words[i - 1]
            gap_start = prev_w.end_us
            gap_end = w.start_us
            if gap_end > gap_start:
                mid = (gap_start + gap_end) // 2
                dist = abs(src_us - mid)
                if dist < best_dist:
                    best_dist = dist
                    best_pos = mid

    if best_pos != src_us:
        return best_pos, True
    return src_us, False


def edited_duration_us(timeline: Timeline) -> int:
    """Return the total edited duration (µs)."""
    return timeline.duration_us


def segment_at_edited_time(
    timeline: Timeline, edited_us: int
) -> Optional[Segment]:
    """Return the Segment active at the given edited time."""
    _, seg = edited_to_source(timeline, edited_us)
    return seg
