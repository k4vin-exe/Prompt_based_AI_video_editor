"""
perception/topics.py
--------------------
Chapter / topic segmentation of a transcript.

Uses fastembed (bge-small-en-v1.5, Apache 2.0) to embed each sentence,
then TextTiling / cosine-similarity drop to find topic boundaries.
Optionally calls LLM to name each chapter.

Output: list of Chapter dicts
  {
    "chapter_id": int,
    "title": str | None,
    "start_word_id": str,   # e.g. "w0042"
    "end_word_id": str,
    "start_us": int,
    "end_us": int,
    "keywords": [str]
  }
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple


@dataclass
class Chapter:
    chapter_id: int
    title: Optional[str]
    start_word_id: str
    end_word_id: str
    start_us: int
    end_us: int
    keywords: List[str]

    def to_dict(self) -> dict:
        return asdict(self)


def segment_topics(
    words: List[Dict[str, Any]],
    min_chapter_words: int = 30,
    similarity_threshold: float = 0.75,
    llm_adapter=None,
) -> List[Chapter]:
    """
    Segment the transcript words into thematic chapters.

    Args:
        words:                  Word dicts with text, start_us, end_us.
        min_chapter_words:      Minimum words per chapter (avoids micro-chapters).
        similarity_threshold:   Cosine similarity below which a new chapter starts.
        llm_adapter:            Optional LLM adapter to generate chapter titles.

    Returns:
        List of Chapter dataclass instances.
    """
    if not words:
        return []

    # Group words into sentences (split on long pauses or end-of-sentence punctuation)
    sentences = _split_into_sentences(words)
    if len(sentences) < 2:
        return [_make_chapter(0, words, words, words, None)]

    # Embed sentences
    embeddings = _embed_sentences(sentences)

    if embeddings is None or len(embeddings) < 2:
        # Fallback: single chapter
        return [_make_chapter(0, sentences[0]["words"], sentences[-1]["words"], words, None)]

    # Find boundaries via cosine similarity drops
    boundaries = _find_boundaries(embeddings, similarity_threshold, sentences, min_chapter_words)

    # Build chapters
    chapters = _build_chapters(sentences, boundaries, words, llm_adapter)
    return chapters


def _split_into_sentences(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Group consecutive words into sentence-level chunks.
    Returns list of {"words": [...], "text": str, "start_us": int, "end_us": int}.
    """
    sentences = []
    current: List[Dict[str, Any]] = []
    PAUSE_US = 800_000  # 0.8 s → new sentence

    for i, w in enumerate(words):
        current.append(w)
        # Sentence boundary: end-of-sentence punctuation or long pause to next word
        text = w["text"].strip()
        is_eos = text.endswith((".", "?", "!"))
        if i < len(words) - 1:
            next_gap = words[i + 1]["start_us"] - w["end_us"]
            long_pause = next_gap >= PAUSE_US
        else:
            long_pause = True

        if is_eos or long_pause:
            if current:
                sentences.append({
                    "words": current,
                    "text": " ".join(cw["text"] for cw in current),
                    "start_us": current[0]["start_us"],
                    "end_us": current[-1]["end_us"],
                })
                current = []

    if current:
        sentences.append({
            "words": current,
            "text": " ".join(cw["text"] for cw in current),
            "start_us": current[0]["start_us"],
            "end_us": current[-1]["end_us"],
        })

    return sentences


def _embed_sentences(sentences: List[Dict[str, Any]]):
    """
    Embed sentence texts using fastembed bge-small-en-v1.5 (Apache 2.0).
    Returns numpy array of shape (N, D), or None if fastembed not available.
    """
    try:
        from fastembed import TextEmbedding  # type: ignore
        import numpy as np

        model_name = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
        embedder = TextEmbedding(model_name=model_name)
        texts = [s["text"] for s in sentences]
        embeddings = list(embedder.embed(texts))
        return np.array(embeddings)

    except ImportError:
        return None
    except Exception:
        return None


