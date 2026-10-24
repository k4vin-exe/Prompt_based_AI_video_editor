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
    if "INSTRUCTION:" in text:
        text = text.split("INSTRUCTION:")[-1].strip()

    try:
        from nlu.parser import _rule_parse_single
        parsed = _rule_parse_single(text)
        if parsed.get("intent") != "unknown":
            return json.dumps(parsed)
    except Exception:
        pass

    t = text.lower().strip()

    # Undo / redo / render
    if re.fullmatch(r"undo", t):
        return json.dumps({"intent": "undo", "params": {}})
    if re.fullmatch(r"redo", t):
        return json.dumps({"intent": "redo", "params": {}})
    if re.search(r"\brender\b", t):
        return json.dumps({"intent": "render", "params": {}})

    # Restore / bring back / put back (check early before cut)
    if re.search(r"\b(restore|bring\s+back|put\s+back)\b|put\s+.+\s+back", t):
        return json.dumps({"intent": "restore_edit", "params": {"description": text, "which": text}})

    # Remove fillers (check before generic cut)
    if re.search(r"\b(filler|fillers|um|ums|uh|uhs)\b|clean\s+up", t):
        return json.dumps({"intent": "remove_fillers", "params": {}})

    # Remove silences (check before generic cut)
    if re.search(r"\b(silence|silences|pause|pauses|gap|gaps)\b", t):
        thresh = 1.0
        m = re.search(r"(\d+(?:\.\d+)?)\s*s", t)
        if m:
            thresh = float(m.group(1))
        return json.dumps({"intent": "remove_silences", "params": {"threshold_s": thresh}})

    # Bleep / censor / mute (MUST be before caption because of "over the word")
    if re.search(r"\b(bleep|beep|censor)\b|replace.+bleep", t):
        return json.dumps({"intent": "bleep", "params": {"anchor": None}})
    if re.search(r"\bmute\b", t):
        return json.dumps({"intent": "mute", "params": {"anchor": None}})

    # Restyle caption (MUST be before add_caption)
    if re.search(r"\b(make|change|turn)\b.+\bcaption\b|\bcaption\b.+\b(red|blue|green|yellow|white|black|color|bigger|smaller|font)\b", t):
        color_m = re.search(r"\b(red|blue|green|yellow|white|black|orange|purple|pink)\b", t)
        style = {"color": color_m.group(1)} if color_m else {}
        return json.dumps({"intent": "restyle_caption", "params": {"target": "that caption", "style": style}})

    # Speed
    if re.search(r"\b(speed|faster|slower|twice\s+as\s+fast|double\s+the\s+speed|accelerate|play.+at.+x)\b", t):
        factor = 2.0 if re.search(r"\b(twice|2x|double)\b", t) else 1.5
        if re.search(r"\bslow\b", t):
            factor = 0.5
        return json.dumps({"intent": "speed", "params": {"factor": factor, "start": None, "end": None}})

    # Topic-based removal (check before generic cut)
    if re.search(r"\b(cut|remove|delete|trim|get\s+rid\s+of|take\s+out)\b", t):
        topic_m = re.search(r"(?:part\s+about|section\s+about|bit\s+about|bit\s+where.+about|everything\s+about)\s+(\w+)", t)
        if not topic_m:
            topic_m = re.search(r"(\w+)\s+(?:section|discussion|topic|part|segment)", t)
        if topic_m:
            cand = topic_m.group(1)
            if cand not in ("first", "beginning", "next", "last", "end", "whole"):
                return json.dumps({"intent": "remove_topic", "params": {"topic": cand, "occurrence": None}})

    # Remove topic: "take out everything about X"
    if re.search(r"everything\s+about", t):
        topic_m = re.search(r"about\s+(\w+)", t)
        topic = topic_m.group(1) if topic_m else "unknown"
        return json.dumps({"intent": "remove_topic", "params": {"topic": topic, "occurrence": None}})

    # Keep
    if re.search(r"\bkeep\b", t):
        return json.dumps({"intent": "keep", "params": {"start": None, "end": None}})

    # Cut: cut / remove / delete / trim / get rid of / take out
    if re.search(r"\b(cut|remove|delete|trim|get\s+rid\s+of|take\s+out)\b", t):
        return json.dumps({"intent": "cut", "params": {"start": None, "end": None}})

    # Caption: add / put / show / display / overlay
    if re.search(r"\b(caption|subtitle|text|overlay)\b", t):
        if re.search(r"\bauto\b", t):
            return json.dumps({"intent": "auto_caption", "params": {}})
        return json.dumps({"intent": "add_caption", "params": {"text": "", "anchor": None}})
    if re.search(r"\b(put|show|display|overlay|add)\b.+\b(?:text|words?|['\"].+['\"])", t) or re.search(r"\bin\b.+\badd\b.+['\"].+['\"]", t):
        return json.dumps({"intent": "add_caption", "params": {"text": "", "anchor": None}})
    if re.search(r"\b(when\s+i\s+say|over\s+the\s+words?|over\s+the\s+phrase)", t):
        return json.dumps({"intent": "add_caption", "params": {"text": "", "anchor": None}})

    # Music
    if re.search(r"\bmusic\b|\bbackground\b", t):
        return json.dumps({"intent": "add_music", "params": {"url": ""}})

    # Unknown
    return json.dumps({"intent": "unknown", "params": {}})

