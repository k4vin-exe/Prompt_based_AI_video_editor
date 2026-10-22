"""
engine/otio_export.py
---------------------
OpenTimelineIO (.otio) exporter for IncuBrix Timelines. (Brief §Outstanding level)
Enables exported timelines to be opened in Adobe Premiere, DaVinci Resolve, Final Cut Pro,
and any other NLE supporting the OpenTimelineIO interchange standard.
"""
from __future__ import annotations

import json
from typing import Dict, Any, Optional
from .timeline import Timeline, Segment


def export_to_otio(
    timeline: Timeline,
    media_reference_url: str = "media/interview.mp4",
    fps: float = 30.0,
    project_name: str = "IncuBrix_Timeline",
) -> Dict[str, Any]:
    """
    Export an IncuBrix Timeline to standard OpenTimelineIO JSON format.
    """
    video_clips = []
    audio_clips = []

    for i, seg in enumerate(timeline.segments):
        start_frame = int(round((seg.src_start_us / 1_000_000.0) * fps))
        duration_frames = int(round((seg.edited_duration_us() / 1_000_000.0) * fps))

        time_range = {
            "OTIO_SCHEMA": "TimeRange.1",
            "start_time": {
                "OTIO_SCHEMA": "RationalTime.1",
                "rate": fps,
                "value": start_frame,
            },
            "duration": {
                "OTIO_SCHEMA": "RationalTime.1",
                "rate": fps,
                "value": duration_frames,
            },
        }

        media_ref = {
            "OTIO_SCHEMA": "ExternalReference.1",
            "target_url": media_reference_url,
            "available_range": time_range,
        }

        effects = []
        if seg.speed != 1.0:
            effects.append({
                "OTIO_SCHEMA": "LinearTimeWarp.1",
                "name": f"Speed_{seg.speed}x",
                "time_scalar": seg.speed,
            })

        clip_data = {
            "OTIO_SCHEMA": "Clip.1",
            "name": f"Clip_{i:04d}",
            "source_range": time_range,
            "media_reference": media_ref,
            "effects": effects,
            "metadata": {
                "speed": seg.speed,
                "muted": seg.muted,
                "bleep": seg.bleep,
                "src_start_us": seg.src_start_us,
                "src_end_us": seg.src_end_us,
            },
        }
        video_clips.append(clip_data)

        if not seg.muted:
            audio_clips.append(clip_data)

    otio_doc = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": project_name,
        "metadata": {
            "generator": "IncuBrix Video Editor v0.1.0",
            "timeline_hash": timeline.timeline_hash(),
            "duration_us": timeline.duration_us,
        },
        "global_start_time": {
            "OTIO_SCHEMA": "RationalTime.1",
            "rate": fps,
            "value": 0,
        },
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "Tracks",
            "children": [
                {
                    "OTIO_SCHEMA": "Track.1",
                    "name": "Video Track",
                    "kind": "Video",
                    "children": video_clips,
                },
                {
                    "OTIO_SCHEMA": "Track.1",
                    "name": "Audio Track",
                    "kind": "Audio",
                    "children": audio_clips,
                },
            ],
        },
    }
    return otio_doc


def save_otio_file(
    timeline: Timeline,
    output_path: str,
    media_reference_url: str = "media/interview.mp4",
    fps: float = 30.0,
) -> str:
    """Save OTIO JSON to a file."""
    doc = export_to_otio(timeline, media_reference_url, fps)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    return output_path
