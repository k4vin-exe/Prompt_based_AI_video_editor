"""
tests/unit/test_nlu_paraphrase.py
----------------------------------
Paraphrase test suite.

Verifies that 4-5 alternative phrasings of each editing operation resolve to
the correct intent. This is the key evidence that the NLU layer handles
"ANY natural-language instruction in ANY phrasing" (BRIEF requirement).

All tests use MockLLMAdapter (no API keys) with pre-recorded cassettes.
The cassettes are populated by the rule-based fallback in llm_mock.py
on first run; subsequent runs replay deterministically.
"""
from __future__ import annotations

import pytest
from nlu.parser import parse_instruction
from nlu.adapters.llm_mock import MockLLMAdapter


@pytest.fixture
def llm():
    return MockLLMAdapter()


# ── Helper ────────────────────────────────────────────────────────────────────

def parse(text: str, llm) -> str:
    """Parse instruction and return the intent string."""
    result = parse_instruction(text, llm_adapter=llm)
    return result.get("intent", "unknown")


# ── Cut / Remove ──────────────────────────────────────────────────────────────

CUT_PARAPHRASES = [
    "Cut the first 30 seconds",
    "Remove the first half minute",
    "Delete the beginning 30 seconds",
    "Trim off the first 30 seconds",
    "Get rid of the first 30 seconds",
]

@pytest.mark.parametrize("instruction", CUT_PARAPHRASES)
def test_cut_paraphrases(instruction, llm):
    intent = parse(instruction, llm)
    assert intent == "cut", f"Expected 'cut' for: {instruction!r}, got {intent!r}"


# ── Remove Fillers ────────────────────────────────────────────────────────────

FILLER_PARAPHRASES = [
    "Remove the filler words",
    "Cut out all the ums and uhs",
    "Delete the um and uh sounds",
    "Get rid of all the um noises",
    "Clean up the filler words like um and uh",
]

@pytest.mark.parametrize("instruction", FILLER_PARAPHRASES)
def test_remove_fillers_paraphrases(instruction, llm):
    intent = parse(instruction, llm)
    assert intent == "remove_fillers", f"Expected 'remove_fillers' for: {instruction!r}, got {intent!r}"


# ── Remove Silences ───────────────────────────────────────────────────────────

SILENCE_PARAPHRASES = [
    "Remove silences longer than 1 second",
    "Cut out pauses longer than 1s",
    "Delete any silence that's more than 1 second long",
    "Take out all gaps longer than 1 second",
    "Remove the long silences over 1 second",
]

@pytest.mark.parametrize("instruction", SILENCE_PARAPHRASES)
def test_remove_silences_paraphrases(instruction, llm):
    intent = parse(instruction, llm)
    assert intent == "remove_silences", f"Expected 'remove_silences' for: {instruction!r}, got {intent!r}"


# ── Remove Topic ──────────────────────────────────────────────────────────────

TOPIC_PARAPHRASES = [
    "Remove the part about pricing",
    "Cut out the pricing section",
    "Delete the bit where they talk about pricing",
    "Get rid of the pricing discussion",
    "Take out everything about pricing",
]

@pytest.mark.parametrize("instruction", TOPIC_PARAPHRASES)
def test_remove_topic_paraphrases(instruction, llm):
    intent = parse(instruction, llm)
    assert intent == "remove_topic", f"Expected 'remove_topic' for: {instruction!r}, got {intent!r}"


# ── Add Caption ───────────────────────────────────────────────────────────────

CAPTION_PARAPHRASES = [
    "Add a caption 'Welcome!' when I say welcome to the channel",
    "Put a 'Welcome!' text when I say welcome to the channel",
    "Show 'Welcome!' on screen when I say welcome to the channel",
    "Display the text 'Welcome!' over the words welcome to the channel",
    "Overlay 'Welcome!' on the phrase welcome to the channel",
]

@pytest.mark.parametrize("instruction", CAPTION_PARAPHRASES)
def test_add_caption_paraphrases(instruction, llm):
    intent = parse(instruction, llm)
    assert intent == "add_caption", f"Expected 'add_caption' for: {instruction!r}, got {intent!r}"


