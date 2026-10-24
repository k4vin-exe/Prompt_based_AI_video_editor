"""
tests/unit/test_nlu_grounding.py
--------------------------------
Unit tests for NLU grounding resolver and context pack generator.
"""
import pytest
from engine.transcript import build_transcript
from engine.session import Session
from nlu.grounding import resolve_phrase, resolve_topic, resolve_speaker, resolve_chapter
from nlu.context import build_context_pack


@pytest.fixture
def sample_transcript():
    words = [
        {"text": "welcome", "start_us": 1_000_000, "end_us": 1_500_000, "speaker": "host"},
        {"text": "to", "start_us": 1_600_000, "end_us": 1_800_000, "speaker": "host"},
        {"text": "the", "start_us": 1_900_000, "end_us": 2_100_000, "speaker": "host"},
        {"text": "channel", "start_us": 2_200_000, "end_us": 2_800_000, "speaker": "host"},
        {"text": "today", "start_us": 3_000_000, "end_us": 3_500_000, "speaker": "guest"},
        {"text": "we", "start_us": 3_600_000, "end_us": 3_800_000, "speaker": "guest"},
        {"text": "discuss", "start_us": 3_900_000, "end_us": 4_300_000, "speaker": "guest"},
        {"text": "pricing", "start_us": 4_400_000, "end_us": 5_000_000, "speaker": "guest"},
    ]
    return build_transcript(words, source_id="src_test", duration_us=10_000_000)


def test_resolve_phrase(sample_transcript):
    """Verify resolve_phrase locates exact multi-word spans."""
    spans = resolve_phrase(sample_transcript, "welcome to the channel")
    assert len(spans) == 1
    span = spans[0]
    assert span.word_start.id == "w0000"
    assert span.word_end.id == "w0003"
    assert span.src_start_us == 1_000_000
    assert span.src_end_us == 2_800_000

    # Non-existent phrase returns empty list
    none_spans = resolve_phrase(sample_transcript, "nonexistent sentence")
    assert len(none_spans) == 0


def test_resolve_topic(sample_transcript):
    """Verify resolve_topic finds topic occurrences in transcript."""
    spans = resolve_topic(sample_transcript, "pricing")
    assert len(spans) >= 1
    assert any("pricing" in s.phrase_text.lower() for s in spans)


def test_resolve_speaker(sample_transcript):
    """Verify resolve_speaker maps positional hints and aliases."""
    assert resolve_speaker(sample_transcript, "host") == "host"
    assert resolve_speaker(sample_transcript, "guest") == "guest"
    assert resolve_speaker(sample_transcript, "first") == "host"
    assert resolve_speaker(sample_transcript, "second") == "guest"
    assert resolve_speaker(sample_transcript, "nonexistent") is None


def test_resolve_chapter(sample_transcript):
    """Verify resolve_chapter resolves chapter names and indices."""
    analysis = {
        "chapters": [
            {
                "chapter_id": 0,
                "title": "Introduction",
                "start_word_id": "w0000",
                "end_word_id": "w0003",
                "start_us": 1_000_000,
                "end_us": 2_800_000,
                "keywords": ["welcome", "channel"],
            },
            {
                "chapter_id": 1,
                "title": "Pricing Discussion",
                "start_word_id": "w0004",
                "end_word_id": "w0007",
                "start_us": 3_000_000,
                "end_us": 5_000_000,
                "keywords": ["pricing", "discuss"],
            },
        ]
    }
    span0 = resolve_chapter(sample_transcript, "intro", analysis)
    assert span0 == ("w0000", "w0003")

    span1 = resolve_chapter(sample_transcript, "pricing", analysis)
    assert span1 == ("w0004", "w0007")

    span_idx = resolve_chapter(sample_transcript, "chapter 2", analysis)
    assert span_idx == ("w0004", "w0007")


def test_build_context_pack(sample_transcript):
    """Verify build_context_pack returns compact session context."""
    session = Session(sample_transcript)
    pack = build_context_pack(session)

    assert "SOURCE_DURATION: 10.0s" in pack
    assert "CURRENT_DURATION: 10.0s" in pack
    assert "SPEAKERS: host, guest" in pack
