"""
tests/conftest.py
-----------------
Shared pytest fixtures for all test modules.
"""
import json
import os
import sys
import pytest

# Add project root to path so `engine`, `nlu`, etc. are importable without install
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def simple_transcript():
    """
    A 10-word, 10-second transcript for unit tests.
    Words: alpha beta gamma delta epsilon zeta eta theta iota kappa
    Each word: 900ms duration, 100ms gap.
    """
    from engine.transcript import build_transcript
    raw = []
    words = ["alpha", "beta", "gamma", "delta", "epsilon",
             "zeta", "eta", "theta", "iota", "kappa"]
    t = 0
    word_dur_us = 900_000
    gap_us = 100_000
    for i, w in enumerate(words):
        raw.append({
            "text": w,
            "start_us": t,
            "end_us": t + word_dur_us,
            "speaker": "speaker_0",
            "confidence": 0.99,
        })
        t += word_dur_us + gap_us
    return build_transcript(raw, source_id="simple_test", duration_us=10_000_000)


@pytest.fixture
def interview_transcript():
    """
    Load the interview_300s fixture (5-min video used in worked example).
    """
    from engine.transcript import Transcript
    fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "transcripts", "interview_300s.json"
    )
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    from engine.transcript import build_transcript
    return build_transcript(
        data["words"],
        source_id="interview_300s",
        duration_us=data["duration_us"],
        language=data.get("language"),
    )


@pytest.fixture
def empty_history():
    from engine.history import History
    return History()


@pytest.fixture
def mock_stt():
    from nlu.adapters.stt_mock import MockSTTAdapter
    return MockSTTAdapter()


@pytest.fixture
def mock_llm():
    from nlu.adapters.llm_mock import MockLLMAdapter
    return MockLLMAdapter()
