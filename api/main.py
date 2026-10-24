"""
api/main.py
-----------
Entrypoint exporting the FastAPI app instance for ASGI servers.
"""
from api.app import app

__all__ = ["app"]
