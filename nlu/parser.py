"""
nlu/parser.py
-------------
Deterministic Natural Language Understanding (NLU) instruction parser.
Translates plain English editing instructions into structured intent dicts
conforming to INTENT_SCHEMA.

Enforces:
- Brief §Must-have 4: "All timeline logic is ordinary code you wrote. An AI model may
  only translate words into structured operations."
- Time policy: defaults to current_edited, unless "in the original" / "in the source" is stated (R-TIME-02, R-TIME-03).
- Fast and 100% deterministic rule parser with zero API tokens or latency.
- Pluggable LLM fallback for unrecognized instructions when configured.
"""
from __future__ import annotations

import re
import json
from typing import Dict, Any, List, Optional, Tuple

from .intent_schema import validate_intent
from .adapters.llm_base import LLMAdapter
from .timeparse import parse_time, extract_time_expressions


COLOR_NAMES = {
    "red": "#ff0000",
    "blue": "#0000ff",
    "green": "#00ff00",
    "yellow": "#ffff00",
    "white": "#ffffff",
    "black": "#000000",
    "orange": "#ffa500",
    "purple": "#800080",
    "pink": "#ffc0cb",
}


def parse_instruction(
    text: str,
    llm_adapter: Optional[LLMAdapter] = None,
) -> Dict[str, Any]:
    """
    Parse a user instruction into a validated intent dictionary.
    First tries deterministic regex matching; if that yields unknown and an LLM is
    provided, delegates to the LLM adapter.
    """
    raw_text = text.strip()
    if not raw_text:
        return {"intent": "unknown", "params": {"error": "empty instruction"}}

    # Multi-part instruction check (split by " and " if it contains two distinct command verbs)
    multi_intents = _try_split_multi(raw_text, llm_adapter)
    if multi_intents:
        return {
            "intent": "multi",
            "params": {"intents": multi_intents},
        }

    # Deterministic parse
    intent = _rule_parse_single(raw_text)

    # If unknown and LLM adapter is available, call LLM
    if intent["intent"] == "unknown" and llm_adapter is not None:
        intent = _llm_parse(raw_text, llm_adapter)

    # Validate against JSON schema
    valid, err = validate_intent(intent)
    if not valid:
        return {
            "intent": "unknown",
            "params": {"error": f"Schema validation error: {err}", "raw_intent": intent},
        }

    return intent


def _detect_policy(text: str) -> str:
    """Check if original source policy is specified."""
    t = text.lower()
    if "in the original" in t or "in the source" in t or "original time" in t:
        return "original_source"
    return "current_edited"


