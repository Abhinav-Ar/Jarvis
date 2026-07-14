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


if __name__ == "__main__":
    unittest.main()
