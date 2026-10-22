"""
engine/transcript.py
--------------------
Immutable transcript data structures.

A Transcript is created once at transcription time and never modified.
Word IDs are stable integers assigned sequentially (w0000, w0001, …).
All times are integer microseconds (avoids float rounding).

Design note: we use dataclasses with frozen=True so accidental mutation
raises an error immediately rather than silently corrupting the history.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Optional, List


def _word_id(n: int) -> str:
    """Stable word ID format: w0000, w0001, …  (R-ANCHOR-02)"""
    return f"w{n:04d}"


@dataclass(frozen=True)
class Word:
    """
    One transcript word.  Immutable for the lifetime of the project.

    Attributes
    ----------
    id          : stable word ID, e.g. 'w0003'  (R-ANCHOR-02)
    index       : integer position in the original word list (0-based)
    text        : the word text as recognised by STT
    start_us    : start time in integer microseconds  (R-TIME-08)
    end_us      : end time in integer microseconds
    speaker     : speaker label, e.g. 'speaker_0' or None
    confidence  : STT confidence in [0.0, 1.0]; None if unavailable
    """
    id: str
    index: int
    text: str
    start_us: int
    end_us: int
    speaker: Optional[str] = None
    confidence: Optional[float] = None

    @property
    def word_id(self) -> str:
        """Alias for id attribute (e.g. 'w0003')."""
        return self.id

    def duration_us(self) -> int:
        return self.end_us - self.start_us

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Word":
        return Word(**d)


@dataclass(frozen=True)
class Transcript:
    """
    The complete, immutable source transcript.

    words       : ordered tuple of Word objects
    source_id   : stable identifier for the source media file (e.g. sha256 prefix)
    duration_us : total source duration in microseconds
    """
    words: tuple  # tuple[Word, ...]
    source_id: str
    duration_us: int
    language: Optional[str] = None

    # ── Lookup helpers ────────────────────────────────────────────────────────

    def word_by_id(self, word_id: str) -> Optional[Word]:
        """O(n) lookup — transcripts are small; no index needed at this scale."""
        for w in self.words:
            if w.id == word_id:
                return w
        return None

    def words_in_source_range(self, start_us: int, end_us: int) -> List[Word]:
        """
        Return all words whose span overlaps [start_us, end_us).
        A word overlaps if word.start_us < end_us AND word.end_us > start_us.
        """
        return [
            w for w in self.words
            if w.start_us < end_us and w.end_us > start_us
        ]

    def gap_before_word(self, index: int) -> int:
        """
        Return the silence gap (µs) immediately before words[index].
        Returns 0 for index == 0.
        """
        if index == 0:
            return 0
        return self.words[index].start_us - self.words[index - 1].end_us

    def gap_after_word(self, index: int) -> int:
        """
        Return the silence gap (µs) immediately after words[index].
        Returns 0 for the last word.
        """
        if index >= len(self.words) - 1:
            return 0
        return self.words[index + 1].start_us - self.words[index].end_us

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "duration_us": self.duration_us,
            "language": self.language,
            "words": [w.to_dict() for w in self.words],
        }

    @staticmethod
    def from_dict(d: dict) -> "Transcript":
        words = tuple(Word.from_dict(w) for w in d["words"])
        return Transcript(
            words=words,
            source_id=d["source_id"],
            duration_us=d["duration_us"],
            language=d.get("language"),
        )

    @staticmethod
    def from_json(s: str) -> "Transcript":
        return Transcript.from_dict(json.loads(s))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def build_transcript(
    raw_words: List[dict],
    source_id: str,
    duration_us: int,
    language: Optional[str] = None,
) -> Transcript:
    """
    Construct a Transcript from a list of raw STT word dicts.

    Each dict must have: text, start_us, end_us.
    Optional: speaker, confidence.

    Word IDs are assigned sequentially starting at 0  (R-ANCHOR-02).
    """
    words = []
    for i, raw in enumerate(raw_words):
        words.append(Word(
            id=_word_id(i),
            index=i,
            text=raw["text"],
            start_us=int(raw["start_us"]),
            end_us=int(raw["end_us"]),
            speaker=raw.get("speaker"),
            confidence=raw.get("confidence"),
        ))
    return Transcript(
        words=tuple(words),
        source_id=source_id,
        duration_us=duration_us,
        language=language,
    )
