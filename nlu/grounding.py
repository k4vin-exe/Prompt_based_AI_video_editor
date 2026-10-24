"""
nlu/grounding.py
----------------
Grounding Resolver: maps LLM-produced selectors to concrete word-ID spans.

The LLM returns a structured intent like:
  {"intent": "cut", "params": {"phrase": "welcome to the channel"}}
  {"intent": "remove_topic", "params": {"topic": "pricing"}}
  {"intent": "add_caption", "params": {"text": "Welcome!", "anchor_phrase": "welcome to the channel"}}

The grounding resolver resolves "phrase" / "anchor_phrase" / "topic" / "speaker"
fields into (word_id_start, word_id_end) spans using the transcript.

For "topic", it uses fastembed semantic search if available; falls back to
keyword/synonym matching (nlu.search.find_topic_occurrences).

Returns a list of MatchSpan objects (defined in nlu.search) so the session
can present clarification if needed.

This is DETERMINISTIC CODE — no LLM involvement in the resolution.
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any, Tuple

from engine.transcript import Transcript
from nlu.search import find_exact_phrase, find_topic_occurrences, MatchSpan


def resolve_phrase(
    transcript: Transcript,
    phrase: str,
) -> List[MatchSpan]:
    """
    Find all occurrences of an exact phrase in the transcript.
    Returns MatchSpan list (may be empty or multiple for clarification).
    """
    return find_exact_phrase(transcript, phrase)


def resolve_topic(
    transcript: Transcript,
    topic: str,
    analysis: Optional[Dict[str, Any]] = None,
) -> List[MatchSpan]:
    """
    Find occurrences of a topic/concept in the transcript.

    First tries fastembed semantic search against sentence embeddings.
    Falls back to keyword+synonym matching in nlu.search.

    If analysis.json has pre-computed chapters, also checks chapter keywords.
    """
    # Try semantic search first
    semantic_matches = _semantic_search(transcript, topic, analysis)
    if semantic_matches:
        return semantic_matches

    # Keyword/synonym fallback
    return find_topic_occurrences(transcript, topic)


def resolve_speaker(
    transcript: Transcript,
    speaker_hint: str,
) -> Optional[str]:
    """
    Resolve a speaker hint (e.g. "guest", "host", "speaker_0") to the canonical
    speaker label in the transcript.

    Returns the canonical speaker ID, or None if unresolvable.
    """
    if not speaker_hint:
        return None

    # Get all speaker IDs from transcript
    speaker_ids = list(dict.fromkeys(
        w.speaker for w in transcript.words if w.speaker
    ))

    if not speaker_ids:
        return None

    hint_lower = speaker_hint.lower().strip()

    # Exact match
    if speaker_hint in speaker_ids:
        return speaker_hint

    # Positional hints: "guest" = 2nd speaker, "host" = 1st
    FIRST_ALIASES = {"host", "interviewer", "main", "first", "speaker_0", "speaker1"}
    SECOND_ALIASES = {"guest", "interviewee", "second", "speaker_1", "speaker2"}

    if hint_lower in FIRST_ALIASES and speaker_ids:
        return speaker_ids[0]
    if hint_lower in SECOND_ALIASES and len(speaker_ids) >= 2:
        return speaker_ids[1]

    # Partial match
    for sid in speaker_ids:
        if hint_lower in sid.lower():
            return sid

    return None


def resolve_chapter(
    transcript: Transcript,
    chapter_hint: str,
    analysis: Optional[Dict[str, Any]] = None,
) -> Optional[Tuple[str, str]]:
    """
    Resolve a chapter reference (e.g. "the pricing chapter", "chapter 2") to
    a (word_id_start, word_id_end) tuple.

    Returns None if not resolvable.
    """
    if not analysis or not analysis.get("chapters"):
        return None

    chapters = analysis["chapters"]
    hint_lower = chapter_hint.lower().strip()

    # Check by index: "chapter 2", "the second chapter"
    ORDINALS = ["first", "second", "third", "fourth", "fifth",
                "sixth", "seventh", "eighth", "ninth", "tenth"]
    for i, ordinal in enumerate(ORDINALS):
        if ordinal in hint_lower or str(i + 1) in hint_lower:
            if i < len(chapters):
                ch = chapters[i]
                return (ch["start_word_id"], ch["end_word_id"])

    # Check by keyword match
    for ch in chapters:
        keywords = [kw.lower() for kw in ch.get("keywords", [])]
        title = (ch.get("title") or "").lower()
        if any(kw in hint_lower for kw in keywords) or hint_lower in title:
            return (ch["start_word_id"], ch["end_word_id"])

    return None


# ── Semantic search via fastembed ──────────────────────────────────────────────

def _semantic_search(
    transcript: Transcript,
    topic: str,
    analysis: Optional[Dict[str, Any]] = None,
) -> List[MatchSpan]:
    """
    Find semantically similar sentences to the topic query using fastembed.
    Returns MatchSpan list, or empty list if fastembed is unavailable.
    """
    try:
        from fastembed import TextEmbedding  # type: ignore
        import numpy as np
        import os

        model_name = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
        embedder = TextEmbedding(model_name=model_name)

        # Embed the query
        query_emb = list(embedder.embed([topic]))[0]

        # Build sentence chunks from transcript words
        sentences = _build_sentences(transcript)
        if not sentences:
            return []

        texts = [s["text"] for s in sentences]
        sent_embs = np.array(list(embedder.embed(texts)))

        # Cosine similarity
        query_norm = np.linalg.norm(query_emb)
        if query_norm == 0:
            return []

        sims = sent_embs @ query_emb / (
            np.linalg.norm(sent_embs, axis=1) * query_norm + 1e-10
        )

        # Threshold: 0.6 similarity
        threshold = float(os.environ.get("EMBED_SIMILARITY_THRESHOLD", "0.6"))
        matches = []
        for i, sim in enumerate(sims):
            if sim >= threshold:
                s = sentences[i]
                matches.append(MatchSpan(
                    match_index=len(matches) + 1,
                    word_start=s["first_word"],
                    word_end=s["last_word"],
                    phrase_text=s["text"],
                    context_text=s["text"],
                    src_start_us=s["start_us"],
                    src_end_us=s["end_us"],
                    speaker=s["first_word"].speaker or "",
                    confidence=float(s["first_word"].confidence or 0.9),
                    score=float(sim),
                ))

        # Sort by start time, deduplicate overlapping spans
        matches.sort(key=lambda m: m.src_start_us)
        return _deduplicate_spans(matches)

    except (ImportError, Exception):
        return []


def _build_sentences(transcript: Transcript) -> List[Dict[str, Any]]:
    """Group transcript words into sentence chunks (same logic as topics.py)."""
    sentences = []
    current = []
    PAUSE_US = 800_000

    words = transcript.words
    for i, w in enumerate(words):
        current.append(w)
        is_eos = w.text.strip().endswith((".", "?", "!"))
        if i < len(words) - 1:
            long_pause = (words[i + 1].start_us - w.end_us) >= PAUSE_US
        else:
            long_pause = True

        if is_eos or long_pause:
            if current:
                sentences.append({
                    "text": " ".join(cw.text for cw in current),
                    "first_word": current[0],
                    "last_word": current[-1],
                    "start_us": current[0].start_us,
                    "end_us": current[-1].end_us,
                })
                current = []

    if current:
        sentences.append({
            "text": " ".join(cw.text for cw in current),
            "first_word": current[0],
            "last_word": current[-1],
            "start_us": current[0].start_us,
            "end_us": current[-1].end_us,
        })

    return sentences


def _deduplicate_spans(spans: List[MatchSpan]) -> List[MatchSpan]:
    """Remove overlapping spans, keeping the highest-score one."""
    if not spans:
        return []

    result = [spans[0]]
    for span in spans[1:]:
        last = result[-1]
        # Overlapping if this span starts before last one ends
        if span.src_start_us < last.src_end_us:
            if span.score > last.score:
                result[-1] = span
        else:
            result.append(span)
    return result
