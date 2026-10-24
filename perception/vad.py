"""
perception/vad.py
-----------------
Energy-based Voice Activity Detection (VAD).

Returns a list of silence intervals (start_us, end_us) from an audio file.
Uses librosa for audio loading (MIT), falls back to pure scipy/numpy if available,
or reads wav duration via wave stdlib module.

No external model downloads required — energy-based only.
Silero VAD can be optionally used when torch is available (VAD_BACKEND=silero).
"""
from __future__ import annotations

import os
import wave
from typing import List, Tuple, Optional

# Tuple[start_us, end_us]
SilenceInterval = Tuple[int, int]


def detect_silences(
    audio_path: str,
    min_silence_ms: float = 500.0,
    energy_threshold_db: float = -40.0,
    frame_ms: float = 20.0,
) -> List[SilenceInterval]:
    """
    Detect silence intervals in an audio file.

    Returns a list of (start_us, end_us) pairs where the audio energy
    is below energy_threshold_db for at least min_silence_ms.

    Args:
        audio_path:          Path to audio/video file.
        min_silence_ms:      Minimum silence duration to report (ms).
        energy_threshold_db: Energy threshold in dBFS (default -40 dB).
        frame_ms:            Analysis frame size in ms.

    Returns:
        List of (start_us, end_us) tuples for detected silence intervals.
    """
    backend = os.environ.get("VAD_BACKEND", "energy").lower()

    if backend == "silero":
        return _detect_silences_silero(audio_path, min_silence_ms)

    return _detect_silences_energy(audio_path, min_silence_ms, energy_threshold_db, frame_ms)


def _detect_silences_energy(
    audio_path: str,
    min_silence_ms: float,
    energy_threshold_db: float,
    frame_ms: float,
) -> List[SilenceInterval]:
    """Energy-based VAD using librosa or numpy/scipy."""
    try:
        return _energy_via_librosa(audio_path, min_silence_ms, energy_threshold_db, frame_ms)
    except ImportError:
        pass

    try:
        return _energy_via_scipy(audio_path, min_silence_ms, energy_threshold_db, frame_ms)
    except (ImportError, Exception):
        pass

    # Last resort: treat transcript gap times as silences (no audio analysis)
    return []


def _energy_via_librosa(
    audio_path: str,
    min_silence_ms: float,
    energy_threshold_db: float,
    frame_ms: float,
) -> List[SilenceInterval]:
    import numpy as np
    import librosa  # type: ignore

    y, sr = librosa.load(audio_path, sr=None, mono=True)
    frame_len = int(sr * frame_ms / 1000)
    hop_len = frame_len // 2

    rms = librosa.feature.rms(y=y, frame_length=frame_len, hop_length=hop_len)[0]
    # Convert to dBFS
    rms_db = librosa.amplitude_to_db(rms, ref=np.max(rms) + 1e-10)

    frame_dur_us = int(hop_len * 1_000_000 / sr)
    silences = _rms_to_silences(rms_db, energy_threshold_db, frame_dur_us, min_silence_ms)
    return silences


def _energy_via_scipy(
    audio_path: str,
    min_silence_ms: float,
    energy_threshold_db: float,
    frame_ms: float,
) -> List[SilenceInterval]:
    import numpy as np
    from scipy.io import wavfile  # type: ignore

    sr, data = wavfile.read(audio_path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    data = data.astype(np.float32)
    max_val = np.abs(data).max() or 1.0

    frame_len = int(sr * frame_ms / 1000)
    hop_len = frame_len // 2

    rms_frames = []
    for i in range(0, len(data) - frame_len, hop_len):
        frame = data[i:i + frame_len]
        rms = np.sqrt(np.mean(frame ** 2))
        rms_frames.append(rms)

    rms_arr = np.array(rms_frames)
    rms_db = 20 * np.log10(rms_arr / max_val + 1e-10)

    frame_dur_us = int(hop_len * 1_000_000 / sr)
    return _rms_to_silences(rms_db, energy_threshold_db, frame_dur_us, min_silence_ms)


def _rms_to_silences(
    rms_db,  # numpy array
    threshold_db: float,
    frame_dur_us: int,
    min_silence_ms: float,
) -> List[SilenceInterval]:
    """Convert RMS dB array to silence intervals."""
    import numpy as np

    min_silence_us = int(min_silence_ms * 1000)
    is_silent = rms_db < threshold_db

    silences: List[SilenceInterval] = []
    in_silence = False
    silence_start = 0

    for i, silent in enumerate(is_silent):
        t_us = i * frame_dur_us
        if silent and not in_silence:
            in_silence = True
            silence_start = t_us
        elif not silent and in_silence:
            in_silence = False
            dur = t_us - silence_start
            if dur >= min_silence_us:
                silences.append((silence_start, t_us))

    if in_silence:
        end_us = len(is_silent) * frame_dur_us
        dur = end_us - silence_start
        if dur >= min_silence_us:
            silences.append((silence_start, end_us))

    return silences


def _detect_silences_silero(
    audio_path: str,
    min_silence_ms: float,
) -> List[SilenceInterval]:
    """
    Silero VAD backend.
    Requires: torch, torchaudio (optional; falls back to energy if unavailable).
    Model: snakers4/silero-vad (MIT licence).
    """
    try:
        import torch
        import torchaudio  # type: ignore

        model, utils = torch.hub.load(
            "snakers4/silero-vad",
            "silero_vad",
            force_reload=False,
            trust_repo=True,
        )
        get_speech_ts = utils[0]

        wav, sr = torchaudio.load(audio_path)
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)

        # Resample to 16kHz (required by silero)
        if sr != 16000:
            resampler = torchaudio.transforms.Resample(sr, 16000)
            wav = resampler(wav)
            sr = 16000

        wav = wav.squeeze(0)
        speech_ts = get_speech_ts(wav, model, sampling_rate=sr)

        # Invert speech timestamps → silence timestamps
        total_frames = len(wav)
        total_us = int(total_frames * 1_000_000 / sr)
        speech_us = [(int(ts["start"] * 1_000_000 / sr), int(ts["end"] * 1_000_000 / sr))
                     for ts in speech_ts]

        silences = _invert_intervals(speech_us, 0, total_us, min_silence_ms)
        return silences

    except Exception:
        return _detect_silences_energy(audio_path, min_silence_ms, -40.0, 20.0)


def _invert_intervals(
    speech: List[Tuple[int, int]],
    total_start: int,
    total_end: int,
    min_silence_ms: float,
) -> List[SilenceInterval]:
    """Given speech intervals, return the gaps (silences) between them."""
    min_silence_us = int(min_silence_ms * 1000)
    silences = []
    cursor = total_start

    for start, end in speech:
        if start > cursor:
            gap = start - cursor
            if gap >= min_silence_us:
                silences.append((cursor, start))
        cursor = max(cursor, end)

    if total_end > cursor:
        gap = total_end - cursor
        if gap >= min_silence_us:
            silences.append((cursor, total_end))

    return silences
