# AGENTS.md — AI Agent Guide for IncuBrix Video Editor

> **Audience**: This guide is specifically written for AI Coding Assistants (Antigravity, Cursor, Claude Code, GitHub Copilot, Codex, ChatGPT) and automated agents inspecting or running this codebase after downloading/cloning.

---

## ⚡ 1. TL;DR — Run in 60 Seconds

### On Windows
```cmd
run.bat
```
*(Or manually):*
```powershell
copy .env.example .env
pip install -r requirements.txt
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```
Open **`http://127.0.0.1:8000/demo`** in your browser.

### On Linux / macOS
```bash
chmod +x run.sh && ./run.sh
```
*(Or manually):*
```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## 🔑 2. What to Add and Where to Add It

The only file you or your user needs to configure is **`.env`** in the root project directory:

```bash
# In the project root:
cp .env.example .env
```

### Choose ONE AI Provider:

| Provider | Cost | Recommended For | Required Keys in `.env` |
| :--- | :--- | :--- | :--- |
| **Option A: Groq (Recommended)** | **100% Free** (30 requests/min) | Ultra-fast STT + LLM reasoning | `LLM_ADAPTER=groq`<br>`STT_ADAPTER=groq`<br>`GROQ_API_KEY=gsk_...` (get free key at [console.groq.com/keys](https://console.groq.com/keys)) |
| **Option B: Google Gemini** | **100% Free** (15 requests/min) | Free cloud multimodal reasoning | `LLM_ADAPTER=gemini`<br>`GEMINI_API_KEY=...` (get free key at [aistudio.google.com](https://aistudio.google.com/)) |
| **Option C: Hugging Face** | **100% Free** Serverless | Open-source Qwen 72B | `LLM_ADAPTER=huggingface`<br>`HF_TOKEN=hf_...` (get free token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)) |
| **Option D: Ollama (100% Local)** | **Free & Offline** (Zero API keys) | Private, local offline editing | `LLM_ADAPTER=ollama`<br>`OLLAMA_BASE_URL=http://localhost:11434`<br>`LLM_OLLAMA_MODEL=llama3.2` |
| **Option E: Offline Mock (No Keys)** | **Zero Keys** | Instant local tests & unit tests | `LLM_ADAPTER=mock`<br>`STT_ADAPTER=mock` |

### System Prerequisites:
1. **Python 3.10 to 3.13** installed.
2. **FFmpeg**: Must be available on system `PATH` (or specified in `.env` via `FFMPEG_PATH=C:\path\to\ffmpeg.exe`).
   - Windows: `winget install Gyan.FFmpeg` or `choco install ffmpeg`
   - Ubuntu/Debian: `sudo apt install ffmpeg`
   - macOS: `brew install ffmpeg`

---

## 🏗️ 3. Architecture Overview & Core Invariants

### The Core Invariant
> **Edits attach to immutable transcript word spans (`w0000..wNNNN`), NEVER to raw clock times.**

- If a user cuts the first 10 seconds of a video, any captions, bleeps, or audio tracks placed later in the video **stick to their words** and never drift out of sync.
- The timeline fold is a pure, mathematical reduction:
  $$\text{Timeline} = \text{fold}(\text{Transcript}, \text{active\_ops})$$
- AI models (LLMs) are **strictly constrained** to parsing natural language instructions into validated JSON intents. They **never mutate timeline tracks directly**.
- Video rendering is performed locally via FFmpeg with `-movflags +faststart` to guarantee standard, immediate MP4 playback and browser compatibility.

### Pipeline Flow
```
User Video (.mp4)
      │
      ▼
Perception Pipeline (faster-whisper / Groq STT + VAD + Diarization)
      │
      ▼
Immutable Word Transcript [w0000..wNNNN]
      │
User Prompt ("Cut first 5s", "Add caption 'Welcome' at start", "Add captions fully")
      │
      ▼
NLU Parser (Fast Deterministic Rules + LLM Fallback) -> Validated Intent JSON
      │
      ▼
Session Coordinator (Applied / Clarification / Rejected answers)
      │
      ▼
Pure Timeline Fold (produces Canonical Timeline JSON & SHA-256 Hash)
      │
      ▼
Export & Render Pipeline (FFmpeg MP4 + OpenTimelineIO .otio + manifest.json)
      │
      ▼
Direct Local Export (Saved to C:\Users\<user>\Downloads\edited_video.mp4)
```

