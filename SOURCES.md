# SOURCES.md — All Models, Libraries, Media and Data Sources

Every model, library, dataset and media source used in this project is listed here.
All items in the default execution path must have a commercially-usable licence.

---

## Python Libraries

| Library | Version | Licence | Purpose |
|---------|---------|---------|---------|
| Python | 3.11+ | PSF-2.0 | Runtime |
| FastAPI | ≥0.111 | MIT | HTTP API framework |
| Uvicorn | ≥0.29 | BSD-3 | ASGI server |
| Pydantic | ≥2.7 | MIT | Data validation |
| SQLAlchemy | ≥2.0 | MIT | Database ORM |
| aiosqlite | ≥0.20 | MIT | SQLite async driver |
| asyncpg | ≥0.29 | Apache-2.0 | PostgreSQL async driver |
| Alembic | ≥1.13 | MIT | DB migrations |
| boto3 / aioboto3 | ≥1.34 / ≥13 | Apache-2.0 | S3-compatible storage |
| faster-whisper | ≥1.0 | MIT | STT (CPU, local) |
| groq | ≥0.9 | MIT | LLM + STT via Groq API |
| fastembed | ≥0.3 | Apache-2.0 | Embeddings (BGE-small) |
| jsonschema | ≥4.22 | MIT | Intent schema validation |
| pytest | ≥8.2 | MIT | Testing framework |
| hypothesis | ≥6.100 | MPL-2.0 | Property-based testing |
| pyyaml | ≥6.0 | MIT | Session YAML parsing |
| httpx | ≥0.27 | BSD-3 | Async HTTP client |
| python-multipart | ≥0.0.9 | Apache-2.0 | File uploads |
| python-dotenv | ≥1.0 | BSD-3 | .env loading |
| pdfplumber | ≥0.11 | MIT | Brief PDF extraction (dev only) |

## AI Models

| Model | Provider | Licence | Purpose | Cost |
|-------|----------|---------|---------|------|
| faster-whisper (base) | Systran (via HF) | MIT | STT (default) | Free/local |
| BGE-small-en-v1.5 | BAAI via fastembed | Apache-2.0 | Semantic embeddings | Free/local |
| llama-3.1-8b-instant | Meta via Groq | Llama-3 Community | NLU intent parsing (optional) | Free tier |
| whisper-large-v3 | OpenAI via Groq | MIT | STT (Groq adapter) | ~$0.111/hr |

## Infrastructure / Images

| Image | Licence | Purpose |
|-------|---------|---------|
| python:3.11-slim | PSF-2.0 | API container |
| postgres:16-alpine | PostgreSQL | Database |
| minio/minio | AGPL-3.0 (SaaS use OK) | Object storage in dev |
| minio/mc | AGPL-3.0 | Bucket init |
| ffmpeg | LGPL-2.1 / GPL-2.0 | Video rendering |

> **Note on MinIO**: MinIO server is AGPL-3.0 but its use as a network storage service
> (not embedded in our product) is permitted commercially. The shipped service uses
> S3-compatible storage (boto3/aioboto3); MinIO is only in the compose for local dev.

## Test Media

All test media generated programmatically using ffmpeg (lavfi sources):
- Solid colour + drawtext frame barcode (no copyright)
- Synthetic audio pips (pure sine tones, no copyright)
- No real persons' voices, faces or content used

## Transcript Fixtures

`tests/fixtures/transcripts/interview_300s.json` — synthetic fixture created
by the development team. No real recording.

---
*Last updated: Phase 0*
