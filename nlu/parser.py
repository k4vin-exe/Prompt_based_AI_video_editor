"""
nlu/parser.py
-------------
NLU instruction parser — AI-primary, regex-fallback.

Architecture:
  1. Fast-path regex: handles unambiguous meta-commands (undo, redo, render,
     clarification_reply). These are never sent to an LLM.
  2. LLM primary: if an llm_adapter is provided, the instruction is sent to the
     LLM WITH a context pack. The LLM returns a validated intent JSON.
  3. Regex fallback: if no LLM is configured, the full rule-based parser runs.
     This is the "offline / mock" path used in CI.

Enforces Brief §Must-have 4:
  "An AI model may only translate words into structured operations;
   all timeline logic is ordinary code you wrote."

The LLM returns ONLY the intent + params JSON. No timeline mutation happens here.
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
    context_pack: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Parse a user instruction into a validated intent dictionary.

    Strategy (AI-primary):
    1. Fast-path regex for unambiguous meta-commands.
    2. LLM (if adapter provided) with context pack for everything else.
    3. Full rule-based parser as fallback when no LLM is configured.

    Args:
        text:         Raw user instruction string.
        llm_adapter:  Optional LLM adapter. When provided, it is the primary
                      intent translator (Brief §Must-have 4).
        context_pack: Optional compact session context string from nlu.context.
    """
    raw_text = text.strip()
    if not raw_text:
        return {"intent": "unknown", "params": {"error": "empty instruction"}}

    # ── Step 1: Fast-path meta-commands (never need LLM) ─────────────────────
    fast = _fast_path_meta(raw_text)
    if fast is not None:
        return fast

    # ── Step 2: LLM primary ───────────────────────────────────────────────────
    if llm_adapter is not None:
        try:
            intent = _llm_parse(raw_text, llm_adapter, context_pack)
            valid, err = validate_intent(intent)
            if valid and intent.get("intent") != "unknown":
                return intent
        except Exception:
            # LLM adapter error or network timeout → fall through to deterministic rules
            pass
        # LLM returned unknown or invalid → fall through to regex

    # ── Step 3: Full rule-based fallback ─────────────────────────────────────
    # Multi-part instruction check
    multi_intents = _try_split_multi(raw_text, None)
    if multi_intents:
        return {
            "intent": "multi",
            "params": {"intents": multi_intents},
        }

    intent = _rule_parse_single(raw_text)

    # Validate against JSON schema
    valid, err = validate_intent(intent)
    if not valid:
        return {
            "intent": "unknown",
            "params": {"error": f"Schema validation error: {err}", "raw_intent": intent},
        }

    return intent


def _fast_path_meta(text: str) -> Optional[Dict[str, Any]]:
    """
    Instantly handle unambiguous meta-commands without LLM or regex.
    Returns None if the instruction is not a meta-command.
    """
    tl = text.lower().strip()

    if re.fullmatch(r"render(?:\s+the\s+video)?", tl):
        return {"intent": "render", "params": {}}
    if re.fullmatch(r"undo", tl):
        return {"intent": "undo", "params": {}}
    if re.fullmatch(r"redo", tl):
        return {"intent": "redo", "params": {}}
    if re.search(
        r"^(?:auto[- ]?caption(?:ing)?|auto[- ]?subtitle(?:s|ing)?|caption(?:s)?\s+(?:the\s+)?(?:whole|entire|full)\s+video|subtitle(?:s)?\s+(?:the\s+)?(?:whole|entire|full)\s+video|(?:add|generate|create|put|show)\s+(?:full\s+)?(?:captions?|subtitles?)(?:\s+(?:fully|full|everywhere|throughout|all\s+over|for\s+(?:the\s+)?(?:whole|entire|full)\s+video))?|caption(?:s)?\s+(?:fully|full|all|everything)|subtitle(?:s)?\s+(?:fully|full|all|everything)|full\s+(?:captions?|subtitles?))$",
        tl,
    ):
        return {"intent": "auto_caption", "params": {"style": {}}}

    if re.search(r"\b(cut|remove|delete)\s+(everything|the\s+whole\s+video)\b", tl):
        return {"intent": "cut", "params": {"start": "0", "end": "end", "policy": "current_edited"}}

    # Ordinal clarification reply: "the second one", "all"
    ord_match = re.search(r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|1st|2nd|3rd|\d+)\s+one\b", tl)
    if ord_match:
        return {"intent": "clarification_reply", "params": {"choice": ord_match.group(1)}}
    if tl in ("all", "all of them", "all 3", "every one", "everything"):
        return {"intent": "clarification_reply", "params": {"choice": "all"}}

    return None


