"""
tests/unit/test_engine_render.py
--------------------------------
Unit and integration tests for engine.render:
- R-REND-02: Frame-rounding rule
- R-REND-04: Rendered length equals timeline length within 1 frame
- R-SPEED-03: Sped-up caption minimum display duration
- ASS subtitle formatting
- Video rendering execution and duration verification
"""
import os
import pytest
from engine.transcript import build_transcript
from engine.timeline import fold, TimelineCaption
from engine.ops import CutOp, SpeedOp, AddCaptionOp
from engine.render import (
    round_to_frame, generate_ass_subtitles, render_timeline, RenderResult
)


def test_round_to_frame_formula():
    fps = 30.0
    # Exactly half-frame rounds up
    assert round_to_frame(0.5 / fps, fps) == pytest.approx(1.0 / fps)
    # Below half-frame rounds down
    assert round_to_frame(0.4 / fps, fps) == pytest.approx(0.0)


def test_ass_subtitles_minimum_duration(tmp_path):
    ass_path = str(tmp_path / "test.ass")
    # Caption lasting only 0.2s (e.g. after speedup)
    captions = [
        TimelineCaption(
            caption_id=1,
            text="Fast Caption",
            word_id_start="w0000",
            word_id_end="w0000",
            style={"color": "#ff0000"},
            hidden=False,
            edited_start_us=1_000_000,
            edited_end_us=1_200_000,  # 0.2s
        )
    ]
    generate_ass_subtitles(captions, fps=30.0, output_path=ass_path)
    with open(ass_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Fast Caption" in content
    # R-SPEED-03: Display duration must be extended to at least 0.7s: 1.00s to 1.70s
    assert "0:00:01.00" in content
    assert "0:00:01.70" in content


def test_render_timeline_duration_within_one_frame(tmp_path):
    words = [
        {"text": "hello", "start_us": 500_000, "end_us": 900_000},
        {"text": "world", "start_us": 1_000_000, "end_us": 1_500_000},
    ]
    t = build_transcript(words, source_id="sync_oracle", duration_us=5_000_000)
    # Cut 1.0s to 2.0s -> target duration is 4.0s
    ops = [CutOp(op_id=1, group_id=1, start_us=1_000_000, end_us=2_000_000)]
    timeline = fold(t, ops)

    out_mp4 = str(tmp_path / "rendered.mp4")
    res = render_timeline(timeline, "tests/fixtures/sync_oracle_test.mp4", out_mp4)

    assert isinstance(res, RenderResult)
    assert os.path.exists(out_mp4)
    assert res.target_duration_s == 4.0
    # Must match within 1 frame (R-REND-04)
    assert res.duration_diff_frames <= 1.0