# ── Speed ─────────────────────────────────────────────────────────────────────

SPEED_PARAPHRASES = [
    "Speed up from 1:00 to 1:30 by 2x",
    "Make the section from 1:00 to 1:30 twice as fast",
    "Double the speed between 1:00 and 1:30",
    "Play 1:00 to 1:30 at 2x speed",
    "Accelerate 1:00 to 1:30 by 2 times",
]

@pytest.mark.parametrize("instruction", SPEED_PARAPHRASES)
def test_speed_paraphrases(instruction, llm):
    intent = parse(instruction, llm)
    assert intent == "speed", f"Expected 'speed' for: {instruction!r}, got {intent!r}"


# ── Bleep ─────────────────────────────────────────────────────────────────────

BLEEP_PARAPHRASES = [
    "Bleep the word shit",
    "Censor the word shit",
    "Mute out the swear word shit",
    "Beep over the word shit",
    "Replace the word shit with a bleep",
]

@pytest.mark.parametrize("instruction", BLEEP_PARAPHRASES)
def test_bleep_paraphrases(instruction, llm):
    intent = parse(instruction, llm)
    assert intent in ("bleep", "mute"), f"Expected 'bleep'/'mute' for: {instruction!r}, got {intent!r}"


# ── Undo ──────────────────────────────────────────────────────────────────────

UNDO_PARAPHRASES = [
    "Undo",
    "undo",
    "UNDO",
]

@pytest.mark.parametrize("instruction", UNDO_PARAPHRASES)
def test_undo_exact_paraphrases(instruction, llm):
    intent = parse(instruction, llm)
    assert intent == "undo", f"Expected 'undo' for: {instruction!r}, got {intent!r}"


# ── Restore Edit ──────────────────────────────────────────────────────────────

RESTORE_PARAPHRASES = [
    "Actually, put the intro back",
    "Restore the intro",
    "Bring back the intro",
    "Put back what I removed at the beginning",
]

@pytest.mark.parametrize("instruction", RESTORE_PARAPHRASES)
def test_restore_paraphrases(instruction, llm):
    intent = parse(instruction, llm)
    assert intent == "restore_edit", f"Expected 'restore_edit' for: {instruction!r}, got {intent!r}"


# ── Keep ──────────────────────────────────────────────────────────────────────

KEEP_PARAPHRASES = [
    "Keep only 1:00 to 2:00",
    "Keep from 1:00 to 2:00",
]

@pytest.mark.parametrize("instruction", KEEP_PARAPHRASES)
def test_keep_paraphrases(instruction, llm):
    intent = parse(instruction, llm)
    assert intent == "keep", f"Expected 'keep' for: {instruction!r}, got {intent!r}"


# ── Render ────────────────────────────────────────────────────────────────────

RENDER_PARAPHRASES = [
    "render",
    "render the video",
    "Render",
    "Render the video",
]

@pytest.mark.parametrize("instruction", RENDER_PARAPHRASES)
def test_render_paraphrases(instruction, llm):
    intent = parse(instruction, llm)
    assert intent == "render", f"Expected 'render' for: {instruction!r}, got {intent!r}"


# ── Restyle Caption ───────────────────────────────────────────────────────────

RESTYLE_PARAPHRASES = [
    "Make that caption red",
    "Change that caption to red",
    "Turn the caption red",
]

@pytest.mark.parametrize("instruction", RESTYLE_PARAPHRASES)
def test_restyle_caption_paraphrases(instruction, llm):
    intent = parse(instruction, llm)
    assert intent == "restyle_caption", f"Expected 'restyle_caption' for: {instruction!r}, got {intent!r}"


# ── Background Music ──────────────────────────────────────────────────────────

MUSIC_PARAPHRASES = [
    "Add background music",
    "Play some background music",
    "Add music in the background",
]

@pytest.mark.parametrize("instruction", MUSIC_PARAPHRASES)
def test_add_music_paraphrases(instruction, llm):
    intent = parse(instruction, llm)
    assert intent == "add_music", f"Expected 'add_music' for: {instruction!r}, got {intent!r}"
