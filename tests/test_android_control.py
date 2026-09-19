import unittest
from unittest.mock import patch
import android_capabilities as android


class AndroidControlTests(unittest.TestCase):
    def test_allowlisted_packages_exist(self):
        self.assertEqual(android.APP_PACKAGES["youtube"], "com.google.android.youtube")
        self.assertEqual(android.APP_PACKAGES["telegram"], "org.telegram.messenger")
        self.assertEqual(android.APP_PACKAGES["settings"], "com.android.settings")

    @patch("android_capabilities.get_foreground_package", return_value={"ok": True, "verified": True, "package": "com.google.android.youtube"})
    @patch("android_capabilities._run", return_value={"ok": True, "stdout": "Events injected", "stderr": "", "code": 0})
    @patch("android_capabilities._exists", return_value=True)
    def test_launch_is_only_success_when_foreground_matches(self, exists, run, foreground):
        result = android.launch_app("youtube")
        self.assertTrue(result["ok"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["package"], "com.google.android.youtube")

    @patch("android_capabilities.get_foreground_package", return_value={"ok": True, "verified": True, "package": "com.android.chrome"})
    @patch("android_capabilities._run", return_value={"ok": True, "stdout": "Events injected", "stderr": "", "code": 0})
    @patch("android_capabilities._exists", return_value=True)
    def test_launch_does_not_claim_success_for_wrong_foreground(self, exists, run, foreground):
        result = android.launch_app("youtube")
        self.assertFalse(result["ok"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["error"], "foreground_verification_failed")


if __name__ == "__main__":
    unittest.main()
