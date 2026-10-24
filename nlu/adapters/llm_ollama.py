"""
nlu/adapters/llm_ollama.py
--------------------------
Ollama LLM adapter (fully local, free).

Env vars:
  OLLAMA_BASE_URL  : base URL (default "http://localhost:11434")
  OLLAMA_MODEL     : model name (default "llama3.2")

Ollama is MIT-licensed. Model licences vary; llama3.2 is Meta Llama Community (commercial OK).
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .llm_base import LLMAdapter


class OllamaLLMAdapter(LLMAdapter):
    """Ollama local LLM adapter for intent parsing."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self._model_name = model or os.environ.get("OLLAMA_MODEL", "llama3.2")

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def version(self) -> str:
        return self._model_name

    @property
    def cost_per_1k_tokens_usd(self) -> float:
        return 0.0  # local

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        import httpx  # type: ignore

        payload = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": 0},
        }
        resp = httpx.post(
            f"{self._base_url}/api/chat",
            json=payload,
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"].strip()
