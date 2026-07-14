import unittest

import generation


class GenerationTests(unittest.TestCase):
    def test_codex_worker_is_discoverable(self):
        workers = generation.available_workers()["workers"]
        codex = next(worker for worker in workers if worker["name"] == "Codex")
        self.assertTrue(codex["available"])
        self.assertEqual(codex["mode"], "workspace-write")

    def test_generation_requires_explicit_authorization(self):
        result = generation.start_codex_job("Jarvis", "change code", confirmed=False)
        self.assertFalse(result["ok"])
        self.assertTrue(result["requires_user"])


if __name__ == "__main__":
    unittest.main()
