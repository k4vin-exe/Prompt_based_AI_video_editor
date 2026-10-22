"""
tests/unit/test_engine_transcript.py
-------------------------------------
Unit tests for engine.transcript — immutable data structures.
"""
import pytest
from engine.transcript import Word, Transcript, build_transcript, _word_id


class TestWordId:
    def test_format(self):
        assert _word_id(0) == "w0000"
        assert _word_id(1) == "w0001"
        assert _word_id(9999) == "w9999"
        assert _word_id(10000) == "w10000"  # extends beyond 4 digits

    def test_stable(self):
        """Word IDs must be deterministic."""
        assert _word_id(42) == _word_id(42)


class TestWord:
    def test_frozen(self):
        w = Word(id="w0000", index=0, text="hello", start_us=0, end_us=500_000)
        with pytest.raises((AttributeError, TypeError, Exception)):
            w.text = "world"  # type: ignore

    def test_duration(self):
        w = Word(id="w0000", index=0, text="hi", start_us=1_000_000, end_us=1_500_000)
        assert w.duration_us() == 500_000

    def test_roundtrip(self):
        w = Word(id="w0003", index=3, text="hello", start_us=1000, end_us=2000,
                 speaker="speaker_0", confidence=0.95)
        assert Word.from_dict(w.to_dict()) == w


class TestBuildTranscript:
    def _raw(self):
        return [
            {"text": "hello", "start_us": 0, "end_us": 500_000, "confidence": 0.99},
            {"text": "world", "start_us": 600_000, "end_us": 1_100_000, "confidence": 0.98},
            {"text": "bye",   "start_us": 2_000_000, "end_us": 2_500_000, "confidence": 0.95},
        ]

    def test_word_ids_sequential(self):
        t = build_transcript(self._raw(), source_id="test", duration_us=3_000_000)
        assert t.words[0].id == "w0000"
        assert t.words[1].id == "w0001"
        assert t.words[2].id == "w0002"

    def test_immutable_after_build(self):
        t = build_transcript(self._raw(), source_id="test", duration_us=3_000_000)
        with pytest.raises((AttributeError, TypeError)):
            t.words = ()  # type: ignore

    def test_word_by_id(self):
        t = build_transcript(self._raw(), source_id="test", duration_us=3_000_000)
        w = t.word_by_id("w0001")
        assert w is not None
        assert w.text == "world"

    def test_word_by_id_missing(self):
        t = build_transcript(self._raw(), source_id="test", duration_us=3_000_000)
        assert t.word_by_id("w9999") is None

    def test_words_in_source_range(self):
        t = build_transcript(self._raw(), source_id="test", duration_us=3_000_000)
        # Range that covers hello and world but not bye
        words = t.words_in_source_range(0, 1_200_000)
        assert len(words) == 2
        assert words[0].text == "hello"
        assert words[1].text == "world"

    def test_words_in_source_range_exact_boundary(self):
        t = build_transcript(self._raw(), source_id="test", duration_us=3_000_000)
        # Boundary at exactly word start — should include
        words = t.words_in_source_range(600_000, 1_200_000)
        assert any(w.text == "world" for w in words)

    def test_gap_before_word(self):
        t = build_transcript(self._raw(), source_id="test", duration_us=3_000_000)
        assert t.gap_before_word(0) == 0
        assert t.gap_before_word(1) == 100_000   # 600000 - 500000

    def test_gap_after_word(self):
        t = build_transcript(self._raw(), source_id="test", duration_us=3_000_000)
        assert t.gap_after_word(0) == 100_000
        assert t.gap_after_word(2) == 0  # last word

    def test_roundtrip_json(self):
        t = build_transcript(self._raw(), source_id="test-42", duration_us=3_000_000, language="en")
        t2 = Transcript.from_json(t.to_json())
        assert t2.source_id == t.source_id
        assert t2.duration_us == t.duration_us
        assert len(t2.words) == len(t.words)
        assert t2.words[0].id == "w0000"
