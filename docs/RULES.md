# IncuBrix Editing Engine — Rules Reference

This file is the **single source of truth** for every rule the engine enforces.
Every rule listed here is implemented in deterministic code (never by an LLM).
The code cites the rule number in a comment; if a rule changes here, the code must change too.

---

## R-TIME: Time Expression Parsing

| ID | Rule |
|----|------|
| R-TIME-01 | All time expressions are resolved at instruction time, before any operation is applied. |
| R-TIME-02 | **Default time policy: `current_edited`**. A time like "1:20" or "80 seconds" refers to 1 minute 20 seconds into the **currently edited video** (i.e. after all active cuts, speed changes, and reorders). Every answer that resolves a time states: *"Using current-edited-time policy."* |
| R-TIME-03 | Override with the phrase "in the original" or "in the source": e.g. "at 1:20 in the original". This uses `original_source` policy. Every answer states: *"Using original-source-time policy."* |
| R-TIME-04 | After resolving to a current-edited time, the engine maps that position to the underlying **word ID span** (or nearest inter-word gap for cut boundaries). This anchor is stored, not the clock time. |
| R-TIME-05 | Supported time expression formats (all converted to integer microseconds): M:SS, H:MM:SS, N seconds, N minutes, N mins, a minute twenty (natural language), the last N seconds, the first N seconds, the last N minutes, the first N minutes. |
| R-TIME-06 | "The last N seconds" is resolved relative to the **current edited duration** at instruction time. |
| R-TIME-07 | "The first N seconds/minutes" is resolved from t=0 of the current edited video. |
| R-TIME-08 | Fractional seconds are rounded to the nearest microsecond (integer). |

---

## R-ANCHOR: Content Anchoring

| ID | Rule |
|----|------|
| R-ANCHOR-01 | Every operation is anchored to a **word-ID span** [word_id_start, word_id_end) or a **source range** [src_start_us, src_end_us) in integer microseconds. Clock positions are never stored in operations. |
| R-ANCHOR-02 | Word IDs are assigned at transcription time and are **immutable** for the lifetime of the project. Format: wN where N is a zero-padded integer (e.g. w0000, w0001). |
| R-ANCHOR-03 | Cut boundaries are snapped to the nearest **inter-word gap** (silence between words). The gap is defined as [word[i].end_us, word[i+1].start_us]. If VAD is enabled, boundaries also snap to the deepest energy valley within the gap. |
| R-ANCHOR-04 | The mapping from current-edited time to word anchor is performed by engine.timemap.map_edited_to_source(). This is a pure function of the current timeline fold. |

---

## R-HISTORY: Event-Sourced History

| ID | Rule |
|----|------|
| R-HIST-01 | Operations are **append-only**. The source transcript is never modified. |
| R-HIST-02 | One instruction = one undo group. An undo group may contain multiple atomic operations (e.g. a three-part instruction). |
| R-HIST-03 | timeline = fold(base_transcript, active_ops) where active_ops is the ordered list of non-revoked operations. This is a **pure function**: same inputs = same output, no side effects. |
| R-HIST-04 | Undo moves the undo pointer back one group (marks ops as revoked). Redo moves it forward. A new edit (any non-undo/redo instruction) clears the redo stack. |
| R-HIST-05 | "Restore a specific earlier edit" revokes only that op (by ID), leaving all others active, then re-folds. The revocation is itself an operation in the history (so it can be undone). |
| R-HIST-06 | timeline_hash = sha256(canonical_json) where canonical_json has: sorted keys, integer microsecond times, counter-based operation IDs (never UUIDs or timestamps). Same session x3 runs must produce identical hashes. |

---

## R-OPS: Operation Rules

### R-CUT: Cut / Keep

