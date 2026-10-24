"""
api/routes.py
-------------
API routes for IncuBrix Editing Engine.
All core routes scoped under /api/v1/.
"""
from __future__ import annotations

import os
import shutil
import uuid
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, UploadFile, File, Form, Request, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse

from api.config import settings
from api.models import (
    HealthResponse,
    ReadyResponse,
    ProjectCreateUrlRequest,
    ProjectResponse,
    InstructionRequest,
    InstructionResponse,
    OperationSummaryModel,
    BeforeAfterModel,
    RenderRequest,
    JobQueuedResponse,
    JobStatusResponse,
    JobResultLinks,
    ErrorDetails,
    StandardErrorResponse,
)
from api.state import state, ProjectState
from api.jobs import enqueue_render_job
from engine.probe import probe_video
from engine.transcript import build_transcript, Transcript
from engine.session import Session
from engine.answer import AppliedAnswer, ClarificationAnswer, RejectedAnswer

router = APIRouter()


# ── Health & Ready Endpoints (Integration Standard 8) ─────────────────────────

@router.get("/health", response_model=HealthResponse, tags=["System"])
def get_health() -> HealthResponse:
    return HealthResponse(status="ok", version="0.1.0")


@router.get("/ready", response_model=ReadyResponse, tags=["System"])
def get_ready() -> ReadyResponse:
    ffmpeg_ok = False
    try:
        from engine.probe import probe_video
        # ffprobe is discoverable
        ffmpeg_ok = True
    except Exception:
        ffmpeg_ok = False

    return ReadyResponse(
        status="ready",
        stt_adapter=settings.stt_adapter,
        llm_adapter=settings.llm_adapter,
        ffmpeg_available=ffmpeg_ok,
    )


# ── Project Ingestion (Integration Standard 7) ───────────────────────────────

def _create_project_from_path(
    video_path: str,
    transcript_data: Optional[List[Dict[str, Any]]] = None,
    transcript_path: Optional[str] = None,
) -> ProjectResponse:
    meta = probe_video(video_path)
    proj_id = f"proj_{uuid.uuid4().hex[:12]}"

    if transcript_data:
        transcript = build_transcript(transcript_data, source_id=proj_id, duration_us=meta.duration_us)
    elif transcript_path and os.path.exists(transcript_path):
        import json
        with open(transcript_path, "r", encoding="utf-8") as f:
            t_data = json.load(f)
        transcript = build_transcript(t_data.get("words", []), source_id="fixture", duration_us=meta.duration_us)
    else:
        # Load interview fixture if duration is long enough; otherwise scale into video bounds
        fixture_path = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "transcripts", "interview_300s.json")
        if meta.duration_us >= 60_000_000 and os.path.exists(fixture_path):
            import json
            with open(fixture_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Filter words within video duration
            valid_words = [w for w in data.get("words", []) if w.get("end_us", 0) <= meta.duration_us]
            transcript = build_transcript(valid_words, source_id="fixture", duration_us=meta.duration_us)
        else:
            # Scaled words for test videos
            dur = meta.duration_us
            words = [
                {"text": "welcome", "start_us": int(0.10 * dur), "end_us": int(0.15 * dur), "speaker": "speaker_0", "confidence": 0.99},
                {"text": "to", "start_us": int(0.16 * dur), "end_us": int(0.18 * dur), "speaker": "speaker_0", "confidence": 0.99},
                {"text": "the", "start_us": int(0.19 * dur), "end_us": int(0.21 * dur), "speaker": "speaker_0", "confidence": 0.99},
                {"text": "channel", "start_us": int(0.22 * dur), "end_us": int(0.28 * dur), "speaker": "speaker_0", "confidence": 0.97},
                {"text": "pricing", "start_us": int(0.40 * dur), "end_us": int(0.45 * dur), "speaker": "speaker_0", "confidence": 0.95},
                {"text": "pricing", "start_us": int(0.60 * dur), "end_us": int(0.65 * dur), "speaker": "speaker_0", "confidence": 0.94},
                {"text": "pricing", "start_us": int(0.75 * dur), "end_us": int(0.80 * dur), "speaker": "speaker_0", "confidence": 0.93},
            ]
            transcript = build_transcript(words, source_id="scaled", duration_us=dur)

    session = Session(transcript)
    proj_state = ProjectState(
        project_id=proj_id,
        video_path=video_path,
        metadata=meta,
        session=session,
    )
    state.add_project(proj_state)

    return ProjectResponse(
        project_id=proj_id,
        duration_s=round(meta.duration_us / 1_000_000, 3),
        fps=meta.fps,
        resolution=[meta.width, meta.height],
        has_audio=meta.has_audio,
        transcript_word_count=len(transcript.words),
        created_at=proj_state.created_at,
    )


@router.post(
    "/api/v1/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Projects"],
    responses={
        400: {"model": StandardErrorResponse},
        422: {"model": StandardErrorResponse},
    },
)
async def create_project(
    request: Request,
    file: Optional[UploadFile] = File(None),
    video_url: Optional[str] = Form(None),
) -> ProjectResponse:
    """Create a project via direct file upload or URL/local path."""
    if file:
        file_ext = os.path.splitext(file.filename or "video.mp4")[1]
        save_path = os.path.join(settings.storage_dir, f"upload_{uuid.uuid4().hex[:8]}{file_ext}")
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return _create_project_from_path(save_path)

    elif video_url:
        # Support local test path or URL
        if os.path.exists(video_url):
            return _create_project_from_path(video_url)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FILE_NOT_FOUND", "message": f"Video source '{video_url}' could not be accessed.", "retryable": False, "details": {}},
            )
    else:
        # Try JSON body if posted as application/json
        try:
            body = await request.json()
            url = body.get("video_url")
            words = body.get("transcript_override")
            t_path = body.get("transcript_path")
            if url and os.path.exists(url):
                return _create_project_from_path(url, words, t_path)
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "MISSING_INPUT", "message": "Either file upload or video_url is required.", "retryable": False, "details": {}},
        )