---

## 📂 4. Project Directory Structure

```
├── api/                     # FastAPI backend service
│   ├── app.py               # Application factory, CORS, error handling
│   ├── routes.py            # REST endpoints (/api/v1/projects, /instructions, /render, /download)
│   ├── state.py             # In-memory thread-safe project & job state
│   ├── jobs.py              # Background rendering worker & progress tracking
│   └── config.py            # Pydantic environment configuration (.env)
├── engine/                  # Deterministic Video Editing Engine
│   ├── timeline.py          # Pure fold function, segment slicing, captions
│   ├── session.py           # Session coordinator, undo/redo stack, word anchors
│   ├── render.py            # FFmpeg CLI execution pipeline (+faststart MP4)
│   ├── probe.py             # ffprobe video metadata extraction
│   ├── transcript.py        # Immutable transcript representation & search
│   └── otio_export.py       # OpenTimelineIO interchange export
├── nlu/                     # Natural Language Understanding
│   ├── parser.py            # Hybrid fast regex rule engine + LLM adapter
│   ├── time_parser.py       # Deterministic time parser ("first 30s", "1:30 to 2:00")
│   └── adapters/            # LLM & STT adapters (Groq, Gemini, HF, Ollama, Mock)
├── perception/              # Video Perception Pipeline
│   └── pipeline.py          # Audio extraction, STT, VAD silence detection, chapters
├── web/                     # Live Interactive Web Editor UI
│   ├── index.html           # Modern glassmorphism dark-mode video editor
│   ├── index.css            # Responsive styles & visual timeline layout
│   └── app.js               # Client state, timeline track renderer, MP4 download handler
├── tests/                   # Test Suite (186 unit & integration tests)
│   ├── unit/                # Parser, timeline, session, probe unit tests
│   ├── integration/         # API lifecycle, jobs, idempotency tests
│   └── scenarios/           # 15 YAML scripted editing benchmark scenarios
├── run.bat / run.sh         # One-click startup scripts
├── .env.example             # Documented template for environment variables
└── requirements.txt         # Python dependencies
```

---

## 🧪 5. Testing & Verification

Run the complete test suite (runs 100% offline with zero API keys required):

```bash
pytest tests/ -v
```

All 186 unit and integration tests should pass in under 5 seconds.

### Quick Health Verification
When the server is running on `http://127.0.0.1:8000`:
```bash
curl http://127.0.0.1:8000/ready
```
Returns:
```json
{
  "status": "ready",
  "stt_adapter": "groq",
  "llm_adapter": "groq",
  "ffmpeg_available": true
}
```

---

## 💡 6. Supported Natural Language Instructions

The editor supports natural prompts out of the box:

- **Cuts & Trims**:
  - *"Cut the first 5 seconds"*
  - *"Remove the part from 0:10 to 0:25"*
  - *"Cut the last 10 seconds"*
  - *"Remove the white screen at the end"* / *"Cut intro"*
- **Captions & Subtitles**:
  - *"Add captions fully"* / *"Auto caption the whole video"*
  - *"Add a caption 'Welcome!' at the start"*
  - *"Add caption 'Don't miss this' when I say subscribe"*
  - *"Make that caption red"* / *"Make caption bigger"*
- **Cleanups & Audio**:
  - *"Remove filler words"* (um, uh, like)
  - *"Remove silences longer than 2 seconds"*
  - *"Bleep the word [curse]"*
  - *"Speed up from 1:00 to 1:30 by 2x"*
- **Undo / Redo**:
  - *"Undo"* / *"Redo"* / *"Restore the intro"*

---

## 🚀 7. Production & Export Deliverables

When an edit is applied and rendered, the engine generates:
1. **`edited_video.mp4`**: A rendered H.264/AAC video with burned-in subtitles and cuts, automatically placed directly into the user's `Downloads` directory and `outputs/`.
2. **`final_timeline.otio`**: An industry-standard OpenTimelineIO file for import into Premiere Pro, DaVinci Resolve, or Final Cut Pro.
3. **`final_timeline.json`**: Exact canonical timeline metadata with SHA-256 hash.
4. **`manifest.json`**: Full reproducibility audit trail with metrics and timestamps.
