"""
api/jobs.py
-----------
Background job worker for asynchronous rendering tasks.
Implements:
- Integration Standard 3 (202 Accepted, progress 0-100, status tracking)
- HMAC-SHA256 signed callback webhooks (X-IncuBrix-Signature header)
- Integration Standard 9 (Output manifest generation)
"""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Dict, Any
import httpx

from api.config import settings
from api.state import state
from engine.render import render_timeline
from engine.otio_export import save_otio_file

logger = logging.getLogger("incubrix.jobs")
_executor = ThreadPoolExecutor(max_workers=settings.max_concurrent_renders, thread_name_prefix="render-worker")


def enqueue_render_job(job_id: str, project_id: str, base_url: str) -> None:
    """Submit background render task to thread pool executor."""
    _executor.submit(_execute_render_job, job_id, project_id, base_url)


def _execute_render_job(job_id: str, project_id: str, base_url: str) -> None:
    start_time = time.time()
    logger.info(f"Starting render job {job_id} for project {project_id}")

    proj = state.get_project(project_id)
    if not proj:
        state.update_job(
            job_id,
            status="failed",
            error={"code": "PROJECT_NOT_FOUND", "message": f"Project '{project_id}' not found", "retryable": False, "details": {}},
        )
        return

    # Create job artifact directory under storage
    job_dir = os.path.join(settings.storage_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)

    try:
        # Step 1: Queued -> Running (10%)
        state.update_job(job_id, status="running", progress=10)

        video_out_path = os.path.join(job_dir, "final_video.mp4")
        timeline_out_path = os.path.join(job_dir, "final_timeline.json")
        otio_out_path = os.path.join(job_dir, "final_timeline.otio")
        manifest_out_path = os.path.join(job_dir, "manifest.json")

        # Step 2: Preparing timeline & styles (30%)
        timeline = proj.session.timeline
        state.update_job(job_id, progress=30)

        # Step 3: FFmpeg rendering (50%)
        state.update_job(job_id, progress=50)
        render_res = render_timeline(
            timeline=timeline,
            source_video_path=proj.video_path,
            output_video_path=video_out_path,
        )

        # Save convenience copies directly to outputs/ and system Downloads
        try:
            outputs_dir = Path("outputs")
            outputs_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(video_out_path, outputs_dir / "final_video.mp4")
            shutil.copyfile(video_out_path, outputs_dir / "edited_video.mp4")

            downloads_dir = Path.home() / "Downloads"
            if downloads_dir.exists():
                shutil.copyfile(video_out_path, downloads_dir / "edited_video.mp4")
                shutil.copyfile(video_out_path, downloads_dir / "final_video.mp4")
        except Exception as copy_err:
            logger.warning(f"Convenience copy failed: {copy_err}")

        # Step 4: Export timeline JSON, OTIO, and manifest (80%)
        state.update_job(job_id, progress=80)

        with open(timeline_out_path, "w", encoding="utf-8") as f:
            json.dump(timeline.to_dict(), f, indent=2, sort_keys=True)

        save_otio_file(timeline, otio_out_path, media_reference_url=proj.video_path)

        manifest = {
            "manifest_version": "1.0",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "job_id": job_id,
            "project_id": project_id,
            "engine_version": "0.1.0",
            "models": {
                "nlu": "deterministic_rule_parser_v1 (fallback: mock_llm_0.1.0)",
                "stt": f"{settings.stt_adapter}",
                "embeddings": f"{settings.embedding_adapter}",
            },
            "render_metrics": render_res.to_dict(),
            "final_timeline_hash": proj.session.get_timeline_hash(),
            "final_duration_s": proj.session.get_duration_s(),
            "cost_estimate_usd": 0.0,
            "licence_notes": "All default components commercially usable (MIT/Apache-2.0). Zero non-commercial or AGPL libraries in core path.",
        }
        with open(manifest_out_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        # Base download links
        clean_base = base_url.rstrip("/")
        results_links = {
            "video_url": f"{clean_base}/api/v1/download/{job_id}/final_video.mp4",
            "stream_url": f"{clean_base}/api/v1/stream/{job_id}/final_video.mp4",
            "timeline_url": f"{clean_base}/api/v1/download/{job_id}/final_timeline.json",
            "otio_url": f"{clean_base}/api/v1/download/{job_id}/final_timeline.otio",
            "manifest_url": f"{clean_base}/api/v1/download/{job_id}/manifest.json",
        }

        latency_ms = int((time.time() - start_time) * 1000)
        job_state = state.update_job(
            job_id,
            status="succeeded",
            progress=100,
            results=results_links,
            latency_ms=latency_ms,
        )

        logger.info(f"Render job {job_id} succeeded in {latency_ms} ms")

        # Step 5: Webhook dispatch if callback_url configured (Integration Standard 3)
        if job_state and job_state.callback_url:
            _dispatch_webhook(job_state)

    except Exception as e:
        logger.exception(f"Render job {job_id} failed: {e}")
        error_details = {
            "code": "RENDER_PIPELINE_ERROR",
            "message": str(e),
            "retryable": True,
            "details": {"exception_type": type(e).__name__},
        }
        state.update_job(job_id, status="failed", error=error_details)
        job_state = state.get_job(job_id)
        if job_state and job_state.callback_url:
            _dispatch_webhook(job_state)


def _dispatch_webhook(job: Any) -> None:
    """Send HMAC-SHA256 signed POST notification to callback_url."""
    try:
        payload = {
            "job_id": job.job_id,
            "project_id": job.project_id,
            "status": job.status,
            "progress": job.progress,
            "results": job.results,
            "error": job.error,
            "latency_ms": job.latency_ms,
            "updated_at": job.updated_at,
        }
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        sig = hmac.new(settings.hmac_secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-IncuBrix-Signature": f"sha256={sig}",
        }

        with httpx.Client(timeout=5.0) as client:
            client.post(job.callback_url, content=payload_bytes, headers=headers)
        logger.info(f"Successfully posted webhook for job {job.job_id} to {job.callback_url}")
    except Exception as e:
        logger.warning(f"Failed to post webhook for job {job.job_id}: {e}")
