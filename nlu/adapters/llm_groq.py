"""
nlu/adapters/llm_groq.py
------------------------
Groq LLM adapter (free tier — very fast inference).

Env vars:
  GROQ_API_KEY    : Groq API key (required for live mode)
  GROQ_LLM_MODEL  : model name (default "llama-3.1-8b-instant")

Groq free tier: 30 RPM, 30k TPD — enough for all test sessions.
Licence: groq SDK is Apache 2.0. Llama-3.1 is Meta Llama Community License (commercial OK).
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .llm_base import LLMAdapter


class GroqLLMAdapter(LLMAdapter):
    """Groq-hosted LLM adapter for intent parsing."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._api_key = (api_key or os.environ.get("GROQ_API_KEY", "")).strip()
        self._model_name = (
            model
            or os.environ.get("LLM_GROQ_MODEL")
            or os.environ.get("GROQ_LLM_MODEL")
            or "llama-3.1-8b-instant"
        ).strip()
        self._client = None

    @property
    def name(self) -> str:
        return "groq"

    @property
    def version(self) -> str:
        return self._model_name

    @property
    def cost_per_1k_tokens_usd(self) -> float:
        return 0.0  # free tier

    def _get_client(self):
        if self._client is None:
            from groq import Groq  # type: ignore
            self._client = Groq(api_key=self._api_key)
        return self._client

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self._model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,   # Deterministic
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()
