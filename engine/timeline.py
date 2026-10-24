"""
engine/timeline.py
------------------
Timeline data structure and the fold() pure function.

A Timeline is the result of applying active_ops to the base transcript.
It describes the edited video as an ordered list of Segments — contiguous
source ranges that will be played in sequence.

fold() is a PURE FUNCTION: same inputs always produce the same output.
This is the foundation of determinism (R-HIST-03, R-HIST-06).

The timeline_hash is computed over the canonical JSON of the timeline
(sorted keys, integer times, counter IDs, no timestamps/UUIDs).  (R-HIST-06)

Key design: we never store edited-timeline times in ops or the timeline
JSON. The timeline stores SOURCE positions; edited times are computed on
the fly by timemap.py when needed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple, Dict, Any

from .transcript import Transcript
from .ops import (
    BaseOp, CutOp, KeepOp, ReorderOp, SpeedOp,
    MuteOp, BleepOp, AddCaptionOp, RestyleCaptionOp, AddMusicOp, RevokeOp,
)


# ── Segment ───────────────────────────────────────────────────────────────────

@dataclass
class Segment:
    """
    One contiguous piece of the source that will play in the output.

    src_start_us : inclusive start in source timeline (µs)
    src_end_us   : exclusive end in source timeline (µs)
    speed        : playback speed factor (default 1.0)
    muted        : True if audio is silenced
    bleep        : True if audio is replaced with 1 kHz tone

    Derived fields (computed, not stored in ops):
    edited_start_us  : where this segment starts in the edited timeline
    edited_end_us    : where this segment ends in the edited timeline
    """
    src_start_us: int
    src_end_us: int
    speed: float = 1.0
    muted: bool = False
    bleep: bool = False
    edited_start_us: int = 0   # set by fold()
    edited_end_us: int = 0     # set by fold()

    def src_duration_us(self) -> int:
        return self.src_end_us - self.src_start_us

    def edited_duration_us(self) -> int:
        """Duration in the edited timeline after speed change."""
        src_dur = self.src_duration_us()
        return int(src_dur / self.speed)

    def to_dict(self) -> dict:
        return {
            "src_start_us": self.src_start_us,
            "src_end_us": self.src_end_us,
            "speed": self.speed,
            "muted": self.muted,
            "bleep": self.bleep,
            "edited_start_us": self.edited_start_us,
            "edited_end_us": self.edited_end_us,
        }


# ── Caption in the timeline ───────────────────────────────────────────────────

@dataclass
class TimelineCaption:
    """
    A caption as it exists in the computed timeline.

    caption_id      : stable ID matching the AddCaptionOp
    text            : caption text
    word_id_start   : first word ID (source anchor)
    word_id_end     : last word ID (source anchor)
    style           : merged style dict
    hidden          : True if all anchored words have been cut (R-CUT-06)
    edited_start_us : display start in edited timeline (µs) — derived
    edited_end_us   : display end in edited timeline (µs) — derived
    """
    caption_id: int
    text: str
    word_id_start: str
    word_id_end: str
    style: dict
    hidden: bool = False
    edited_start_us: int = 0
    edited_end_us: int = 0

    def to_dict(self) -> dict:
        return {
            "caption_id": self.caption_id,
            "text": self.text,
            "word_id_start": self.word_id_start,
            "word_id_end": self.word_id_end,
            "style": self.style,
            "hidden": self.hidden,
            "edited_start_us": self.edited_start_us,
            "edited_end_us": self.edited_end_us,
        }


# ── Music ─────────────────────────────────────────────────────────────────────

@dataclass
class TimelineMusic:
    """Background music with auto-ducking configuration."""
    music_url: str
    duck_level_db: float

    def to_dict(self) -> dict:
        return {"music_url": self.music_url, "duck_level_db": self.duck_level_db}


# ── Timeline ──────────────────────────────────────────────────────────────────

@dataclass
class Timeline:
    """
    The fully computed edited timeline.

    segments  : ordered list of Segments to play in sequence
    captions  : all captions (including hidden ones for restore support)
    music     : optional background music track
    duration_us : total edited duration (sum of segment edited_duration_us)
    """
    segments: List[Segment]
    captions: List[TimelineCaption]
    music: Optional[TimelineMusic]
    duration_us: int

    def to_dict(self) -> dict:
        return {
            "duration_us": self.duration_us,
            "segments": [s.to_dict() for s in self.segments],
            "captions": [c.to_dict() for c in self.captions],
            "music": self.music.to_dict() if self.music else None,
        }

    def to_json(self) -> str:
        """Canonical JSON with sorted keys for deterministic hashing."""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def timeline_hash(self) -> str:
        """
        sha256 of canonical JSON.  (R-HIST-06)
        Same session × 3 runs must produce identical hashes.
        """
        canonical = self.to_json()
        return hashlib.sha256(canonical.encode()).hexdigest()


# ── fold() ────────────────────────────────────────────────────────────────────

def fold(transcript: Transcript, active_ops: List[BaseOp]) -> Timeline:
    """
    Pure function: apply active_ops to the transcript to produce a Timeline.
    (R-HIST-03)

    Algorithm overview:
    1. Start with one segment covering the entire source.
    2. Apply CutOps / KeepOps to split and remove segments.
    3. Apply ReorderOps to resequence segments.
    4. Apply SpeedOps to annotate segments with speed factors.
    5. Apply MuteOps / BleepOps to annotate segments.
    6. Resolve captions: for each AddCaptionOp, find its word span in
       the surviving segments; hide if no words survive.
    7. Apply RestyleCaptionOps to update caption styles.
    8. Collect music ops.
    9. Compute edited_start_us / edited_end_us for every segment and caption.
    """
    # Step 0: Filter operations revoked by RevokeOp (R-HIST-05)
    revoked_target_ids = {op.target_op_id for op in active_ops if isinstance(op, RevokeOp)}
    effective_ops = [op for op in active_ops if op.op_id not in revoked_target_ids and not isinstance(op, RevokeOp)]

    # Step 1: initial segment list
    segments = [Segment(
        src_start_us=0,
        src_end_us=transcript.duration_us,
    )]

    # Step 2: cuts
    for op in effective_ops:
        if isinstance(op, CutOp):
            segments = _apply_cut(segments, op.start_us, op.end_us)
        elif isinstance(op, KeepOp):
            # Keep = cut everything outside [start, end]
            segments = _apply_cut(segments, 0, op.start_us)
            segments = _apply_cut(segments, op.end_us, transcript.duration_us)

    # Step 3: reorder
    for op in effective_ops:
        if isinstance(op, ReorderOp):
            segments = _apply_reorder(segments, op.sections)

    # Step 4: speed — last-writer-wins with range splitting (R-SPEED-02)
    speed_ops = [op for op in effective_ops if isinstance(op, SpeedOp)]
    for op in speed_ops:
        segments = _apply_speed(segments, op.start_us, op.end_us, op.factor)

    # Step 5: mute / bleep
    for op in effective_ops:
        if isinstance(op, MuteOp):
            segments = _apply_flag(segments, op.start_us, op.end_us, "muted", True)
        elif isinstance(op, BleepOp):
            segments = _apply_flag(segments, op.start_us, op.end_us, "bleep", True)

    # Step 6-8: compute edited times
    segments = _assign_edited_times(segments)
    total_duration = segments[-1].edited_end_us if segments else 0

    # Step 6: captions
    captions = _resolve_captions(transcript, segments, effective_ops)

    # Step 8: music
    music = None
    for op in effective_ops:
        if isinstance(op, AddMusicOp):
            music = TimelineMusic(
                music_url=op.music_url,
                duck_level_db=op.duck_level_db,
            )

    return Timeline(
        segments=segments,
        captions=captions,
        music=music,
        duration_us=total_duration,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _apply_cut(segments: List[Segment], cut_start: int, cut_end: int) -> List[Segment]:
    """
    Remove source range [cut_start, cut_end) from the segment list.
    Segments that overlap the cut are split.
    """
    if cut_start >= cut_end:
        return segments

    result = []
    for seg in segments:
        # No overlap: keep as-is
        if seg.src_end_us <= cut_start or seg.src_start_us >= cut_end:
            result.append(seg)
            continue
        # Partial overlap on the left side
        if seg.src_start_us < cut_start:
            left = Segment(
                src_start_us=seg.src_start_us,
                src_end_us=cut_start,
                speed=seg.speed, muted=seg.muted, bleep=seg.bleep,
            )
            result.append(left)
        # Partial overlap on the right side
        if seg.src_end_us > cut_end:
            right = Segment(
                src_start_us=cut_end,
                src_end_us=seg.src_end_us,
                speed=seg.speed, muted=seg.muted, bleep=seg.bleep,
            )
            result.append(right)
        # If seg is fully within cut, it disappears
    return result


def _apply_reorder(segments: List[Segment], sections: tuple) -> List[Segment]:
    """
    Reorder: build a new segment list playing sections in the given order.
    Sections are source ranges; each maps to the surviving segments within it.
    """
    result = []
    for (sec_start, sec_end) in sections:
        for seg in segments:
            # Intersection of seg with [sec_start, sec_end)
            new_start = max(seg.src_start_us, sec_start)
            new_end = min(seg.src_end_us, sec_end)
            if new_start < new_end:
                result.append(Segment(
                    src_start_us=new_start,
                    src_end_us=new_end,
                    speed=seg.speed, muted=seg.muted, bleep=seg.bleep,
                ))
    return result


def _apply_speed(
    segments: List[Segment], spd_start: int, spd_end: int, factor: float
) -> List[Segment]:
    """
    Apply speed factor to source range [spd_start, spd_end).
    Splits segments at boundaries; last-writer-wins (R-SPEED-02).
    """
    result = []
    for seg in segments:
        if seg.src_end_us <= spd_start or seg.src_start_us >= spd_end:
            result.append(seg)
            continue
        # Split left
        if seg.src_start_us < spd_start:
            result.append(Segment(
                src_start_us=seg.src_start_us, src_end_us=spd_start,
                speed=seg.speed, muted=seg.muted, bleep=seg.bleep,
            ))
        # Intersection gets new speed
        new_start = max(seg.src_start_us, spd_start)
        new_end = min(seg.src_end_us, spd_end)
        result.append(Segment(
            src_start_us=new_start, src_end_us=new_end,
            speed=factor, muted=seg.muted, bleep=seg.bleep,
        ))
        # Split right
        if seg.src_end_us > spd_end:
            result.append(Segment(
                src_start_us=spd_end, src_end_us=seg.src_end_us,
                speed=seg.speed, muted=seg.muted, bleep=seg.bleep,
            ))
    return result


def _apply_flag(
    segments: List[Segment], flag_start: int, flag_end: int,
    attr: str, value: bool
) -> List[Segment]:
    """Apply muted or bleep flag to a source range, splitting segments."""
    result = []
    for seg in segments:
        if seg.src_end_us <= flag_start or seg.src_start_us >= flag_end:
            result.append(seg)
            continue
        if seg.src_start_us < flag_start:
            left = Segment(
                src_start_us=seg.src_start_us, src_end_us=flag_start,
                speed=seg.speed, muted=seg.muted, bleep=seg.bleep,
            )
            result.append(left)
        new_start = max(seg.src_start_us, flag_start)
        new_end = min(seg.src_end_us, flag_end)
        mid_kwargs = {
            "src_start_us": new_start, "src_end_us": new_end,
            "speed": seg.speed, "muted": seg.muted, "bleep": seg.bleep,
        }
        mid_kwargs[attr] = value
        result.append(Segment(**mid_kwargs))
        if seg.src_end_us > flag_end:
            right = Segment(
                src_start_us=flag_end, src_end_us=seg.src_end_us,
                speed=seg.speed, muted=seg.muted, bleep=seg.bleep,
            )
            result.append(right)
    return result


def _assign_edited_times(segments: List[Segment]) -> List[Segment]:
    """Compute edited_start_us / edited_end_us for each segment."""
    cursor = 0
    result = []
    for seg in segments:
        dur = seg.edited_duration_us()
        seg.edited_start_us = cursor
        seg.edited_end_us = cursor + dur
        cursor += dur
        result.append(seg)
    return result


def _resolve_captions(
    transcript: Transcript,
    segments: List[Segment],
    active_ops: List[BaseOp],
) -> List[TimelineCaption]:
    """
    Build the list of TimelineCaption objects.

    For each AddCaptionOp:
    - Find the words in [word_id_start, word_id_end].
    - Check which of those words survive in the current segments.
    - If some survive: anchor to surviving words, compute edited times.
    - If none survive: mark hidden=True.  (R-CUT-06)
    Apply RestyleCaptionOps on top.
    """
    # Build a lookup: caption_id -> style dict (cumulative merges)
    style_overrides: Dict[int, dict] = {}
    for op in active_ops:
        if isinstance(op, RestyleCaptionOp):
            existing = style_overrides.get(op.caption_id, {})
            if not isinstance(existing, dict):
                existing = {}
            op_style = op.style if isinstance(op.style, dict) else ({"color": op.style} if isinstance(op.style, str) and op.style else {})
            style_overrides[op.caption_id] = {**existing, **op_style}

    captions = []
    for op in active_ops:
        if not isinstance(op, AddCaptionOp):
            continue

        # Collect words in [word_id_start, word_id_end]
        word_ids = _word_ids_in_range(transcript, op.word_id_start, op.word_id_end)

        # Find surviving word positions in the edited timeline
        surviving_spans = []
        for wid in word_ids:
            word = transcript.word_by_id(wid)
            if word is None:
                continue
            edited = _src_range_to_edited(segments, word.start_us, word.end_us)
            if edited is not None:
                surviving_spans.append(edited)

        base_style = op.style if isinstance(op.style, dict) else ({"color": op.style} if isinstance(op.style, str) and op.style else {})
        overrides = style_overrides.get(op.caption_id, {})
        if not isinstance(overrides, dict):
            overrides = {}
        merged_style = {**base_style, **overrides}

        if not surviving_spans:
            captions.append(TimelineCaption(
                caption_id=op.caption_id,
                text=op.text,
                word_id_start=op.word_id_start,
                word_id_end=op.word_id_end,
                style=merged_style,
                hidden=True,
            ))
        else:
            edit_start = min(s[0] for s in surviving_spans)
            edit_end = max(s[1] for s in surviving_spans)
            captions.append(TimelineCaption(
                caption_id=op.caption_id,
                text=op.text,
                word_id_start=op.word_id_start,
                word_id_end=op.word_id_end,
                style=merged_style,
                hidden=False,
                edited_start_us=edit_start,
                edited_end_us=edit_end,
            ))
    return captions


def _word_ids_in_range(
    transcript: Transcript, id_start: str, id_end: str
) -> List[str]:
    """Return word IDs from id_start to id_end (inclusive), in order."""
    collecting = False
    result = []
    for word in transcript.words:
        if word.id == id_start:
            collecting = True
        if collecting:
            result.append(word.id)
        if word.id == id_end:
            break
    return result


def _src_range_to_edited(
    segments: List[Segment], src_start: int, src_end: int
) -> Optional[Tuple[int, int]]:
    """
    Find the edited-timeline range for a source range.
    Returns (edited_start, edited_end) or None if the range is fully cut.
    """
    spans = []
    for seg in segments:
        # Intersection with this segment
        overlap_start = max(seg.src_start_us, src_start)
        overlap_end = min(seg.src_end_us, src_end)
        if overlap_start >= overlap_end:
            continue
        # Offset into the segment
        offset_us = overlap_start - seg.src_start_us
        # Edited start
        edit_start = seg.edited_start_us + int(offset_us / seg.speed)
        edit_dur = int((overlap_end - overlap_start) / seg.speed)
        spans.append((edit_start, edit_start + edit_dur))
    if not spans:
        return None
    return (min(s[0] for s in spans), max(s[1] for s in spans))
