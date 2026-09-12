import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nexo_bootstrap", ROOT / "scripts" / "bootstrap_nexo.py")
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


class BootstrapTests(unittest.TestCase):
    def test_wrappers_exist(self):
        self.assertTrue((ROOT / "bootstrap.sh").is_file())
        self.assertTrue((ROOT / "bootstrap.bat").is_file())

    def test_hardware_shape(self):
        info = MOD.hardware()
        self.assertIn("machine", info)
        self.assertGreaterEqual(info["cpu_count"], 1)
        self.assertIsInstance(info["gpu"], list)
        self.assertIn("termux", info)

    def test_secret_boundary(self):
        source = (ROOT / "scripts" / "bootstrap_nexo.py").read_text(encoding="utf-8")
        self.assertNotIn("TELEGRAM_BOT_TOKEN", source)
        self.assertEqual(MOD.ENV_FILE, Path.home() / ".nexo.env")

    def test_pm2_boundary(self):
        self.assertEqual(MOD.PM2_NAMES, ("nexo-backend", "nexo-llama"))
        source = (ROOT / "scripts" / "bootstrap_nexo.py").read_text(encoding="utf-8")
        self.assertNotIn("omnix-backend", source.lower())

    def test_venv_is_outside_repository(self):
        self.assertTrue(str(MOD.VENV).startswith(str(Path.home() / ".nexo")))
        self.assertNotIn(str(ROOT), str(MOD.VENV))

    def test_termux_does_not_create_second_runtime(self):
        with patch.dict(os.environ, {"PREFIX": str(Path.home())}, clear=False):
            python_path, owns_venv = MOD.setup_python()
        self.assertEqual(python_path, Path(MOD.sys.executable).resolve())
        self.assertFalse(owns_venv)

    def test_db_matches_existing_memory_engine(self):
        source = (ROOT / "core" / "memory_engine.py").read_text(encoding="utf-8")
        self.assertIn('DB = BASE / "data" / "memory.db"', source)
        self.assertEqual(MOD.DB, ROOT / "data" / "memory.db")

    def test_dependency_manifest_is_shared_repo_manifest(self):
        self.assertEqual(MOD.dependency_manifest(), ROOT / "requirements-nexo.txt")

    def test_no_destructive_git_operations(self):
        source = (ROOT / "scripts" / "bootstrap_nexo.py").read_text(encoding="utf-8")
        for forbidden in ("git reset --hard", "git clean", "git push --force", "git checkout -f"):
            self.assertNotIn(forbidden, source)

    def test_model_detection_is_optional(self):
        value = MOD.find_model()
        self.assertTrue(value is None or value.lower().endswith(".gguf"))


if __name__ == "__main__":
    unittest.main()