| ID | Rule |
|----|------|
| R-CUT-01 | cut(start, end) removes the source range [start_us, end_us). Anchors are word spans. |
| R-CUT-02 | **Reject whole-video cut**: if the cut would remove >= 99% of the current timeline duration, the instruction is rejected with code WHOLE_VIDEO_CUT. |
| R-CUT-03 | Out-of-range cut: if either boundary falls outside [0, current_duration], reject with TIME_OUT_OF_RANGE. |
| R-CUT-04 | Duplicate cut: if an identical (start_us, end_us) cut is already active in the history, reject with DUPLICATE_OPERATION and cite the earlier op ID. |
| R-CUT-05 | Cut boundaries snap to the nearest inter-word gap (see R-ANCHOR-03). The snapped position is reported in the answer summary. |
| R-CUT-06 | Partial cut of a captioned phrase: if a cut removes some but not all words of a caption's word span, the caption's anchor is updated to the surviving words. If no words survive, the caption is hidden (status: hidden_no_words) and the user is warned. The caption is restored if the cut is undone. |

### R-SPEED: Speed Change

| ID | Rule |
|----|------|
| R-SPEED-01 | Valid speed range: [0.25x, 4.0x] inclusive. Outside this range -> reject SPEED_OUT_OF_RANGE. |
| R-SPEED-02 | Overlapping speed changes: **last-writer-wins with range splitting**. If a new speed range [A, B] overlaps an existing speed range [C, D], the existing range is split into [C, A) and (B, D] (one or both may be empty and are dropped). The new range [A, B] is applied at the new speed. This is deterministic. |
| R-SPEED-03 | A sped-up caption must display for at least **0.7 seconds** after the speed-up is applied. If the sped-up duration < 0.7 s, the caption display window is extended to 0.7 s. A warning is included in the answer. |

### R-MUTE / R-BLEEP: Mute and Bleep

| ID | Rule |
|----|------|
| R-MUTE-01 | mute(word_ids) silences the audio for those word spans. The word IDs are the anchor. |
| R-BLEEP-01 | bleep(word_ids) replaces audio with a 1 kHz sine tone for exactly the duration of the word span. |
| R-BLEEP-02 | Low-confidence words (confidence < 0.5) are flagged in the manifest but are **never auto-bleeped**. The user must explicitly request it. |

### R-FILLER: Filler Word Removal

| ID | Rule |
|----|------|
| R-FILLER-01 | Filler words: um, uh, and like (only when used as a filler, see R-FILLER-02). |
| R-FILLER-02 | **"like" filler rule (deterministic)**: A word "like" is classified as a filler if BOTH: (a) the word before OR after it has a pause gap >= FILLER_LIKE_MIN_PAUSE_S (default 0.15 s), AND (b) the word is not at a sentence-final position. Uses only word timing data; no ML model. |
| R-FILLER-03 | Filler removal **never cuts into** a word with an active mute or bleep. If conflict detected, skip that filler and warn. |
| R-FILLER-04 | Filler removal is implemented as a series of cut operations (one per filler instance), each anchored to that word's source span. |

### R-SILENCE: Silence Removal

| ID | Rule |
|----|------|
| R-SIL-01 | remove_silences(threshold_s) removes all inter-word gaps >= threshold_s seconds from the source. |
| R-SIL-02 | **Deliberate pause detection**: a silence after a sentence-ending word (followed by punctuation . ? !) is preserved. These are never removed; a warning lists which pauses were preserved. |
| R-SIL-03 | Minimum silence threshold: 0.5 s. Below this, reject with SILENCE_THRESHOLD_TOO_LOW. |

### R-CAPTION: Captions and Text Overlays

| ID | Rule |
|----|------|
| R-CAP-01 | Every caption is anchored to a word-ID span [word_id_start, word_id_end). Its display time is computed from the current fold. |
| R-CAP-02 | auto_caption() creates one caption per word (or per phrase if chunked), anchored to each word span. |
| R-CAP-03 | restyle_caption(caption_id, style) updates style of a specific caption. Caption IDs are stable counter-based integers. |
| R-CAP-04 | Reference resolution for "that caption": use the most recently added/modified caption if exactly one. If zero or ambiguous, ask for clarification. |
| R-CAP-05 | Minimum caption display duration: 0.7 s (see R-SPEED-03). |

