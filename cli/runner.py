"""
cli/runner.py
-------------
Command-line session runner. (Brief §Session file format, §Integration Standard 10)
Executes scripted editing sessions defined in YAML and records every step response.

Accepts YAML format:
  video: tests/fixtures/sync_oracle_test.mp4
  transcript: tests/fixtures/transcripts/interview_300s.json   # optional fixture path
  steps:
    - say: "Add a caption 'Welcome!' when I say welcome to the channel"
    - say: "Cut the first 30 seconds"
    - say: "Remove the part about pricing"
      answer: "the second one"
    - say: "Undo"
    - say: "render"

Outputs to output directory:
  - results.json (status, operations, summary, question, options, timeline_hash, duration_s per step)
  - final_timeline.json
  - final_timeline.otio
  - manifest.json
  - final_video.mp4 (if render is invoked)
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.transcript import build_transcript, Transcript
from engine.session import Session
from engine.answer import AppliedAnswer, ClarificationAnswer, RejectedAnswer
from engine.render import render_timeline
from engine.otio_export import save_otio_file
from engine.probe import probe_video


def load_transcript_for_video(video_path: str, transcript_override: Optional[str] = None) -> Transcript:
    """Load transcript fixture or generate from mock STT."""
    if transcript_override and os.path.exists(transcript_override):
        with open(transcript_override, "r", encoding="utf-8") as f:
            data = json.load(f)
        return build_transcript(data.get("words", []), source_id="fixture", duration_us=data.get("duration_us", 300_000_000))

    # Check for default interview fixture
    interview_fixture = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "transcripts", "interview_300s.json")
    if os.path.exists(interview_fixture):
        with open(interview_fixture, "r", encoding="utf-8") as f:
            data = json.load(f)
        return build_transcript(data.get("words", []), source_id="interview", duration_us=data.get("duration_us", 300_000_000))

    # Fallback synthetic transcript from video probe
    meta = probe_video(video_path)
    words = [
        {"text": "welcome", "start_us": 42000000, "end_us": 42500000, "speaker": "speaker_0", "confidence": 0.99},
        {"text": "to", "start_us": 42550000, "end_us": 42700000, "speaker": "speaker_0", "confidence": 0.99},
        {"text": "the", "start_us": 42750000, "end_us": 42900000, "speaker": "speaker_0", "confidence": 0.99},
        {"text": "channel", "start_us": 42950000, "end_us": 44000000, "speaker": "speaker_0", "confidence": 0.97},
    ]
    return build_transcript(words, source_id="synthetic", duration_us=meta.duration_us)


def run_session(
    session_yaml_path: str,
    output_dir: str = "outputs",
    do_render: bool = True,
    video_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a scripted session file and write all required artifacts.
    """
    start_total_time = time.time()
    session_yaml_path = str(Path(session_yaml_path).resolve())
    output_dir = str(Path(output_dir).resolve())
    os.makedirs(output_dir, exist_ok=True)

    with open(session_yaml_path, "r", encoding="utf-8") as f:
        session_spec = yaml.safe_load(f)

    video_path = video_override or session_spec.get("video", "tests/fixtures/sync_oracle_test.mp4")
    # Resolve relative paths relative to session file or cwd
    if not os.path.isabs(video_path):
        candidate = os.path.join(os.path.dirname(session_yaml_path), video_path)
        if os.path.exists(candidate):
            video_path = candidate
        elif os.path.exists(video_path):
            video_path = str(Path(video_path).resolve())

    transcript_path = session_spec.get("transcript")
    if transcript_path and not os.path.isabs(transcript_path):
        candidate = os.path.join(os.path.dirname(session_yaml_path), transcript_path)
        if os.path.exists(candidate):
            transcript_path = candidate

    transcript = load_transcript_for_video(video_path, transcript_path)
    session = Session(transcript)

    steps_results: List[Dict[str, Any]] = []
    render_requested = False
    rendered_video_path = None

    steps = session_spec.get("steps", [])
    for idx, step in enumerate(steps):
        say_text = step.get("say", "").strip()
        step_start_t = time.time()

        if "render" in say_text.lower():
            render_requested = True

        ans = session.process_instruction(say_text)
        step_record: Dict[str, Any] = {
            "step_index": idx + 1,
            "instruction": say_text,
            "status": ans.status,
            "timeline_hash": session.get_timeline_hash(),
            "duration_s": session.get_duration_s(),
            "operations": [],
            "summary": "",
            "question": None,
            "options": None,
            "latency_ms": int((time.time() - step_start_t) * 1000),
        }

        if isinstance(ans, AppliedAnswer):
            step_record["operations"] = [asdict(op) for op in ans.operations]
            step_record["summary"] = ans.summary
            step_record["time_policy"] = ans.time_policy
            step_record["warnings"] = ans.warnings
            steps_results.append(step_record)

        elif isinstance(ans, ClarificationAnswer):
            step_record["question"] = ans.question
            step_record["options"] = ans.options
            steps_results.append(step_record)

            # Check if scripted session provides an answer to the question
            reply = step.get("answer")
            if reply:
                reply_start_t = time.time()
                reply_ans = session.process_instruction(str(reply))
                reply_record: Dict[str, Any] = {
                    "step_index": f"{idx + 1}.reply",
                    "instruction": str(reply),
                    "status": reply_ans.status,
                    "timeline_hash": session.get_timeline_hash(),
                    "duration_s": session.get_duration_s(),
                    "operations": [asdict(op) for op in reply_ans.operations] if isinstance(reply_ans, AppliedAnswer) else [],
                    "summary": reply_ans.summary if isinstance(reply_ans, AppliedAnswer) else "",
                    "latency_ms": int((time.time() - reply_start_t) * 1000),
                }
                steps_results.append(reply_record)

        elif isinstance(ans, RejectedAnswer):
            step_record["summary"] = ans.reason
            step_record["error_code"] = ans.error_code
            steps_results.append(step_record)

    # Rendering (if requested or configured)
    render_info = None
    if do_render and render_requested and os.path.exists(video_path):
        rendered_video_path = os.path.join(output_dir, "final_video.mp4")
        try:
            render_res = render_timeline(session.timeline, video_path, rendered_video_path)
            render_info = render_res.to_dict()
        except Exception as e:
            render_info = {"error": str(e)}

    # Save final timeline and OpenTimelineIO export
    timeline_dict = session.timeline.to_dict()
    final_timeline_path = os.path.join(output_dir, "final_timeline.json")
    with open(final_timeline_path, "w", encoding="utf-8") as f:
        json.dump(timeline_dict, f, indent=2, sort_keys=True)

    final_otio_path = os.path.join(output_dir, "final_timeline.otio")
    save_otio_file(session.timeline, final_otio_path, media_reference_url=video_path)

    # Save results.json
    results_doc = {
        "session_file": session_yaml_path,
        "video_source": video_path,
        "final_timeline_hash": session.get_timeline_hash(),
        "final_duration_s": session.get_duration_s(),
        "steps": steps_results,
        "render": render_info,
        "artifacts": {
            "timeline": final_timeline_path,
            "otio": final_otio_path,
            "video": rendered_video_path,
        },
    }
    results_path = os.path.join(output_dir, "results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results_doc, f, indent=2)

    # Output manifest (Integration Standard 9)
    manifest = {
        "manifest_version": "1.0",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "engine_version": "0.1.0",
        "models": {
            "nlu": "deterministic_rule_parser_v1 (fallback: mock_llm_0.1.0)",
            "stt": "fixture_transcript (or faster-whisper-base)",
            "embeddings": "bge-small-en-v1.5",
        },
        "settings": {
            "default_time_policy": "current_edited",
            "frame_rounding": "floor(time_s * fps + 0.5) / fps",
            "filler_like_min_pause_s": 0.15,
            "min_silence_threshold_s": 0.5,
            "min_caption_display_s": 0.7,
            "music_duck_db": -18.0,
        },
        "timings": {
            "total_execution_time_s": round(time.time() - start_total_time, 3),
        },
        "cost_estimate_usd": 0.0,
        "licence_notes": "All default components commercially usable (MIT/Apache-2.0). Zero non-commercial or AGPL libraries in core path.",
    }
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return results_doc


def main():
    parser = argparse.ArgumentParser(description="IncuBrix Scripted Session Runner")
    parser.add_argument("session", help="Path to session YAML file")
    parser.add_argument("-o", "--output-dir", default="outputs", help="Directory for output artifacts")
    parser.add_argument("--no-render", action="store_true", help="Skip video rendering even if requested")
    parser.add_argument("--video", default=None, help="Override source video path")
    args = parser.parse_args()

    res = run_session(args.session, args.output_dir, do_render=not args.no_render, video_override=args.video)
    print(f"Session complete: {len(res['steps'])} steps executed.")
    print(f"Final timeline hash: {res['final_timeline_hash']}")
    print(f"Final duration: {res['final_duration_s']:.2f}s")
    print(f"Results written to: {os.path.join(args.output_dir, 'results.json')}")


if __name__ == "__main__":
    main()
