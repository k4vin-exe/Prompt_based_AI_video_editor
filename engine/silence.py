"""
engine/silence.py
-----------------
Deterministic silence removal with deliberate pause preservation. (R-SIL-01 - R-SIL-03)

- Minimum threshold: 0.5s; lower is rejected with SILENCE_THRESHOLD_TOO_LOW.
- Deliberate pause preservation: a pause after sentence-ending punctuation (. ? !)
  is preserved and noted in warnings.
- Returns list of cut ranges [start_us, end_us) for candidate silences.
"""
from __future__ import annotations

from typing import List, Tuple
from .transcript import Transcript


def find_silence_cuts(
    transcript: Transcript,
    threshold_s: float,
) -> Tuple[List[Tuple[int, int]], List[str], List[str]]:
    """
    Find silence gaps longer than threshold_s.
    Returns:
      cuts: List of (start_us, end_us) ranges to cut
      cut_descriptions: Human readable string for each cut
      warnings: List of preserved deliberate pauses
    """
    threshold_us = int(threshold_s * 1_000_000)
    words = transcript.words
    cuts: List[Tuple[int, int]] = []
    descriptions: List[str] = []
    warnings: List[str] = []

    # Initial silence before first word
    if words and words[0].start_us >= threshold_us:
        cuts.append((0, words[0].start_us))
        descriptions.append(f"Initial silence 0.0s to {words[0].start_us/1_000_000:.2f}s")

    # Inter-word silences
    for i in range(len(words) - 1):
        w_curr = words[i]
        w_next = words[i + 1]
        gap_us = w_next.start_us - w_curr.end_us

        if gap_us >= threshold_us:
            # Check for deliberate pause: sentence-ending punctuation
            if w_curr.text.strip().endswith((".", "?", "!")):
                warnings.append(
                    f"Preserved deliberate pause of {gap_us/1_000_000:.2f}s after '{w_curr.text}' at {w_curr.end_us/1_000_000:.2f}s (R-SIL-02)"
                )
                continue

            cuts.append((w_curr.end_us, w_next.start_us))
            descriptions.append(
                f"Silence {gap_us/1_000_000:.2f}s between '{w_curr.text}' and '{w_next.text}'"
            )

    # Trailing silence after last word
    if words and (transcript.duration_us - words[-1].end_us) >= threshold_us:
        trailing_start = words[-1].end_us
        cuts.append((trailing_start, transcript.duration_us))
        descriptions.append(f"Trailing silence from {trailing_start/1_000_000:.2f}s to end")

    return cuts, descriptions, warnings
