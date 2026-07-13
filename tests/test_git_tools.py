import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import git_tools


class GitToolTests(unittest.TestCase):
    def test_commit_and_push_requires_explicit_confirmation(self):
        result = git_tools.commit_and_push("Jarvis", "Update Jarvis", False)
        self.assertFalse(result["ok"])
        self.assertTrue(result["confirmation_required"])

    def test_repository_cannot_escape_github_folder(self):
        with self.assertRaises(ValueError):
            git_tools._resolve_repository("../../.ssh")

    def test_status_provides_context_for_commit_message(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / "Jarvis"
            (repo / ".git").mkdir(parents=True)
            responses = [" M assist.py", "main", " assist.py | 4 ++++\n 1 file changed"]
            with patch.object(git_tools, "REPOSITORY_ROOT", root), patch(
                "git_tools._git", side_effect=responses
            ):
                result = git_tools.status("Jarvis")
            self.assertTrue(result["has_changes"])
            self.assertEqual(result["branch"], "main")
            self.assertIn("assist.py", result["diff_summary"])

    def test_existing_commit_can_be_pushed_without_recommitting(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / "Jarvis"
            (repo / ".git").mkdir(parents=True)
            responses = ["", "abc123", "main", "git@github.com:user/Jarvis.git", "", "", "0"]
            with patch.object(git_tools, "REPOSITORY_ROOT", root), patch(
                "git_tools._git", side_effect=responses
            ) as git:
                result = git_tools.commit_and_push("Jarvis", "Update Jarvis", True)
            self.assertTrue(result["pushed"])
            self.assertFalse(result["committed"])
            calls = [call.args for call in git.call_args_list]
            self.assertIn((repo.resolve(), "push", "--set-upstream", "origin", "main"), calls)


if __name__ == "__main__":
    unittest.main()
