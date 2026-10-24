"""
tests/unit/test_nlu_parser.py
-----------------------------
Unit tests for deterministic NLU parser and intent schema validation.
"""
import pytest
from nlu.parser import parse_instruction
from nlu.intent_schema import validate_intent


def test_parse_cut_first_30_seconds():
    intent = parse_instruction("Cut the first 30 seconds")
    assert intent["intent"] == "cut"
    assert intent["params"]["start"] == "0"
    assert "first 30 seconds" in intent["params"]["end"]
    assert intent["params"]["policy"] == "current_edited"
    valid, err = validate_intent(intent)
    assert valid, err


def test_parse_add_caption():
    intent = parse_instruction("Add a caption 'Welcome!' when I say welcome to the channel")
    assert intent["intent"] == "add_caption"
    assert intent["params"]["text"] == "Welcome!"
    assert intent["params"]["target_phrase"] == "welcome to the channel"
    valid, err = validate_intent(intent)
    assert valid, err


def test_parse_remove_topic():
    intent = parse_instruction("Remove the part about pricing")
    assert intent["intent"] == "remove_topic"
    assert intent["params"]["topic"] == "pricing"
    valid, err = validate_intent(intent)
    assert valid, err


def test_parse_speed_range():
    intent = parse_instruction("Speed up from 1:00 to 1:30 by 2x")
    assert intent["intent"] == "speed"
    assert intent["params"]["factor"] == 2.0
    assert intent["params"]["start"] == "1:00"
    assert intent["params"]["end"] == "1:30"
    valid, err = validate_intent(intent)
    assert valid, err


def test_parse_restore_intro():
    intent = parse_instruction("Actually, put the intro back")
    assert intent["intent"] == "restore_edit"
    assert "intro" in intent["params"]["description"]
    valid, err = validate_intent(intent)
    assert valid, err


def test_parse_undo_and_redo():
    assert parse_instruction("Undo")["intent"] == "undo"
    assert parse_instruction("Redo")["intent"] == "redo"


def test_parse_make_caption_red():
    intent = parse_instruction("Make that caption red")
    assert intent["intent"] == "restyle_caption"
    assert intent["params"]["style"]["color"] == "#ff0000"
    valid, err = validate_intent(intent)
    assert valid, err


def test_parse_render():
    assert parse_instruction("Render")["intent"] == "render"


def test_parse_policy_override():
    intent = parse_instruction("Cut 0:30 to 1:00 in the original")
    assert intent["intent"] == "cut"
    assert intent["params"]["policy"] == "original_source"


def test_parse_remove_fillers():
    intent = parse_instruction("Cut out the ums")
    assert intent["intent"] == "remove_fillers"


def test_parse_remove_silences():
    intent = parse_instruction("Remove silences longer than 1.5 seconds")
    assert intent["intent"] == "remove_silences"
    assert intent["params"]["threshold_s"] == 1.5


@pytest.mark.parametrize("phrase", [
    "add captions fully",
    "add full captions",
    "add captions",
    "add subtitles fully",
    "add full subtitles",
    "add subtitles",
    "auto caption",
    "auto-caption",
    "caption the whole video",
    "generate captions",
    "generate subtitles",
    "caption fully",
    "caption everything",
])
def test_parse_auto_caption_variations(phrase):
    intent = parse_instruction(phrase)
    assert intent["intent"] == "auto_caption"
    valid, err = validate_intent(intent)
    assert valid, err


def test_parse_auto_caption_styled():
    intent = parse_instruction("add captions fully in red")
    assert intent["intent"] == "auto_caption"
    assert intent["params"]["style"]["color"] == "#ff0000"
    valid, err = validate_intent(intent)
    assert valid, err

