"""
nlu/intent_schema.py
--------------------
JSON Schemas and validator for all NLU intent objects.
All timeline logic is deterministic code (R-HIST-03, Brief §Must-have 4);
an LLM or rule-based parser only outputs JSON adhering to this schema.
"""
from __future__ import annotations

import json
from typing import Dict, Any, Tuple, Optional
import jsonschema

INTENT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "NLUIntent",
    "type": "object",
    "required": ["intent", "params"],
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "cut",
                "keep",
                "speed",
                "add_caption",
                "restyle_caption",
                "auto_caption",
                "remove_fillers",
                "remove_silences",
                "mute",
                "bleep",
                "remove_topic",
                "remove_speaker",
                "add_music",
                "undo",
                "redo",
                "restore_edit",
                "render",
                "clarification_reply",
                "add_effect",
                "aspect_ratio",
                "split_clip",
                "add_clip",
                "ai_consult",
                "multi",
                "unknown",
            ],
        },
        "params": {"type": "object"},
    },
    "definitions": {
        "CutParams": {
            "type": "object",
            "properties": {
                "start": {"type": ["string", "null", "number"]},
                "end": {"type": ["string", "null", "number"]},
                "policy": {"type": "string", "enum": ["current_edited", "original_source"]},
                "raw_text": {"type": "string"},
            },
        },
        "SpeedParams": {
            "type": "object",
            "required": ["factor"],
            "properties": {
                "factor": {"type": "number"},
                "start": {"type": ["string", "null", "number"]},
                "end": {"type": ["string", "null", "number"]},
                "policy": {"type": "string", "enum": ["current_edited", "original_source"]},
            },
        },
        "AddCaptionParams": {
            "type": "object",
            "required": ["text"],
            "properties": {
                "text": {"type": "string"},
                "target_phrase": {"type": ["string", "null"]},
                "start": {"type": ["string", "null", "number"]},
                "end": {"type": ["string", "null", "number"]},
                "style": {"type": "object"},
            },
        },
        "RestyleCaptionParams": {
            "type": "object",
            "required": ["style"],
            "properties": {
                "target": {"type": ["string", "null"]},
                "caption_id": {"type": ["integer", "null"]},
                "style": {
                    "type": "object",
                    "properties": {
                        "color": {"type": "string"},
                        "font_size": {"type": "integer"},
                        "bold": {"type": "boolean"},
                        "italic": {"type": "boolean"},
                        "position": {"type": "string", "enum": ["top", "bottom", "center"]},
                        "background": {"type": "string"},
                    },
                },
            },
        },
        "RemoveFillersParams": {
            "type": "object",
            "properties": {
                "fillers": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
        },
        "RemoveSilencesParams": {
            "type": "object",
            "properties": {
                "threshold_s": {"type": "number", "minimum": 0.0},
            },
        },
        "RemoveTopicParams": {
            "type": "object",
            "required": ["topic"],
            "properties": {
                "topic": {"type": "string"},
                "occurrence": {"type": ["string", "integer", "null"]},
            },
        },
        "RestoreEditParams": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "target_op_id": {"type": ["integer", "null"]},
                "which": {"type": "string"},
            },
        },
        "MultiParams": {
            "type": "object",
            "required": ["intents"],
            "properties": {
                "intents": {
                    "type": "array",
                    "items": {"$ref": "#"},
                }
            },
        },
    },
}

_VALIDATOR = jsonschema.Draft7Validator(INTENT_SCHEMA)


def validate_intent(intent_dict: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate that an intent dict adheres to the JSON schema.
    Returns (True, None) if valid, or (False, error_message) if invalid.
    """
    errors = list(_VALIDATOR.iter_errors(intent_dict))
    if not errors:
        return True, None
    msg = "; ".join(e.message for e in errors)
    return False, msg
