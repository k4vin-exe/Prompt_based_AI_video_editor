"""
engine/visual_style.py
----------------------
Client for Hugging Face Qwen-Video-Edit Space (https://hugging-apps-qwen-video-edit.hf.space/).
Enables generative diffusion-based visual re-styling on short video clips (e.g. "make it look like a painting", "anime style").
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any
import httpx


class QwenVideoEditClient:
    """Client for Hugging Face Qwen-Video-Edit Gradio & MCP service."""

    BASE_URL = "https://hugging-apps-qwen-video-edit.hf.space"

    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = (base_url or self.BASE_URL).rstrip("/")

    def is_available(self) -> bool:
        """Check if the Gradio space is accessible."""
        try:
            with httpx.Client(timeout=6.0) as client:
                r = client.get(f"{self.base_url}/gradio_api/info")
                return r.status_code == 200
        except Exception:
            return False

    def upload_file(self, file_path: str | Path) -> str:
        """Upload a video file to the Gradio upload endpoint."""
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        upload_url = f"{self.base_url}/gradio_api/upload"
        with open(p, "rb") as f:
            files = {"files": (p.name, f, "video/mp4")}
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(upload_url, files=files)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    return data[0]
                raise RuntimeError(f"Unexpected upload response from Gradio: {data}")
