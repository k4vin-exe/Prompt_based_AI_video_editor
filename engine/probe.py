"""
engine/probe.py
---------------
Video intake and metadata probe.
Reads duration, frame rate, resolution, audio channels/sample rate, and detects VFR.
(Brief §What you build, R-REND-05, R-REND-06)

Supports probing via ffprobe (preferred) or ffmpeg -i fallback.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, Tuple


def get_ffmpeg_path() -> str:
    """Find ffmpeg executable from PATH or bundled imageio-ffmpeg."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return "ffmpeg"


def get_ffprobe_path() -> Optional[str]:
    """Find ffprobe executable if available."""
    path = shutil.which("ffprobe")
    if path:
        return path
    # Check next to imageio_ffmpeg if exists
    try:
        import imageio_ffmpeg
        bdir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
        probe_candidate = os.path.join(bdir, "ffprobe.exe")
        if os.path.exists(probe_candidate):
            return probe_candidate
    except Exception:
        pass
    return None


@dataclass
class VideoMetadata:
    """Metadata extracted from a video source file."""
    path: str
    duration_s: float
    duration_us: int
    fps: float
    width: int
    height: int
    has_audio: bool
    audio_sample_rate: int = 44100
    audio_channels: int = 2
    is_vfr: bool = False
    format_name: str = "mp4"
    video_codec: str = "h264"
    audio_codec: str = "aac"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def probe_video(video_path: str) -> VideoMetadata:
    """
    Probe a video file and return its VideoMetadata.
    Raises FileNotFoundError if file does not exist, or ValueError if unparseable.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    probe_exe = get_ffprobe_path()
    if probe_exe:
        try:
            return _probe_with_ffprobe(probe_exe, video_path)
        except Exception:
            pass  # Fallback to ffmpeg -i

    ffmpeg_exe = get_ffmpeg_path()
    return _probe_with_ffmpeg(ffmpeg_exe, video_path)


def _probe_with_ffprobe(ffprobe_exe: str, video_path: str) -> VideoMetadata:
    cmd = [
        ffprobe_exe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(proc.stdout)

    format_info = info.get("format", {})
    duration_s = float(format_info.get("duration", 0.0))

    video_stream = None
    audio_stream = None
    for s in info.get("streams", []):
        if s.get("codec_type") == "video" and video_stream is None:
            video_stream = s
        elif s.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = s

    if video_stream is None:
        raise ValueError(f"No video stream found in {video_path}")

    # FPS extraction
    fps_str = video_stream.get("r_frame_rate", "30/1")
    if "/" in fps_str:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 30.0
    else:
        fps = float(fps_str)

    width = int(video_stream.get("width", 1920))
    height = int(video_stream.get("height", 1080))
    v_codec = video_stream.get("codec_name", "h264")

    # Check VFR: avg_frame_rate vs r_frame_rate difference
    is_vfr = False
    avg_fps_str = video_stream.get("avg_frame_rate")
    if avg_fps_str and "/" in avg_fps_str:
        num, den = avg_fps_str.split("/")
        avg_fps = float(num) / float(den) if float(den) != 0 else fps
        if abs(avg_fps - fps) > 0.05:
            is_vfr = True

    has_audio = audio_stream is not None
    sample_rate = int(audio_stream.get("sample_rate", 44100)) if audio_stream else 0
    channels = int(audio_stream.get("channels", 2)) if audio_stream else 0
    a_codec = audio_stream.get("codec_name", "aac") if audio_stream else "none"

    return VideoMetadata(
        path=video_path,
        duration_s=duration_s,
        duration_us=int(duration_s * 1_000_000),
        fps=fps,
        width=width,
        height=height,
        has_audio=has_audio,
        audio_sample_rate=sample_rate,
        audio_channels=channels,
        is_vfr=is_vfr,
        format_name=format_info.get("format_name", "mp4"),
        video_codec=v_codec,
        audio_codec=a_codec,
    )


def _probe_with_ffmpeg(ffmpeg_exe: str, video_path: str) -> VideoMetadata:
    """Probe using ffmpeg -i output."""
    cmd = [ffmpeg_exe, "-i", video_path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = proc.stderr

    # Duration: Duration: 00:05:00.00, start: 0.000000, bitrate: ...
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if dur_match:
        h = int(dur_match.group(1))
        m = int(dur_match.group(2))
        s = float(dur_match.group(3))
        duration_s = h * 3600 + m * 60 + s
    else:
        duration_s = 0.0

    # Video stream: Stream #0:0: Video: h264 (High), yuv420p, 1920x1080 [SAR 1:1 DAR 16:9], 30 fps, 30 tbr...
    vid_match = re.search(r"Stream #0:\d+.*?: Video: ([^,\s]+).*?,\s*(\d+)x(\d+).*?,\s*([\d.]+)\s*fps", output)
    if vid_match:
        v_codec = vid_match.group(1)
        width = int(vid_match.group(2))
        height = int(vid_match.group(3))
        fps = float(vid_match.group(4))
    else:
        # Relaxed match
        res_match = re.search(r"(\d{3,4})x(\d{3,4})", output)
        width = int(res_match.group(1)) if res_match else 1920
        height = int(res_match.group(2)) if res_match else 1080
        fps_match = re.search(r"([\d.]+)\s*fps", output)
        fps = float(fps_match.group(1)) if fps_match else 30.0
        v_codec = "h264"

    # Check VFR: tbr != fps by significant margin
    is_vfr = False
    tbr_match = re.search(r"([\d.]+)\s*tbr", output)
    if tbr_match:
        tbr = float(tbr_match.group(1))
        if abs(tbr - fps) > 0.5:
            is_vfr = True

    # Audio stream: Stream #0:1: Audio: aac (LC), 44100 Hz, stereo, fltp...
    aud_match = re.search(r"Stream #0:\d+.*?: Audio: ([^,\s]+).*?,\s*(\d+)\s*Hz,\s*([^,]+)", output)
    if aud_match:
        has_audio = True
        a_codec = aud_match.group(1)
        sample_rate = int(aud_match.group(2))
        channels_str = aud_match.group(3).lower()
        channels = 1 if "mono" in channels_str else 2
    else:
        has_audio = False
        a_codec = "none"
        sample_rate = 0
        channels = 0

    return VideoMetadata(
        path=video_path,
        duration_s=duration_s,
        duration_us=int(duration_s * 1_000_000),
        fps=fps,
        width=width,
        height=height,
        has_audio=has_audio,
        audio_sample_rate=sample_rate,
        audio_channels=channels,
        is_vfr=is_vfr,
        format_name="mp4",
        video_codec=v_codec,
        audio_codec=a_codec,
    )
