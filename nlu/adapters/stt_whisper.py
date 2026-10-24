"""
nlu/adapters/stt_whisper.py
---------------------------
faster-whisper STT adapter.

Env vars:
  WHISPER_MODEL   : model size (default "base")
  WHISPER_DEVICE  : "cpu" | "cuda" | "auto"  (default "cpu")
  WHISPER_COMPUTE : "int8" | "float16" | "float32" (default "int8")
  WHISPER_LANGUAGE: force language code, e.g. "en" (default auto-detect)

Licence: faster-whisper is MIT; models are openai-whisper Apache-2.0.
"""
from __future__ import annotations

import os
from typing import Optional, List

from .stt_base import STTAdapter


class WhisperSTTAdapter(STTAdapter):
    """
    Real STT adapter using faster-whisper.
    Returns word-level timing compatible with engine.transcript.build_transcript().
    """

    def __init__(
        self,
        model: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        language: Optional[str] = None,
    ) -> None:
        self._model_size = model or os.environ.get("WHISPER_MODEL", "base")
        self._device = device or os.environ.get("WHISPER_DEVICE", "cpu")
        self._compute_type = compute_type or os.environ.get("WHISPER_COMPUTE", "int8")
        self._language = language or os.environ.get("WHISPER_LANGUAGE") or None
        self._model = None  # lazy-loaded

    @property
    def name(self) -> str:
        return "faster_whisper"

    @property
    def version(self) -> str:
        return self._model_size

    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
        return self._model

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        diarize: bool = False,
    ) -> dict:
        """
        Transcribe audio_path and return:
          {
            "words": [{text, start_us, end_us, speaker, confidence}, ...],
            "language": str,
            "duration_us": int
          }
        """
        model = self._load_model()
        lang = language or self._language
        segments, info = model.transcribe(
            audio_path,
            language=lang,
            word_timestamps=True,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )

        words: List[dict] = []
        for segment in segments:
            if segment.words is None:
                continue
            for w in segment.words:
                words.append({
                    "text": w.word.strip(),
                    "start_us": int(w.start * 1_000_000),
                    "end_us": int(w.end * 1_000_000),
                    "speaker": None,   # diarization is separate
                    "confidence": float(w.probability),
                })

        # Duration from info (detected by faster-whisper)
        duration_us = int(info.duration * 1_000_000) if info.duration else (
            words[-1]["end_us"] if words else 0
        )
        detected_language = info.language or lang or "en"

        return {
            "words": words,
            "language": detected_language,
            "duration_us": duration_us,
        }
