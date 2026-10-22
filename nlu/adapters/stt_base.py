"""
nlu/adapters/stt_base.py
------------------------
Abstract base class for all STT adapters.

Every adapter returns a list of word dicts compatible with
engine.transcript.build_transcript().

Required keys per word dict:
  text       : str
  start_us   : int (microseconds)
  end_us     : int (microseconds)

Optional:
  speaker    : str | None
  confidence : float | None
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional


class STTAdapter(ABC):
    """Interface for speech-to-text adapters."""

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        diarize: bool = False,
    ) -> dict:
        """
        Transcribe the audio file at audio_path.

        Returns a dict with:
          words       : list of word dicts (text, start_us, end_us, speaker?, confidence?)
          language    : detected language code (e.g. "en")
          duration_us : total audio duration in microseconds
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable adapter name for manifests."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Version string for manifests."""
        ...

    @property
    def cost_per_minute_usd(self) -> float:
        """Estimated cost in USD per minute of audio. 0.0 for free/local."""
        return 0.0
