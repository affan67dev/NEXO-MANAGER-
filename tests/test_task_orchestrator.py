import tempfile
import unittest
from pathlib import Path
from core.task_orchestrator import TaskOrchestrator, TaskSpec, TaskStore


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import core.task_orchestrator as mod
        self.old_db = mod.DB
        mod.DB = Path(self.tmp.name) / "memory.db"
        self.store = TaskStore()
        self.orch = TaskOrchestrator(self.store)

    def tearDown(self):
        import core.task_orchestrator as mod
        mod.DB = self.old_db
        self.tmp.cleanup()

    def test_dependency_order_and_state(self):
        seen = []
        a = TaskSpec("open youtube", task_id="a")
        b = TaskSpec("search song", task_id="b", dependencies=["a"])
        c = TaskSpec("play song", task_id="c", dependencies=["b"])
        def run(task):
            seen.append(task.task_id)
            return {"ok": True, "verified": True, "response": task.objective}
        results = self.orch.run("r1", [a, b, c], run)
        self.assertEqual(seen, ["a", "b", "c"])
        self.assertTrue(all(x["state"] == "completed" for x in results))
        rows = self.store.get_request("r1")
        self.assertEqual([r["state"] for r in rows], ["completed"] * 3)

    def test_failure_isolated_and_dependents_cancelled(self):
        a = TaskSpec("independent success", task_id="a")
        b = TaskSpec("independent failure", task_id="b")
        c = TaskSpec("depends on failure", task_id="c", dependencies=["b"])
        d = TaskSpec("independent success 2", task_id="d")
        def run(task):
            if task.task_id == "b": return {"ok": False, "verified": False, "permanent": True, "error": "boom"}
            return {"ok": True, "verified": True}
        results = self.orch.run("r2", [a, b, c, d], run, max_parallel=2)
        states = {x["task_id"]: x["state"] for x in results}
        self.assertEqual(states["b"], "failed")
        self.assertEqual(states["c"], "cancelled")
        self.assertEqual(states["a"], "completed")
        self.assertEqual(states["d"], "completed")

    def test_retry_then_success(self):
        attempts = {"x": 0}
        x = TaskSpec("temporary", task_id="x", max_retries=2)
        def run(task):
            attempts["x"] += 1
            if attempts["x"] < 2: return {"ok": False, "verified": False, "error": "temporary"}
            return {"ok": True, "verified": True}
        result = self.orch.run("r3", [x], run)[0]
        self.assertEqual(attempts["x"], 2)
        self.assertEqual(result["state"], "completed")

    def test_cycle_is_rejected(self):
        with self.assertRaises(ValueError):
            self.orch.enqueue("r4", [TaskSpec("a", task_id="a", dependencies=["b"]), TaskSpec("b", task_id="b", dependencies=["a"])])


if __name__ == "__main__":
    unittest.main()