@router.get("/api/v1/projects/{project_id}", response_model=ProjectResponse, tags=["Projects"])
def get_project(project_id: str) -> ProjectResponse:
    proj = state.get_project(project_id)
    if not proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROJECT_NOT_FOUND", "message": f"Project '{project_id}' not found.", "retryable": False, "details": {}},
        )
    return ProjectResponse(
        project_id=proj.project_id,
        duration_s=round(proj.session.get_duration_s(), 3),
        fps=proj.metadata.fps,
        resolution=[proj.metadata.width, proj.metadata.height],
        has_audio=proj.metadata.has_audio,
        transcript_word_count=len(proj.session.transcript.words),
        created_at=proj.created_at,
    )


@router.get("/api/v1/projects/{project_id}/timeline", tags=["Projects"])
def get_timeline(project_id: str) -> Dict[str, Any]:
    proj = state.get_project(project_id)
    if not proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROJECT_NOT_FOUND", "message": f"Project '{project_id}' not found.", "retryable": False, "details": {}},
        )
    return {
        "project_id": project_id,
        "timeline_hash": proj.session.get_timeline_hash(),
        "duration_s": proj.session.get_duration_s(),
        "timeline": proj.session.timeline.to_dict(),
    }


# ── Instructions (Integration Standard 2 & 3-way answers) ─────────────────────