def _detect_policy(text: str) -> str:
    """Check if original source policy is specified."""
    t = text.lower()
    if "in the original" in t or "in the source" in t or "original time" in t:
        return "original_source"
    return "current_edited"


def _rule_parse_single(text: str) -> Dict[str, Any]:
    if "INSTRUCTION:" in text:
        text = text.split("INSTRUCTION:")[-1].strip()
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
    # or "put a 'Welcome!' text when I say...", "show 'Welcome!' on screen...", etc.
    # or "in the intro add 'welcome'"
    in_loc_match = re.search(r"in\s+(?:the\s+)?([a-z0-9_]+)\s+add\s+(?:a\s+caption\s+)?['\"]([^'\"]+)['\"]", t, re.IGNORECASE)
    if in_loc_match:
        return {
            "intent": "add_caption",
            "params": {
                "text": in_loc_match.group(2).strip(),
                "target_phrase": in_loc_match.group(1).strip(),
                "style": {},
            },
        }

    caption_quote_match = re.search(
        r"(?:add\s+(?:a\s+)?caption\s+|put\s+(?:a\s+)?|show\s+|display\s+(?:the\s+text\s+)?|overlay\s+)['\"]([^'\"]+)['\"](?:\s+(?:text\s+|on\s+screen\s+)?(?:when\s+(?:i|someone)\s+say(?:s)?|on\s+the\s+words?|over\s+the\s+words?|over|on\s+the\s+phrase)\s+(.+))?",
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

    # Auto caption / full video subtitles
    auto_caption_match = re.search(
        r"\b(?:auto[- ]?caption(?:ing)?|auto[- ]?subtitle(?:s|ing)?|caption(?:s)?\s+(?:the\s+)?(?:whole|entire|full)\s+video|subtitle(?:s)?\s+(?:the\s+)?(?:whole|entire|full)\s+video|(?:add|generate|create|put|show)\s+(?:full\s+)?(?:captions?|subtitles?)(?:\s+(?:fully|full|everywhere|throughout|all\s+over|for\s+(?:the\s+)?(?:whole|entire|full)\s+video))?|caption(?:s)?\s+(?:fully|full|all|everything)|subtitle(?:s)?\s+(?:fully|full|all|everything)|full\s+(?:captions?|subtitles?))\b",
        tl,
    )
    if auto_caption_match and not re.search(r"\bwhen\s+(?:i|someone)\s+say|over\s+the\s+words?|on\s+the\s+phrase\b", tl):
        style: Dict[str, Any] = {}
        for color_name, hex_code in COLOR_NAMES.items():
            if re.search(rf"\b{color_name}\b", tl):
                style["color"] = hex_code
                break
        if "bigger" in tl or "large" in tl:
            style["font_size"] = 36
        elif "smaller" in tl:
            style["font_size"] = 18
        return {"intent": "auto_caption", "params": {"style": style}}

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
    if re.search(r"\b(bleep|beep|censor|mute)\b", tl):
        is_bleep = "mute" not in tl
        target_match = re.search(r"(?:bleep|beep|censor|mute(?:\s+out)?|replace)\s+(?:over\s+)?(?:the\s+(?:swear\s+)?words?|when\s+(?:i|someone)\s+say(?:s)?)\s+['\"]?([^'\"]+?)['\"]?(?:\s+with\s+a\s+bleep)?$", t, re.IGNORECASE)
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
    if re.search(r"\b(cut|remove|delete)\s+(everything|the\s+whole\s+video)\b", tl):
        return {
            "intent": "cut",
            "params": {"start": "0", "end": "end", "policy": policy, "raw_text": t},
        }

    # 15. Remove topic: "remove the part about pricing", "cut the pricing bit", "remove pricing section"
    topic_match = re.search(r"(?:remove|cut|delete|get\s+rid\s+of|take\s+out)\s+(?:everything\s+about\s+|the\s+part\s+about\s+|the\s+bit\s+about\s+|the\s+bit\s+where.+about\s+|the\s+section\s+about\s+|the\s+)?(.+?)(?:\s+part|\s+bit|\s+section|\s+discussion)?$", tl)
    if topic_match:
        candidate = topic_match.group(1).strip()
        # Check if candidate is time-based or generic
        if candidate not in ("everything", "the whole video", "all") and not re.search(r"\b(first|last|\d+|second|seconds|minute|minutes)\b", candidate):
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
    if re.search(r"\b(cut|remove|delete|trim|get\s+rid\s+of|take\s+out)\b", tl):
        # Outro / trailing screen: "remove the white screen at the end", "cut the outro", "cut the end", "remove blank screen at the end"
        if re.search(r"\b(cut|remove|delete|trim|get\s+rid\s+of|take\s+out)\b.*\b(at\s+the\s+end|at\s+the\s+tail|at\s+the\s+outro|the\s+outro|the\s+ending)\b", tl):
            return {
                "intent": "cut",
                "params": {"start": "the end", "end": "end", "policy": policy, "raw_text": t},
            }

        # Intro / start screen: "remove the black screen at the start", "cut the intro", "remove the beginning"
        if re.search(r"\b(cut|remove|delete|trim|get\s+rid\s+of|take\s+out)\b.*\b(at\s+the\s+start|at\s+the\s+beginning|at\s+the\s+intro|the\s+intro|the\s+beginning|the\s+start)\b", tl):
            return {
                "intent": "cut",
                "params": {"start": "0", "end": "the start", "policy": policy, "raw_text": t},
            }

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

        # Relative: "the first 30 seconds", "the last 10 seconds", "the beginning 30 seconds", "the first half minute"
        first_last_match = re.search(r"((?:the\s+)?(first|last|beginning)\s+[0-9a-z\s]+(?:seconds?|minutes?|mins?|secs?|half\s+minute))", tl)
        if first_last_match:
            expr = first_last_match.group(1)
            kind = first_last_match.group(2)
            if kind in ("first", "beginning"):
                return {
                    "intent": "cut",
                    "params": {"start": "0", "end": expr, "policy": policy, "raw_text": t},
                }
            else:
                return {
                    "intent": "cut",
                    "params": {"start": expr, "end": "end", "policy": policy, "raw_text": t},
                }

    # 16. Visual Effects: "Add vibration flash", "add flash effect", "cinematic filter", "glitch", "blur", "vintage"
    if re.search(r"\b(vibration\s+flash|flash(?:\s+effect)?|cinematic(?:\s+filter|\s+grade)?|glitch|vintage|blur|black\s+and\s+white|vignette)\b", tl):
        eff_type = "vibration_flash"
        if "cinematic" in tl:
            eff_type = "cinematic_grade"
        elif "glitch" in tl:
            eff_type = "glitch"
        elif "vintage" in tl:
            eff_type = "vintage_vhs"
        elif "blur" in tl:
            eff_type = "blur"
        elif "black and white" in tl:
            eff_type = "black_white"
        elif "vignette" in tl:
            eff_type = "vignette"
        return {
            "intent": "add_effect",
            "params": {"effect_type": eff_type, "name": eff_type.replace("_", " ").title(), "raw_text": t},
        }

    # 17. Aspect Ratio / Framing: "Make it 9:16 reels", "Crop to 9:16", "16:9", "tiktok format", "square 1:1"
    if re.search(r"\b(9:16|16:9|1:1|4:5|reels|tiktok|shorts|portrait|landscape|square)\b", tl):
        ratio = "9:16"
        if "16:9" in tl or "landscape" in tl:
            ratio = "16:9"
        elif "1:1" in tl or "square" in tl:
            ratio = "1:1"
        elif "4:5" in tl:
            ratio = "4:5"
        return {
            "intent": "aspect_ratio",
            "params": {"ratio": ratio, "raw_text": t},
        }

    # 18. Split: "Split at 0:15", "Split clip at 10s", "Cut video into two at 0:20"
    split_match = re.search(r"(?:split|divide)(?:\s+(?:the\s+)?(?:video|clip))?(?:\s+at|\s+around)?\s+([0-9a-z:\s]+)", tl)
    if split_match:
        return {
            "intent": "split_clip",
            "params": {"at_time": split_match.group(1).strip(), "raw_text": t},
        }

    # 19. Add / Append Clips: "Add another clip", "Add clip 2", "Append clip", "Import footage"
    if re.search(r"\b(?:add|append|insert|import)\s+(?:another\s+|new\s+|second\s+|extra\s+)?(?:clip|video|media|file|footage)\b", tl):
        return {
            "intent": "add_clip",
            "params": {"action": "append", "raw_text": t},
        }

    # 20. Conversational AI Assistant / Creative Advice: "How can I make this video better?", "Give me hook ideas", "Summarize"
    if (
        re.search(r"^(?:how|what|why|can\s+you|could\s+you|give\s+me|tell\s+me|suggest|tips?|ideas?|summarize|analyze|review|explain|help|assist)\b", tl)
        or "?" in t
        or any(w in tl for w in ["make it better", "make it viral", "improve", "recommend", "pacing", "critique", "engagement"])
    ):
        return {
            "intent": "ai_consult",
            "params": {"prompt": t, "raw_text": t},
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


def _normalize_intent_dict(data: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
    """Normalize slight LLM schema variations to canonical engine intent format."""
    intent = str(data.get("intent", "unknown")).lower().strip()
    params = data.get("params", {})
    if not isinstance(params, dict):
        params = {}

    # Map synonymous intents
    intent_map = {
        "trim": "cut",
        "trim_video": "cut",
        "slice": "cut",
        "cut_video": "cut",
        "remove": "cut",
        "subtitles": "auto_caption",
        "add_subtitles": "auto_caption",
        "subtitle": "auto_caption",
        "captions": "auto_caption",
        "generate_captions": "auto_caption",
        "full_captions": "auto_caption",
        "effect": "add_effect",
        "vfx": "add_effect",
        "filter": "add_effect",
        "visual_effect": "add_effect",
        "aspect": "aspect_ratio",
        "crop": "aspect_ratio",
        "resize": "aspect_ratio",
        "format": "aspect_ratio",
        "split": "split_clip",
        "split_video": "split_clip",
        "advice": "ai_consult",
        "consult": "ai_consult",
        "question": "ai_consult",
        "chat": "ai_consult",
    }
    if intent in intent_map:
        intent = intent_map[intent]

    # Normalize cut params if duration or target were used
    if intent == "cut":
        dur = params.get("duration_seconds") or params.get("duration") or params.get("duration_s")
        target = str(params.get("target", "")).lower()
        if dur is not None and not params.get("end"):
            if any(k in target for k in ["start", "intro", "beginning", "head"]):
                params["start"] = "0"
                params["end"] = f"{dur}s"
            elif any(k in target for k in ["end", "outro", "tail", "last"]):
                params["start"] = f"the last {dur} seconds"
                params["end"] = "end"
            else:
                params["start"] = "0"
                params["end"] = f"{dur}s"

    # Normalize effect params
    if intent == "add_effect":
        if "type" in params and "effect_type" not in params:
            params["effect_type"] = params["type"]
        if "effect_type" not in params:
            params["effect_type"] = "vibration_flash"

    # Normalize aspect ratio params
    if intent == "aspect_ratio":
        ratio = str(params.get("ratio", params.get("aspect_ratio", "9:16")))
        if "9:16" in ratio or "vertical" in ratio or "reel" in ratio or "short" in ratio or "tiktok" in ratio:
            params["ratio"] = "9:16"
        elif "1:1" in ratio or "square" in ratio:
            params["ratio"] = "1:1"
        elif "16:9" in ratio or "landscape" in ratio or "horizontal" in ratio:
            params["ratio"] = "16:9"
        else:
            params["ratio"] = ratio

    data["intent"] = intent
    data["params"] = params
    return data


def _llm_parse(
    text: str,
    llm_adapter: LLMAdapter,
    context_pack: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Use configured LLM adapter to translate instruction to intent JSON.

    The system prompt instructs the LLM to output ONLY a JSON object.
    The user prompt includes the instruction and (if provided) the context pack.
    """
    system_prompt = (
        "You are the NLU parser for a prompt-based video editing engine.\n"
        "Translate the user instruction into a JSON object with exactly two keys: \"intent\" and \"params\".\n\n"
        "Allowed intents and schemas:\n"
        "  cut             : {\"start\": \"0\", \"end\": \"5s\", \"policy\": \"current_edited\"}\n"
        "  keep            : {\"start\": \"1:00\", \"end\": \"2:00\", \"policy\": \"current_edited\"}\n"
        "  speed           : {\"factor\": 2.0, \"start\": \"0:10\", \"end\": \"0:30\", \"policy\": \"current_edited\"}\n"
        "  add_caption     : {\"text\": \"Welcome!\", \"target_phrase\": \"welcome\", \"style\": {\"color\": \"#ffff00\"}}\n"
        "  auto_caption    : {\"style\": {\"color\": \"#ffff00\"}}\n"
        "  restyle_caption : {\"target\": \"that caption\", \"style\": {\"color\": \"#ff0000\", \"bold\": true}}\n"
        "  add_effect      : {\"effect_type\": \"vibration_flash\", \"intensity\": 1.0}\n"
        "  aspect_ratio    : {\"ratio\": \"9:16\"}\n"
        "  split_clip      : {\"at_time\": \"5.0\"}\n"
        "  add_clip        : {\"clip_name\": \"clip_2.mp4\"}\n"
        "  remove_fillers  : {}\n"
        "  remove_silences : {\"threshold_s\": 1.0}\n"
        "  mute            : {\"target_phrase\": \"target\"}\n"
        "  bleep           : {\"target_phrase\": \"swear\"}\n"
        "  remove_topic    : {\"topic\": \"pricing\", \"occurrence\": null}\n"
        "  remove_speaker  : {\"speaker\": \"guest\", \"topic\": \"past\"}\n"
        "  add_music       : {\"music_url\": \"lofi.mp3\", \"duck_level_db\": -18.0}\n"
        "  ai_consult      : {\"query\": \"...\"}\n"
        "  undo            : {}\n"
        "  redo            : {}\n"
        "  restore_edit    : {\"description\": \"intro\", \"which\": \"intro\"}\n"
        "  render          : {}\n"
        "  unknown         : {\"error\": \"...\"}\n\n"
        "Rules:\n"
        "- Output ONLY valid JSON. No explanation, no markdown fences, no conversational filler.\n"
        "- For aspect ratio (9:16, 16:9, 1:1, vertical, reels, shorts, tiktok), use intent 'aspect_ratio'.\n"
        "- For vibration flash, cinematic grade, glitch, vintage, blur, use intent 'add_effect'.\n"
        "- For advice, suggestions, 'how to make viral', 'what can you do', use intent 'ai_consult'.\n"
        "- For auto-captioning or full video subtitles ('add captions fully', 'auto caption'), use intent 'auto_caption'.\n"
    )

    user_prompt = text
    if context_pack:
        user_prompt = f"CONTEXT:\n{context_pack}\n\nINSTRUCTION: {text}"

    raw = llm_adapter.complete(system_prompt, user_prompt)

    # Strip markdown code fences if present
    raw = raw.strip()
    if "```" in raw:
        fence_match = re.search(r"```(?:json)?(.*?)```", raw, re.DOTALL)
        if fence_match:
            raw = fence_match.group(1).strip()

    # Extract JSON object if embedded in text
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        raw = json_match.group(0)

    try:
        parsed = json.loads(raw)
        return _normalize_intent_dict(parsed, text)
    except Exception:
        # Fall back to rule-based parser on JSON failure
        return _rule_parse_single(text)

