"""
tests/unit/test_perception.py
-----------------------------
Unit tests for the Perception pipeline: VAD, speaker diarization, topic segmentation,
and end-to-end analysis.json generation and caching.
"""
import os
import json
import tempfile
import pytest

from perception.pipeline import analyse, load_analysis, analysis_to_transcript
from perception.diarize import assign_speakers
from perception.topics import segment_topics
from nlu.adapters.stt_mock import MockSTTAdapter


def test_assign_speakers_heuristic():
    """Verify fallback heuristic assigns speaker IDs based on pauses/turns."""
    words = [
        {"text": "Hello", "start_us": 0, "end_us": 500_000},
        {"text": "world", "start_us": 600_000, "end_us": 1_000_000},
        # 2-second pause -> speaker turn
        {"text": "Hi", "start_us": 3_000_000, "end_us": 3_500_000},
        {"text": "there", "start_us": 3_600_000, "end_us": 4_000_000},
    ]
    res = assign_speakers(words, audio_path="dummy.wav")
    assert len(res) == 4
    assert res[0]["speaker"] == "speaker_0"
    assert res[1]["speaker"] == "speaker_0"
    assert res[2]["speaker"] == "speaker_1"
    assert res[3]["speaker"] == "speaker_1"


def test_segment_topics():
    """Verify segment_topics segments word lists into Chapter objects."""
    words = [
        {"id": f"w{i:04d}", "text": f"word{i}", "start_us": i * 500_000, "end_us": (i + 1) * 500_000}
        for i in range(40)
    ]
    chapters = segment_topics(words, min_chapter_words=10)
    assert len(chapters) >= 1
    assert chapters[0].start_word_id == "w0000"
    assert chapters[0].start_us == 0
    assert chapters[-1].end_word_id == "w0039"


def test_perception_pipeline_analyse_and_cache():
    """Verify end-to-end perception pipeline generates and caches analysis.json."""
    video_path = "tests/fixtures/sync_oracle_test.mp4"
    stt = MockSTTAdapter()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Run 1: initial analysis
        res1 = analyse(video_path, stt_adapter=stt, cache_dir=tmpdir)

        assert "source_id" in res1
        assert "source_hash" in res1
        assert "transcript" in res1
        assert "model_manifest" in res1
        assert "silences" in res1
        assert "speakers" in res1
        assert "chapters" in res1

        # Check analysis file on disk
        analysis_file = os.path.join(tmpdir, "sync_oracle_test_analysis.json")
        assert os.path.exists(analysis_file)

        # Load cached directly
        loaded = load_analysis(video_path, cache_dir=tmpdir)
        assert loaded is not None
        assert loaded["source_hash"] == res1["source_hash"]

        # Run 2: cached read
        res2 = analyse(video_path, stt_adapter=stt, cache_dir=tmpdir)
        assert res2["source_hash"] == res1["source_hash"]
        assert res2["created_at"] == res1["created_at"]

        # Reconstruct transcript
        transcript = analysis_to_transcript(res1)
        assert transcript.source_id == res1["source_id"]
        assert len(transcript.words) == len(res1["transcript"]["words"])
