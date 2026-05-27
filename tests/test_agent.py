"""Tests for the core agent loop logic.

These tests cover the pure/deterministic parts of engine/agent.py:
  - decide_next_stage: all stage transitions
  - AgentState serialization: to_json / from_json round-trip
  - agent_brain: correct state mutations for each tool call
  - build_commit_message: direct schedule presentation construction
"""

import datetime

from engine.agent import AgentState, agent_brain, decide_next_stage

# ---------------------------------------------------------------------------
# decide_next_stage
# ---------------------------------------------------------------------------


class TestDecideNextStage:
    def test_assess_readiness_stays_until_complete(self):
        s = AgentState(stage="assess_readiness", readiness_complete=False)
        assert decide_next_stage(s) == "assess_readiness"

    def test_assess_readiness_advances_when_complete(self):
        s = AgentState(stage="assess_readiness", readiness_complete=True)
        assert decide_next_stage(s) == "collect_context"

    def test_collect_context_stays_until_intake_complete(self):
        s = AgentState(stage="collect_context", intake_complete=False)
        assert decide_next_stage(s) == "collect_context"

    def test_collect_context_advances_to_fetch_weather(self):
        s = AgentState(stage="collect_context", intake_complete=True)
        assert decide_next_stage(s) == "fetch_weather"

    def test_fetch_weather_always_advances_to_plan(self):
        s = AgentState(stage="fetch_weather")
        assert decide_next_stage(s) == "plan"

    def test_plan_stays_until_schedule_exists(self):
        s = AgentState(stage="plan", schedule=[])
        assert decide_next_stage(s) == "plan"

    def test_plan_advances_when_schedule_populated(self):
        s = AgentState(stage="plan", schedule=[{"step_id": 1, "step_label": "autolyse"}])
        assert decide_next_stage(s) == "commit"

    def test_commit_advances_to_guide_when_committed(self):
        s = AgentState(stage="commit", committed=True, schedule=[{"step_id": "enjoy"}])
        assert decide_next_stage(s) == "guide"

    def test_commit_stays_while_waiting_for_user(self):
        s = AgentState(stage="commit", committed=False, schedule=[{"step_id": "enjoy"}])
        assert decide_next_stage(s) == "commit"

    def test_commit_returns_to_plan_when_deadline_updated(self):
        s = AgentState(stage="commit", committed=False, schedule=[])
        assert decide_next_stage(s) == "plan"

    def test_guide_stays_while_steps_remain(self):
        s = AgentState(
            stage="guide",
            schedule=[{"step_id": 1}, {"step_id": 2}],
            completed_steps=[1],
        )
        assert decide_next_stage(s) == "guide"

    def test_guide_advances_to_complete_when_all_steps_done(self):
        s = AgentState(
            stage="guide",
            schedule=[{"step_id": 1}, {"step_id": 2}],
            completed_steps=[1, 2],
        )
        assert decide_next_stage(s) == "complete"

    def test_guide_stays_when_schedule_empty(self):
        # No schedule means we can't declare completion
        s = AgentState(stage="guide", schedule=[], completed_steps=[])
        assert decide_next_stage(s) == "guide"

    def test_unknown_stage_returns_itself(self):
        s = AgentState(stage="complete")
        assert decide_next_stage(s) == "complete"


# ---------------------------------------------------------------------------
# AgentState serialization
# ---------------------------------------------------------------------------


class TestAgentStateSerialization:
    def test_round_trip_defaults(self):
        s = AgentState()
        assert AgentState.from_json(s.to_json()) == s

    def test_round_trip_with_data(self):
        s = AgentState(
            stage="collect_context",
            messages=[{"role": "user", "content": "hello"}],
            session_key="abc-123",
            bot_name="Doughy",
            readiness_complete=True,
            user_experience_level="beginner",
            stage_boundaries={"collect_context": 2},
        )
        assert AgentState.from_json(s.to_json()) == s

    def test_round_trip_with_intake(self):
        s = AgentState(
            stage="fetch_weather",
            intake={
                "starter_health": "very active",
                "deadline": "2026-04-26T09:00:00",
                "last_fed_at": "2026-04-25T08:00:00",
                "feeding_ratio": "1:5:5",
                "earliest_start_time": "2026-04-25T20:00:00",
            },
            intake_complete=True,
            bake_session_id=42,
        )
        restored = AgentState.from_json(s.to_json())
        assert restored.intake == s.intake
        assert restored.bake_session_id == 42
        assert restored.intake_complete is True

    def test_none_fields_survive_round_trip(self):
        s = AgentState(weather_scrape_run_id=None, weather_weighted_temps=None)
        restored = AgentState.from_json(s.to_json())
        assert restored.weather_scrape_run_id is None
        assert restored.weather_weighted_temps is None

    def test_nested_dicts_survive_round_trip(self):
        s = AgentState(weather_weighted_temps={"hour_0": 18.5, "hour_2": 19.0, "hour_5": None})
        restored = AgentState.from_json(s.to_json())
        assert restored.weather_weighted_temps == {"hour_0": 18.5, "hour_2": 19.0, "hour_5": None}


# ---------------------------------------------------------------------------
# agent_brain tool dispatch
# ---------------------------------------------------------------------------


