import importlib.util
from pathlib import Path
import unittest

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

    def test_secret_boundary(self):
        source = (ROOT / "scripts" / "bootstrap_nexo.py").read_text(encoding="utf-8")
        self.assertNotIn("TELEGRAM_BOT_TOKEN", source)
        self.assertEqual(MOD.ENV_FILE, Path.home() / ".nexo.env")

    def test_pm2_boundary(self):
        self.assertEqual(MOD.PM2_NAMES, ("nexo-backend", "nexo-llama"))

    def test_model_detection_is_optional(self):
        value = MOD.find_model()
        self.assertTrue(value is None or value.endswith(".gguf"))

if __name__ == "__main__":
    unittest.main()
