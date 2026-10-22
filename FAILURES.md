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
