"""
tests/unit/test_cli_runner.py
-----------------------------
Unit tests for cli/runner.py and cli/batch.py.
Verifies YAML session execution, output artifacts generation,
100% determinism, and metrics calculation.
"""
import json
import os
import tempfile
import pytest

from cli.runner import run_session
from cli.batch import run_batch


def test_cli_runner_worked_example():
    """Verify run_session on 01_worked_example.yaml generates all required files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        res = run_session(
            "tests/scenarios/01_worked_example.yaml",
            output_dir=tmpdir,
            do_render=False,
        )

        assert "final_timeline_hash" in res
        assert res["final_duration_s"] > 0
        assert len(res["steps"]) >= 8

        # Check required files
        results_file = os.path.join(tmpdir, "results.json")
        timeline_file = os.path.join(tmpdir, "final_timeline.json")
        otio_file = os.path.join(tmpdir, "final_timeline.otio")
        manifest_file = os.path.join(tmpdir, "manifest.json")

        assert os.path.exists(results_file)
        assert os.path.exists(timeline_file)
        assert os.path.exists(otio_file)
        assert os.path.exists(manifest_file)

        with open(results_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["final_timeline_hash"] == res["final_timeline_hash"]


def test_cli_runner_clarification_and_rejection():
    """Verify run_session properly records clarification answers and rejected operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        res_clarify = run_session(
            "tests/scenarios/12_topic_search_clarification.yaml",
            output_dir=tmpdir,
            do_render=False,
        )
        assert len(res_clarify["steps"]) == 2
        assert res_clarify["steps"][0]["status"] == "needs_clarification"
        assert res_clarify["steps"][1]["status"] == "applied"

    with tempfile.TemporaryDirectory() as tmpdir:
        res_reject = run_session(
            "tests/scenarios/03_whole_video_cut_rejected.yaml",
            output_dir=tmpdir,
            do_render=False,
        )
        assert len(res_reject["steps"]) == 1
        assert res_reject["steps"][0]["status"] == "rejected"
        assert res_reject["steps"][0]["error_code"] == "WHOLE_VIDEO_CUT"


def test_cli_batch_runner():
    """Verify run_batch processes scenarios and achieves 100% determinism."""
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics = run_batch("tests/scenarios", output_dir=tmpdir, runs_per_session=2, do_render=False)
        assert metrics["total_sessions"] >= 10
        assert metrics["determinism_share"] == 1.0
        assert os.path.exists(os.path.join(tmpdir, "batch_summary.json"))
