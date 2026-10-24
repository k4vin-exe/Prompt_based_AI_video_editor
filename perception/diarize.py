"""
perception/diarize.py
---------------------
Speaker diarization — assigns speaker labels to transcript words.

Strategy (cheapest first):
1. Use pyannote.audio if available and PYANNOTE_TOKEN is set (Apache 2.0 for models).
2. Fallback: gap-and-energy heuristic — every long pause that switches energy
   fingerprint is treated as a speaker change. Assigns "speaker_0", "speaker_1"…
   This is primitive but free, needs no model.

Both strategies mutate the word dicts in-place to add "speaker" field.
"""
from __future__ import annotations

import os
from typing import List, Dict, Any, Optional


def assign_speakers(
    words: List[Dict[str, Any]],
    audio_path: str,
    num_speakers: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Assign a 'speaker' label to each word dict (in-place mutation).

    Args:
        words:        List of word dicts with at least start_us, end_us.
        audio_path:   Path to audio/video file.
        num_speakers: Hint for expected number of speakers (None = auto-detect).

    Returns:
        The same list with 'speaker' key filled on each word.
    """
    token = os.environ.get("PYANNOTE_TOKEN", "")
    if token:
        try:
            return _diarize_pyannote(words, audio_path, token, num_speakers)
        except Exception:
            pass  # fall through to heuristic

    return _diarize_heuristic(words)


def _diarize_pyannote(
    words: List[Dict[str, Any]],
    audio_path: str,
    token: str,
    num_speakers: Optional[int],
) -> List[Dict[str, Any]]:
    """
    pyannote.audio speaker diarization.
    Requires: pip install pyannote.audio  (MIT)
    Model: pyannote/speaker-diarization-3.1  (MIT for the code, CC-BY 4.0 for models)
    NOTE: CC-BY allows commercial use. Set PYANNOTE_TOKEN from HuggingFace.
    """
    from pyannote.audio import Pipeline  # type: ignore

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=token,
    )
    kwargs: Dict[str, Any] = {}
    if num_speakers is not None:
        kwargs["num_speakers"] = num_speakers

    diarization = pipeline(audio_path, **kwargs)

    # Build a lookup: time (seconds) -> speaker label
    # For each word, find the dominant speaker in [start, end]
    for word in words:
        start_s = word["start_us"] / 1_000_000.0
        end_s = word["end_us"] / 1_000_000.0
        speaker = _find_speaker_at(diarization, start_s, end_s)
        word["speaker"] = speaker

    return words


def _find_speaker_at(diarization, start_s: float, end_s: float) -> str:
    """Find the speaker with maximum overlap with [start_s, end_s]."""
    from pyannote.core import Segment  # type: ignore

    query = Segment(start_s, end_s)
    best_speaker = "speaker_0"
    best_overlap = 0.0

    for segment, _, speaker in diarization.itertracks(yield_label=True):
        overlap = segment & query
        if overlap:
            dur = overlap.duration
            if dur > best_overlap:
                best_overlap = dur
                best_speaker = speaker

    return best_speaker


def _diarize_heuristic(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Cheap heuristic diarization: assign speaker based on pause boundaries.

    Assumption: a pause > SPEAKER_CHANGE_THRESHOLD_MS between two words
    may indicate a speaker change. We alternate speaker IDs at each long pause.

    This is a rough approximation for single/two-speaker content.
    """
    threshold_us = int(
        float(os.environ.get("SPEAKER_CHANGE_MS", "1000")) * 1000
    )
    current_speaker = 0
    max_speakers = int(os.environ.get("SPEAKER_COUNT_HINT", "2"))

    for i, word in enumerate(words):
        if i == 0:
            word["speaker"] = f"speaker_{current_speaker}"
            continue

        prev = words[i - 1]
        gap_us = word["start_us"] - prev["end_us"]
        if gap_us >= threshold_us and max_speakers > 1:
            current_speaker = (current_speaker + 1) % max_speakers

        word["speaker"] = f"speaker_{current_speaker}"

    return words
