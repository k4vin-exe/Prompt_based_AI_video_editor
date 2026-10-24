"""
tests/unit/test_nlu_adapters.py
-------------------------------
Unit tests for STT and LLM adapters, adapter factory, and CachingLLMAdapter.
"""
import os
import json
import tempfile
import pytest

from nlu.adapters import make_llm_adapter, make_stt_adapter, CachingLLMAdapter
from nlu.adapters.llm_mock import MockLLMAdapter
from nlu.adapters.llm_groq import GroqLLMAdapter
from nlu.adapters.llm_gemini import GeminiLLMAdapter
from nlu.adapters.llm_ollama import OllamaLLMAdapter
from nlu.adapters.llm_hf import HuggingFaceLLMAdapter
from nlu.adapters.stt_mock import MockSTTAdapter
from nlu.adapters.stt_whisper import WhisperSTTAdapter
from nlu.adapters.llm_base import LLMAdapter


class DummyInnerLLM(LLMAdapter):
    def __init__(self, response: str = '{"intent": "cut", "params": {}}'):
        self.response = response
        self.calls = 0

    @property
    def name(self) -> str:
        return "dummy_llm"

    @property
    def version(self) -> str:
        return "1.0.0"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        return self.response


def test_make_llm_adapter_factory():
    """Verify make_llm_adapter returns expected adapter types."""
    mock_adapter = make_llm_adapter("mock")
    assert isinstance(mock_adapter, MockLLMAdapter)
    assert mock_adapter.name == "mock_llm"
    assert mock_adapter.cost_per_1k_tokens_usd == 0.0

    groq_adapter = make_llm_adapter("groq", cache_mode="live")
    assert isinstance(groq_adapter, GroqLLMAdapter)
    assert groq_adapter.name == "groq"

    gemini_adapter = make_llm_adapter("gemini", cache_mode="live")
    assert isinstance(gemini_adapter, GeminiLLMAdapter)
    assert gemini_adapter.name == "gemini"

    hf_adapter = make_llm_adapter("huggingface", cache_mode="live")
    assert isinstance(hf_adapter, HuggingFaceLLMAdapter)
    assert hf_adapter.name == "huggingface"

    ollama_adapter = make_llm_adapter("ollama", cache_mode="live")
    assert isinstance(ollama_adapter, OllamaLLMAdapter)
    assert ollama_adapter.name == "ollama"

    # Default fallback on unknown name is mock
    unknown_adapter = make_llm_adapter("unknown_provider")
    assert isinstance(unknown_adapter, MockLLMAdapter)


def test_make_stt_adapter_factory():
    """Verify make_stt_adapter returns expected STT adapter types."""
    mock_stt = make_stt_adapter("mock")
    assert isinstance(mock_stt, MockSTTAdapter)
    assert mock_stt.name == "mock_stt"

    whisper_stt = make_stt_adapter("whisper")
    assert isinstance(whisper_stt, WhisperSTTAdapter)
    assert whisper_stt.name == "faster_whisper"

    default_stt = make_stt_adapter("nonexistent")
    assert isinstance(default_stt, MockSTTAdapter)


def test_caching_llm_adapter_record_and_replay():
    """Verify CachingLLMAdapter records responses and replays from cache."""
    with tempfile.TemporaryDirectory() as tmpdir:
        inner = DummyInnerLLM(response='{"intent": "remove_fillers", "params": {}}')
        caching = CachingLLMAdapter(inner, mode="record", cache_dir=tmpdir)

        # First call: cache miss -> calls inner
        res1 = caching.complete("sys", "clean up the ums")
        assert res1 == '{"intent": "remove_fillers", "params": {}}'
        assert inner.calls == 1

        # Second call: cache hit -> returns from disk without calling inner
        res2 = caching.complete("sys", "clean up the ums")
        assert res2 == '{"intent": "remove_fillers", "params": {}}'
        assert inner.calls == 1  # Still 1!

        # Replay mode with hit
        replay = CachingLLMAdapter(inner, mode="replay", cache_dir=tmpdir)
        res3 = replay.complete("sys", "clean up the ums")
        assert res3 == '{"intent": "remove_fillers", "params": {}}'
        assert inner.calls == 1

        # Replay mode with miss -> raises RuntimeError
        with pytest.raises(RuntimeError, match="LLM cache miss in replay mode"):
            replay.complete("sys", "unseen prompt")


def test_mock_llm_adapter_cassettes():
    """Verify MockLLMAdapter records and replays cassettes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = MockLLMAdapter(cassette_dir=tmpdir)
        resp = adapter.complete("sys", "Undo")
        data = json.loads(resp)
        assert data["intent"] == "undo"

        # Verify file was written to tmpdir
        files = os.listdir(tmpdir)
        assert len(files) == 1
        with open(os.path.join(tmpdir, files[0]), "r", encoding="utf-8") as f:
            saved = json.load(f)
            assert saved["intent"] == "undo"
