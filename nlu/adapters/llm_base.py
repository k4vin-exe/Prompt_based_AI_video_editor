"""
nlu/adapters/llm_base.py
------------------------
Abstract base class for LLM adapters used in NLU intent parsing.

The LLM's ONLY job is to translate a natural-language instruction into
a schema-validated intent JSON.  All timeline logic is deterministic code.
(R-HIST-03, Brief §Must-have 4)

The adapter is selected by the LLM_ADAPTER environment variable.
The mock adapter reads from cassette files keyed by sha256(prompt).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class LLMAdapter(ABC):
    """Interface for LLM adapters."""

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """
        Send a prompt to the LLM and return the raw response string.
        Should be JSON (the intent schema).
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable adapter name for manifests."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Model version string for manifests."""
        ...

    @property
    def cost_per_1k_tokens_usd(self) -> float:
        """Estimated cost in USD per 1000 tokens (input+output). 0.0 for free/local."""
        return 0.0
