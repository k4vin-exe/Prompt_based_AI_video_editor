"""
tests/unit/test_engine_otio.py
------------------------------
Unit tests for OpenTimelineIO export (Brief §Outstanding level).
"""
import os
import json
import pytest
from engine.transcript import build_transcript
from engine.timeline import fold
from engine.ops import CutOp, SpeedOp
from engine.otio_export import export_to_otio, save_otio_file


def test_otio_export_structure(tmp_path):
    words = [{"text": "word", "start_us": 0, "end_us": 1_000_000}]
    t = build_transcript(words, source_id="test_otio", duration_us=10_000_000)
    ops = [
        CutOp(op_id=1, group_id=1, start_us=2_000_000, end_us=4_000_000),
        SpeedOp(op_id=2, group_id=2, start_us=4_000_000, end_us=6_000_000, factor=2.0),
    ]
    timeline = fold(t, ops)

    doc = export_to_otio(timeline, media_reference_url="test.mp4", fps=30.0)
    assert doc["OTIO_SCHEMA"] == "Timeline.1"
    assert "tracks" in doc
    tracks = doc["tracks"]["children"]
    assert len(tracks) == 2
    video_track = tracks[0]
    assert video_track["kind"] == "Video"
    assert len(video_track["children"]) == len(timeline.segments)

    # File saving
    out_file = str(tmp_path / "export.otio")
    save_otio_file(timeline, out_file, media_reference_url="test.mp4")
    assert os.path.exists(out_file)

    with open(out_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["OTIO_SCHEMA"] == "Timeline.1"
