# Failures Log

This file records failed attempts honestly, as required by the brief.
Format: date | what failed | root cause | resolution

---

## 2026-10-22 — Phase 0

### Attempt 1: pdfplumber via PowerShell && operator
- **What failed**: `pip install pdfplumber -q && python -c ...` in PowerShell
- **Root cause**: PowerShell uses `;` not `&&` for command chaining
- **Resolution**: Split into two separate commands

### Attempt 2: RULES.md as artifact path
- **What failed**: Tried to write docs/RULES.md as an `ArtifactMetadata` file
- **Root cause**: Artifact files must be under the app data brain directory; project files are not artifacts
- **Resolution**: Wrote without ArtifactMetadata for project files

### Attempt 3: Natural language time parser — "a minute twenty"
- **What failed**: `parse_time("a minute twenty")` returned 60s instead of 80s
- **Root cause**: `_WORD_TO_INT` only had 1-10; "twenty" mapped to None → `int("twenty")` fails → extra=0
- **Resolution**: Added eleven–sixty to `_WORD_TO_INT`; verified 68/68 tests pass

---

## 2026-10-22 — Phase 1

### Attempt 4: "Actually, put the intro back" regex
- **What failed**: NLU parser returned `unknown` for "Actually, put the intro back".
- **Root cause**: Regex looked for contiguous `put\s+back\s+(.+)`, failing when the target phrase sits between "put" and "back" ("put [the intro] back").
- **Resolution**: Updated pattern to `(?:put\s+(.+?)\s+back|put\s+back\s+(.+)|restore\s+(.+)|bring\s+back\s+(.+))`.

### Attempt 5: Whole-video cut vs remove topic precedence
- **What failed**: "cut everything" was categorized as `remove_topic` with topic `"everything"`, returning `NO_MATCH` instead of `WHOLE_VIDEO_CUT`.
- **Root cause**: `remove_topic` regex was evaluated before the whole-video cut check.
- **Resolution**: Reordered rules so whole-video cut phrases are matched prior to general topic extraction.

### Attempt 6: RevokeOp handling in timeline fold()
- **What failed**: At Step 5 of the worked example ("Actually, put the intro back"), the timeline duration did not increase.
- **Root cause**: `RevokeOp` was appended to history, but `fold()` did not filter out ops targeted by active `RevokeOp`s.
- **Resolution**: Added step 0 in `fold()` to compute `effective_ops` by excluding any op targeted by an active `RevokeOp`, implementing true event-sourced revocation.

---

## 2026-10-22 — Phase 2

### Attempt 7: FFmpeg concat filter pad ordering
- **What failed**: `render_timeline` raised `RuntimeError: Media type mismatch between 'Parsed_asetpts_3' (audio) and 'Parsed_concat_8' input pad 2 (video)`.
- **Root cause**: Input tags to `concat=n=N:v=1:a=1` were grouped as all video then all audio (`[v0][v1][a0][a1]`). FFmpeg requires alternating video and audio pads per segment (`[v0][a0][v1][a1]...`).
- **Resolution**: Changed tag generation to `"".join(f"[v{i}][a{i}]" for i in range(num_segs))`. Verified render succeeds with 0.0 frames duration error.

---

## 2026-10-23 — Phase 3

### Attempt 8: Nested undo groups in multi-part instructions
- **What failed**: Running batch session with multi-part instruction (`cut the first 10 seconds and speed up from 1:00 to 1:30 by 2x`) raised `RuntimeError: end_group() called without begin_group()`.
- **Root cause**: `_execute_multi_instruction` opened an undo group, but the sub-intent handlers (`_handle_cut`, `_handle_speed`) also called `begin_group` and `commit_group`. The first sub-handler's `commit_group()` closed the undo group prematurely.
- **Resolution**: Refactored `History` to support re-entrant undo groups using `_group_depth` counter. Sub-operations inside a multi-part instruction now seamlessly attach to the outer undo group, ensuring single-step atomic undo (R-HIST-02, R-CL-05). Verified 100% determinism across all 15 scenarios.

---

## 2026-10-23 — Phase 4

### Attempt 9: Background render pipeline argument mismatch
- **What failed**: Background render job failed with `TypeError: render_timeline() got an unexpected keyword argument 'output_path'`.
- **Root cause**: `api/jobs.py` passed keyword argument `output_path`, whereas `engine/render.py` declared parameter `output_video_path`.
- **Resolution**: Aligned parameter name to `output_video_path` in `api/jobs.py`.

### Attempt 10: BeforeAfter attribute name mismatch in API routes
- **What failed**: `POST /api/v1/projects/{id}/instructions` returned 500 with `AttributeError: 'BeforeAfter' object has no attribute 'before_duration_s'`.
- **Root cause**: `engine/answer.py` stores microsecond integers (`duration_us_before`, `duration_us_after`), while `api/routes.py` attempted to access `.before_duration_s` directly.
- **Resolution**: Updated `api/routes.py` to divide microsecond integers by `1_000_000` and construct `BeforeAfterModel`. Verified all integration tests pass.

---
