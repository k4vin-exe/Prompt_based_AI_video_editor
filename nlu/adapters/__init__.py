"""
nlu/adapters/__init__.py
------------------------
Adapter factories for LLM and STT.

LLM_ADAPTER env var:
  "mock"   — MockLLMAdapter (default, no API key required)
  "groq"   — GroqLLMAdapter
  "gemini" — GeminiLLMAdapter
  "ollama" — OllamaLLMAdapter

STT_ADAPTER env var:
  "mock"   — MockSTTAdapter (default)
  "whisper"— WhisperSTTAdapter (faster-whisper)
  "groq"   — GroqSTTAdapter (if available)

LLM_CACHE_MODE env var:
  "live"   — always call real LLM, no caching
  "record" — call real LLM and save response to cache file
  "replay" — load from cache file; error if missing
  (default: "record" — caches on first call, replays after)
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

from .llm_base import LLMAdapter
from .stt_base import STTAdapter


# ── LLM Factory ───────────────────────────────────────────────────────────────

def make_llm_adapter(
    adapter_name: Optional[str] = None,
    cache_mode: Optional[str] = None,
    cache_dir: Optional[str] = None,
) -> LLMAdapter:
    """
    Create an LLM adapter selected by adapter_name (or LLM_ADAPTER env var).
    Wraps the adapter with a CachingLLMAdapter unless cache_mode is 'live'.
    """
    env_adapter = os.environ.get("LLM_ADAPTER", "").strip().lower()
    if adapter_name:
        name = adapter_name.lower()
    elif env_adapter and env_adapter != "mock":
        name = env_adapter
    elif os.environ.get("GROQ_API_KEY", "").strip():
        name = "groq"
    elif env_adapter:
        name = env_adapter
    else:
        name = "mock"
    mode = (cache_mode or os.environ.get("LLM_CACHE_MODE", "record")).lower()

    if name == "mock":
        from .llm_mock import MockLLMAdapter
        # Mock already has its own cassette system; wrap is optional
        inner: LLMAdapter = MockLLMAdapter(cassette_dir=cache_dir)
    elif name == "groq":
        if os.environ.get("GROQ_API_KEY", "").strip():
            from .llm_groq import GroqLLMAdapter
            inner = GroqLLMAdapter()
        else:
            from .llm_mock import MockLLMAdapter
            inner = MockLLMAdapter(cassette_dir=cache_dir)
    elif name == "gemini":
        from .llm_gemini import GeminiLLMAdapter
        inner = GeminiLLMAdapter()
    elif name in ("huggingface", "hf"):
        from .llm_hf import HuggingFaceLLMAdapter
        inner = HuggingFaceLLMAdapter()
    elif name == "ollama":
        from .llm_ollama import OllamaLLMAdapter
        inner = OllamaLLMAdapter()
    else:
        # Unknown adapter name → fall back to mock
        from .llm_mock import MockLLMAdapter
        inner = MockLLMAdapter(cassette_dir=cache_dir)

    if name not in ("groq", "gemini", "ollama", "huggingface", "hf") or mode == "live":
        return inner  # Mock already handles its own cache; live mode skips caching

    return CachingLLMAdapter(inner, mode=mode, cache_dir=cache_dir)


# ── STT Factory ───────────────────────────────────────────────────────────────

def make_stt_adapter(adapter_name: Optional[str] = None) -> STTAdapter:
    """Create an STT adapter selected by adapter_name (or STT_ADAPTER env var)."""
    env_stt = os.environ.get("STT_ADAPTER", "").strip().lower()
    if adapter_name:
        name = adapter_name.lower()
    elif env_stt and env_stt != "mock":
        name = env_stt
    elif os.environ.get("GROQ_API_KEY", "").strip():
        name = "groq"
    elif env_stt:
        name = env_stt
    else:
        name = "mock"

    if name == "mock":
        from .stt_mock import MockSTTAdapter
        return MockSTTAdapter()
    elif name == "whisper":
        from .stt_whisper import WhisperSTTAdapter
        return WhisperSTTAdapter()
    elif name == "groq":
        if os.environ.get("GROQ_API_KEY", "").strip():
            try:
                from .stt_groq import GroqSTTAdapter  # type: ignore
                return GroqSTTAdapter()
            except Exception:
                from .stt_mock import MockSTTAdapter
                return MockSTTAdapter()
        else:
            from .stt_mock import MockSTTAdapter
            return MockSTTAdapter()
    else:
        from .stt_mock import MockSTTAdapter
        return MockSTTAdapter()


# ── Caching Wrapper ────────────────────────────────────────────────────────────

_DEFAULT_CACHE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "intent_cache"
)


class CachingLLMAdapter(LLMAdapter):
    """
    Wraps any LLMAdapter with file-based request/response caching.

    Modes:
      "record" (default): call inner adapter if cache miss; save result to file.
      "replay": always load from file; raise RuntimeError on cache miss.
      "live":   never cache (this wrapper is not used in live mode).

    Cache key: sha256(system_prompt + "|||" + user_prompt)[:24]
    Cache file: <cache_dir>/<key>.json  (contains {"response": str})
    """

    def __init__(
        self,
        inner: LLMAdapter,
        mode: str = "record",
        cache_dir: Optional[str] = None,
    ) -> None:
        self._inner = inner
        self._mode = mode
        self._cache_dir = cache_dir or os.environ.get("LLM_CACHE_DIR", _DEFAULT_CACHE_DIR)
        os.makedirs(self._cache_dir, exist_ok=True)

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def version(self) -> str:
        return self._inner.version

    @property
    def cost_per_1k_tokens_usd(self) -> float:
        return self._inner.cost_per_1k_tokens_usd

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        key = self._cache_key(system_prompt, user_prompt)
        cache_path = os.path.join(self._cache_dir, f"{key}.json")

        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data["response"]

        if self._mode == "replay":
            raise RuntimeError(
                f"LLM cache miss in replay mode. Key={key}. "
                f"Run once in 'record' mode to populate the cache."
            )

        # Call the real adapter
        response = self._inner.complete(system_prompt, user_prompt)

        if self._mode == "record":
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"response": response, "adapter": self._inner.name}, f)

        return response

    def _cache_key(self, system_prompt: str, user_prompt: str) -> str:
        combined = system_prompt + "|||" + user_prompt
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:24]
