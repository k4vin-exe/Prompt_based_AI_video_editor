"""
api/models.py
-------------
Pydantic data models for the IncuBrix Editing Engine API.
Strict adherence to:
- Integration Standard 2 (Documented HTTP API)
- Integration Standard 3 (Background jobs & progress 0-100)
- Integration Standard 5 (JSON error schema: code, message, retryable, details)
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# ── Standardized JSON Error (Integration Standard 5) ─────────────────────────

class ErrorDetails(BaseModel):
    code: str = Field(..., description="UPPER_SNAKE_CASE error code, e.g. WHOLE_VIDEO_CUT, NO_MATCH")
    message: str = Field(..., description="Human-readable explanation of what failed")
    retryable: bool = Field(default=False, description="Whether repeating the request might succeed without changes")
    details: Dict[str, Any] = Field(default_factory=dict, description="Diagnostic context or parameter details")


class StandardErrorResponse(BaseModel):
    error: ErrorDetails


# ── Health & Ready ───────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = Field(default="ok", examples=["ok"])
    version: str = Field(default="0.1.0", examples=["0.1.0"])


class ReadyResponse(BaseModel):
    status: str = Field(default="ready", examples=["ready"])
    stt_adapter: str = Field(..., examples=["mock"])
    llm_adapter: str = Field(..., examples=["mock"])
    ffmpeg_available: bool = Field(..., examples=[True])


# ── Project Ingestion ────────────────────────────────────────────────────────

class ProjectCreateUrlRequest(BaseModel):
    video_url: str = Field(..., description="Public URL or local file path to the video file", examples=["tests/fixtures/sync_oracle_test.mp4"])
    transcript_path: Optional[str] = Field(None, description="Optional path to transcript JSON fixture", examples=["tests/fixtures/transcripts/interview_300s.json"])
    transcript_override: Optional[List[Dict[str, Any]]] = Field(None, description="Optional word-level transcript fixture")


class ProjectResponse(BaseModel):
    project_id: str = Field(..., description="Unique identifier for the project", examples=["proj_abc123"])
    duration_s: float = Field(..., description="Original video duration in seconds", examples=[300.0])
    fps: float = Field(..., description="Video frame rate", examples=[25.0])
    resolution: List[int] = Field(..., description="[width, height] in pixels", examples=[[1280, 720]])
    has_audio: bool = Field(..., description="True if video has at least one audio stream", examples=[True])
    transcript_word_count: int = Field(..., description="Number of timestamped words in transcript", examples=[17])
    created_at: str = Field(..., description="UTC ISO8601 creation timestamp")


# ── Instructions (3-Way Answers) ─────────────────────────────────────────────

class InstructionRequest(BaseModel):
    say: str = Field(..., description="Plain-language editing command", examples=["Cut the first 30 seconds"])
    time_policy: Optional[str] = Field(
        None,
        description="Optional time policy override: 'current_edited' or 'original_source'",
        examples=["current_edited"],
    )


class OperationSummaryModel(BaseModel):
    op_id: int
    op_type: str
    description: str


class BeforeAfterModel(BaseModel):
    before_duration_s: float
    after_duration_s: float
    duration_delta_s: float
    before_timeline_hash: str
    after_timeline_hash: str


class InstructionResponse(BaseModel):
    status: str = Field(..., description="'applied', 'needs_clarification', or 'rejected'", examples=["applied"])

    # When status == 'applied'
    operations: Optional[List[OperationSummaryModel]] = None
    summary: Optional[str] = None
    before_after: Optional[BeforeAfterModel] = None
    time_policy: Optional[str] = None
    warnings: Optional[List[str]] = None

    # When status == 'needs_clarification'
    question: Optional[str] = None
    options: Optional[List[str]] = None
    context: Optional[Dict[str, Any]] = None

    # When status == 'rejected'
    reason: Optional[str] = None
    error_code: Optional[str] = None
    original_instruction: Optional[str] = None

    # Current Timeline State
    current_duration_s: float
    current_timeline_hash: str


# ── Rendering & Background Jobs (Integration Standard 3) ─────────────────────

class RenderRequest(BaseModel):
    callback_url: Optional[str] = Field(
        None,
        description="Webhook URL called with HMAC-SHA256 signature when render finishes",
        examples=["https://webhook.site/my-callback"],
    )


class JobQueuedResponse(BaseModel):
    job_id: str = Field(..., description="Unique background job identifier", examples=["job_render_123"])
    status: str = Field(default="queued", examples=["queued"])
    created_at: str = Field(..., examples=["2026-10-23T00:00:00Z"])


class JobResultLinks(BaseModel):
    video_url: str = Field(..., description="Direct download link to rendered MP4 video")
    timeline_url: str = Field(..., description="Direct download link to final timeline JSON")
    otio_url: str = Field(..., description="Direct download link to OpenTimelineIO export")
    manifest_url: str = Field(..., description="Direct download link to output manifest JSON")


class JobStatusResponse(BaseModel):
    job_id: str
    status: str = Field(..., description="'queued', 'running', 'succeeded', or 'failed'")
    progress: int = Field(..., ge=0, le=100, description="Job progress percentage 0-100")
    created_at: str
    updated_at: str
    latency_ms: Optional[int] = None
    results: Optional[JobResultLinks] = None
    error: Optional[ErrorDetails] = None
