from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.router import route


class FoundationTests(unittest.TestCase):
    def test_router_returns_known_agent(self):
        self.assertIn(route("hello NEXO"), {"manager", "planning"})
        self.assertEqual(route("security vulnerability review"), "security")
        self.assertEqual(route("fix backend error"), "coding")
        self.assertEqual(route("database backup"), "database")


if __name__ == "__main__":
    unittest.main()
