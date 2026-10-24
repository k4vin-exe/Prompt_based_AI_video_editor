"""
api/app.py
----------
FastAPI application factory for the IncuBrix Editing Engine.
Implements:
- Integration Standard 1 (One-command start)
- Integration Standard 2 (Documented HTTP API, routes under /api/v1/)
- Integration Standard 4 (Idempotency-Key on POST requests)
- Integration Standard 5 (Clear JSON errors: code, message, retryable, details)
- Integration Standard 8 (Structured JSON logging & X-Correlation-Id)
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Callable
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.config import settings
from api.routes import router
from api.state import state

# Setup root logger with JSON format
logger = logging.getLogger("incubrix.api")
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))


def create_app() -> FastAPI:
    app = FastAPI(
        title="IncuBrix Prompt-Based Video Editing Engine",
        version="0.1.0",
        description="Turns natural language instructions into exact, reversible video edits with pure deterministic timeline fold.",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.cors_origins == "*" else settings.cors_origins.split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Middleware: Correlation ID & Structured Logging (R-INT-08) ────────────

    @app.middleware("http")
    async def logging_and_correlation_middleware(request: Request, call_next: Callable) -> Response:
        corr_id = request.headers.get("X-Correlation-Id") or f"corr_{uuid.uuid4().hex[:12]}"
        request.state.correlation_id = corr_id
        start_time = time.time()

        # Idempotency handling for POST requests (R-INT-04)
        idempotency_key = request.headers.get("Idempotency-Key")
        if request.method == "POST" and idempotency_key:
            cache_key = f"{request.url.path}:{idempotency_key}"
            cached = state.get_idempotent_response(cache_key)
            if cached:
                cached_headers = dict(cached.headers)
                cached_headers["X-Correlation-Id"] = corr_id
                cached_headers["X-Cache-Lookup"] = "HIT"
                return Response(
                    content=cached.body,
                    status_code=cached.status_code,
                    headers=cached_headers,
                    media_type=cached.headers.get("content-type", "application/json"),
                )

        response = await call_next(request)
        latency_ms = int((time.time() - start_time) * 1000)

        response.headers["X-Correlation-Id"] = corr_id

        # Cache successful POST response if Idempotency-Key was provided
        if request.method == "POST" and idempotency_key and response.status_code < 400:
            cache_key = f"{request.url.path}:{idempotency_key}"
            # Read response body for caching
            body_chunks = [chunk async for chunk in response.body_iterator]
            full_body = b"".join(body_chunks)
            state.set_idempotent_response(
                cache_key,
                status_code=response.status_code,
                headers=dict(response.headers),
                body=full_body,
            )
            response = Response(
                content=full_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # Structured JSON log
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": "INFO" if response.status_code < 400 else "ERROR",
            "correlation_id": corr_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
        }
        logger.info(json.dumps(log_entry))

        return response

    # ── Exception Handlers: Standard JSON Errors (R-INT-05) ───────────────────

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        corr_id = getattr(request.state, "correlation_id", "unknown")
        if isinstance(exc.detail, dict):
            code = exc.detail.get("code", "HTTP_ERROR")
            message = exc.detail.get("message", "An error occurred")
            retryable = exc.detail.get("retryable", False)
            details = exc.detail.get("details", {})
        else:
            code = "HTTP_ERROR"
            message = str(exc.detail)
            retryable = exc.status_code >= 500
            details = {}

        return JSONResponse(
            status_code=exc.status_code,
            headers={"X-Correlation-Id": corr_id},
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                    "details": details,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        corr_id = getattr(request.state, "correlation_id", "unknown")
        return JSONResponse(
            status_code=422,
            headers={"X-Correlation-Id": corr_id},
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "retryable": False,
                    "details": {"errors": exc.errors()},
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        corr_id = getattr(request.state, "correlation_id", "unknown")
        logger.exception(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=500,
            headers={"X-Correlation-Id": corr_id},
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred processing your request.",
                    "retryable": True,
                    "details": {"exception": type(exc).__name__},
                }
            },
        )

    app.include_router(router)

    # Mount static assets and live demo UI
    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.exists():
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse
        app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

        @app.get("/", include_in_schema=False)
        @app.get("/demo", include_in_schema=False)
        async def serve_demo():
            return FileResponse(str(web_dir / "index.html"))

    fixtures_dir = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
    if fixtures_dir.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/tests/fixtures", StaticFiles(directory=str(fixtures_dir)), name="fixtures")

    storage_dir = Path(settings.storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/storage", StaticFiles(directory=str(storage_dir)), name="storage")

    return app


app = create_app()


def main():
    import uvicorn
    uvicorn.run("api.app:app", host=settings.host, port=settings.port, reload=(settings.env == "development"))


if __name__ == "__main__":
    main()
