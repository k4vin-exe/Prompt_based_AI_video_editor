"""
tests/unit/test_engine_session.py
---------------------------------
Comprehensive tests for engine.session:
- The 8-step Worked Example from the brief
- Hard cases and rule-based rejections
- 3-run determinism verification (100% identical timeline_hash)
"""
import pytest
from engine.transcript import build_transcript
from engine.session import Session
from engine.answer import AppliedAnswer, ClarificationAnswer, RejectedAnswer


def _create_interview_session(interview_transcript) -> Session:
    return Session(interview_transcript)


class TestWorkedExample:
    """
    Verify the exact 8-step worked example specified in BRIEF.pdf §Core level:
      1. Add a caption 'Welcome!' when I say welcome to the channel -> Applied
      2. Cut the first 30 seconds -> Applied (caption now plays at 0:12-0:14)
      3. Remove the part about pricing -> Needs clarification (3 mentions: 1:05, 2:40, 3:15)
         User: the second one -> Applied
      4. Speed up from 1:00 to 1:30 by 2x -> Applied, stating time policy
      5. Actually, put the intro back -> Applied (intro returns, caption at 0:42, pricing/speed stay)
      6. Undo -> Reverses step 5 only
      7. Make that caption red -> Applied to Welcome! caption
      8. Render -> Audio and video in sync, caption on right words
    """

    def test_worked_example_full_flow(self, interview_transcript):
        session = Session(interview_transcript)
        orig_dur = session.get_duration_s()
        assert orig_dur == 300.0

        # Step 1: Add caption
        ans1 = session.process_instruction("Add a caption 'Welcome!' when I say welcome to the channel")
        assert isinstance(ans1, AppliedAnswer)
        assert ans1.status == "applied"
        assert len(session.timeline.captions) == 1
        cap = session.timeline.captions[0]
        assert cap.text == "Welcome!"
        # In original source, "welcome to the channel" is 42.0s to 44.0s
        assert cap.edited_start_us == 42_000_000
        assert cap.edited_end_us == 44_000_000

        # Step 2: Cut first 30 seconds
        ans2 = session.process_instruction("Cut the first 30 seconds")
        assert isinstance(ans2, AppliedAnswer)
        assert ans2.status == "applied"
        assert session.get_duration_s() == 270.0
        # Caption now plays at 0:12-0:14 (42s - 30s = 12s)
        cap = session.timeline.captions[0]
        assert cap.edited_start_us == 12_000_000
        assert cap.edited_end_us == 14_000_000

        # Step 3: Remove the part about pricing -> Clarification needed
        ans3 = session.process_instruction("Remove the part about pricing")
        assert isinstance(ans3, ClarificationAnswer)
        assert ans3.status == "needs_clarification"
        assert "Pricing is mentioned at" in ans3.question
        assert len(ans3.options) >= 3

        # User clarification reply: "the second one"
        ans3_reply = session.process_instruction("the second one")
        assert isinstance(ans3_reply, AppliedAnswer)
        assert ans3_reply.status == "applied"
        assert "second mention" in ans3_reply.summary.lower()

        # Step 4: Speed up from 1:00 to 1:30 by 2x
        ans4 = session.process_instruction("Speed up from 1:00 to 1:30 by 2x")
        assert isinstance(ans4, AppliedAnswer)
        assert ans4.status == "applied"
        assert ans4.time_policy == "current_edited"

        # Step 5: Actually, put the intro back
        dur_before_restore = session.get_duration_s()
        ans5 = session.process_instruction("Actually, put the intro back")
        assert isinstance(ans5, AppliedAnswer)
        assert ans5.status == "applied"
        # First 30 seconds returned: duration is ~30s longer than before restore
        assert session.get_duration_s() > dur_before_restore
        # Caption is back at 0:42!
        cap = session.timeline.captions[0]
        assert cap.edited_start_us == 42_000_000
        assert cap.edited_end_us == 44_000_000

        # Step 6: Undo -> Reverses step 5 only
        ans6 = session.process_instruction("Undo")
        assert isinstance(ans6, AppliedAnswer)
        # Intro is cut again!
        assert session.get_duration_s() == pytest.approx(dur_before_restore, 0.1)
        cap = session.timeline.captions[0]
        assert cap.edited_start_us == 12_000_000

        # Step 7: Make that caption red
        ans7 = session.process_instruction("Make that caption red")
        assert isinstance(ans7, AppliedAnswer)
        assert session.timeline.captions[0].style.get("color") == "#ff0000"

        # Step 8: Render
        ans8 = session.process_instruction("Render")
        assert isinstance(ans8, AppliedAnswer)
        assert ans8.status == "applied"


