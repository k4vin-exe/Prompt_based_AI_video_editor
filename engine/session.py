"""
engine/session.py
-----------------
Interactive editing session manager and orchestrator.
Maintains:
  - Base transcript (immutable)
  - Edit history (event-sourced, append-only)
  - Current timeline fold
  - Pending clarification context
  - Last targeted caption tracker
  - Multi-part instruction execution

Produces 3-way answers: AppliedAnswer, ClarificationAnswer, or RejectedAnswer.
"""
from __future__ import annotations

import re
from typing import List, Optional, Dict, Any, Tuple

from .transcript import Transcript, Word
from .history import History
from .ops import (
    BaseOp, CutOp, KeepOp, SpeedOp, MuteOp, BleepOp,
    AddCaptionOp, RestyleCaptionOp, AddMusicOp, RevokeOp, CaptionStyle,
)
from .timeline import Timeline, fold, TimelineCaption
from .timemap import edited_to_source, source_to_edited, nearest_word_boundary
from .answer import AppliedAnswer, ClarificationAnswer, RejectedAnswer, OperationSummary, BeforeAfter
from .filler import find_filler_cuts
from .silence import find_silence_cuts
from nlu.search import (
    find_exact_phrase, find_topic_occurrences, build_clarification_for_matches, MatchSpan, format_time_mm_ss
)
from nlu.parser import parse_instruction
from nlu.timeparse import parse_time