def _rule_parse_single(text: str) -> Dict[str, Any]:
    t = text.strip()
    tl = t.lower()
    policy = _detect_policy(t)

    # 1. Render
    if re.fullmatch(r"render(?:\s+the\s+video)?", tl):
        return {"intent": "render", "params": {}}

    # 2. Undo / Redo
    if re.fullmatch(r"undo", tl):
        return {"intent": "undo", "params": {}}
    if re.fullmatch(r"redo", tl):
        return {"intent": "redo", "params": {}}

    # 3. Clarification replies: "the second one", "the first one", "the 2nd one", "all", "all of them"
    ord_match = re.search(r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|1st|2nd|3rd|\d+)\s+one\b", tl)
    if ord_match:
        return {"intent": "clarification_reply", "params": {"choice": ord_match.group(1)}}
    if tl in ("all", "all of them", "all 3", "every one", "everything"):
        return {"intent": "clarification_reply", "params": {"choice": "all"}}

    # 4. Put back / restore specific edit: "actually, put the intro back", "restore the intro", "put back what i removed"
    put_back_match = re.search(r"(?:actually,?\s*)?(?:put\s+(.+?)\s+back|put\s+back\s+(.+)|restore\s+(.+)|bring\s+back\s+(.+))", tl)
    if put_back_match:
        target_item = (put_back_match.group(1) or put_back_match.group(2) or put_back_match.group(3) or put_back_match.group(4)).strip()
        return {
            "intent": "restore_edit",
            "params": {"description": target_item, "which": target_item},
        }
    # Specific undo target: "undo the second-to-last cut but keep the music"
    undo_specific_match = re.search(r"undo\s+the\s+(second-to-last|last|previous)\s+([a-z_]+)", tl)
    if undo_specific_match:
        return {
            "intent": "restore_edit",
            "params": {
                "which": undo_specific_match.group(1),
                "op_type": undo_specific_match.group(2),
                "raw_text": t,
            },
        }

    # 5. Add caption: "Add a caption 'Welcome!' when I say welcome to the channel"
    # or "add a caption at 1:00 saying hello"
    caption_quote_match = re.search(
        r"add\s+(?:a\s+)?caption\s+['\"]([^'\"]+)['\"](?:\s+(?:when\s+(?:i|someone)\s+say(?:s)?|on\s+the\s+words?|over)\s+(.+))?",
        t, re.IGNORECASE,
    )
    if caption_quote_match:
        cap_text = caption_quote_match.group(1)
        target_phrase = caption_quote_match.group(2)
        if target_phrase:
            target_phrase = target_phrase.strip().strip("'\"")
        return {
            "intent": "add_caption",
            "params": {
                "text": cap_text,
                "target_phrase": target_phrase,
                "style": {},
            },
        }

    # Auto caption
    if "auto-caption" in tl or "auto caption" in tl or "caption the whole video" in tl:
        return {"intent": "auto_caption", "params": {"style": {}}}

    # 6. Restyle caption: "Make that caption red", "Make that caption bigger", "change caption color to blue"
    restyle_match = re.search(r"(?:make|change|turn)\s+(?:that\s+caption|the\s+caption|it)\s+(.+)", tl)
    if restyle_match:
        spec = restyle_match.group(1).strip()
        style: Dict[str, Any] = {}
        for color_name, hex_code in COLOR_NAMES.items():
            if color_name in spec:
                style["color"] = hex_code
                break
        if "bigger" in spec or "large" in spec:
            style["font_size"] = 36
        elif "smaller" in spec:
            style["font_size"] = 18
        if "bold" in spec:
            style["bold"] = True
        if "italic" in spec:
            style["italic"] = True
        if "top" in spec:
            style["position"] = "top"
        elif "bottom" in spec:
            style["position"] = "bottom"

        if style:
            return {
                "intent": "restyle_caption",
                "params": {"target": "that caption", "style": style},
            }

    # 7. Speed: "Speed up from 1:00 to 1:30 by 2x", "speed up 10x", "speed up by 1.5x from X to Y"
    if "speed" in tl or "slow down" in tl or "faster" in tl or "slower" in tl:
        factor = 1.5
        factor_match = re.search(r"(\d+(?:\.\d+)?)\s*x\b", tl)
        if factor_match:
            factor = float(factor_match.group(1))
        elif "2x" in tl or "double" in tl:
            factor = 2.0
        elif "slow down" in tl:
            factor = 0.5

        # Check for range: "from X to Y"
        range_match = re.search(r"from\s+([0-9a-z:\s]+?)\s+to\s+([0-9a-z:\s]+?)(?:\s+by|\s*$)", tl)
        start_val = None
        end_val = None
        if range_match:
            start_val = range_match.group(1).strip()
            end_val = range_match.group(2).strip()
        else:
            # Check for extracted times
            times = extract_time_expressions(t)
            if len(times) >= 2:
                start_val = t[times[0][0]:times[0][1]]
                end_val = t[times[1][0]:times[1][1]]
            elif len(times) == 1:
                start_val = t[times[0][0]:times[0][1]]

        return {
            "intent": "speed",
            "params": {
                "factor": factor,
                "start": start_val,
                "end": end_val,
                "policy": policy,
            },
        }

    # 8. Filler words: "cut out the ums", "remove filler words", "remove ums and uhs"
    if "filler" in tl or re.search(r"\b(ums?|uhs?)\b", tl):
        return {"intent": "remove_fillers", "params": {}}

    # 9. Silences: "remove silences longer than 1 second", "cut silences > 0.5s"
    if "silence" in tl or "pauses" in tl:
        thresh = 1.0
        thresh_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:s|sec|seconds?)", tl)
        if thresh_match:
            thresh = float(thresh_match.group(1))
        return {
            "intent": "remove_silences",
            "params": {"threshold_s": thresh},
        }

    # 10. Background music: "add background music ..."
    if "background music" in tl or ("music" in tl and ("add" in tl or "play" in tl)):
        url_match = re.search(r"(https?://\S+|\S+\.mp3|\S+\.wav)", t)
        url = url_match.group(1) if url_match else "default_music.mp3"
        return {
            "intent": "add_music",
            "params": {"music_url": url, "duck_level_db": -18.0},
        }

    # 11. Bleep / Mute
    if "bleep" in tl or "mute" in tl:
        is_bleep = "bleep" in tl
        # phrase match: "bleep the word X" or "bleep when I say X"
        target_match = re.search(r"(?:bleep|mute)\s+(?:the\s+words?|when\s+(?:i|someone)\s+say(?:s)?)\s+['\"]?([^'\"]+)['\"]?", t, re.IGNORECASE)
        phrase = target_match.group(1).strip() if target_match else None
        return {
            "intent": "bleep" if is_bleep else "mute",
            "params": {"target_phrase": phrase},
        }

    # 12. Speaker-specific removal: "remove everything the guest says about their old job"
    spk_match = re.search(r"remove\s+everything\s+(?:the\s+)?([a-z0-9_]+)\s+says\s+about\s+(.+)", tl)
    if spk_match:
        speaker_id = spk_match.group(1).strip()
        topic = spk_match.group(2).strip()
        return {
            "intent": "remove_speaker",
            "params": {"speaker": speaker_id, "topic": topic},
        }

    # 13. Remove after phrase: "remove everything after I say thanks"
    after_match = re.search(r"(?:remove|cut)\s+everything\s+after\s+(?:i\s+say\s+)?['\"]?([^'\"]+)['\"]?", tl)
    if after_match:
        phrase = after_match.group(1).strip()
        return {
            "intent": "cut",
            "params": {
                "start": f"after:{phrase}",
                "end": "end",
                "policy": policy,
                "raw_text": t,
            },
        }

    # 14. Cut everything / whole video
    if tl in ("cut everything", "remove everything", "delete everything", "cut the whole video", "remove the whole video"):
        return {
            "intent": "cut",
            "params": {"start": "0", "end": "end", "policy": policy, "raw_text": t},
        }

    # 15. Remove topic: "remove the part about pricing", "cut the pricing bit", "remove pricing section"
    topic_match = re.search(r"(?:remove|cut|delete)\s+(?:the\s+part\s+about|the\s+bit\s+about|the\s+section\s+about|the\s+)?(.+?)(?:\s+part|\s+bit|\s+section)?$", tl)
    if topic_match:
        candidate = topic_match.group(1).strip()
        # Check if candidate is time-based
        if not re.search(r"\b(first|last|\d+|second|seconds|minute|minutes)\b", candidate):
            return {
                "intent": "remove_topic",
                "params": {"topic": candidate},
            }

    # "keep only 1:00 to 2:00"
    if "keep only" in tl or "keep from" in tl:
        range_match = re.search(r"(?:from\s+)?([0-9a-z:\s]+)\s+to\s+([0-9a-z:\s]+)", tl)
        if range_match:
            return {
                "intent": "keep",
                "params": {
                    "start": range_match.group(1).strip(),
                    "end": range_match.group(2).strip(),
                    "policy": policy,
                },
            }

    # Cut: "cut the first 30 seconds", "remove 0:30-0:40", "cut from 1:00 to 1:30", "cut 0:30 to 1:00"
    if re.search(r"\b(cut|remove|delete)\b", tl):
        # Range with dash or "to": "0:30-0:40" or "0:30 to 1:00" or "from 1:00 to 1:30"
        range_match = re.search(r"(?:from\s+)?(\d+:\d+|\d+)\s*(?:-|to)\s*(\d+:\d+|\d+)", tl)
        if range_match:
            return {
                "intent": "cut",
                "params": {
                    "start": range_match.group(1),
                    "end": range_match.group(2),
                    "policy": policy,
                    "raw_text": t,
                },
            }

        # Relative: "the first 30 seconds", "the last 10 seconds"
        first_last_match = re.search(r"(the\s+(?:first|last)\s+[0-9a-z\s]+(?:seconds?|minutes?|mins?|secs?))", tl)
        if first_last_match:
            expr = first_last_match.group(1)
            if "first" in expr:
                return {
                    "intent": "cut",
                    "params": {"start": "0", "end": expr, "policy": policy, "raw_text": t},
                }
            else:
                return {
                    "intent": "cut",
                    "params": {"start": expr, "end": "end", "policy": policy, "raw_text": t},
                }

    return {"intent": "unknown", "params": {"raw_text": t}}