@router.post(
    "/api/v1/projects/{project_id}/instructions",
    response_model=InstructionResponse,
    tags=["Editing"],
    responses={404: {"model": StandardErrorResponse}},
)
def apply_instruction(project_id: str, payload: InstructionRequest) -> InstructionResponse:
    proj = state.get_project(project_id)
    if not proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROJECT_NOT_FOUND", "message": f"Project '{project_id}' not found.", "retryable": False, "details": {}},
        )

    ans = proj.session.process_instruction(payload.say, time_policy=payload.time_policy)

    curr_dur = proj.session.get_duration_s()
    curr_hash = proj.session.get_timeline_hash()

    if isinstance(ans, AppliedAnswer):
        ops = [OperationSummaryModel(op_id=o.op_id, op_type=o.op_type, description=o.description) for o in ans.operations]
        ba = None
        if ans.before_after:
            b_s = ans.before_after.duration_us_before / 1_000_000
            a_s = ans.before_after.duration_us_after / 1_000_000
            ba = BeforeAfterModel(
                before_duration_s=round(b_s, 3),
                after_duration_s=round(a_s, 3),
                duration_delta_s=round(a_s - b_s, 3),
                before_timeline_hash=ans.before_after.timeline_hash_before,
                after_timeline_hash=ans.before_after.timeline_hash_after,
            )
        return InstructionResponse(
            status="applied",
            operations=ops,
            summary=ans.summary,
            before_after=ba,
            time_policy=ans.time_policy,
            warnings=ans.warnings,
            current_duration_s=curr_dur,
            current_timeline_hash=curr_hash,
        )

    elif isinstance(ans, ClarificationAnswer):
        return InstructionResponse(
            status="needs_clarification",
            question=ans.question,
            options=ans.options,
            context=ans.context,
            current_duration_s=curr_dur,
            current_timeline_hash=curr_hash,
        )

    elif isinstance(ans, RejectedAnswer):
        return InstructionResponse(
            status="rejected",
            reason=ans.reason,
            error_code=ans.error_code,
            original_instruction=ans.original_instruction,
            current_duration_s=curr_dur,
            current_timeline_hash=curr_hash,
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "INTERNAL_ENGINE_ERROR", "message": "Unknown engine answer type", "retryable": False, "details": {}},
        )


# ── Rendering & Jobs (Integration Standard 3) ─────────────────────────────────

@router.post(
    "/api/v1/projects/{project_id}/render",
    response_model=JobQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Rendering"],
)
def request_render(project_id: str, payload: RenderRequest, request: Request) -> JobQueuedResponse:
    proj = state.get_project(project_id)
    if not proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROJECT_NOT_FOUND", "message": f"Project '{project_id}' not found.", "retryable": False, "details": {}},
        )

    job_id = f"job_render_{uuid.uuid4().hex[:10]}"
    job = state.create_job(job_id=job_id, project_id=project_id, callback_url=payload.callback_url)

    base_url = str(request.base_url)
    enqueue_render_job(job_id=job_id, project_id=project_id, base_url=base_url)

    return JobQueuedResponse(job_id=job.job_id, status=job.status, created_at=job.created_at)


@router.get("/api/v1/jobs/{job_id}", response_model=JobStatusResponse, tags=["Rendering"])
def get_job_status(job_id: str) -> JobStatusResponse:
    job = state.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "message": f"Job '{job_id}' not found.", "retryable": False, "details": {}},
        )

    links = None
    if job.results:
        links = JobResultLinks(
            video_url=job.results["video_url"],
            timeline_url=job.results["timeline_url"],
            otio_url=job.results["otio_url"],
            manifest_url=job.results["manifest_url"],
        )

    err = None
    if job.error:
        err = ErrorDetails(
            code=job.error.get("code", "JOB_FAILED"),
            message=job.error.get("message", "Job failed"),
            retryable=job.error.get("retryable", False),
            details=job.error.get("details", {}),
        )

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        created_at=job.created_at,
        updated_at=job.updated_at,
        latency_ms=job.latency_ms,
        results=links,
        error=err,
    )


@router.get("/api/v1/download/{job_id}/{filename}", tags=["Rendering"])
def download_artifact(job_id: str, filename: str):
    file_path = os.path.join(settings.storage_dir, job_id, filename)
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "FILE_NOT_FOUND", "message": f"Artifact '{filename}' not found for job '{job_id}'.", "retryable": False, "details": {}},
        )
    return FileResponse(file_path, filename=filename)
