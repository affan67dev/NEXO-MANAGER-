import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import core.operational_history as history

class OperationalHistoryTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"memory.db"
            with patch.object(history,"DB",db):
                self.assertTrue(history.record_event("error",{"app":"test","diagnosis":"sample","result":"failed"}))
                rows=history.search_events("diagnosis",10)
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]["payload"]["app"],"test")

if __name__=="__main__":
    unittest.main()
