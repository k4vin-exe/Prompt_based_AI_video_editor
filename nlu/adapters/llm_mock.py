"""
nlu/adapters/llm_mock.py
------------------------
Mock LLM adapter for testing.  No API keys required.

Behaviour:
  1. Check the cassette directory for a file keyed by sha256(system+user prompt).
     If found, return the cached response.
  2. Otherwise use a rule-based fallback that handles the most common intents.
     This ensures tests are fully deterministic even without cassettes.

Cassette file format: plain text file containing the JSON response.
Key: sha256(system_prompt + "|||" + user_prompt)[:16].txt
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Optional

from .llm_base import LLMAdapter

_DEFAULT_CASSETTE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "tests", "fixtures", "llm_cassettes"
)


class MockLLMAdapter(LLMAdapter):
    """
    Mock LLM that reads cassettes or applies a deterministic rule-based parser.
    """

    def __init__(self, cassette_dir: Optional[str] = None) -> None:
        self._cassette_dir = cassette_dir or os.environ.get(
            "LLM_CASSETTE_DIR", _DEFAULT_CASSETTE_DIR
        )
        os.makedirs(self._cassette_dir, exist_ok=True)

    @property
    def name(self) -> str:
        return "mock_llm"

    @property
    def version(self) -> str:
        return "0.1.0"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        # Check cassette cache first
        key = self._cassette_key(system_prompt, user_prompt)
        cassette_path = os.path.join(self._cassette_dir, f"{key}.txt")
        if os.path.exists(cassette_path):
            with open(cassette_path, "r", encoding="utf-8") as f:
                return f.read()

        # Rule-based fallback
        response = _rule_based_intent(user_prompt)
        # Save as cassette for future runs (determinism)
        with open(cassette_path, "w", encoding="utf-8") as f:
            f.write(response)
        return response

    def record_cassette(
        self, system_prompt: str, user_prompt: str, response: str
    ) -> str:
        """
        Manually record a cassette response.
        Returns the cassette key.
        """
        key = self._cassette_key(system_prompt, user_prompt)
        cassette_path = os.path.join(self._cassette_dir, f"{key}.txt")
        with open(cassette_path, "w", encoding="utf-8") as f:
            f.write(response)
        return key

    def _cassette_key(self, system_prompt: str, user_prompt: str) -> str:
        combined = system_prompt + "|||" + user_prompt
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:24]


# ── Rule-based intent parser fallback ────────────────────────────────────────

def _rule_based_intent(text: str) -> str:
    """
    Simple deterministic parser for common intents.
    Returns a JSON string matching the intent schema.

    This handles the most common patterns so unit tests work without cassettes.
    The NLU layer's real rule-based parser (nlu/rules.py) is more complete;
    this is just a last resort for the mock.
    """
    t = text.lower().strip()

    # Cut: "cut from X to Y" / "remove from X to Y"
    if re.search(r"\b(cut|remove|delete)\b", t):
        if re.search(r"\bfiller\b|\bum\b|\buh\b", t):
            return json.dumps({"intent": "remove_fillers", "params": {}})
        if re.search(r"\bsilence\b", t):
            return json.dumps({"intent": "remove_silences", "params": {"threshold_s": 1.0}})
        return json.dumps({"intent": "cut", "params": {"start": None, "end": None}})

    # Caption
    if re.search(r"\bcaption\b|\btext\b|\bsubtitle\b", t):
        if re.search(r"\bauto\b", t):
            return json.dumps({"intent": "auto_caption", "params": {}})
        return json.dumps({"intent": "add_caption", "params": {"text": "", "anchor": None}})

    # Speed
    if re.search(r"\bspeed\b|\bfaster\b|\bslower\b", t):
        return json.dumps({"intent": "speed", "params": {"factor": 1.5, "start": None, "end": None}})

    # Undo / redo
    if re.search(r"\bundo\b", t):
        return json.dumps({"intent": "undo", "params": {}})
    if re.search(r"\bredo\b", t):
        return json.dumps({"intent": "redo", "params": {}})

    # Render
    if re.search(r"\brender\b", t):
        return json.dumps({"intent": "render", "params": {}})

    # Music
    if re.search(r"\bmusic\b|\bbackground\b", t):
        return json.dumps({"intent": "add_music", "params": {"url": ""}})

    # Mute / bleep
    if re.search(r"\bbleep\b", t):
        return json.dumps({"intent": "bleep", "params": {"anchor": None}})
    if re.search(r"\bmute\b", t):
        return json.dumps({"intent": "mute", "params": {"anchor": None}})

    # Unknown
    return json.dumps({"intent": "unknown", "params": {}})
