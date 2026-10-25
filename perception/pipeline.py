"""
perception/pipeline.py
-----------------------
Main Perception pipeline.

Runs once per source file and caches results in analysis.json next to the source.

analysis.json schema:
{
  "source_id":     str,           // sha256[:16] of source file
  "source_hash":   str,           // full sha256 of source file
  "created_at":    str,           // ISO-8601 UTC timestamp
  "model_manifest": {             // models used (for output manifest)
    "stt": {"name": str, "version": str},
    "vad": {"backend": str},
    "embed": {"model": str}
  },
  "transcript": {                 // same format as engine.transcript.Transcript.to_dict()
    "source_id": str,
    "duration_us": int,
    "language": str,
    "words": [{"id","index","text","start_us","end_us","speaker","confidence"}]
  },
  "silences": [                   // VAD output
    {"start_us": int, "end_us": int}
  ],
  "speakers": [str],              // unique speaker labels found
  "chapters": [                   // topic segmentation
    {"chapter_id":int,"title":str,"start_word_id":str,"end_word_id":str,
     "start_us":int,"end_us":int,"keywords":[str]}
  ]
}
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from engine.transcript import build_transcript, Transcript


def analyse(
    video_path: str,
    stt_adapter=None,
    llm_adapter=None,
    force_rerun: bool = False,
    cache_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run full perception pipeline on video_path.

    Returns the analysis dict (and writes it to analysis.json).

    Args:
        video_path:   Path to the source video/audio file.
        stt_adapter:  STTAdapter instance (defaults to WhisperSTTAdapter if None).
        llm_adapter:  Optional LLM adapter for chapter title generation.
        force_rerun:  If True, ignore cache and re-run everything.
        cache_dir:    Directory to write analysis.json (defaults to dirname of video_path).
    """
    source_hash = _sha256_file(video_path)
    source_id = source_hash[:16]

    analysis_path = _analysis_path(video_path, cache_dir)

    # Return cached result if valid
    if not force_rerun and os.path.exists(analysis_path):
        with open(analysis_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if cached.get("source_hash") == source_hash:
            return cached
        # Hash mismatch → file changed → rerun

    # ── Step 1: STT ──────────────────────────────────────────────────────────
    if stt_adapter is None:
        stt_adapter = _default_stt_adapter()

    audio_for_stt = _extract_audio_if_needed(video_path)
    try:
        stt_result = stt_adapter.transcribe(audio_for_stt, diarize=False)
    except Exception:
        stt_result = {"words": [], "language": "en", "duration_us": 0}
    finally:
        if audio_for_stt != video_path and os.path.exists(audio_for_stt):
            try:
                os.remove(audio_for_stt)
            except OSError:
                pass

    words_raw = stt_result.get("words", [])
    language = stt_result.get("language", "en")
    duration_us = stt_result.get("duration_us", 0)

    # If STT didn't get duration_us from audio, probe the video
    if duration_us == 0:
        try:
            from engine.probe import probe_video
            meta = probe_video(video_path)
            duration_us = meta.duration_us
        except Exception:
            pass

    # ── Step 2: Diarization ───────────────────────────────────────────────────
    try:
        from perception.diarize import assign_speakers
        words_raw = assign_speakers(words_raw, video_path)
    except Exception:
        pass  # Words keep speaker=None

    # ── Step 3: Build Transcript (assigns word IDs) ───────────────────────────
    transcript = build_transcript(words_raw, source_id, duration_us, language)

    # ── Step 4: VAD (silence detection) ──────────────────────────────────────
    silences = []
    try:
        from perception.vad import detect_silences
        # Extract audio to a temp wav if input is video
        audio_path = _extract_audio_if_needed(video_path)
        silences = detect_silences(audio_path)
        if audio_path != video_path:
            try:
                os.remove(audio_path)
            except OSError:
                pass
    except Exception:
        pass

    # ── Step 5: Topic segmentation ────────────────────────────────────────────
    chapters = []
    try:
        from perception.topics import segment_topics
        # Need word dicts with IDs assigned
        words_with_ids = [w.to_dict() for w in transcript.words]
        chapter_objs = segment_topics(words_with_ids, llm_adapter=llm_adapter)
        chapters = [c.to_dict() for c in chapter_objs]
    except Exception:
        pass

    # ── Step 6: Collect unique speakers ──────────────────────────────────────
    speakers = list(dict.fromkeys(
        w.speaker for w in transcript.words if w.speaker is not None
    ))

    # ── Step 7: Assemble analysis.json ────────────────────────────────────────
    model_manifest = {
        "stt": {"name": stt_adapter.name, "version": stt_adapter.version},
        "vad": {"backend": os.environ.get("VAD_BACKEND", "energy")},
        "embed": {"model": os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")},
    }

    analysis = {
        "source_id": source_id,
        "source_hash": source_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_manifest": model_manifest,
        "transcript": transcript.to_dict(),
        "silences": [{"start_us": s[0], "end_us": s[1]} for s in silences],
        "speakers": speakers,
        "chapters": chapters,
    }

    try:
        os.makedirs(os.path.dirname(analysis_path) or ".", exist_ok=True)
        with open(analysis_path, "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return analysis


def load_analysis(video_path: str, cache_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Load cached analysis.json without re-running the pipeline."""
    path = _analysis_path(video_path, cache_dir)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def analysis_to_transcript(analysis: Dict[str, Any]) -> Transcript:
    """Reconstruct a Transcript from an analysis dict."""
    return Transcript.from_dict(analysis["transcript"])


# ── Private helpers ────────────────────────────────────────────────────────────

def _sha256_file(path: str) -> str:
    """Compute SHA-256 of file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _analysis_path(video_path: str, cache_dir: Optional[str] = None) -> str:
    """Return the path where analysis.json should be written."""
    base = os.path.splitext(os.path.basename(video_path))[0]
    if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return os.path.join("/tmp", f"{base}_analysis.json")
    directory = cache_dir or os.path.dirname(os.path.abspath(video_path))
    return os.path.join(directory, f"{base}_analysis.json")


def _default_stt_adapter():
    """Select STT adapter based on STT_ADAPTER env var with resilient fallback."""
    adapter_name = os.environ.get(
        "STT_ADAPTER",
        "mock" if (os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME")) else "whisper"
    ).lower()

    if adapter_name == "mock":
        from nlu.adapters.stt_mock import MockSTTAdapter
        return MockSTTAdapter()
    elif adapter_name == "groq":
        try:
            from nlu.adapters.stt_groq import GroqSTTAdapter  # type: ignore
            return GroqSTTAdapter()
        except Exception:
            from nlu.adapters.stt_mock import MockSTTAdapter
            return MockSTTAdapter()
    try:
        from nlu.adapters.stt_whisper import WhisperSTTAdapter
        return WhisperSTTAdapter()
    except Exception:
        from nlu.adapters.stt_mock import MockSTTAdapter
        return MockSTTAdapter()


def _extract_audio_if_needed(video_path: str) -> str:
    """
    If video_path is a video file, extract audio to a temporary WAV for VAD.
    Returns the path to use for audio analysis.
    """
    ext = os.path.splitext(video_path)[1].lower()
    if ext in (".wav", ".flac", ".mp3", ".m4a", ".ogg"):
        return video_path

    import tempfile
    import subprocess
    import shutil

    from engine.probe import get_ffmpeg_path
    ffmpeg = get_ffmpeg_path()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()

    try:
        subprocess.run([
            ffmpeg, "-threads", "1", "-y", "-i", video_path,
            "-vn", "-ar", "16000", "-ac", "1",
            "-f", "wav", tmp.name,
        ], check=True, capture_output=True)
        return tmp.name
    except Exception:
        try:
            os.remove(tmp.name)
        except OSError:
            pass
        return video_path
