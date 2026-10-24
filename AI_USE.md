# AI_USE.md — AI Tool Usage Disclosure

As required by the brief (Tools section), every AI coding tool used is documented here.

---

## Tools Used

| Tool | Purpose | What it did | What I verified |
|------|---------|-------------|-----------------|
| **Antigravity / Claude Sonnet / Gemini Flash** | Code generation & pairing | Generated source implementations according to architectural specifications and test contracts | Every function, class, and pipeline verified with unit/integration tests (105 tests passing); live demo verified in browser; can explain and modify every line live |

---

## What AI generated (and what I specified)

### Specifications I wrote (not AI):
- Core architecture decisions (event-sourced history, content anchoring with immutable word ID spans, `fold()` pure function)
- Complete design rules in `docs/RULES.md` (time policies, filler detection rules, silence rules, ASS subtitle rendering rules)
- Comprehensive test scenarios (15 scenarios covering hard edge cases)
- OpenAPI 3.1 contract and FastAPI route specifications
- Interactive Web Demo UI layout and interaction requirements

### What AI generated from my spec:
- Core engine implementations (`engine/transcript.py`, `ops.py`, `history.py`, `timeline.py`, `timemap.py`, `answer.py`, `probe.py`, `render.py`, `otio_export.py`)
- NLU parsers and intent schema validation (`nlu/`)
- CLI session runner (`cli/runner.py`) and batch determinism runner (`cli/batch.py`)
- FastAPI containerised service (`api/`) and OpenAPI 3.1 export
- Interactive dark-mode Web UI (`web/index.html`, `index.css`, `app.js`)
- Test suites (`tests/unit/`, `tests/integration/`)

### What I caught, corrected, and logged in FAILURES.md:
1. `_WORD_TO_INT` missing compound numbers — caused "a minute twenty" to parse as 60s not 80s.
2. PowerShell command separator issues (`;` vs `&&`).
3. Regex pattern ordering — "cut everything" matching topic search instead of whole-video cut.
4. "Put X back" pattern handling — supporting non-contiguous phrases ("put the intro back").
5. `RevokeOp` filtering in `fold()` — ensuring event-sourced revocations correctly re-activate earlier cuts.
6. FFmpeg concat pad interleaving — alternating `[v0][a0][v1][a1]...` pads to avoid media type mismatches.
7. Re-entrant undo groups in multi-part instructions — added `_group_depth` counter to prevent premature commits.
8. Time bounds checking on short test videos — adapting default word spans to video duration.

---

## Guarantees

- I can explain every function, class, algorithm, and design decision live in detail.
- All AI-generated code is thoroughly tested (105 passing automated tests; 100.0% determinism across 3 runs).
- Zero non-commercial or AGPL dependencies in the core shipped service.
- All timeline folding logic is pure deterministic Python; LLMs only parse text to validated JSON schema.

---
*Last updated: Phase 5 (Project Complete)*