class TestDeterminism:
    """Must-have 4: Same session run 3 times must produce 100% identical timeline_hash."""

    def test_three_runs_identical_hash(self, interview_transcript):
        steps = [
            "Add a caption 'Welcome!' when I say welcome to the channel",
            "Cut the first 30 seconds",
            "Remove the part about pricing",
            "the second one",
            "Speed up from 1:00 to 1:30 by 2x",
            "Make that caption red",
        ]

        hashes = []
        for run in range(3):
            session = Session(interview_transcript)
            for step in steps:
                session.process_instruction(step)
            hashes.append(session.get_timeline_hash())

        assert hashes[0] == hashes[1] == hashes[2]
        assert len(set(hashes)) == 1


class TestHardCasesAndRejections:
    """Verify rule enforcement and edge cases from Brief §Hard cases."""

    def test_whole_video_cut_rejected(self, interview_transcript):
        session = Session(interview_transcript)
        ans = session.process_instruction("cut everything")
        assert isinstance(ans, RejectedAnswer)
        assert ans.error_code == "WHOLE_VIDEO_CUT"

    def test_speed_out_of_range_rejected(self, interview_transcript):
        session = Session(interview_transcript)
        ans = session.process_instruction("speed up 10x")
        assert isinstance(ans, RejectedAnswer)
        assert ans.error_code == "SPEED_OUT_OF_RANGE"

    def test_silence_threshold_too_low(self, interview_transcript):
        session = Session(interview_transcript)
        ans = session.process_instruction("remove silences longer than 0.2 seconds")
        assert isinstance(ans, RejectedAnswer)
        assert ans.error_code == "SILENCE_THRESHOLD_TOO_LOW"

    def test_duplicate_cut_rejected(self, interview_transcript):
        session = Session(interview_transcript)
        ans1 = session.process_instruction("Cut 0:30-0:40 in the original")
        assert isinstance(ans1, AppliedAnswer)
        ans2 = session.process_instruction("Cut 0:30-0:40 in the original")
        assert isinstance(ans2, RejectedAnswer)
        assert ans2.error_code == "DUPLICATE_OPERATION"

    def test_restyle_caption_when_none_exists(self, interview_transcript):
        session = Session(interview_transcript)
        ans = session.process_instruction("make that caption red")
        assert isinstance(ans, RejectedAnswer)
        assert ans.error_code == "CAPTION_NO_WORDS"

    def test_restore_sentence_under_caption(self, interview_transcript):
        session = Session(interview_transcript)
        # Add caption on "welcome to the channel"
        session.process_instruction("Add a caption 'Welcome!' when I say welcome to the channel")
        # Cut that exact sentence
        session.process_instruction("Cut from 0:40 to 0:45 in the original")
        # Caption is now hidden
        assert session.timeline.captions[0].hidden is True
        # Undo the cut
        session.process_instruction("Undo")
        # Caption is restored and visible
        assert session.timeline.captions[0].hidden is False

    def test_filler_word_removal(self, interview_transcript):
        session = Session(interview_transcript)
        ans = session.process_instruction("Cut out the ums")
        assert isinstance(ans, AppliedAnswer)
        assert "filler" in ans.summary.lower()

    def test_silence_removal_with_deliberate_pause(self, interview_transcript):
        session = Session(interview_transcript)
        ans = session.process_instruction("remove silences longer than 1.0 second")
        assert isinstance(ans, AppliedAnswer)
