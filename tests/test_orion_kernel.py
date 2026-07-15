import tempfile
import time
import unittest
from pathlib import Path

from orion_kernel import IntelligenceRouter, OrionKernel


class OrionKernelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.kernel = OrionKernel(Path(self.temporary.name) / "agent.db")

    def tearDown(self):
        self.kernel.stop_monitor()
        self.temporary.cleanup()

    def test_world_state_tracks_provenance_and_expiry(self):
        self.kernel.observe("app.frontmost", "Safari", "workspace", confidence=0.9, ttl=0.01)
        fact = self.kernel.world_snapshot("app.")["facts"][0]
        self.assertEqual(fact["source"], "workspace")
        self.assertEqual(fact["value"], "Safari")
        time.sleep(0.02)
        self.assertEqual(self.kernel.world_snapshot("app.")["facts"], [])

    def test_four_memory_layers_are_searchable(self):
        for layer in self.kernel.MEMORY_LAYERS:
            self.kernel.remember(layer, f"{layer}-theme", "blue workspace")
        matches = self.kernel.recall("blue")['matches']
        self.assertEqual({item["layer"] for item in matches}, self.kernel.MEMORY_LAYERS)

    def test_goal_supervisor_retains_referential_followup(self):
        first = self.kernel.before_request("Arrange Safari and Notes", "one", "session")
        second = self.kernel.before_request("continue with that", "two", "session")
        self.assertEqual(first["goal_id"], second["goal_id"])

    def test_completed_turn_still_resolves_followup_to_same_session_goal(self):
        first = self.kernel.before_request("Create a budget spreadsheet", "one", "session-continuity")
        self.kernel.after_response(
            "Create a budget spreadsheet", "The spreadsheet is ready.", "one",
            "session-continuity", first["goal_id"], first["route"],
        )
        second = self.kernel.before_request("add a chart to it", "two", "session-continuity")
        self.assertEqual(first["goal_id"], second["goal_id"])

    def test_restart_pauses_and_explicit_resume_reactivates_previous_goal(self):
        first = self.kernel.before_request("Create and verify my budget", "one", "old-session")
        recovered = self.kernel.recover_interrupted_goals()
        self.assertEqual(recovered["goals"][0]["id"], first["goal_id"])
        resumed = self.kernel.before_request("continue the previous task", "two", "new-session")
        self.assertEqual(resumed["goal_id"], first["goal_id"])

    def test_router_uses_local_and_cloud_lanes(self):
        self.assertEqual(IntelligenceRouter.route("open Safari")["lane"], "local_workflow")
        self.assertEqual(IntelligenceRouter.route("latest news today")["lane"], "cloud_research")
        self.assertEqual(IntelligenceRouter.route("what is on my screen")["lane"], "local_semantic_then_vision")

    def test_taught_workflow_is_retrieved_by_trigger(self):
        result = self.kernel.teach_workflow("Focus Mode", "start focus mode", ["open Notes", "mute notifications"])
        self.assertTrue(result["ok"])
        context = self.kernel.context_for("start focus mode")
        self.assertEqual(context["matched_workflows"][0]["name"], "Focus Mode")

    def test_replay_records_sanitized_outcome(self):
        turn = self.kernel.before_request("check battery", "request", "session")
        self.kernel.after_response("check battery", "Battery is fine.", "request", "session", turn["goal_id"], turn["route"])
        with self.kernel._connect() as database:
            row = database.execute("SELECT outcome,response FROM replay_turns").fetchone()
        self.assertEqual(row["outcome"], "completed")
        self.assertEqual(row["response"], "Battery is fine.")

    def test_adapter_registry_has_core_integrations(self):
        names = {item["name"] for item in self.kernel.adapters()["adapters"]}
        self.assertTrue({"macOS", "Accessibility", "Git", "Spotify", "OpenAI"}.issubset(names))

    def test_explicit_correction_becomes_relevant_local_context(self):
        first = self.kernel.before_request("Play my workout playlist", "one", "session")
        self.kernel.after_response(
            "Play my workout playlist", "Playing it.", "one", "session", first["goal_id"], first["route"]
        )
        correction = self.kernel.before_request("No, I wanted my owned workout playlist", "two", "session")
        self.kernel.after_response(
            "No, I wanted my owned workout playlist", "Playing your owned playlist.",
            "two", "session", correction["goal_id"], correction["route"],
        )
        context = self.kernel.context_for("Play my workout playlist again")
        self.assertTrue(any(item["source"] == "explicit_user_correction" for item in context["memory"]))

    def test_repeated_intent_sequence_produces_advisory_prediction(self):
        self.kernel.before_request("Commit my repository", "1", "pattern")
        self.kernel.before_request("Arrange my workspace", "2", "pattern")
        self.kernel.before_request("Commit another repository", "3", "pattern")
        self.kernel.before_request("Arrange the workspace again", "4", "pattern")
        predicted = self.kernel._likely_next_intents("git_delivery")
        self.assertEqual(predicted[0]["intent"], "workspace_layout")
        self.assertIn("do not execute", predicted[0]["policy"])

    def test_context_contains_objective_expansion_and_similar_success(self):
        turn = self.kernel.before_request("Install Blender", "one", "history")
        self.kernel.after_response("Install Blender", "Blender is installed.", "one", "history", turn["goal_id"], turn["route"])
        context = self.kernel.context_for("Install Blender again")
        self.assertEqual(context["anticipation"]["category"], "software_installation")
        self.assertTrue(context["similar_successes_and_corrections"])


if __name__ == "__main__":
    unittest.main()