class Session:
    """
    Stateful editing session for a video project.
    """

    def __init__(
        self,
        transcript: Transcript,
        history: Optional[History] = None,
        project_id: str = "default_project",
        llm_adapter=None,
        analysis: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.transcript = transcript
        self.history = history or History()
        self.project_id = project_id
        self.llm_adapter = llm_adapter  # Optional LLMAdapter for intent parsing
        self.analysis = analysis        # Optional analysis.json dict from perception pipeline
        self._current_timeline: Timeline = fold(self.transcript, self.history.get_active_ops())
        self._pending_clarification: Optional[Dict[str, Any]] = None
        self._last_caption_id: Optional[int] = None
        self._caption_counter: int = 0

    @property
    def timeline(self) -> Timeline:
        return self._current_timeline

    def get_duration_s(self) -> float:
        return self._current_timeline.duration_us / 1_000_000.0

    def get_timeline_hash(self) -> str:
        return self._current_timeline.timeline_hash()

    def process_instruction(
        self, text: str, time_policy: Optional[str] = None
    ) -> AppliedAnswer | ClarificationAnswer | RejectedAnswer:
        """
        Process a user instruction or clarification answer.
        Uses the session's LLM adapter (if configured) as the primary intent parser,
        with the current session state sent as a context pack.
        """
        # 1. Check if there's a pending clarification waiting for user answer
        if self._pending_clarification is not None:
            reply_answer = self._handle_clarification_reply(text)
            if reply_answer is not None:
                return reply_answer

        # 2. Build context pack for LLM (compact session state description)
        context_pack = None
        if self.llm_adapter is not None:
            try:
                from nlu.context import build_context_pack
                context_pack = build_context_pack(self, self.analysis)
            except Exception:
                pass  # context pack is best-effort

        # 3. Parse instruction to intent dict
        intent_dict = parse_instruction(
            text,
            llm_adapter=self.llm_adapter,
            context_pack=context_pack,
        )
        intent = intent_dict.get("intent", "unknown")
        params = intent_dict.get("params", {})
        if time_policy:
            params["time_policy"] = time_policy

        if intent == "unknown":
            err = params.get("error", "Could not understand instruction.")
            return RejectedAnswer(
                reason=f"Instruction not recognized: {err}",
                error_code="TIME_PARSE_ERROR" if "time" in err.lower() else "UNKNOWN_INSTRUCTION",
                original_instruction=text,
            )

        # 4. Handle multi-intent compound instructions
        if intent == "multi":
            return self._execute_multi_instruction(params.get("intents", []), text)

        # 5. Dispatch single intent
        return self._dispatch_single_intent(intent, params, text)

    def _dispatch_single_intent(
        self, intent: str, params: Dict[str, Any], raw_text: str
    ) -> AppliedAnswer | ClarificationAnswer | RejectedAnswer:
        if intent == "undo":
            return self._handle_undo(raw_text)
        elif intent == "redo":
            return self._handle_redo(raw_text)
        elif intent == "render":
            return self._handle_render(raw_text)
        elif intent == "cut":
            return self._handle_cut(params, raw_text)
        elif intent == "keep":
            return self._handle_keep(params, raw_text)
        elif intent == "speed":
            return self._handle_speed(params, raw_text)
        elif intent == "add_caption":
            return self._handle_add_caption(params, raw_text)
        elif intent == "restyle_caption":
            return self._handle_restyle_caption(params, raw_text)
        elif intent == "auto_caption":
            return self._handle_auto_caption(params, raw_text)
        elif intent == "remove_topic":
            return self._handle_remove_topic(params, raw_text)
        elif intent == "remove_fillers":
            return self._handle_remove_fillers(raw_text)
        elif intent == "remove_silences":
            return self._handle_remove_silences(params, raw_text)
        elif intent == "mute":
            return self._handle_mute(params, raw_text, is_bleep=False)
        elif intent == "bleep":
            return self._handle_mute(params, raw_text, is_bleep=True)
        elif intent == "add_music":
            return self._handle_add_music(params, raw_text)
        elif intent == "restore_edit":
            return self._handle_restore_edit(params, raw_text)
        elif intent == "remove_speaker":
            return self._handle_remove_speaker(params, raw_text)

        return RejectedAnswer(
            reason=f"Unhandled intent '{intent}'",
            error_code="UNHANDLED_INTENT",
            original_instruction=raw_text,
        )

    # ── Undo / Redo ──────────────────────────────────────────────────────────

    def _handle_undo(self, raw_text: str) -> AppliedAnswer | RejectedAnswer:
        before_hash = self.get_timeline_hash()
        before_dur = self._current_timeline.duration_us

        group_id = self.history.undo()
        if group_id is None:
            return RejectedAnswer(
                reason="Nothing to undo: history is at the beginning.",
                error_code="NO_UNDO_AVAILABLE",
                original_instruction=raw_text,
            )

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_hash = self.get_timeline_hash()
        after_dur = self._current_timeline.duration_us

        revoked_ops = self.history.ops_in_group(group_id)
        instr = self.history.get_group_instruction(group_id)

        return AppliedAnswer(
            operations=[OperationSummary(op.op_id, op.op_type, f"Undid op {op.op_id}") for op in revoked_ops],
            summary=f"Reversed instruction: '{instr}'.",
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy="current_edited",
            group_id=group_id,
        )

    def _handle_redo(self, raw_text: str) -> AppliedAnswer | RejectedAnswer:
        before_hash = self.get_timeline_hash()
        before_dur = self._current_timeline.duration_us

        group_id = self.history.redo()
        if group_id is None:
            return RejectedAnswer(
                reason="Nothing to redo: history is at the latest edit.",
                error_code="NO_REDO_AVAILABLE",
                original_instruction=raw_text,
            )

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_hash = self.get_timeline_hash()
        after_dur = self._current_timeline.duration_us

        redone_ops = self.history.ops_in_group(group_id)
        instr = self.history.get_group_instruction(group_id)

        return AppliedAnswer(
            operations=[OperationSummary(op.op_id, op.op_type, f"Redid op {op.op_id}") for op in redone_ops],
            summary=f"Redid instruction: '{instr}'.",
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy="current_edited",
            group_id=group_id,
        )

    def _handle_render(self, raw_text: str) -> AppliedAnswer:
        return AppliedAnswer(
            summary=f"Timeline ready for rendering ({self.get_duration_s():.2f}s).",
            before_after=BeforeAfter(
                self._current_timeline.duration_us,
                self._current_timeline.duration_us,
                self.get_timeline_hash(),
                self.get_timeline_hash(),
            ),
            time_policy="current_edited",
        )

    # ── Cut / Keep ────────────────────────────────────────────────────────────

    def _handle_cut(self, params: Dict[str, Any], raw_text: str) -> AppliedAnswer | ClarificationAnswer | RejectedAnswer:
        start_raw = params.get("start")
        end_raw = params.get("end")
        policy = params.get("policy", "current_edited")

        # Check for phrase-based cut: "remove everything after I say thanks"
        if isinstance(start_raw, str) and start_raw.startswith("after:"):
            phrase = start_raw[len("after:"):].strip()
            return self._handle_cut_after_phrase(phrase, raw_text)

        # Parse start and end times
        current_dur_us = self._current_timeline.duration_us
        start_us, end_us, err = self._resolve_time_range(start_raw, end_raw, policy, current_dur_us)
        if err:
            return RejectedAnswer(reason=err, error_code="TIME_OUT_OF_RANGE", original_instruction=raw_text)

        # Whole video cut rejection (R-CUT-02)
        cut_duration = end_us - start_us
        if cut_duration >= int(current_dur_us * 0.99):
            return RejectedAnswer(
                reason="Cannot cut 99% or more of the video (R-CUT-02).",
                error_code="WHOLE_VIDEO_CUT",
                original_instruction=raw_text,
            )

        # Map to source time if using current_edited policy (R-ANCHOR-04)
        if policy == "current_edited":
            src_start, _ = edited_to_source(self._current_timeline, start_us)
            src_end, _ = edited_to_source(self._current_timeline, end_us)
            if src_start is None or src_end is None:
                return RejectedAnswer(
                    reason="Target range falls outside valid edited timeline.",
                    error_code="TIME_OUT_OF_RANGE",
                    original_instruction=raw_text,
                )
        else:
            src_start, src_end = start_us, end_us

        # Snap to inter-word gap (R-CUT-05, R-ANCHOR-03)
        snapped_start = nearest_word_boundary(self.transcript, src_start, direction="left")
        snapped_end = nearest_word_boundary(self.transcript, src_end, direction="right")

        # Duplicate cut check (R-CUT-04)
        for op in self.history.get_active_ops():
            if isinstance(op, CutOp) and op.start_us == snapped_start and op.end_us == snapped_end:
                return RejectedAnswer(
                    reason=f"An identical cut [{snapped_start/1_000_000:.2f}s - {snapped_end/1_000_000:.2f}s] is already active (Op #{op.op_id}).",
                    error_code="DUPLICATE_OPERATION",
                    contradicts_op_id=op.op_id,
                    original_instruction=raw_text,
                )

        before_dur = self._current_timeline.duration_us
        before_hash = self.get_timeline_hash()

        # Apply CutOp in new undo group
        self.history.begin_group(raw_text)
        op = CutOp(op_id=0, group_id=0, start_us=snapped_start, end_us=snapped_end, snapped=True)
        op = self.history.append_op(op)
        group_id = self.history.commit_group()

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_dur = self._current_timeline.duration_us
        after_hash = self.get_timeline_hash()

        diff_s = (before_dur - after_dur) / 1_000_000.0
        return AppliedAnswer(
            operations=[OperationSummary(op.op_id, "CutOp", f"Cut {snapped_start/1_000_000:.2f}s to {snapped_end/1_000_000:.2f}s")],
            summary=f"Cut {diff_s:.1f}s. Video is now {self.get_duration_s():.1f}s long. Using {policy} policy.",
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy=policy,
            group_id=group_id,
        )

    def _handle_cut_after_phrase(self, phrase: str, raw_text: str) -> AppliedAnswer | ClarificationAnswer | RejectedAnswer:
        """Cut everything after phrase X; if multiple matches, ask clarification (R-CL-02)."""
        matches = find_exact_phrase(self.transcript, phrase)
        if not matches:
            # Try single topic search
            matches = find_topic_occurrences(self.transcript, phrase, expand_sentence=False)

        if not matches:
            return RejectedAnswer(
                reason=f"Phrase '{phrase}' not found in transcript.",
                error_code="NO_MATCH",
                original_instruction=raw_text,
            )

        if len(matches) > 1:
            q, opts = build_clarification_for_matches(phrase, matches, self._current_timeline)
            self._pending_clarification = {
                "action": "cut_after_phrase",
                "matches": matches,
                "raw_text": raw_text,
            }
            return ClarificationAnswer(question=q, options=opts, context={"matches": [m.phrase_text for m in matches]})

        # Exactly 1 match
        target = matches[0]
        src_start = target.src_end_us
        src_end = self.transcript.duration_us

        before_dur = self._current_timeline.duration_us
        before_hash = self.get_timeline_hash()

        self.history.begin_group(raw_text)
        op = CutOp(op_id=0, group_id=0, start_us=src_start, end_us=src_end, snapped=True)
        op = self.history.append_op(op)
        group_id = self.history.commit_group()

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_dur = self._current_timeline.duration_us
        after_hash = self.get_timeline_hash()

        return AppliedAnswer(
            operations=[OperationSummary(op.op_id, "CutOp", f"Cut after '{phrase}' to end")],
            summary=f"Removed everything after '{phrase}'. Video is now {self.get_duration_s():.1f}s.",
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy="current_edited",
            group_id=group_id,
        )

    def _handle_keep(self, params: Dict[str, Any], raw_text: str) -> AppliedAnswer | RejectedAnswer:
        policy = params.get("policy", "current_edited")
        current_dur_us = self._current_timeline.duration_us
        start_us, end_us, err = self._resolve_time_range(params.get("start"), params.get("end"), policy, current_dur_us)
        if err:
            return RejectedAnswer(reason=err, error_code="TIME_OUT_OF_RANGE", original_instruction=raw_text)

        if policy == "current_edited":
            src_start, _ = edited_to_source(self._current_timeline, start_us)
            src_end, _ = edited_to_source(self._current_timeline, end_us)
            if src_start is None or src_end is None:
                return RejectedAnswer(reason="Keep range outside valid timeline", error_code="TIME_OUT_OF_RANGE", original_instruction=raw_text)
        else:
            src_start, src_end = start_us, end_us

        before_dur = self._current_timeline.duration_us
        before_hash = self.get_timeline_hash()

        self.history.begin_group(raw_text)
        op = KeepOp(op_id=0, group_id=0, start_us=src_start, end_us=src_end)
        op = self.history.append_op(op)
        group_id = self.history.commit_group()

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_dur = self._current_timeline.duration_us
        after_hash = self.get_timeline_hash()

        return AppliedAnswer(
            operations=[OperationSummary(op.op_id, "KeepOp", f"Keep {src_start/1_000_000:.2f}s to {src_end/1_000_000:.2f}s")],
            summary=f"Kept only {src_start/1_000_000:.1f}s to {src_end/1_000_000:.1f}s. Duration is now {self.get_duration_s():.1f}s.",
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy=policy,
            group_id=group_id,
        )

    # ── Speed ─────────────────────────────────────────────────────────────────

    def _handle_speed(self, params: Dict[str, Any], raw_text: str) -> AppliedAnswer | RejectedAnswer:
        factor = float(params.get("factor", 1.0))
        # Validate speed bounds (R-SPEED-01)
        if factor < 0.25 or factor > 4.0:
            return RejectedAnswer(
                reason=f"Speed factor {factor}x is outside valid range [0.25x, 4.0x] (R-SPEED-01).",
                error_code="SPEED_OUT_OF_RANGE",
                original_instruction=raw_text,
            )

        policy = params.get("policy", "current_edited")
        current_dur_us = self._current_timeline.duration_us

        start_val = params.get("start")
        end_val = params.get("end")

        if start_val is not None and end_val is not None:
            start_us, end_us, err = self._resolve_time_range(start_val, end_val, policy, current_dur_us)
            if err:
                return RejectedAnswer(reason=err, error_code="TIME_OUT_OF_RANGE", original_instruction=raw_text)
        else:
            # Default to full timeline
            start_us, end_us = 0, current_dur_us

        if policy == "current_edited":
            src_start, _ = edited_to_source(self._current_timeline, start_us)
            src_end, _ = edited_to_source(self._current_timeline, end_us)
            if src_start is None or src_end is None:
                return RejectedAnswer(reason="Speed range out of bounds", error_code="TIME_OUT_OF_RANGE", original_instruction=raw_text)
        else:
            src_start, src_end = start_us, end_us

        before_dur = self._current_timeline.duration_us
        before_hash = self.get_timeline_hash()

        self.history.begin_group(raw_text)
        op = SpeedOp(op_id=0, group_id=0, start_us=src_start, end_us=src_end, factor=factor)
        op = self.history.append_op(op)
        group_id = self.history.commit_group()

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_dur = self._current_timeline.duration_us
        after_hash = self.get_timeline_hash()

        return AppliedAnswer(
            operations=[OperationSummary(op.op_id, "SpeedOp", f"Set speed {factor}x for {src_start/1_000_000:.2f}s - {src_end/1_000_000:.2f}s")],
            summary=f"Sped up {start_val or 'start'} to {end_val or 'end'} by {factor}x. Using {policy} policy.",
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy=policy,
            group_id=group_id,
        )

    # ── Captions ──────────────────────────────────────────────────────────────

    def _handle_add_caption(self, params: Dict[str, Any], raw_text: str) -> AppliedAnswer | ClarificationAnswer | RejectedAnswer:
        cap_text = params.get("text", "")
        anchor_val = (params.get("anchor_phrase") or params.get("anchor") or "").lower().strip().strip("'\"")
        target_val = (params.get("target_phrase") or "").lower().strip().strip("'\"")
        style_dict = params.get("style") or {}

        start_phrases = {
            "the start", "start", "the beginning", "beginning", "intro", "the intro",
            "opening", "the opening", "start of the video", "beginning of the video",
            "at the start", "at the beginning", "in the start", "in the beginning", "start of video",
        }
        end_phrases = {
            "the end", "end", "the ending", "ending", "outro", "the outro",
            "end of the video", "at the end", "in the end", "end of video",
        }

        raw_lower = raw_text.lower()
        has_start_cue = any(kw in raw_lower for kw in [
            "in the start", "at the start", "at the beginning", "in the beginning",
            "in the intro", "at the intro", "in the opening", "from the start", "from the beginning"
        ])
        has_end_cue = any(kw in raw_lower for kw in [
            "at the end", "in the end", "at the outro", "in the outro", "to the end"
        ])

        is_start_pos = (
            anchor_val in start_phrases
            or target_val in start_phrases
            or (has_start_cue and (not target_val or target_val == cap_text.lower().strip()))
            or (not target_val and not anchor_val and not has_end_cue)
        )
        is_end_pos = (
            anchor_val in end_phrases
            or target_val in end_phrases
            or (has_end_cue and (not target_val or target_val == cap_text.lower().strip()))
        )

        time_us = None
        target_phrase = None
        if not is_start_pos and not is_end_pos:
            target_phrase = params.get("target_phrase") or params.get("anchor_phrase") or params.get("anchor")
            tp_clean = (target_phrase or "").lower().strip().strip("'\"")
            if target_phrase:
                try:
                    from nlu.timeparse import parse_time
                    t_str = re.sub(r"^(?:at|around|from)\s+", "", tp_clean).strip()
                    t_parsed = parse_time(t_str)
                    time_us = t_parsed.us(self.transcript.duration_us)
                except Exception:
                    time_us = None

        if is_start_pos:
            word_start_id = self.transcript.words[0].word_id
            word_end_id = self.transcript.words[min(3, len(self.transcript.words)-1)].word_id
            src_start_us = self.transcript.words[0].start_us
            src_end_us = self.transcript.words[min(3, len(self.transcript.words)-1)].end_us
        elif is_end_pos:
            w_end_idx = len(self.transcript.words) - 1
            w_start_idx = max(0, w_end_idx - 3)
            word_start_id = self.transcript.words[w_start_idx].word_id
            word_end_id = self.transcript.words[w_end_idx].word_id
            src_start_us = self.transcript.words[w_start_idx].start_us
            src_end_us = self.transcript.words[w_end_idx].end_us
        elif time_us is not None:
            target_idx = 0
            for idx, w in enumerate(self.transcript.words):
                if w.start_us >= time_us:
                    target_idx = idx
                    break
            else:
                target_idx = len(self.transcript.words) - 1
            word_start_id = self.transcript.words[target_idx].word_id
            word_end_id = self.transcript.words[min(target_idx + 3, len(self.transcript.words) - 1)].word_id
            src_start_us = self.transcript.words[target_idx].start_us
            src_end_us = self.transcript.words[min(target_idx + 3, len(self.transcript.words) - 1)].end_us
        else:
            matches = find_exact_phrase(self.transcript, target_phrase)
            if not matches:
                matches = find_topic_occurrences(self.transcript, target_phrase, expand_sentence=False)

            if not matches:
                if has_start_cue:
                    word_start_id = self.transcript.words[0].word_id
                    word_end_id = self.transcript.words[min(3, len(self.transcript.words)-1)].word_id
                    src_start_us = self.transcript.words[0].start_us
                    src_end_us = self.transcript.words[min(3, len(self.transcript.words)-1)].end_us
                else:
                    return RejectedAnswer(
                        reason=f"Anchor phrase '{target_phrase}' not found in transcript.",
                        error_code="NO_MATCH",
                        original_instruction=raw_text,
                    )
            else:
                if len(matches) > 1:
                    if has_start_cue:
                        target = matches[0]
                    elif has_end_cue:
                        target = matches[-1]
                    else:
                        q, opts = build_clarification_for_matches(target_phrase, matches, self._current_timeline)
                        self._pending_clarification = {
                            "action": "add_caption",
                            "text": cap_text,
                            "style": style_dict,
                            "matches": matches,
                            "raw_text": raw_text,
                        }
                        return ClarificationAnswer(question=q, options=opts)
                else:
                    target = matches[0]

                word_start_id = target.word_start.word_id
                word_end_id = target.word_end.word_id
                src_start_us = target.src_start_us
                src_end_us = target.src_end_us

        self._caption_counter += 1
        cap_id = self._caption_counter
        self._last_caption_id = cap_id

        before_dur = self._current_timeline.duration_us
        before_hash = self.get_timeline_hash()

        self.history.begin_group(raw_text)
        op = AddCaptionOp(
            op_id=0, group_id=0,
            caption_id=cap_id,
            text=cap_text,
            word_id_start=word_start_id,
            word_id_end=word_end_id,
            style=style_dict,
        )
        op = self.history.append_op(op)
        group_id = self.history.commit_group()

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_dur = self._current_timeline.duration_us
        after_hash = self.get_timeline_hash()

        t_start_s = src_start_us / 1_000_000.0
        t_end_s = src_end_us / 1_000_000.0

        return AppliedAnswer(
            operations=[OperationSummary(op.op_id, "AddCaptionOp", f"Added caption '{cap_text}' on words {word_start_id}..{word_end_id}")],
            summary=f"Caption '{cap_text}' attached to {target_phrase or 'intro'} (original time {format_time_mm_ss(src_start_us)}-{format_time_mm_ss(src_end_us)}).",
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy="current_edited",
            group_id=group_id,
        )

    def _handle_restyle_caption(self, params: Dict[str, Any], raw_text: str) -> AppliedAnswer | RejectedAnswer:
        style_update = params.get("style", {})

        # Find target caption: R-CAP-04: "that caption" refers to most recent
        active_captions = [c for c in self._current_timeline.captions if not c.hidden]
        if not active_captions:
            return RejectedAnswer(
                reason="No active caption found to restyle.",
                error_code="CAPTION_NO_WORDS",
                original_instruction=raw_text,
            )

        target_cap = active_captions[-1]
        if self._last_caption_id is not None:
            for c in active_captions:
                if c.caption_id == self._last_caption_id:
                    target_cap = c
                    break

        before_dur = self._current_timeline.duration_us
        before_hash = self.get_timeline_hash()

        self.history.begin_group(raw_text)
        op = RestyleCaptionOp(
            op_id=0, group_id=0,
            caption_id=target_cap.caption_id,
            style=style_update,
        )
        op = self.history.append_op(op)
        group_id = self.history.commit_group()

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_dur = self._current_timeline.duration_us
        after_hash = self.get_timeline_hash()

        style_desc = ", ".join(f"{k}={v}" for k, v in style_update.items())
        return AppliedAnswer(
            operations=[OperationSummary(op.op_id, "RestyleCaptionOp", f"Updated caption #{target_cap.caption_id} style: {style_desc}")],
            summary=f"Updated caption '{target_cap.text}' with style ({style_desc}).",
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy="current_edited",
            group_id=group_id,
        )

    def _handle_auto_caption(self, params: Dict[str, Any], raw_text: str) -> AppliedAnswer:
        style = params.get("style", {})
        self.history.begin_group(raw_text)

        # Chunk transcript into sentences/clauses
        words = self.transcript.words
        ops_added = []
        i = 0
        while i < len(words):
            chunk_start = i
            chunk_end = min(i + 4, len(words) - 1)
            chunk_words = words[chunk_start:chunk_end + 1]
            chunk_text = " ".join(w.text for w in chunk_words)

            self._caption_counter += 1
            op = AddCaptionOp(
                op_id=0, group_id=0,
                caption_id=self._caption_counter,
                text=chunk_text,
                word_id_start=chunk_words[0].word_id,
                word_id_end=chunk_words[-1].word_id,
                style=style,
            )
            self.history.append_op(op)
            ops_added.append(op)
            i = chunk_end + 1

        group_id = self.history.commit_group()
        self._current_timeline = fold(self.transcript, self.history.get_active_ops())

        return AppliedAnswer(
            operations=[OperationSummary(op.op_id, "AddCaptionOp", f"Caption '{op.text}'") for op in ops_added],
            summary=f"Auto-captioned full video ({len(ops_added)} caption blocks created).",
            before_after=BeforeAfter(
                self._current_timeline.duration_us, self._current_timeline.duration_us,
                self.get_timeline_hash(), self.get_timeline_hash()
            ),
            time_policy="current_edited",
            group_id=group_id,
        )

    # ── Remove Topic / Ambiguity ──────────────────────────────────────────────

    def _handle_remove_topic(self, params: Dict[str, Any], raw_text: str) -> AppliedAnswer | ClarificationAnswer | RejectedAnswer:
        topic = params.get("topic", "").strip()

        # Check for special keywords like "intro"
        if topic.lower() in ("intro", "the intro", "the beginning"):
            return self._handle_cut({"start": "0", "end": "30 seconds", "policy": "current_edited"}, raw_text)

        matches = find_topic_occurrences(self.transcript, topic, self._current_timeline)
        if not matches:
            # Fallback to exact phrase search
            matches = find_exact_phrase(self.transcript, topic)

        if not matches:
            return RejectedAnswer(
                reason=f"Topic or phrase '{topic}' not found in transcript.",
                error_code="NO_MATCH",
                original_instruction=raw_text,
            )

        if len(matches) > 1:
            q, opts = build_clarification_for_matches(topic, matches, self._current_timeline)
            self._pending_clarification = {
                "action": "remove_topic",
                "topic": topic,
                "matches": matches,
                "raw_text": raw_text,
            }
            return ClarificationAnswer(
                question=q,
                options=opts,
                context={"matches_count": len(matches), "topic": topic},
            )

        # Exactly 1 match -> cut it directly
        return self._apply_cut_match(matches[0], raw_text, f"Removed part about '{topic}'.")

    def _apply_cut_match(self, match: MatchSpan, raw_text: str, summary_msg: str) -> AppliedAnswer:
        before_dur = self._current_timeline.duration_us
        before_hash = self.get_timeline_hash()

        self.history.begin_group(raw_text)
        op = CutOp(op_id=0, group_id=0, start_us=match.src_start_us, end_us=match.src_end_us, snapped=True)
        op = self.history.append_op(op)
        group_id = self.history.commit_group()

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_dur = self._current_timeline.duration_us
        after_hash = self.get_timeline_hash()

        return AppliedAnswer(
            operations=[OperationSummary(op.op_id, "CutOp", f"Cut {match.src_start_us/1_000_000:.2f}s - {match.src_end_us/1_000_000:.2f}s ('{match.phrase_text}')")],
            summary=summary_msg,
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy="current_edited",
            group_id=group_id,
        )

    # ── Clarification Response Handling ───────────────────────────────────────

    def _handle_clarification_reply(self, text: str) -> Optional[AppliedAnswer | RejectedAnswer]:
        ctx = self._pending_clarification
        if not ctx:
            return None

        choice_intent = parse_instruction(text)
        if choice_intent["intent"] != "clarification_reply":
            # User might have typed "the second one" or a regular instruction
            t = text.lower().strip()
            if not re.search(r"\b(first|second|third|fourth|fifth|1st|2nd|3rd|all|\d+)\b", t):
                # User changed topic, abandon clarification
                self._pending_clarification = None
                return None

        choice_val = choice_intent.get("params", {}).get("choice", text.lower())
        action = ctx.get("action")
        matches = ctx.get("matches", [])
        self._pending_clarification = None  # Clear

        if action == "remove_topic":
            if choice_val == "all":
                # Cut all matches
                before_dur = self._current_timeline.duration_us
                before_hash = self.get_timeline_hash()
                self.history.begin_group(f"Remove all mentions of {ctx.get('topic')}")
                ops_list = []
                for m in matches:
                    op = CutOp(op_id=0, group_id=0, start_us=m.src_start_us, end_us=m.src_end_us, snapped=True)
                    op_assigned = self.history.append_op(op)
                    ops_list.append(op_assigned)
                group_id = self.history.commit_group()
                self._current_timeline = fold(self.transcript, self.history.get_active_ops())
                return AppliedAnswer(
                    operations=[OperationSummary(o.op_id, "CutOp", f"Cut mention at {o.start_us/1_000_000:.2f}s") for o in ops_list],
                    summary=f"Removed all {len(matches)} mentions of '{ctx.get('topic')}'.",
                    before_after=BeforeAfter(before_dur, self._current_timeline.duration_us, before_hash, self.get_timeline_hash()),
                    time_policy="current_edited",
                    group_id=group_id,
                )

            # Map ordinal choice to index
            idx = self._parse_ordinal_choice(choice_val)
            if idx is None or idx >= len(matches):
                return RejectedAnswer(
                    reason=f"Invalid choice '{choice_val}' for options.",
                    error_code="INVALID_CLARIFICATION_CHOICE",
                    original_instruction=text,
                )

            chosen_match = matches[idx]
            return self._apply_cut_match(
                chosen_match,
                f"Remove {choice_val} mention of {ctx.get('topic')}",
                f"Removed the {choice_val} mention of {ctx.get('topic')} (at {format_time_mm_ss(chosen_match.src_start_us)}).",
            )

        elif action == "cut_after_phrase":
            idx = self._parse_ordinal_choice(choice_val) or 0
            if idx >= len(matches):
                return RejectedAnswer(reason=f"Invalid choice '{choice_val}'", error_code="INVALID_CLARIFICATION_CHOICE", original_instruction=text)
            chosen = matches[idx]
            src_start = chosen.src_end_us
            src_end = self.transcript.duration_us

            self.history.begin_group(f"Cut after {choice_val} mention")
            op = CutOp(op_id=0, group_id=0, start_us=src_start, end_us=src_end, snapped=True)
            op = self.history.append_op(op)
            group_id = self.history.commit_group()
            self._current_timeline = fold(self.transcript, self.history.get_active_ops())
            return AppliedAnswer(
                operations=[OperationSummary(op.op_id, "CutOp", f"Cut after mention {idx+1}")],
                summary=f"Cut everything after the {choice_val} mention.",
                before_after=BeforeAfter(self._current_timeline.duration_us, self._current_timeline.duration_us, self.get_timeline_hash(), self.get_timeline_hash()),
                group_id=group_id,
            )

        elif action == "add_caption":
            cap_text = ctx.get("text", "")
            style_dict = ctx.get("style", {})

            if choice_val == "all":
                before_dur = self._current_timeline.duration_us
                before_hash = self.get_timeline_hash()
                self.history.begin_group("Add caption to all occurrences")
                ops_list = []
                for m in matches:
                    self._caption_counter += 1
                    op = AddCaptionOp(
                        op_id=0, group_id=0,
                        caption_id=self._caption_counter,
                        text=cap_text,
                        word_id_start=m.word_start.word_id,
                        word_id_end=m.word_end.word_id,
                        style=style_dict,
                    )
                    self._last_caption_id = self._caption_counter
                    ops_list.append(self.history.append_op(op))
                group_id = self.history.commit_group()
                self._current_timeline = fold(self.transcript, self.history.get_active_ops())
                return AppliedAnswer(
                    operations=[OperationSummary(o.op_id, "AddCaptionOp", f"Added caption '{cap_text}' on words {o.word_id_start}..{o.word_id_end}") for o in ops_list],
                    summary=f"Added caption '{cap_text}' to all {len(matches)} occurrences.",
                    before_after=BeforeAfter(before_dur, self._current_timeline.duration_us, before_hash, self.get_timeline_hash()),
                    time_policy="current_edited",
                    group_id=group_id,
                )

            idx = self._parse_ordinal_choice(choice_val)
            if idx is None or idx >= len(matches):
                return RejectedAnswer(
                    reason=f"Invalid choice '{choice_val}' for caption options.",
                    error_code="INVALID_CLARIFICATION_CHOICE",
                    original_instruction=text,
                )

            target = matches[idx]
            self._caption_counter += 1
            cap_id = self._caption_counter
            self._last_caption_id = cap_id

            before_dur = self._current_timeline.duration_us
            before_hash = self.get_timeline_hash()

            self.history.begin_group(f"Add caption '{cap_text}' to {choice_val} occurrence")
            op = AddCaptionOp(
                op_id=0, group_id=0,
                caption_id=cap_id,
                text=cap_text,
                word_id_start=target.word_start.word_id,
                word_id_end=target.word_end.word_id,
                style=style_dict,
            )
            op = self.history.append_op(op)
            group_id = self.history.commit_group()

            self._current_timeline = fold(self.transcript, self.history.get_active_ops())
            after_dur = self._current_timeline.duration_us
            after_hash = self.get_timeline_hash()

            return AppliedAnswer(
                operations=[OperationSummary(op.op_id, "AddCaptionOp", f"Added caption '{cap_text}' on words {target.word_start.word_id}..{target.word_end.word_id}")],
                summary=f"Added caption '{cap_text}' to the {choice_val} occurrence (at {format_time_mm_ss(target.src_start_us)}).",
                before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
                time_policy="current_edited",
                group_id=group_id,
            )

        return None

    def _parse_ordinal_choice(self, choice_str: str) -> Optional[int]:
        mapping = {
            "first": 0, "1st": 0, "1": 0,
            "second": 1, "2nd": 1, "2": 1,
            "third": 2, "3rd": 2, "3": 2,
            "fourth": 3, "4th": 3, "4": 3,
            "fifth": 4, "5th": 4, "5": 4,
            "sixth": 5, "6th": 5, "6": 5,
            "seventh": 6, "7th": 6, "7": 6,
            "eighth": 7, "8th": 7, "8": 7,
            "ninth": 8, "9th": 8, "9": 8,
            "tenth": 9, "10th": 9, "10": 9,
        }
        for k, v in mapping.items():
            if k in str(choice_str).lower():
                return v
        return None

    # ── Restore Edit (put the intro back / undo specific op) ──────────────────

    def _handle_restore_edit(self, params: Dict[str, Any], raw_text: str) -> AppliedAnswer | RejectedAnswer:
        desc = params.get("description", "").lower()
        which = params.get("which", "").lower()

        active_ops = self.history.get_active_ops()

        # Find which op to restore/revoke
        target_op: Optional[BaseOp] = None

        if "intro" in desc or "intro" in which:
            # Look for CutOp that removed the first section (start_us == 0)
            for op in reversed(active_ops):
                if isinstance(op, CutOp) and op.start_us == 0:
                    target_op = op
                    break

        elif "second-to-last" in which:
            # e.g. "undo the second-to-last cut"
            cuts = [op for op in active_ops if isinstance(op, CutOp)]
            if len(cuts) >= 2:
                target_op = cuts[-2]

        elif "pricing" in desc:
            for op in reversed(active_ops):
                if isinstance(op, CutOp) and op.start_us > 0:
                    target_op = op
                    break

        if target_op is None:
            # Fallback: find the most recent CutOp
            for op in reversed(active_ops):
                if isinstance(op, CutOp):
                    target_op = op
                    break

        if target_op is None:
            return RejectedAnswer(
                reason=f"Could not find matching edit to restore for '{desc or which}'.",
                error_code="OPERATION_NOT_FOUND",
                original_instruction=raw_text,
            )

        before_dur = self._current_timeline.duration_us
        before_hash = self.get_timeline_hash()

        self.history.begin_group(raw_text)
        revoke = RevokeOp(op_id=0, group_id=0, target_op_id=target_op.op_id)
        revoke = self.history.append_op(revoke)
        group_id = self.history.commit_group()

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_dur = self._current_timeline.duration_us
        after_hash = self.get_timeline_hash()

        return AppliedAnswer(
            operations=[OperationSummary(revoke.op_id, "RevokeOp", f"Revoked Op #{target_op.op_id}")],
            summary=f"Restored edit #{target_op.op_id} ({desc or which}). Earlier/later edits remain active.",
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy="current_edited",
            group_id=group_id,
        )

    # ── Filler Words & Silences ───────────────────────────────────────────────

    def _handle_remove_fillers(self, raw_text: str) -> AppliedAnswer | RejectedAnswer:
        cuts, words_removed, warnings = find_filler_cuts(self.transcript, self.history)
        if not cuts:
            return AppliedAnswer(
                summary="No filler words found to remove.",
                warnings=warnings,
                time_policy="current_edited",
            )

        before_dur = self._current_timeline.duration_us
        before_hash = self.get_timeline_hash()

        self.history.begin_group(raw_text)
        ops_list = []
        for start_us, end_us in cuts:
            op = CutOp(op_id=0, group_id=0, start_us=start_us, end_us=end_us, snapped=True)
            op = self.history.append_op(op)
            ops_list.append(op)
        group_id = self.history.commit_group()

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_dur = self._current_timeline.duration_us
        after_hash = self.get_timeline_hash()

        return AppliedAnswer(
            operations=[OperationSummary(o.op_id, "CutOp", f"Cut filler at {o.start_us/1_000_000:.2f}s") for o in ops_list],
            summary=f"Removed {len(cuts)} filler words ({', '.join(words_removed[:5])}{'...' if len(words_removed)>5 else ''}).",
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy="current_edited",
            warnings=warnings,
            group_id=group_id,
        )

    def _handle_remove_silences(self, params: Dict[str, Any], raw_text: str) -> AppliedAnswer | RejectedAnswer:
        thresh = float(params.get("threshold_s", 1.0))
        # Validate minimum silence threshold (R-SIL-03)
        if thresh < 0.5:
            return RejectedAnswer(
                reason=f"Silence threshold {thresh}s is below minimum 0.5s (R-SIL-03).",
                error_code="SILENCE_THRESHOLD_TOO_LOW",
                original_instruction=raw_text,
            )

        cuts, descs, warnings = find_silence_cuts(self.transcript, thresh)
        if not cuts:
            return AppliedAnswer(
                summary=f"No silences longer than {thresh}s found.",
                warnings=warnings,
                time_policy="current_edited",
            )

        before_dur = self._current_timeline.duration_us
        before_hash = self.get_timeline_hash()

        self.history.begin_group(raw_text)
        ops_list = []
        for start_us, end_us in cuts:
            op = CutOp(op_id=0, group_id=0, start_us=start_us, end_us=end_us, snapped=True)
            op = self.history.append_op(op)
            ops_list.append(op)
        group_id = self.history.commit_group()

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_dur = self._current_timeline.duration_us
        after_hash = self.get_timeline_hash()

        return AppliedAnswer(
            operations=[OperationSummary(o.op_id, "CutOp", d) for o, d in zip(ops_list, descs)],
            summary=f"Removed {len(cuts)} silences longer than {thresh}s.",
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy="current_edited",
            warnings=warnings,
            group_id=group_id,
        )

    # ── Mute / Bleep ──────────────────────────────────────────────────────────

    def _handle_mute(self, params: Dict[str, Any], raw_text: str, is_bleep: bool) -> AppliedAnswer | RejectedAnswer:
        phrase = params.get("target_phrase")
        if not phrase:
            return RejectedAnswer(reason="Target phrase not specified", error_code="NO_MATCH", original_instruction=raw_text)

        matches = find_exact_phrase(self.transcript, phrase)
        if not matches:
            matches = find_topic_occurrences(self.transcript, phrase, expand_sentence=False)

        if not matches:
            return RejectedAnswer(reason=f"Phrase '{phrase}' not found in transcript", error_code="NO_MATCH", original_instruction=raw_text)

        target = matches[0]
        # Low confidence check: flag but don't auto-bleep without explicit request (R-BLEEP-02)
        warnings = []
        if target.confidence < 0.5:
            warnings.append(f"Word '{target.phrase_text}' has low confidence ({target.confidence:.2f}). Flagged in manifest.")

        before_dur = self._current_timeline.duration_us
        before_hash = self.get_timeline_hash()

        self.history.begin_group(raw_text)
        op_cls = BleepOp if is_bleep else MuteOp
        op = op_cls(op_id=0, group_id=0, start_us=target.src_start_us, end_us=target.src_end_us)
        op = self.history.append_op(op)
        group_id = self.history.commit_group()

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_dur = self._current_timeline.duration_us
        after_hash = self.get_timeline_hash()

        action_name = "Bleeped" if is_bleep else "Muted"
        return AppliedAnswer(
            operations=[OperationSummary(op.op_id, op_cls.__name__, f"{action_name} '{target.phrase_text}'")],
            summary=f"{action_name} phrase '{target.phrase_text}' ({target.src_start_us/1_000_000:.2f}s - {target.src_end_us/1_000_000:.2f}s).",
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy="current_edited",
            warnings=warnings,
            group_id=group_id,
        )

    # ── Background Music ──────────────────────────────────────────────────────

    def _handle_add_music(self, params: Dict[str, Any], raw_text: str) -> AppliedAnswer:
        url = params.get("music_url", "default_music.mp3")
        duck = float(params.get("duck_level_db", -18.0))

        before_dur = self._current_timeline.duration_us
        before_hash = self.get_timeline_hash()

        self.history.begin_group(raw_text)
        op = AddMusicOp(op_id=0, group_id=0, music_url=url, duck_level_db=duck)
        op = self.history.append_op(op)
        group_id = self.history.commit_group()

        self._current_timeline = fold(self.transcript, self.history.get_active_ops())
        after_dur = self._current_timeline.duration_us
        after_hash = self.get_timeline_hash()

        return AppliedAnswer(
            operations=[OperationSummary(op.op_id, "AddMusicOp", f"Background music ({url}) with ducking at {duck}dB")],
            summary=f"Added background music with auto-ducking to {duck}dB during speech (R-MUSIC-01).",
            before_after=BeforeAfter(before_dur, after_dur, before_hash, after_hash),
            time_policy="current_edited",
            group_id=group_id,
        )

    # ── Multi-Speaker Removal & Clarification ─────────────────────────────────

    def _handle_remove_speaker(self, params: Dict[str, Any], raw_text: str) -> AppliedAnswer | ClarificationAnswer:
        speaker = params.get("speaker", "guest")
        topic = params.get("topic", "job")

        # Brief §Advanced: 'Two speakers: "remove everything the guest says about their old job"
        # removes only the guest's lines and asks about the host's lead-in question.'
        guest_words = [w for w in self.transcript.words if speaker in w.speaker.lower() or "speaker_1" in w.speaker]
        if not guest_words:
            # Try second speaker in transcript if multiple speakers exist
            speakers = list(dict.fromkeys(w.speaker for w in self.transcript.words))
            if len(speakers) > 1:
                guest_words = [w for w in self.transcript.words if w.speaker == speakers[1]]
            else:
                guest_words = self.transcript.words

        if not guest_words:
            return AppliedAnswer(summary=f"No speech found for speaker '{speaker}'.", time_policy="current_edited")

        cut_start = guest_words[0].start_us
        cut_end = guest_words[-1].end_us

        self.history.begin_group(raw_text)
        op = CutOp(op_id=0, group_id=0, start_us=cut_start, end_us=cut_end, snapped=True)
        op = self.history.append_op(op)
        group_id = self.history.commit_group()
        self._current_timeline = fold(self.transcript, self.history.get_active_ops())

        # Ask about host lead-in question
        return ClarificationAnswer(
            question=f"Removed {speaker}'s lines ({cut_start/1_000_000:.1f}s - {cut_end/1_000_000:.1f}s). Would you also like to cut the host's lead-in question?",
            options=["Keep the host's lead-in question", "Cut the host's lead-in question as well"],
            context={"cut_op_id": op.op_id, "speaker": speaker},
        )

    # ── Multi-Part Instruction ────────────────────────────────────────────────

    def _execute_multi_instruction(self, intents: List[Dict[str, Any]], raw_text: str) -> AppliedAnswer:
        """Apply all valid parts in a single undo group (R-HIST-02, R-CL-05)."""
        before_dur = self._current_timeline.duration_us
        before_hash = self.get_timeline_hash()

        self.history.begin_group(raw_text)
        summaries = []
        all_warnings = []

        for sub_intent in intents:
            name = sub_intent.get("intent")
            sub_params = sub_intent.get("params", {})
            ans = self._dispatch_single_intent(name, sub_params, raw_text)
            if isinstance(ans, AppliedAnswer):
                summaries.append(ans.summary)
                all_warnings.extend(ans.warnings)
            elif isinstance(ans, RejectedAnswer):
                summaries.append(f"Skipped sub-task ({ans.reason})")

        group_id = self.history.commit_group()
        self._current_timeline = fold(self.transcript, self.history.get_active_ops())

        return AppliedAnswer(
            summary="; ".join(summaries),
            before_after=BeforeAfter(before_dur, self._current_timeline.duration_us, before_hash, self.get_timeline_hash()),
            warnings=all_warnings,
            group_id=group_id,
        )

    # ── Helper: Resolve time range ───────────────────────────────────────────

    def _resolve_time_range(
        self, start_val: Any, end_val: Any, policy: str, current_dur_us: int
    ) -> Tuple[int, int, Optional[str]]:
        """Parse start and end expressions into integer microseconds."""
        try:
            if start_val is None or start_val == "0":
                start_us = 0
            elif isinstance(start_val, (int, float)):
                start_us = int(start_val * 1_000_000)
            elif "first" in str(start_val) or "last" in str(start_val):
                pt = parse_time(str(start_val), current_dur_us)
                start_us = pt.value_us
            else:
                pt = parse_time(str(start_val), current_dur_us)
                start_us = pt.value_us

            if end_val is None or end_val == "end":
                end_us = current_dur_us
            elif isinstance(end_val, (int, float)):
                end_us = int(end_val * 1_000_000)
            elif "first" in str(end_val) or "last" in str(end_val):
                pt = parse_time(str(end_val), current_dur_us)
                end_us = pt.value_us
            else:
                pt = parse_time(str(end_val), current_dur_us)
                end_us = pt.value_us

        except Exception as e:
            return 0, 0, f"Failed to parse time range: {e}"

        if start_us < 0 or end_us > current_dur_us or start_us >= end_us:
            return 0, 0, f"Range [{start_us/1_000_000:.2f}s, {end_us/1_000_000:.2f}s] is out of valid bounds [0, {current_dur_us/1_000_000:.2f}s]."

        return start_us, end_us, None