class TestAgentBrain:
    def _readiness_output(self, experience_level="beginner", has_essentials=True, missing=""):
        return {
            "text": "Great, let's get started!",
            "tool": {
                "name": "SubmitReadiness",
                "args": {
                    "experience_level": experience_level,
                    "has_essentials": has_essentials,
                    "missing_items": missing,
                },
            },
        }

    def test_submit_readiness_sets_complete(self):
        s = AgentState(stage="assess_readiness")
        s = agent_brain(s, self._readiness_output("some_experience"))
        assert s.readiness_complete is True
        assert s.user_experience_level == "some_experience"

    def test_submit_readiness_ignores_wrong_stage(self):
        s = AgentState(stage="collect_context", readiness_complete=False)
        s = agent_brain(s, self._readiness_output())
        assert s.readiness_complete is False  # wrong stage — should not fire

    def test_no_tool_call_leaves_state_unchanged(self):
        s = AgentState(stage="assess_readiness", readiness_complete=False)
        original_stage = s.stage
        s = agent_brain(s, {"text": "Tell me about your starter.", "tool": None})
        assert s.readiness_complete is False
        assert s.stage == original_stage

    def test_unknown_tool_name_leaves_state_unchanged(self):
        s = AgentState(stage="assess_readiness")
        s = agent_brain(s, {"text": "", "tool": {"name": "UnknownTool", "args": {}}})
        assert s.readiness_complete is False

    def test_report_conflict_extends_conflicts_and_clears_schedule(self):
        s = AgentState(
            stage="commit",
            schedule=[{"step_id": "enjoy"}],
            bake_session_id=None,  # no DB write
            conflicts=[],
        )
        llm_output = {
            "text": "",
            "tool": {
                "name": "ReportConflict",
                "args": {
                    "windows": [
                        {
                            "from_iso": "2026-05-27T19:00:00",
                            "to_iso": "2026-05-27T21:00:00",
                            "reason": "dinner",
                        }
                    ]
                },
            },
        }
        s = agent_brain(s, llm_output)
        assert len(s.conflicts) == 1
        assert s.conflicts[0]["from_iso"] == "2026-05-27T19:00:00"
        assert s.conflicts[0]["reason"] == "dinner"
        assert s.schedule == []  # cleared to trigger re-plan
        assert s.plan_enjoy_iso is None
        assert s.plan_deadline_delta_min is None
        assert s.plan_adjustments is None

    def test_report_conflict_accumulates_across_calls(self):
        s = AgentState(
            stage="commit",
            schedule=[],
            bake_session_id=None,
            conflicts=[
                {
                    "from_iso": "2026-05-27T08:00:00",
                    "to_iso": "2026-05-27T09:00:00",
                    "reason": "gym",
                }
            ],
        )
        llm_output = {
            "text": "",
            "tool": {
                "name": "ReportConflict",
                "args": {
                    "windows": [
                        {
                            "from_iso": "2026-05-27T19:00:00",
                            "to_iso": "2026-05-27T21:00:00",
                            "reason": "dinner",
                        }
                    ]
                },
            },
        }
        s = agent_brain(s, llm_output)
        assert len(s.conflicts) == 2
        assert s.conflicts[0]["reason"] == "gym"
        assert s.conflicts[1]["reason"] == "dinner"


# ---------------------------------------------------------------------------
# build_commit_message
# ---------------------------------------------------------------------------


class TestBuildCommitMessage:
    def _make_state(self, delta_min: int = 0, adjustments: dict | None = None) -> AgentState:
        start = datetime.datetime(2026, 5, 27, 8, 0)
        deadline = datetime.datetime(2026, 5, 28, 18, 0)
        from engine.agent import AgentState
        from engine.stages.plan import build_optimized_schedule

        s = AgentState()
        s.intake = {
            "earliest_start_time": start.isoformat(),
            "deadline": deadline.isoformat(),
            "starter_health": "active",
            "last_fed_at": start.isoformat(),
            "feeding_ratio": "1:1:1",
            "deadline_flexibility": "firm",
        }
        s.weather_weighted_temps = {"hour_0": 24.0, "hour_2": 24.0}
        schedule, _, variant, skipped = build_optimized_schedule(s)
        s.schedule = schedule
        s.plan_skipped_steps = skipped
        s.plan_enjoy_iso = next(
            (st["start_iso"] for st in schedule if st["step_id"] == "enjoy"), None
        )
        s.plan_deadline_delta_min = delta_min
        s.plan_adjustments = adjustments or {
            "warm_water_bulk": False,
            "room_temp_proof": False,
            "bench_rest_skipped": False,
        }
        return s

    def test_message_starts_with_code_block(self):
        from engine.stages.commit import build_commit_message

        s = self._make_state()
        msg = build_commit_message(s)
        assert msg.startswith("```"), "Message must start with a code block"
        assert "```" in msg, "Code block must be closed"

    def test_message_contains_step_labels(self):
        from engine.stages.commit import build_commit_message

        s = self._make_state()
        msg = build_commit_message(s)
        assert "The big mix" in msg
        assert "Bulk fermentation" in msg
        assert "Enjoy!" in msg

    def test_case_a_ends_with_commit_question(self):
        from engine.stages.commit import build_commit_message

        s = self._make_state(delta_min=10)  # within ±30 min, no high-impact
        msg = build_commit_message(s)
        assert "Ready to lock this in?" in msg
        assert "⚠️" not in msg.split("```")[-1]  # no warning after the code block

    def test_case_b_shows_monitoring_warning(self):
        from engine.stages.commit import build_commit_message

        s = self._make_state(
            delta_min=5,
            adjustments={
                "warm_water_bulk": True,
                "room_temp_proof": False,
                "bench_rest_skipped": False,
            },
        )
        msg = build_commit_message(s)
        assert "close monitoring" in msg
        assert "warm water bulk" in msg

    def test_case_c_shows_deadline_miss(self):
        from engine.stages.commit import build_commit_message

        s = self._make_state(delta_min=90)  # 90 min late → Case C
        msg = build_commit_message(s)
        assert "Best I can do" in msg
        assert "90 min late" in msg
        assert "Want to try a different finish time" in msg
