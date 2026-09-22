import unittest
from unittest.mock import patch
import android_capabilities as android

class AndroidControlTests(unittest.TestCase):
    def test_allowlisted_packages_exist(self):
        self.assertEqual(android.APP_PACKAGES["youtube"],"com.google.android.youtube")
        self.assertEqual(android.APP_PACKAGES["telegram"],"org.telegram.messenger")

    @patch("android_capabilities.get_foreground_package",return_value={"ok":True,"verified":True,"package":"com.google.android.youtube"})
    @patch("android_capabilities._run",return_value={"ok":True,"stdout":"Events injected","stderr":"","code":0})
    @patch("android_capabilities._exists",return_value=True)
    def test_launch_requires_foreground_verification(self, *_):
        result=android.launch_app("youtube")
        self.assertTrue(result["verified"])

    @patch("android_capabilities.get_foreground_package",return_value={"ok":True,"verified":True,"package":"com.android.chrome"})
    @patch("android_capabilities._run",return_value={"ok":True,"stdout":"Events injected","stderr":"","code":0})
    @patch("android_capabilities._exists",return_value=True)
    def test_wrong_foreground_is_not_success(self, *_):
        result=android.launch_app("youtube")
        self.assertFalse(result["verified"])
        self.assertEqual(result["error"],"foreground_verification_failed")

    @patch("android_capabilities._exists",return_value=False)
    def test_ui_tree_fails_closed_when_unavailable(self,_):
        result=android.inspect_ui_tree()
        self.assertFalse(result["verified"])
        self.assertEqual(result["error"],"uiautomator_unavailable")

if __name__=="__main__":
    unittest.main()
