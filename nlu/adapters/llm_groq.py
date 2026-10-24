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
        default_model = "qwen/qwen3.8-27b"
        configured = (
            model
            or os.environ.get("LLM_GROQ_MODEL")
            or os.environ.get("GROQ_LLM_MODEL")
            or default_model
        ).strip()
        # If the deprecated llama-3.1-8b-instant was requested, use active qwen model
        if configured == "llama-3.1-8b-instant":
            configured = default_model
        self._model_name = configured
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
        candidates = [self._model_name, "qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]
        # Remove duplicates while preserving order
        candidate_models = list(dict.fromkeys(candidates))

        last_err = None
        for cand in candidate_models:
            try:
                response = client.chat.completions.create(
                    model=cand,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.0,   # Deterministic
                    max_tokens=512,
                )
                self._model_name = cand
                return response.choices[0].message.content.strip()
            except Exception as e:
                last_err = e
                # If error is model not found or invalid model, try next candidate
                if "model" in str(e).lower() or "not_found" in str(e).lower() or "404" in str(e):
                    continue
                raise e

        if last_err:
            raise last_err
        raise RuntimeError("No working Groq model found.")