def _try_split_multi(text: str, llm_adapter: Optional[LLMAdapter]) -> Optional[List[Dict[str, Any]]]:
    """
    Check if an instruction is a multi-part instruction joined by ' and '.
    e.g. "Cut the first 30 seconds and add a caption 'Welcome!' when I say welcome to the channel"
    """
    if " and " not in text.lower():
        return None

    # Don't split if "and" is inside quotation marks
    # Split only on " and " outside quotes
    parts = re.split(r"\s+and\s+(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)(?=(?:[^']*'[^']*')*[^']*$)", text, flags=re.IGNORECASE)
    if len(parts) <= 1:
        return None

    parsed_parts = []
    for part in parts:
        res = _rule_parse_single(part.strip())
        if res["intent"] == "unknown":
            return None
        parsed_parts.append(res)

    return parsed_parts if len(parsed_parts) > 1 else None


def _llm_parse(text: str, llm_adapter: LLMAdapter) -> Dict[str, Any]:
    """Use configured LLM adapter to translate instruction to intent JSON."""
    system_prompt = (
        "You are an NLU parser for a video editor. "
        "Translate user instructions into JSON conforming to the intent schema: "
        "{'intent': ..., 'params': {...}}. "
        "Allowed intents: cut, keep, speed, add_caption, restyle_caption, "
        "auto_caption, remove_fillers, remove_silences, mute, bleep, "
        "remove_topic, remove_speaker, add_music, undo, redo, restore_edit, render. "
        "Output ONLY valid JSON."
    )
    raw = llm_adapter.complete(system_prompt, text)
    try:
        return json.loads(raw)
    except Exception:
        return {"intent": "unknown", "params": {"error": "LLM output non-JSON", "raw": raw}}
