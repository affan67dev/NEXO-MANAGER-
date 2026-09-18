import unittest
from unittest.mock import patch
from android_capabilities import capabilities, capture_screen, analyze_screen

class AndroidCapabilityTests(unittest.TestCase):
    @patch("android_capabilities._exists", return_value=False)
    def test_screen_unavailable_is_explicit(self,_):
        result=capture_screen()
        self.assertFalse(result["ok"]); self.assertFalse(result["available"])
        self.assertEqual(result["error"],"screen_capture_unavailable")

    @patch("android_capabilities._exists", side_effect=lambda name: name=="termux-screenshot")
    @patch("android_capabilities._run", return_value={"ok":True,"stdout":"","stderr":"","code":0})
    def test_capture_requires_real_file(self,_run,_exists):
        result=capture_screen()
        self.assertFalse(result["ok"]); self.assertTrue(result["available"])
        self.assertEqual(result["error"],"screen_capture_failed")

    def test_capability_shape(self):
        result=capabilities()
        for key in ("screen_capture","tts","stt","microphone_record","ocr"):
            self.assertIn(key,result)

if __name__=="__main__":
    unittest.main()