### R-MUSIC: Background Music

| ID | Rule |
|----|------|
| R-MUSIC-01 | Background music ducks to duck_level_db (default: -18 dB) during speech intervals from the transcript. |
| R-MUSIC-02 | Speech intervals: [word.start_us - 200ms, word.end_us + 200ms], merged if overlapping. |
| R-MUSIC-03 | Outside speech intervals, music plays at 0 dB. |
| R-MUSIC-04 | Music files must be public domain or CC-BY (no NC). Stated in manifest. |

---

## R-CLARIFY: Clarification and Rejection Rules

| ID | Rule |
|----|------|
| R-CL-01 | **Never guess on destructive operations**. Ambiguity on cut/mute/bleep -> needs_clarification. |
| R-CL-02 | "Remove everything after I say X" with N > 1 matches -> needs_clarification with list. N=1 -> apply. |
| R-CL-03 | Two-speaker remove: remove only the identified speaker, then ask about host lead-in. |
| R-CL-04 | Semantic search results are shown before any cut is applied. |
| R-CL-05 | Multi-part instructions: apply valid parts, report each, all applied parts = one undo group. |
| R-CL-06 | needs_clarification always includes: question (string), options (list with timestamps). |

---

## R-RENDER: Rendering Rules

| ID | Rule |
|----|------|
| R-REND-01 | Rendering is a separate step from editing. |
| R-REND-02 | **Frame-rounding rule**: frame = floor(time_s * fps + 0.5), rounded_time_s = frame / fps. Applied at render time only; not stored. |
| R-REND-03 | A/V sync within 1 frame. Verified by Sync Oracle. |
| R-REND-04 | Rendered length equals timeline length within 1 frame. |
| R-REND-05 | VFR sources: if VFR detected and cannot render, fail with VFR_NOT_SUPPORTED. |
| R-REND-06 | No-audio sources: audio ops skipped with warning; video still renders. |

---

## R-SPEAKER: Multi-Speaker Rules

| ID | Rule |
|----|------|
| R-SPK-01 | Speaker labels: speaker_0, speaker_1, etc. (zero-indexed). |
| R-SPK-02 | Speaker swap warning: adjacent segments < 0.5 s apart with speaker change -> warn POSSIBLE_SPEAKER_SWAP. |
| R-SPK-03 | Overlapping speech warning: words from different speakers with overlapping spans -> warn OVERLAPPING_SPEECH. |

---

## R-REJECT: Error Codes

| Code | Condition |
|------|-----------|
| WHOLE_VIDEO_CUT | Cut removes >= 99% of current timeline |
| TIME_OUT_OF_RANGE | Time outside [0, current_duration] |
| SPEED_OUT_OF_RANGE | Speed outside [0.25, 4.0] |
| DUPLICATE_OPERATION | Identical operation already active |
| SILENCE_THRESHOLD_TOO_LOW | Threshold < 0.5 s |
| VFR_NOT_SUPPORTED | Variable frame rate, cannot render |
| CAPTION_NO_WORDS | Caption words all removed |
| NO_MATCH | Search found no matches |
| AMBIGUOUS_REFERENCE | Reference matches multiple candidates |
| FILLER_BLEEP_CONFLICT | Filler removal conflicts with bleep/mute |
| NO_UNDO_AVAILABLE | History at beginning |
| NO_REDO_AVAILABLE | No revoked ops to restore |
| OPERATION_NOT_FOUND | Restore: op ID not found |
| INVALID_SPEED | Speed not a positive number |
| TIME_PARSE_ERROR | Time expression unparseable |

---

*Last updated: Phase 0. Confirmed before coding begins.*
