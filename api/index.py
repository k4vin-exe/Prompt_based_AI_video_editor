"""
api/index.py
------------
Serverless ASGI entrypoint for Vercel deployment.
Exports the FastAPI `app` instance.
"""
import sys
from pathlib import Path

# Add project root to sys.path so engine, api, nlu, perception import cleanly
root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from api.app import app

__all__ = ["app"]
