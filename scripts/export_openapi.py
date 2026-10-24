"""
scripts/export_openapi.py
-------------------------
Exports the FastAPI application's OpenAPI 3.1 schema to openapi.yaml.
Fulfills Integration Standard 2.
"""
import os
import sys
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.app import app


def export_openapi(output_path: str = "openapi.yaml"):
    openapi_schema = app.openapi()
    # Ensure OpenAPI 3.1 version string
    openapi_schema["openapi"] = "3.1.0"

    output_path = str(Path(output_path).resolve())
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(openapi_schema, f, sort_keys=False, allow_unicode=True)
    print(f"Exported OpenAPI 3.1 schema to {output_path}")


if __name__ == "__main__":
    export_openapi()
