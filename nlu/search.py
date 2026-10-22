"""
nlu/search.py
-------------
Transcript search, phrase matching, semantic topic detection, and ambiguity resolution.
Finds exact phrases, keywords, topics, and speaker turns in Transcript.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

from engine.transcript import Transcript, Word
from engine.timemap import source_to_edited
from engine.timeline import Timeline


@dataclass
class MatchSpan:
    """A matched segment in the transcript."""
    match_index: int                  # 1-indexed occurrence
    word_start: Word
    word_end: Word
    phrase_text: str                  # the exact matched words
    context_text: str                 # surrounding sentence/clause
    src_start_us: int
    src_end_us: int
    speaker: str
    confidence: float
    score: float = 1.0                # 1.0 for exact, < 1.0 for semantic/synonym


def clean_text(text: str) -> str:
    """Normalize text: lowercase, remove punctuation, strip extra whitespace."""
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


# Common semantic synonyms for zero-cost instant matching
SYNONYM_MAP: Dict[str, List[str]] = {
    "pricing": ["pricing", "price", "prices", "cost", "costs", "expensive", "fee", "fees", "subscription", "plan", "rate", "rates"],
    "intro": ["welcome", "hello", "hi", "intro", "introduction", "start", "beginning"],
    "outro": ["thanks", "thank you", "bye", "goodbye", "subscribe", "closing", "outro"],
    "job": ["job", "career", "work", "role", "company", "boss", "employer", "office"],
}


def find_exact_phrase(transcript: Transcript, phrase: str) -> List[MatchSpan]:
    """
    Find contiguous sequence of words matching phrase (case/punctuation insensitive).
    """
    phrase_tokens = clean_text(phrase).split()
    if not phrase_tokens:
        return []

    words = transcript.words
    n_tokens = len(phrase_tokens)
    matches: List[MatchSpan] = []

    for i in range(len(words) - n_tokens + 1):
        window = words[i:i + n_tokens]
        window_tokens = [clean_text(w.text) for w in window]
        if window_tokens == phrase_tokens:
            # Found exact contiguous match
            context_start = max(0, i - 2)
            context_end = min(len(words), i + n_tokens + 2)
            context = " ".join(w.text for w in words[context_start:context_end])
            phrase_str = " ".join(w.text for w in window)
            matches.append(MatchSpan(
                match_index=len(matches) + 1,
                word_start=window[0],
                word_end=window[-1],
                phrase_text=phrase_str,
                context_text=context,
                src_start_us=window[0].start_us,
                src_end_us=window[-1].end_us,
                speaker=window[0].speaker,
                confidence=min(w.confidence for w in window),
                score=1.0,
            ))

    return matches


def find_topic_occurrences(
    transcript: Transcript,
    topic: str,
    timeline: Optional[Timeline] = None,
    expand_sentence: bool = True,
) -> List[MatchSpan]:
    """
    Find occurrences of a topic or keyword in the transcript.
    If expand_sentence is True, expands the matched span to the whole sentence or turn.
    """
    topic_clean = clean_text(topic)
    synonyms = SYNONYM_MAP.get(topic_clean, [topic_clean])

    words = transcript.words
    matches: List[MatchSpan] = []

    for i, word in enumerate(words):
        word_clean = clean_text(word.text)
        is_match = False
        score = 0.0

        if word_clean == topic_clean:
            is_match = True
            score = 1.0
        elif word_clean in synonyms:
            is_match = True
            score = 0.85

        if is_match:
            # Expand to sentence or pause boundaries
            if expand_sentence:
                start_idx, end_idx = _find_sentence_bounds(words, i)
            else:
                start_idx, end_idx = i, i

            span_words = words[start_idx:end_idx + 1]
            context_start = max(0, start_idx - 1)
            context_end = min(len(words), end_idx + 2)
            context = " ".join(w.text for w in words[context_start:context_end])
            phrase_str = " ".join(w.text for w in span_words)

            matches.append(MatchSpan(
                match_index=len(matches) + 1,
                word_start=span_words[0],
                word_end=span_words[-1],
                phrase_text=phrase_str,
                context_text=context,
                src_start_us=span_words[0].start_us,
                src_end_us=span_words[-1].end_us,
                speaker=span_words[0].speaker,
                confidence=min(w.confidence for w in span_words),
                score=score,
            ))

    return matches


def _find_sentence_bounds(words: List[Word], target_idx: int) -> Tuple[int, int]:
    """
    Expand a word index to its sentence or pause-bounded clause.
    Sentence boundary: punctuation (. ? !) or pause gap > 0.5s or speaker change.
    """
    target = words[target_idx]
    start_idx = target_idx
    end_idx = target_idx

    # Walk backwards
    while start_idx > 0:
        prev = words[start_idx - 1]
        gap_s = (words[start_idx].start_us - prev.end_us) / 1_000_000.0
        if prev.text.endswith((".", "?", "!")) or gap_s >= 0.5 or prev.speaker != target.speaker:
            break
        start_idx -= 1

    # Walk forwards
    while end_idx < len(words) - 1:
        curr = words[end_idx]
        nxt = words[end_idx + 1]
        gap_s = (nxt.start_us - curr.end_us) / 1_000_000.0
        if curr.text.endswith((".", "?", "!")) or gap_s >= 0.5 or nxt.speaker != target.speaker:
            break
        end_idx += 1

    return start_idx, end_idx


def format_time_mm_ss(us: int) -> str:
    """Format microseconds as M:SS."""
    total_seconds = int(us / 1_000_000)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def build_clarification_for_matches(
    topic: str,
    matches: List[MatchSpan],
    timeline: Optional[Timeline] = None,
) -> Tuple[str, List[str]]:
    """
    Build clarification question and options according to the brief's format:
    e.g. "Pricing is mentioned at 1:05, 2:40 and 3:15 — which one, or all?"
    Options: ["the first one", "the second one", "the third one", "all"]
    """
    time_strings = []
    for m in matches:
        if timeline is not None:
            ed_time = source_to_edited(timeline, m.src_start_us)
            t_us = ed_time if ed_time is not None else m.src_start_us
        else:
            t_us = m.src_start_us
        time_strings.append(format_time_mm_ss(t_us))

    if len(time_strings) == 2:
        times_formatted = f"{time_strings[0]} and {time_strings[1]}"
    else:
        times_formatted = ", ".join(time_strings[:-1]) + f" and {time_strings[-1]}"

    question = f"{topic.capitalize()} is mentioned at {times_formatted} — which one, or all?"

    ordinal_names = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"]
    options = []
    for i, t_str in enumerate(time_strings):
        name = ordinal_names[i] if i < len(ordinal_names) else f"{i+1}th"
        options.append(f"the {name} one ({t_str})")
    options.append("all of them")

    return question, options
