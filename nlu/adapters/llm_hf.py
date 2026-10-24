"""
nlu/adapters/llm_hf.py
----------------------
Hugging Face Serverless Inference API adapter (free tier).

Env vars:
  HF_TOKEN / HUGGINGFACE_API_KEY : Hugging Face user access token (free tier)
  HF_MODEL / LLM_HF_MODEL       : Model name (default: "Qwen/Qwen2.5-72B-Instruct")

Hugging Face Serverless Inference free tier provides open-source models with OpenAI-compatible chat endpoints.
"""
from __future__ import annotations

import json
import os
from typing import Optional
import httpx

from .llm_base import LLMAdapter


class HuggingFaceLLMAdapter(LLMAdapter):
    """Hugging Face Serverless Inference API adapter for natural language intent parsing."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._api_key = (
            api_key
            or os.environ.get("HF_TOKEN", "")
            or os.environ.get("HUGGINGFACE_API_KEY", "")
            or os.environ.get("HF_API_KEY", "")
        ).strip()
        default_model = "Qwen/Qwen2.5-72B-Instruct"
        self._model_name = (
            model
            or os.environ.get("HF_MODEL")
            or os.environ.get("LLM_HF_MODEL")
            or default_model
        ).strip()

    @property
    def name(self) -> str:
        return "huggingface"

    @property
    def version(self) -> str:
        return self._model_name

    @property
    def cost_per_1k_tokens_usd(self) -> float:
        return 0.0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        candidate_models = [
            self._model_name,
            "Qwen/Qwen2.5-72B-Instruct",
            "meta-llama/Llama-3.2-3B-Instruct",
            "mistralai/Mistral-7B-Instruct-v0.3",
        ]
        # De-duplicate
        candidate_models = list(dict.fromkeys(candidate_models))

        urls = [
            "https://router.huggingface.co/hf-inference/v1/chat/completions",
            "https://api-inference.huggingface.co/v1/chat/completions",
        ]

        last_err = None
        for model_cand in candidate_models:
            payload = {
                "model": model_cand,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.0,
                "max_tokens": 512,
            }
            for url in urls:
                try:
                    with httpx.Client(timeout=25.0) as client:
                        resp = client.post(url, headers=headers, json=payload)
                        if resp.status_code == 200:
                            data = resp.json()
                            self._model_name = model_cand
                            return data["choices"][0]["message"]["content"].strip()
                        last_err = RuntimeError(f"Hugging Face API ({model_cand}) returned HTTP {resp.status_code}: {resp.text}")
                except Exception as e:
                    last_err = e
                    continue

        if last_err:
            raise last_err
        raise RuntimeError("Failed to query Hugging Face Inference API.")
