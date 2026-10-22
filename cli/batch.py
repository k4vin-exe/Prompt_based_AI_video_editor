"""
cli/batch.py
------------
Batch session runner. (Brief §Integration Standard 10)
Runs a folder of session files against the editing engine and records all results.
Verifies determinism across multiple runs (3 runs with identical hash = 100%).
Computes required metrics for the Submission Form Metrics tab.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cli.runner import run_session


def run_batch(
    sessions_dir: str,
    output_dir: str = "outputs/batch_results",
    runs_per_session: int = 3,
    do_render: bool = False,
) -> Dict[str, Any]:
    """
    Run all YAML session files in sessions_dir, repeating each session runs_per_session times.
    """
    start_time = time.time()
    sessions_dir = str(Path(sessions_dir).resolve())
    output_dir = str(Path(output_dir).resolve())
    os.makedirs(output_dir, exist_ok=True)

    session_files = sorted(glob.glob(os.path.join(sessions_dir, "*.yaml")) + glob.glob(os.path.join(sessions_dir, "*.yml")))
    if not session_files:
        print(f"No session YAML files found in {sessions_dir}")
        return {"error": "no_files_found", "sessions": []}

    session_summaries: List[Dict[str, Any]] = []
    all_latencies_ms: List[float] = []
    determinism_passes = 0

    for s_file in session_files:
        base_name = Path(s_file).stem
        session_out_dir = os.path.join(output_dir, base_name)
        os.makedirs(session_out_dir, exist_ok=True)

        hashes: List[str] = []
        last_result = None

        for r in range(runs_per_session):
            run_dir = os.path.join(session_out_dir, f"run_{r+1}")
            res = run_session(s_file, output_dir=run_dir, do_render=do_render and (r == 0))
            hashes.append(res["final_timeline_hash"])
            last_result = res
            for step in res["steps"]:
                if "latency_ms" in step:
                    all_latencies_ms.append(step["latency_ms"])

        is_deterministic = len(set(hashes)) == 1
        if is_deterministic:
            determinism_passes += 1

        summary = {
            "session": base_name,
            "file": s_file,
            "steps_count": len(last_result["steps"]) if last_result else 0,
            "final_duration_s": last_result["final_duration_s"] if last_result else 0.0,
            "final_hash": hashes[0] if hashes else "",
            "deterministic_across_runs": is_deterministic,
            "run_hashes": hashes,
        }
        session_summaries.append(summary)

    all_latencies_ms.sort()
    median_latency = all_latencies_ms[len(all_latencies_ms) // 2] if all_latencies_ms else 0.0
    slowest_latency = all_latencies_ms[-1] if all_latencies_ms else 0.0

    batch_metrics = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_sessions": len(session_files),
        "runs_per_session": runs_per_session,
        "determinism_share": (determinism_passes / len(session_files)) if session_files else 1.0,
        "latency_ms": {
            "median": median_latency,
            "slowest": slowest_latency,
            "p95": all_latencies_ms[int(len(all_latencies_ms) * 0.95)] if all_latencies_ms else 0.0,
        },
        "total_wall_time_s": round(time.time() - start_time, 2),
        "sessions": session_summaries,
    }

    summary_file = os.path.join(output_dir, "batch_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(batch_metrics, f, indent=2)

    return batch_metrics


def main():
    parser = argparse.ArgumentParser(description="IncuBrix Batch Session Runner")
    parser.add_argument("sessions_dir", help="Directory containing session YAML files")
    parser.add_argument("-o", "--output-dir", default="outputs/batch_results", help="Directory for output results")
    parser.add_argument("-n", "--runs", type=int, default=3, help="Number of runs per session to test determinism")
    parser.add_argument("--render", action="store_true", help="Render video on first run")
    args = parser.parse_args()

    metrics = run_batch(args.sessions_dir, args.output_dir, runs_per_session=args.runs, do_render=args.render)
    print(f"\nBatch complete: {metrics['total_sessions']} sessions executed ({args.runs} runs each).")
    print(f"Determinism share: {metrics['determinism_share'] * 100:.1f}%")
    print(f"Median instruction latency: {metrics['latency_ms']['median']:.1f} ms")
    print(f"Slowest instruction latency: {metrics['latency_ms']['slowest']:.1f} ms")
    print(f"Summary saved to: {os.path.join(args.output_dir, 'batch_summary.json')}")


if __name__ == "__main__":
    main()
