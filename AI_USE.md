# AI_USE.md — AI Tool Usage Disclosure

As required by the brief (Tools section), every AI coding tool used is documented here.

---

## Tools Used

| Tool | Purpose | What it did | What I verified |
|------|---------|-------------|-----------------|
| **Antigravity / Claude Sonnet** | Primary code generation | Generated all source files from my specifications and architecture decisions | Every function verified by running tests; all 68 unit tests pass; I understand and can explain every line |

---

## What AI generated (and what I specified)

### Specifications I wrote (not AI):
- Architecture decisions (event-sourced history, content anchoring, fold() as pure function)
- All rules in RULES.md (time policy, filler detection rule, frame rounding rule)
- Test cases and expected values
- The 7 design decisions confirmed before build (time policy, filler rule, SQLite fallback, frame rounding, LLM adapter, STT adapter, git strategy)

### What AI generated from my spec:
- Python source code for all modules (engine/, nlu/, tests/)
- Directory structure
- Docker compose and Dockerfile
- .env.example with my specified settings
- requirements.txt with my specified library choices

### What I caught and corrected:
1. `_WORD_TO_INT` was missing twenty/thirty/forty/fifty/sixty — caused "a minute twenty" to parse as 60s not 80s. Fixed immediately; added to FAILURES.md.
2. Two PowerShell command separator issues (&&) — minor shell syntax corrections.
3. RULES.md was attempted as an artifact — corrected to write as a project file.

---

## Guarantees

- I can explain every function, class and design decision in a live session
- All AI-generated code is verified by tests before being committed
- No AI model builds the timeline directly — the fold() function and all timeline logic is deterministic Python code (verifiable by reading the source)
- LLM adapters only translate natural language to intent JSON; this boundary is enforced by interface design

---
*Last updated: Phase 0*
