"""
api/state.py
------------
Thread-safe in-memory state store for Projects, Sessions, Jobs, and Idempotency Keys.
"""
from __future__ import annotations

import time
import threading
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from engine.session import Session
from engine.probe import VideoMetadata


@dataclass
class ProjectState:
    project_id: str
    video_path: str
    metadata: VideoMetadata
    session: Session
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


@dataclass
class JobState:
    job_id: str
    project_id: str
    status: str  # "queued", "running", "succeeded", "failed"
    progress: int  # 0 to 100
    created_at: str
    updated_at: str
    callback_url: Optional[str] = None
    results: Optional[Dict[str, str]] = None
    error: Optional[Dict[str, Any]] = None
    latency_ms: Optional[int] = None


@dataclass
class IdempotencyRecord:
    status_code: int
    headers: Dict[str, str]
    body: bytes
    timestamp: float


class GlobalState:
    """Thread-safe global state manager."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.projects: Dict[str, ProjectState] = {}
        self.jobs: Dict[str, JobState] = {}
        self.idempotency_cache: Dict[str, IdempotencyRecord] = {}

    # ── Projects ─────────────────────────────────────────────────────────────

    def add_project(self, state: ProjectState) -> None:
        with self._lock:
            self.projects[state.project_id] = state

    def get_project(self, project_id: str) -> Optional[ProjectState]:
        with self._lock:
            return self.projects.get(project_id)

    # ── Jobs ─────────────────────────────────────────────────────────────────

    def create_job(self, job_id: str, project_id: str, callback_url: Optional[str] = None) -> JobState:
        with self._lock:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            job = JobState(
                job_id=job_id,
                project_id=project_id,
                status="queued",
                progress=0,
                created_at=now,
                updated_at=now,
                callback_url=callback_url,
            )
            self.jobs[job_id] = job
            return job

    def get_job(self, job_id: str) -> Optional[JobState]:
        with self._lock:
            return self.jobs.get(job_id)

    def update_job(
        self,
        job_id: str,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        results: Optional[Dict[str, str]] = None,
        error: Optional[Dict[str, Any]] = None,
        latency_ms: Optional[int] = None,
    ) -> Optional[JobState]:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if results is not None:
                job.results = results
            if error is not None:
                job.error = error
            if latency_ms is not None:
                job.latency_ms = latency_ms
            job.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return job

    def get_latest_job_for_project(self, project_id: str) -> Optional[JobState]:
        with self._lock:
            matching = [j for j in self.jobs.values() if j.project_id == project_id and j.status == "succeeded"]
            return matching[-1] if matching else None

    # ── Idempotency ──────────────────────────────────────────────────────────

    def get_idempotent_response(self, key: str) -> Optional[IdempotencyRecord]:
        with self._lock:
            return self.idempotency_cache.get(key)

    def set_idempotent_response(self, key: str, status_code: int, headers: Dict[str, str], body: bytes) -> None:
        with self._lock:
            self.idempotency_cache[key] = IdempotencyRecord(
                status_code=status_code,
                headers=headers,
                body=body,
                timestamp=time.time(),
            )


# Global singleton instance
state = GlobalState()
