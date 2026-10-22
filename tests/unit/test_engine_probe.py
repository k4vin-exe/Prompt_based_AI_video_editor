"""
tests/unit/test_engine_probe.py
-------------------------------
Unit tests for engine.probe: video intake, metadata parsing, and VFR detection.
"""
import pytest
from engine.probe import probe_video, VideoMetadata
from engine.render import round_to_frame


def test_probe_sync_oracle_video():
    meta = probe_video("tests/fixtures/sync_oracle_test.mp4")
    assert isinstance(meta, VideoMetadata)
    assert meta.duration_s == pytest.approx(5.0, 0.1)
    assert meta.fps == pytest.approx(30.0, 0.1)
    assert meta.width == 320
    assert meta.height == 240
    assert meta.has_audio is True
    assert meta.audio_sample_rate == 44100
    assert meta.is_vfr is False


def test_probe_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        probe_video("nonexistent_video.mp4")


def test_round_to_frame():
    fps = 30.0
    # 0.0333s = 1 frame
    assert round_to_frame(0.033, fps) == pytest.approx(1 / 30.0)
    # 0.01s rounds down to 0 frames
    assert round_to_frame(0.01, fps) == pytest.approx(0.0)
    # 1.0s stays 1.0s
    assert round_to_frame(1.0, fps) == pytest.approx(1.0)
