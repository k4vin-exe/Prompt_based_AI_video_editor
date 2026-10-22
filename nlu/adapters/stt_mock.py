"""
nlu/adapters/stt_mock.py
------------------------
Mock STT adapter for testing.  No model downloads required.

Behaviour:
  - If a fixture file exists at FIXTURE_DIR/<source_id>.json, load it.
  - Otherwise generate a synthetic transcript from the audio duration
    (creates fake words with known timing for test determinism).

This adapter is used in all CI tests so tests run with zero API keys.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .stt_base import STTAdapter

# Default fixture directory (can be overridden via env var)
_DEFAULT_FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "tests", "fixtures", "transcripts"
)


class MockSTTAdapter(STTAdapter):
    """
    STT adapter that reads from JSON fixture files or generates synthetic data.

    Fixture file format (JSON):
    {
      "words": [
        {"text": "Hello", "start_us": 0, "end_us": 500000, "speaker": "speaker_0", "confidence": 0.99},
        ...
      ],
      "language": "en",
      "duration_us": 300000000
    }
    """

    def __init__(self, fixture_dir: Optional[str] = None) -> None:
        self._fixture_dir = fixture_dir or os.environ.get(
            "STT_FIXTURE_DIR", _DEFAULT_FIXTURE_DIR
        )

    @property
    def name(self) -> str:
        return "mock_stt"

    @property
    def version(self) -> str:
        return "0.1.0"

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        diarize: bool = False,
    ) -> dict:
        """
        Load fixture if available, otherwise synthesise.
        source_id derived from basename of audio_path (no extension).
        """
        source_id = os.path.splitext(os.path.basename(audio_path))[0]
        fixture_path = os.path.join(self._fixture_dir, f"{source_id}.json")

        if os.path.exists(fixture_path):
            with open(fixture_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data

        # Synthetic fallback: 1 word per 0.5 seconds
        # Duration derived from filename convention: <name>_<duration_s>s.wav
        # or defaults to 60 seconds.
        duration_s = _extract_duration_from_name(source_id) or 60
        return _synthetic_transcript(duration_s, language or "en")


def _extract_duration_from_name(source_id: str) -> Optional[int]:
    """Extract duration from filename like 'test_video_300s'."""
    import re
    m = re.search(r"_(\d+)s$", source_id)
    if m:
        return int(m.group(1))
    return None


def _synthetic_transcript(duration_s: int, language: str = "en") -> dict:
    """
    Generate a synthetic transcript with predictable word timings.

    Word pattern: alternating content words and fillers, 1 word per 0.4s,
    with 0.1s gaps between words.  This gives known timing for tests.
    """
    words_template = [
        "welcome", "to", "the", "channel", "today", "we", "will",
        "talk", "about", "um", "pricing", "and", "um", "features",
        "like", "the", "speed", "and", "quality", "uh", "thanks",
    ]
    words = []
    t_us = 0
    word_dur_us = 400_000   # 0.4 s per word
    gap_us = 100_000        # 0.1 s gap
    i = 0

    while t_us < duration_s * 1_000_000:
        word_text = words_template[i % len(words_template)]
        # Alternate two speakers for multi-speaker fixtures
        speaker = f"speaker_{i % 2}"
        words.append({
            "text": word_text,
            "start_us": t_us,
            "end_us": t_us + word_dur_us,
            "speaker": speaker,
            "confidence": 0.95,
        })
        t_us += word_dur_us + gap_us
        i += 1

    return {
        "words": words,
        "language": language,
        "duration_us": duration_s * 1_000_000,
    }
