"""
nlu/adapters/llm_gemini.py
--------------------------
Google Gemini LLM adapter (free tier via google-generativeai).

Env vars:
  GEMINI_API_KEY   : Google AI Studio API key (required)
  GEMINI_MODEL     : model name (default "gemini-1.5-flash")

The free tier of gemini-1.5-flash provides 15 RPM and 1M TPM at no cost.
Licence: google-generativeai is Apache 2.0.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .llm_base import LLMAdapter


class GeminiLLMAdapter(LLMAdapter):
    """Gemini LLM adapter for intent parsing."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._model_name = model or os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
        self._client = None

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def version(self) -> str:
        return self._model_name

    @property
    def cost_per_1k_tokens_usd(self) -> float:
        # gemini-1.5-flash free tier
        return 0.0

    def _get_client(self):
        if self._client is None:
            import google.generativeai as genai  # type: ignore
            genai.configure(api_key=self._api_key)
            self._client = genai.GenerativeModel(self._model_name)
        return self._client

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        client = self._get_client()
        # Gemini takes a combined prompt; we prepend system as instructions
        combined = f"{system_prompt}\n\n---\n{user_prompt}"
        response = client.generate_content(combined)
        return response.text.strip()
