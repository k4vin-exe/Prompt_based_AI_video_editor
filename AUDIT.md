# AUDIT.md — Step 0 Repo Audit
Generated: 2026-10-24
Scope: full repo against BRIEF.pdf.

## A. What Already Satisfies the Brief

| Component | Files | Brief Requirement |
|-----------|-------|-------------------|
| Event-sourced history | engine/history.py | Must-have 1,4 — append-only, undo/redo/revoke |
| Timeline fold (pure fn) | engine/timeline.py | Must-have 4 — deterministic, same ops = same hash |
| Content anchoring | engine/timeline.py _resolve_captions() | Must-have 2 — captions to word IDs not timestamps |
| Source-time ops | engine/ops.py | Must-have 2 — CutOp,SpeedOp store source µs |
| timeline_hash | engine/timeline.py | Must-have 4 — sha256 canonical JSON |
| Render | engine/render.py | Must-have 5 — FFmpeg A/V render |
| Three-way answers | engine/answer.py, engine/session.py | Must-have 3 |
| Clarification flow | engine/session.py | Must-have 3 — topic ? question ? ordinal reply |
| Filler detection | engine/filler.py | Must-have 6 |
| Silence detection | engine/silence.py | Must-have 6 |
| Time policy | nlu/parser.py, engine/timemap.py | Must-have 7 |
| Transcript data model | engine/transcript.py | Immutable Word+Transcript, w0000 IDs |
| Video probe | engine/probe.py | ffprobe/ffmpeg, VFR detection |
| OTIO export | engine/otio_export.py | Outstanding level |
| STT adapter base+mock | nlu/adapters/stt_base.py, stt_mock.py | Integration Std §3 |
| LLM adapter base+mock | nlu/adapters/llm_base.py, llm_mock.py | Integration Std §3, cassette replay |
| Intent schema | nlu/intent_schema.py | Must-have 4 — validated JSON |
| Phrase/topic search | nlu/search.py | Advanced level — synonym map |
| REST API + OpenAPI | api/ | Integration Std §2 |
| Background jobs | api/jobs.py | Integration Std §3 — 202+job_id |
| Idempotency key | api/routes.py | Integration Std §4 |
| S3/MinIO storage | api/state.py, docker-compose | Integration Std §7 |
| Health/ready | api/app.py | Integration Std §8 |
| 15 scenario YAMLs | tests/scenarios/ | Outstanding proof |
| Session runner CLI | cli/ | Brief §Session runner |
| Env config | api/config.py, .env.example | Integration Std §6 |

## B. What Is Wrong / Missing

### B1. NLU Parser — Regex/Rule-Based (WRONG)
File: nlu/parser.py
380 lines of pure regex/keyword matching. Only handles hard-coded patterns.
LLM fallback (_llm_parse) is wired but session.py calls parse_instruction(text)
with NO llm_adapter — the LLM path is never exercised.
Decision: DEMOTE regex to fast-path fallback; make LLM the PRIMARY intent translator.

### B2. No Real STT Adapter
faster-whisper is in requirements.txt but no WhisperSTTAdapter exists.
Only MockSTTAdapter exists.
Decision: ADD nlu/adapters/stt_whisper.py

### B3. No Perception Pipeline
No pipeline computing: silence segments (VAD), diarization, topic/chapter
segmentation, fastembed embedding index. No analysis.json cached per source.
Decision: ADD perception/pipeline.py + supporting modules.

### B4. No Real LLM Adapters
nlu/adapters/ has only llm_mock.py. No Gemini, Groq, Ollama.
No factory selecting by LLM_ADAPTER env var.
Decision: ADD llm_gemini.py, llm_groq.py, llm_ollama.py; factory in __init__.py.

### B5. No Grounding Resolver
LLM returns params like {"topic":"pricing"} or {"phrase":"welcome to the channel"}.
These must be resolved to word-ID spans before creating ops.
No context pack (speaker list, chapters, history summary) sent to LLM.
Decision: ADD nlu/grounding.py, nlu/context.py.

### B6. No LLM Record/Replay Mode
live | record | replay cache mode absent. LLM_CACHE_MODE env var missing.
Decision: ADD caching layer in adapter factory.

### B7. No Paraphrase Test Suite
No tests verifying 4-5 paraphrases of each operation map to the same intent.
Decision: ADD tests/unit/test_nlu_paraphrase.py.

## C. Keep/Rewrite/Delete Table

| Item | Decision |
|------|----------|
| engine/timeline.py | KEEP — perfect |
| engine/history.py | KEEP — perfect |
| engine/ops.py | KEEP |
| engine/transcript.py | KEEP |
| engine/session.py | KEEP + inject LLM adapter and analysis |
| engine/filler.py | KEEP |
| engine/silence.py | KEEP |
| engine/timemap.py | KEEP |
| engine/answer.py | KEEP |
| engine/probe.py | KEEP |
| engine/render.py | KEEP |
| engine/otio_export.py | KEEP |
| nlu/parser.py | DEMOTE to fast-path fallback |
| nlu/intent_schema.py | KEEP |
| nlu/search.py | KEEP + add embedding search |
| nlu/timeparse.py | KEEP |
| nlu/adapters/stt_base.py | KEEP |
| nlu/adapters/stt_mock.py | KEEP |
| nlu/adapters/llm_base.py | KEEP |
| nlu/adapters/llm_mock.py | KEEP |
| api/ (all) | KEEP |
| tests/scenarios/*.yaml | KEEP |

## D. Build Plan

Step 1: Perception pipeline (faster-whisper STT, energy VAD, diarization,
        fastembed topics, analysis.json cache)
Step 2: LLM adapters + factory (Gemini, Groq, Ollama, record/replay)
Step 3: Grounding resolver + context pack
Step 4: Wire: LLM primary, regex fallback, inject context in session
Step 5: Paraphrase test suite
Step 6: REPORT.md, RULES.md, SOURCES.md updates
