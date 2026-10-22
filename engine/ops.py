"""
engine/ops.py
-------------
All edit operations as immutable dataclasses.

Design principles:
  - Every op stores SOURCE anchors (word IDs or source µs), never edited-timeline times.
  - Op IDs are sequential integers assigned by the history, not UUIDs/timestamps.
    This is required for deterministic timeline_hash (R-HIST-06).
  - Operations are pure data. No I/O, no side effects.
  - Each op has an op_type string matching the class name for serialisation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Literal


# ── Base ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BaseOp:
    """
    Every edit operation inherits from BaseOp.

    op_id       : sequential integer, assigned by History (R-HIST-06)
    group_id    : undo group this op belongs to (one instruction = one group)
    revoked     : True if this op has been undone or explicitly revoked
    op_type     : discriminator string for deserialisation
    """
    op_id: int
    group_id: int
    revoked: bool = False
    op_type: str = "base"

    def with_revoked(self, revoked: bool) -> "BaseOp":
        """Return a copy of this op with a new revoked flag."""
        # frozen=True so we use object.__setattr__ via dataclasses.replace
        import dataclasses
        return dataclasses.replace(self, revoked=revoked)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict) -> "BaseOp":
        """Dispatch to the correct subclass based on op_type."""
        return _OP_REGISTRY[d["op_type"]].from_dict(d)


# ── Cut ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CutOp(BaseOp):
    """
    Remove source range [start_us, end_us) from the timeline.  (R-CUT-01)

    start_us, end_us : source-time boundaries in integer microseconds
    snapped          : True if boundaries were snapped to word gaps (R-CUT-05)
    """
    start_us: int = 0
    end_us: int = 0
    snapped: bool = False
    op_type: str = "CutOp"

    @staticmethod
    def from_dict(d: dict) -> "CutOp":
        return CutOp(
            op_id=d["op_id"], group_id=d["group_id"], revoked=d["revoked"],
            start_us=d["start_us"], end_us=d["end_us"], snapped=d.get("snapped", False),
        )


# ── Keep ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class KeepOp(BaseOp):
    """
    Keep only source range [start_us, end_us); cut everything outside.
    Implemented as two CutOps during fold, but stored as one op for undo.
    """
    start_us: int = 0
    end_us: int = 0
    op_type: str = "KeepOp"

    @staticmethod
    def from_dict(d: dict) -> "KeepOp":
        return KeepOp(
            op_id=d["op_id"], group_id=d["group_id"], revoked=d["revoked"],
            start_us=d["start_us"], end_us=d["end_us"],
        )


# ── Reorder ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReorderOp(BaseOp):
    """
    Reorder sections.  sections is an ordered list of source ranges
    [(start_us, end_us), ...]; the output timeline plays them in that order.
    """
    sections: tuple = ()   # tuple of (start_us, end_us) pairs
    op_type: str = "ReorderOp"

    @staticmethod
    def from_dict(d: dict) -> "ReorderOp":
        return ReorderOp(
            op_id=d["op_id"], group_id=d["group_id"], revoked=d["revoked"],
            sections=tuple(tuple(s) for s in d["sections"]),
        )

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["sections"] = [list(s) for s in self.sections]
        return d


# ── Speed ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SpeedOp(BaseOp):
    """
    Change playback speed of source range [start_us, end_us).  (R-SPEED-01)
    factor : float in [0.25, 4.0]
    """
    start_us: int = 0
    end_us: int = 0
    factor: float = 1.0
    op_type: str = "SpeedOp"

    @staticmethod
    def from_dict(d: dict) -> "SpeedOp":
        return SpeedOp(
            op_id=d["op_id"], group_id=d["group_id"], revoked=d["revoked"],
            start_us=d["start_us"], end_us=d["end_us"], factor=d["factor"],
        )


# ── Mute ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MuteOp(BaseOp):
    """Silence audio for source range [start_us, end_us).  (R-MUTE-01)"""
    start_us: int = 0
    end_us: int = 0
    op_type: str = "MuteOp"

    @staticmethod
    def from_dict(d: dict) -> "MuteOp":
        return MuteOp(
            op_id=d["op_id"], group_id=d["group_id"], revoked=d["revoked"],
            start_us=d["start_us"], end_us=d["end_us"],
        )


# ── Bleep ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BleepOp(BaseOp):
    """Replace audio with 1 kHz tone for source range.  (R-BLEEP-01)"""
    start_us: int = 0
    end_us: int = 0
    op_type: str = "BleepOp"

    @staticmethod
    def from_dict(d: dict) -> "BleepOp":
        return BleepOp(
            op_id=d["op_id"], group_id=d["group_id"], revoked=d["revoked"],
            start_us=d["start_us"], end_us=d["end_us"],
        )


# ── Caption ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CaptionStyle:
    """Styling attributes for a caption. All optional (None = default)."""
    color: Optional[str] = None        # CSS colour string, e.g. "#ff0000"
    font_size: Optional[int] = None    # in points
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    position: Optional[str] = None     # "top" | "bottom" | "center"
    background: Optional[str] = None   # CSS colour for background box

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @staticmethod
    def from_dict(d: dict) -> "CaptionStyle":
        return CaptionStyle(**d)

    def merge(self, other: "CaptionStyle") -> "CaptionStyle":
        """Return a new style that applies `other` on top of `self`."""
        import dataclasses
        d = asdict(self)
        for k, v in asdict(other).items():
            if v is not None:
                d[k] = v
        return CaptionStyle(**d)


@dataclass(frozen=True)
class AddCaptionOp(BaseOp):
    """
    Add a caption anchored to word IDs [word_id_start, word_id_end).  (R-CAP-01)

    caption_id      : stable counter-based integer ID
    text            : caption text
    word_id_start   : first word ID (inclusive)
    word_id_end     : last word ID (inclusive); if empty = single word
    style           : optional CaptionStyle
    """
    caption_id: int = 0
    text: str = ""
    word_id_start: str = "w0000"
    word_id_end: str = "w0000"
    style: Optional[dict] = None   # serialised CaptionStyle dict
    op_type: str = "AddCaptionOp"

    @staticmethod
    def from_dict(d: dict) -> "AddCaptionOp":
        return AddCaptionOp(
            op_id=d["op_id"], group_id=d["group_id"], revoked=d["revoked"],
            caption_id=d["caption_id"], text=d["text"],
            word_id_start=d["word_id_start"], word_id_end=d["word_id_end"],
            style=d.get("style"),
        )


@dataclass(frozen=True)
class RestyleCaptionOp(BaseOp):
    """Update the style of an existing caption.  (R-CAP-03)"""
    caption_id: int = 0
    style: dict = field(default_factory=dict)
    op_type: str = "RestyleCaptionOp"

    @staticmethod
    def from_dict(d: dict) -> "RestyleCaptionOp":
        return RestyleCaptionOp(
            op_id=d["op_id"], group_id=d["group_id"], revoked=d["revoked"],
            caption_id=d["caption_id"], style=d["style"],
        )


# ── Music ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AddMusicOp(BaseOp):
    """Add background music with auto-ducking under speech.  (R-MUSIC-01)"""
    music_url: str = ""           # S3 URL or local path (resolved at render time)
    duck_level_db: float = -18.0  # dB relative to music track during speech
    op_type: str = "AddMusicOp"

    @staticmethod
    def from_dict(d: dict) -> "AddMusicOp":
        return AddMusicOp(
            op_id=d["op_id"], group_id=d["group_id"], revoked=d["revoked"],
            music_url=d["music_url"], duck_level_db=d.get("duck_level_db", -18.0),
        )


# ── Revoke (for restore-specific-edit)  ───────────────────────────────────────

@dataclass(frozen=True)
class RevokeOp(BaseOp):
    """
    Explicitly revoke a previous operation by ID.  (R-HIST-05)
    This is itself an operation so it appears in history and can be undone.
    """
    target_op_id: int = 0
    op_type: str = "RevokeOp"

    @staticmethod
    def from_dict(d: dict) -> "RevokeOp":
        return RevokeOp(
            op_id=d["op_id"], group_id=d["group_id"], revoked=d["revoked"],
            target_op_id=d["target_op_id"],
        )


# ── Registry for deserialisation ──────────────────────────────────────────────

_OP_REGISTRY: Dict[str, Any] = {
    "CutOp": CutOp,
    "KeepOp": KeepOp,
    "ReorderOp": ReorderOp,
    "SpeedOp": SpeedOp,
    "MuteOp": MuteOp,
    "BleepOp": BleepOp,
    "AddCaptionOp": AddCaptionOp,
    "RestyleCaptionOp": RestyleCaptionOp,
    "AddMusicOp": AddMusicOp,
    "RevokeOp": RevokeOp,
}
