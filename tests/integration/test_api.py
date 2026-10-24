"""
tests/integration/test_api.py
-----------------------------
Integration tests for FastAPI service under /api/v1/.
Verifies:
- Integration Standard 1 (Testing without API keys)
- Integration Standard 2 (Documented API & routes under /api/v1/)
- Integration Standard 3 (Background rendering jobs, 202, progress, status)
- Integration Standard 4 (Idempotency-Key caching on POST)
- Integration Standard 5 (JSON error schema: code, message, retryable, details)
- Integration Standard 8 (Health, Ready, Correlation-Id)
"""
import time
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.state import state

client = TestClient(create_app())


def test_health_and_ready():
    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    r_ready = client.get("/ready")
    assert r_ready.status_code == 200
    assert r_ready.json()["status"] == "ready"
    assert "stt_adapter" in r_ready.json()


def test_web_demo_serving():
    """Verify live demo UI is served at root and /demo."""
    r_root = client.get("/")
    assert r_root.status_code == 200
    assert "IncuBrix Editor" in r_root.text

    r_demo = client.get("/demo")
    assert r_demo.status_code == 200
    assert "Visual Timeline Fold" in r_demo.text


def test_standard_error_schema_on_not_found():
    """Verify 404 conforms to Integration Standard 5 schema."""
    resp = client.get("/api/v1/projects/nonexistent_project_id")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "PROJECT_NOT_FOUND"
    assert "message" in data["error"]
    assert "retryable" in data["error"]
    assert "details" in data["error"]


def test_correlation_id_propagation():
    """Verify X-Correlation-Id is echoed in response."""
    cid = "custom-corr-id-999"
    resp = client.get("/health", headers={"X-Correlation-Id": cid})
    assert resp.headers.get("X-Correlation-Id") == cid


def test_project_lifecycle_and_instructions():
    """Test project creation, timeline retrieval, and 3-way instruction answers."""
    # 1. Create project
    create_payload = {
        "video_url": "tests/fixtures/sync_oracle_test.mp4",
    }
    r_proj = client.post("/api/v1/projects", json=create_payload)
    assert r_proj.status_code == 201
    proj_data = r_proj.json()
    project_id = proj_data["project_id"]
    assert project_id.startswith("proj_")
    assert proj_data["duration_s"] > 0

    # 2. Get project timeline
    r_tl = client.get(f"/api/v1/projects/{project_id}/timeline")
    assert r_tl.status_code == 200
    assert "timeline_hash" in r_tl.json()

    # 3. Instruction: Applied
    r_inst1 = client.post(
        f"/api/v1/projects/{project_id}/instructions",
        json={"say": "Cut the first 2 seconds"},
    )
    assert r_inst1.status_code == 200
    res1 = r_inst1.json()
    assert res1["status"] == "applied"
    assert res1["before_after"]["duration_delta_s"] < 0
    assert len(res1["operations"]) == 1

    # 4. Instruction: Needs Clarification
    r_inst2 = client.post(
        f"/api/v1/projects/{project_id}/instructions",
        json={"say": "Remove the part about pricing"},
    )
    assert r_inst2.status_code == 200
    res2 = r_inst2.json()
    assert res2["status"] == "needs_clarification"
    assert "pricing" in res2["question"].lower()
    assert len(res2["options"]) >= 2

    # 5. Clarify: "the second one"
    r_inst3 = client.post(
        f"/api/v1/projects/{project_id}/instructions",
        json={"say": "the second one"},
    )
    assert r_inst3.status_code == 200
    res3 = r_inst3.json()
    assert res3["status"] == "applied"

    # 6. Instruction: Rejected
    r_inst4 = client.post(
        f"/api/v1/projects/{project_id}/instructions",
        json={"say": "cut everything"},
    )
    assert r_inst4.status_code == 200
    res4 = r_inst4.json()
    assert res4["status"] == "rejected"
    assert res4["error_code"] == "WHOLE_VIDEO_CUT"


def test_idempotency_key_caching():
    """Verify Idempotency-Key prevents double execution of POST instructions."""
    # Create a fresh project
    r_proj = client.post(
        "/api/v1/projects",
        json={"video_url": "tests/fixtures/sync_oracle_test.mp4"},
    )
    project_id = r_proj.json()["project_id"]

    idem_key = "test-idem-key-cut-first-2s"
    headers = {"Idempotency-Key": idem_key}

    # First request
    resp1 = client.post(
        f"/api/v1/projects/{project_id}/instructions",
        json={"say": "Cut the first 2 seconds"},
        headers=headers,
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    hash1 = data1["current_timeline_hash"]

    # Second request with SAME Idempotency-Key
    resp2 = client.post(
        f"/api/v1/projects/{project_id}/instructions",
        json={"say": "Cut the first 2 seconds"},
        headers=headers,
    )
    assert resp2.status_code == 200
    assert resp2.headers.get("X-Cache-Lookup") == "HIT"
    data2 = resp2.json()
    assert data2["current_timeline_hash"] == hash1


def test_background_render_job():
    """Verify 202 Accepted, progress polling, and artifact generation."""
    r_proj = client.post(
        "/api/v1/projects",
        json={"video_url": "tests/fixtures/sync_oracle_test.mp4"},
    )
    project_id = r_proj.json()["project_id"]

    # Apply a quick edit
    client.post(
        f"/api/v1/projects/{project_id}/instructions",
        json={"say": "Cut the first 2 seconds"},
    )

    # Request render -> 202 Accepted
    r_render = client.post(
        f"/api/v1/projects/{project_id}/render",
        json={"callback_url": None},
    )
    assert r_render.status_code == 202
    job_id = r_render.json()["job_id"]
    assert job_id.startswith("job_render_")

    # Poll job until completion or timeout (max 15s)
    start_wait = time.time()
    succeeded = False
    final_job_data = None

    while time.time() - start_wait < 15.0:
        r_status = client.get(f"/api/v1/jobs/{job_id}")
        assert r_status.status_code == 200
        job_data = r_status.json()
        final_job_data = job_data
        if job_data["status"] == "succeeded":
            succeeded = True
            break
        elif job_data["status"] == "failed":
            pytest.fail(f"Job failed: {job_data.get('error')}")
        time.sleep(0.3)

    assert succeeded, f"Render job did not finish in time: {final_job_data}"
    assert final_job_data["progress"] == 100
    assert final_job_data["results"] is not None
    assert "video_url" in final_job_data["results"]
    assert "otio_url" in final_job_data["results"]
    assert "manifest_url" in final_job_data["results"]