def _cosine_similarity(a, b) -> float:
    """Cosine similarity between two numpy vectors."""
    import numpy as np
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _find_boundaries(
    embeddings,
    threshold: float,
    sentences: List[Dict[str, Any]],
    min_chapter_words: int,
) -> List[int]:
    """
    Return indices in sentences where a new chapter starts (always includes 0).
    A boundary is placed where cosine similarity to the next sentence drops below threshold
    AND enough words have accumulated since the last boundary.
    """
    boundaries = [0]
    words_since_last = sum(len(s["words"]) for s in sentences[:1])

    for i in range(1, len(embeddings)):
        sim = _cosine_similarity(embeddings[i - 1], embeddings[i])
        if sim < threshold and words_since_last >= min_chapter_words:
            boundaries.append(i)
            words_since_last = len(sentences[i]["words"])
        else:
            words_since_last += len(sentences[i]["words"])

    return boundaries


def _build_chapters(
    sentences: List[Dict[str, Any]],
    boundaries: List[int],
    all_words: List[Dict[str, Any]],
    llm_adapter=None,
) -> List[Chapter]:
    """Convert boundary indices into Chapter objects."""
    chapters = []
    boundary_set = sorted(set(boundaries))

    for ch_idx, start_sent_idx in enumerate(boundary_set):
        end_sent_idx = (
            boundary_set[ch_idx + 1] - 1 if ch_idx + 1 < len(boundary_set)
            else len(sentences) - 1
        )

        chapter_sents = sentences[start_sent_idx:end_sent_idx + 1]
        if not chapter_sents:
            continue

        ch_words_flat = [w for s in chapter_sents for w in s["words"]]
        if not ch_words_flat:
            continue

        keywords = _extract_keywords(ch_words_flat, top_n=5)
        title = None
        if llm_adapter is not None:
            title = _ask_llm_for_title(llm_adapter, chapter_sents, keywords)

        chapters.append(Chapter(
            chapter_id=ch_idx,
            title=title or (", ".join(keywords[:3]) if keywords else f"Chapter {ch_idx + 1}"),
            start_word_id=ch_words_flat[0].get("id", f"w{0:04d}"),
            end_word_id=ch_words_flat[-1].get("id", f"w{0:04d}"),
            start_us=ch_words_flat[0]["start_us"],
            end_us=ch_words_flat[-1]["end_us"],
            keywords=keywords,
        ))

    return chapters


def _make_chapter(
    chapter_id: int,
    first_words: List[Dict[str, Any]],
    last_words: List[Dict[str, Any]],
    all_words: List[Dict[str, Any]],
    llm_adapter,
) -> Chapter:
    """Convenience helper for single-chapter videos."""
    keywords = _extract_keywords(all_words, top_n=5)
    return Chapter(
        chapter_id=chapter_id,
        title=", ".join(keywords[:3]) if keywords else "Main",
        start_word_id=all_words[0].get("id", "w0000") if all_words else "w0000",
        end_word_id=all_words[-1].get("id", "w0000") if all_words else "w0000",
        start_us=all_words[0]["start_us"] if all_words else 0,
        end_us=all_words[-1]["end_us"] if all_words else 0,
        keywords=keywords,
    )


def _extract_keywords(words: List[Dict[str, Any]], top_n: int = 5) -> List[str]:
    """Extract top_n most frequent non-stop-words from word list."""
    STOP = {
        "the", "a", "an", "is", "are", "was", "were", "i", "we", "you", "he", "she", "it",
        "they", "and", "or", "but", "in", "on", "at", "to", "of", "for", "with", "that",
        "this", "so", "um", "uh", "like", "just", "know", "yeah", "okay", "well",
    }
    freq: Dict[str, int] = {}
    for w in words:
        t = re.sub(r"[^\w]", "", w["text"].lower())
        if t and t not in STOP and len(t) > 2:
            freq[t] = freq.get(t, 0) + 1

    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:top_n]]


def _ask_llm_for_title(
    llm_adapter,
    sentences: List[Dict[str, Any]],
    keywords: List[str],
) -> Optional[str]:
    """Ask LLM for a short chapter title (2-5 words). Gracefully returns None on failure."""
    try:
        excerpt = " ".join(s["text"] for s in sentences[:4])[:500]
        kw = ", ".join(keywords)
        system = "You are a chapter-title generator for a video transcript. Reply with ONLY a 2-5 word title."
        user = f"Keywords: {kw}\nExcerpt: {excerpt}"
        raw = llm_adapter.complete(system, user)
        title = raw.strip().strip('"').strip("'")
        if len(title) > 60:
            title = title[:60]
        return title
    except Exception:
        return None
