"""
nlu/adapters/stt_groq.py
------------------------
Groq Whisper STT adapter (free tier, ultra-fast cloud transcription).

Env vars:
  GROQ_API_KEY    : Groq API key (required)
  GROQ_STT_MODEL  : model name (default "whisper-large-v3-turbo")
"""
from __future__ import annotations

import os
from typing import Optional, List, Dict, Any

from .stt_base import STTAdapter


class GroqSTTAdapter(STTAdapter):
    """
    STT adapter using Groq's Whisper API.
    Returns word-level timing compatible with engine.transcript.build_transcript().
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._api_key = (api_key or os.environ.get("GROQ_API_KEY", "")).strip()
        self._model = (model or os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")).strip()
        self._client = None

    @property
    def name(self) -> str:
        return "groq"

    @property
    def version(self) -> str:
        return self._model

    def _get_client(self):
        if self._client is None:
            from groq import Groq
            self._client = Groq(api_key=self._api_key)
        return self._client

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        diarize: bool = False,
    ) -> Dict[str, Any]:
        """
        Transcribe audio_path using Groq Whisper API with word timestamps.
        """
        client = self._get_client()

        with open(audio_path, "rb") as f:
            kwargs: Dict[str, Any] = {
                "file": (os.path.basename(audio_path), f),
                "model": self._model,
                "response_format": "verbose_json",
                "timestamp_granularities": ["word"],
            }
            if language:
                kwargs["language"] = language

            response = client.audio.transcriptions.create(**kwargs)

        words: List[Dict[str, Any]] = []
        raw_words = getattr(response, "words", None) or []
        for w in raw_words:
            # w may be dict or object with word, start, end
            text = getattr(w, "word", None) or (w.get("word") if isinstance(w, dict) else "")
            start = getattr(w, "start", None) or (w.get("start") if isinstance(w, dict) else 0.0)
            end = getattr(w, "end", None) or (w.get("end") if isinstance(w, dict) else 0.0)
            words.append({
                "text": text.strip(),
                "start_us": int(start * 1_000_000),
                "end_us": int(end * 1_000_000),
                "speaker": None,
                "confidence": 0.99,
            })

        duration_s = getattr(response, "duration", None)
        duration_us = int(duration_s * 1_000_000) if duration_s else (
            words[-1]["end_us"] if words else 0
        )
        detected_language = getattr(response, "language", None) or language or "en"

        return {
            "words": words,
            "language": detected_language,
            "duration_us": duration_us,
        }
