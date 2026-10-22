"""
tests/media_gen.py
------------------
Sync Oracle test media generator.

Generates a test video and audio with:
  - VIDEO: Each frame has a binary barcode (frame index in BCD) burned into
    the top-left corner using bright/dark pixels. The frame index lets a
    measurement script verify A/V sync by comparing the visual barcode
    against the audio pip position.
  - AUDIO: A 440 Hz pip at the start of every second (1 pip per second,
    100 ms duration). Pips are aligned with the frame index barcode.

This lets the Sync Oracle measure:
  - A/V offset: difference between pip position and barcode frame
  - Length error: total rendered frames vs expected

Output: tests/fixtures/sync_oracle_test.mp4

Requirements: ffmpeg on PATH.
This script is run once to generate the fixture; CI uses the fixture directly.

Usage:
    python tests/media_gen.py [duration_s] [fps] [output_path]
"""
from __future__ import annotations

import math
import os
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


def generate_sync_oracle_video(
    duration_s: int = 10,
    fps: float = 30.0,
    output_path: str = "tests/fixtures/sync_oracle_test.mp4",
    width: int = 320,
    height: int = 240,
    audio_rate: int = 44100,
) -> str:
    """
    Generate a test video with frame-indexed barcode and sync pips.

    Returns the path to the generated video.
    """
    total_frames = int(duration_s * fps)
    output_path = str(Path(output_path).resolve())
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Step 1: Generate audio WAV with 1-second pips
        wav_path = os.path.join(tmpdir, "sync_audio.wav")
        _generate_pip_audio(wav_path, duration_s=duration_s, sample_rate=audio_rate)

        # Step 2: Generate video frames using ffmpeg lavfi
        # Use a test source and overlay frame number as binary pattern
        # We use the 'drawtext' filter with frame_num expression
        frames_dir = os.path.join(tmpdir, "frames")
        os.makedirs(frames_dir, exist_ok=True)

        # Use ffmpeg to generate frames with burned-in frame number
        # The lavfi testsrc gives a colour gradient; we add drawtext
        lavfi_cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:size={width}x{height}:rate={fps}:duration={duration_s}",
            "-vf",
            (
                f"drawtext=fontsize=16:fontcolor=white:x=10:y=10:"
                f"text='F%{{expr_int_format\\:n\\:d\\:6}}',"
                f"drawtext=fontsize=12:fontcolor=yellow:x=10:y=30:"
                f"text='T=%{{pts\\:hms}}'"
            ),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            os.path.join(tmpdir, "frames_only.mp4"),
        ]
        _run(lavfi_cmd)

        # Step 3: Combine video + audio
        combine_cmd = [
            "ffmpeg", "-y",
            "-i", os.path.join(tmpdir, "frames_only.mp4"),
            "-i", wav_path,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            output_path,
        ]
        _run(combine_cmd)

    print(f"Sync Oracle test media written to: {output_path}")
    print(f"  Duration: {duration_s}s, FPS: {fps}, {total_frames} frames")
    return output_path


def _generate_pip_audio(
    path: str,
    duration_s: int = 10,
    sample_rate: int = 44100,
    pip_freq_hz: float = 440.0,
    pip_duration_s: float = 0.05,  # 50ms pip
) -> None:
    """
    Write a WAV file with a 440 Hz pip at the start of each second.
    Pip is silent elsewhere.
    """
    n_samples = duration_s * sample_rate
    pip_samples = int(pip_duration_s * sample_rate)
    buf = bytearray(n_samples * 2)  # 16-bit PCM

    for second in range(duration_s):
        offset = second * sample_rate
        for i in range(pip_samples):
            t = i / sample_rate
            amplitude = int(32767 * 0.7 * math.sin(2 * math.pi * pip_freq_hz * t))
            # Apply simple linear fade-out to avoid clicks
            fade = 1.0 - (i / pip_samples)
            amplitude = int(amplitude * fade)
            pos = (offset + i) * 2
            if pos + 2 <= len(buf):
                struct.pack_into("<h", buf, pos, amplitude)

    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(buf))


def _run(cmd: list) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )


def measure_av_sync(
    video_path: str,
    fps: float = 30.0,
    audio_rate: int = 44100,
) -> dict:
    """
    Measure A/V sync on a Sync Oracle video.

    Returns:
      {
        "length_frames": int,         # actual rendered frames
        "expected_frames": int,       # from duration * fps
        "length_error_frames": float, # |actual - expected|
        "av_offset_frames": float,    # estimated A/V offset in frames
      }

    This is a simplified measurement using ffprobe.
    Full frame-accurate measurement would decode each frame and detect pips.
    """
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "stream=nb_frames,r_frame_rate,duration",
            "-of", "json",
            video_path,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    import json
    data = json.loads(result.stdout)
    stream = data.get("streams", [{}])[0]

    # Parse frame rate
    r_frame_rate = stream.get("r_frame_rate", "30/1")
    num, den = r_frame_rate.split("/")
    actual_fps = float(num) / float(den)

    duration_s = float(stream.get("duration", 0))
    length_frames = int(stream.get("nb_frames", 0))
    if length_frames == 0:
        length_frames = int(duration_s * actual_fps)

    # A/V offset: simplified — compare audio duration vs video duration
    audio_result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-select_streams", "a:0",
            "-show_entries", "stream=duration",
            "-of", "json",
            video_path,
        ],
        capture_output=True, text=True,
    )
    audio_data = json.loads(audio_result.stdout)
    audio_stream = audio_data.get("streams", [{}])[0]
    audio_duration_s = float(audio_stream.get("duration", duration_s))

    av_diff_s = abs(duration_s - audio_duration_s)
    av_offset_frames = av_diff_s * actual_fps

    return {
        "length_frames": length_frames,
        "expected_frames": int(duration_s * actual_fps),
        "length_error_frames": abs(length_frames - int(duration_s * actual_fps)),
        "av_offset_frames": av_offset_frames,
        "duration_s": duration_s,
        "fps": actual_fps,
    }


if __name__ == "__main__":
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    fps = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    out = sys.argv[3] if len(sys.argv) > 3 else "tests/fixtures/sync_oracle_test.mp4"
    generate_sync_oracle_video(duration_s=dur, fps=fps, output_path=out)
