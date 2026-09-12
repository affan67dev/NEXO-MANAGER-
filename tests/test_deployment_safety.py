import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
AUTO = ROOT / "scripts" / "auto_update.sh"
BOOTSTRAP = ROOT / "scripts" / "bootstrap_nexo_deploy.sh"


class DeploymentSafetyTests(unittest.TestCase):
    def test_scripts_exist_and_parse(self):
        for path in (AUTO, BOOTSTRAP):
            self.assertTrue(path.is_file(), path)
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("#!"), path)

    def test_forbidden_git_operations_are_absent(self):
        text = AUTO.read_text(encoding="utf-8")
        forbidden = ("git reset --hard", "git clean", "git checkout -f", "git checkout --force", "git push --force")
        for token in forbidden:
            self.assertNotIn(token, text)

    def test_only_nexo_pm2_targets_are_present(self):
        text = AUTO.read_text(encoding="utf-8")
        self.assertIn("nexo-backend", text)
        self.assertIn("nexo-llama", text)
        self.assertNotIn("omnix-backend", text.lower())

    def test_release_and_ci_gates_exist(self):
        text = AUTO.read_text(encoding="utf-8")
        self.assertIn("git worktree add --detach", text)
        self.assertIn("NEXO CI", text)
        self.assertIn("git merge --ff-only", text)
        self.assertIn("git read-tree -u", text)
        self.assertIn("transaction", text)

    def test_bootstrap_uses_thirty_minute_schedule(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("*/30 * * * *", text)
        self.assertIn("start_llama_tablet.sh", text)
        self.assertIn("start_nexo_tablet.sh", text)


if __name__ == "__main__":
    unittest.main()
