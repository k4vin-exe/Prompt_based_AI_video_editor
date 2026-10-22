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
