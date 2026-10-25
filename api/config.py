"""
api/config.py
-------------
Centralized configuration loaded from environment variables.
Follows Integration Standard 6 (No hard-coded paths or keys).
"""
import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


def _load_env_file() -> None:
    """Load key-value pairs from root .env file into os.environ if not present."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key and (key not in os.environ or not os.environ[key]):
                            os.environ[key] = val
        except Exception:
            pass


_load_env_file()


class Settings(BaseModel):
    # Service Settings
    host: str = Field(default=os.getenv("HOST", "0.0.0.0"))
    port: int = Field(default=int(os.getenv("PORT", "8000")))
    env: str = Field(default=os.getenv("ENV", "development"))
    log_level: str = Field(default=os.getenv("LOG_LEVEL", "INFO"))

    # Storage Paths
    storage_dir: Path = Field(
        default=Path(
            os.getenv(
                "STORAGE_DIR",
                "/tmp/api_storage" if (os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME")) else "outputs/api_storage"
            )
        ).resolve()
    )
    temp_dir: Path = Field(
        default=Path(
            os.getenv(
                "TEMP_DIR",
                "/tmp/temp" if (os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME")) else "outputs/temp"
            )
        ).resolve()
    )

    # Provider Adapters
    stt_adapter: str = Field(default=os.getenv("STT_ADAPTER", "mock"))
    llm_adapter: str = Field(default=os.getenv("LLM_ADAPTER", "mock"))
    embedding_adapter: str = Field(default=os.getenv("EMBEDDING_ADAPTER", "fastembed"))

    # Security & Callbacks
    hmac_secret: str = Field(default=os.getenv("HMAC_SECRET", "incubrix_secret_key_change_in_prod"))
    cors_origins: str = Field(default=os.getenv("CORS_ORIGINS", "*"))

    # Limits & Defaults
    max_video_size_mb: int = Field(default=int(os.getenv("MAX_VIDEO_SIZE_MB", "500")))
    default_time_policy: str = Field(default=os.getenv("DEFAULT_TIME_POLICY", "current_edited"))
    max_concurrent_renders: int = Field(default=int(os.getenv("MAX_CONCURRENT_RENDERS", "1")))


settings = Settings()
try:
    os.makedirs(settings.storage_dir, exist_ok=True)
    os.makedirs(settings.temp_dir, exist_ok=True)
except Exception:
    pass
