"""
engine/filler.py
----------------
Deterministic filler word detection and removal. (R-FILLER-01 - R-FILLER-04)

Detects "um", "uh", and contextual "like":
  - "like" is a filler if:
    (a) pause before OR after >= 0.15s, AND
    (b) not sentence-final (does not end with . ? !)
  - Checks for active mute/bleep conflicts (R-FILLER-03)
  - Produces CutOp instances anchored to word boundaries
"""
from __future__ import annotations

import re
from typing import List, Tuple, Set

from .transcript import Transcript, Word
from .ops import CutOp, BaseOp, MuteOp, BleepOp
from .history import History

FILLER_LIKE_MIN_PAUSE_S = 0.15


def is_filler_word(
    word: Word,
    prev_word: Word | None,
    next_word: Word | None,
) -> bool:
    """
    Check if a word is a filler word according to R-FILLER-01 and R-FILLER-02.
    """
    clean = re.sub(r"[^\w]", "", word.text.lower())

    if clean in ("um", "uh", "umm", "uhh"):
        return True

    if clean == "like":
        # Check condition (b): not sentence final
        if word.text.strip().endswith((".", "?", "!")):
            return False

        # Check condition (a): pause before or after >= 0.15s
        pause_before_s = 0.0
        if prev_word is not None:
            pause_before_s = (word.start_us - prev_word.end_us) / 1_000_000.0

        pause_after_s = 0.0
        if next_word is not None:
            pause_after_s = (next_word.start_us - word.end_us) / 1_000_000.0

        if pause_before_s >= FILLER_LIKE_MIN_PAUSE_S or pause_after_s >= FILLER_LIKE_MIN_PAUSE_S:
            return True

    return False


def find_filler_cuts(
    transcript: Transcript,
    history: History,
) -> Tuple[List[Tuple[int, int]], List[str], List[str]]:
    """
    Find all filler words to cut.
    Returns:
      cuts: List of (src_start_us, src_end_us) for each filler to cut
      filler_words: List of word representations removed
      warnings: Warnings for any skipped fillers (e.g. bleep conflict)
    """
    active_ops = history.get_active_ops()

    # Collect active mute/bleep ranges (R-FILLER-03)
    protected_ranges: List[Tuple[int, int]] = []
    for op in active_ops:
        if isinstance(op, (MuteOp, BleepOp)):
            protected_ranges.append((op.start_us, op.end_us))

    words = transcript.words
    cuts: List[Tuple[int, int]] = []
    removed_words: List[str] = []
    warnings: List[str] = []

    for i, word in enumerate(words):
        prev_w = words[i - 1] if i > 0 else None
        next_w = words[i + 1] if i < len(words) - 1 else None

        if is_filler_word(word, prev_w, next_w):
            # Check if this word conflicts with any active mute or bleep
            conflicts = False
            for p_start, p_end in protected_ranges:
                if not (word.end_us <= p_start or word.start_us >= p_end):
                    conflicts = True
                    break

            if conflicts:
                warnings.append(
                    f"Skipped filler '{word.text}' at {word.start_us/1_000_000:.2f}s due to active mute/bleep conflict (R-FILLER-03)"
                )
                continue

            cuts.append((word.start_us, word.end_us))
            removed_words.append(word.text)

    return cuts, removed_words, warnings
