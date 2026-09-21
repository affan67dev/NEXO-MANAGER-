import unittest

from core.security_policy import load_policy_bundle


class SecurityPolicyTests(unittest.TestCase):
    def test_policy_bundle_loads_all_sections(self):
        policy = load_policy_bundle()
        self.assertIn("NO FAKE SUCCESS", policy)
        self.assertIn("NO SECURITY BYPASS", policy)
        self.assertIn("CLIENT ISOLATION", policy)
        self.assertIn("TRUTH HIERARCHY", policy)
        self.assertIn("FAILURE IS NOT SUCCESS", policy)

    def test_policy_contains_execution_boundary(self):
        policy = load_policy_bundle()
        self.assertIn("Unknown tool: BLOCK.", policy)
        self.assertIn("EXECUTION MUST BE BOUNDED", policy)
        self.assertIn("SECURITY SELF-PROTECTION", policy)


if __name__ == "__main__":
    unittest.main()
