import tempfile
import threading
import time
import unittest
from pathlib import Path
from core.task_orchestrator import TaskOrchestrator, TaskSpec, TaskStore

class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        import core.task_orchestrator as mod
        self.old_db=mod.DB; mod.DB=Path(self.tmp.name)/"memory.db"
        self.store=TaskStore(); self.orch=TaskOrchestrator(self.store)
    def tearDown(self):
        import core.task_orchestrator as mod
        mod.DB=self.old_db; self.tmp.cleanup()
    def test_dependency_order_and_state(self):
        seen=[]
        tasks=[TaskSpec("open youtube",task_id="a",intent="open_app"),TaskSpec("search song",task_id="b",dependencies=["a"],intent="search"),TaskSpec("play song",task_id="c",dependencies=["b"],intent="play")]
        def run(task): seen.append(task.task_id); return {"ok":True,"verified":True,"response":task.objective}
        results=self.orch.run("r1",tasks,run); self.assertEqual(seen,["a","b","c"]); self.assertTrue(all(x["state"]=="completed" for x in results))
        rows=self.store.get_request("r1"); self.assertEqual([r["state"] for r in rows],["completed"]*3); self.assertEqual(rows[0]["intent"],"open_app")
    def test_failure_isolated_and_dependents_cancelled(self):
        tasks=[TaskSpec("independent success",task_id="a"),TaskSpec("independent failure",task_id="b"),TaskSpec("depends on failure",task_id="c",dependencies=["b"]),TaskSpec("independent success 2",task_id="d")]
        def run(task):
            if task.task_id=="b": return {"ok":False,"verified":False,"permanent":True,"error":"boom"}
            return {"ok":True,"verified":True}
        states={x["task_id"]:x["state"] for x in self.orch.run("r2",tasks,run,max_parallel=2)}; self.assertEqual(states,{"a":"completed","b":"failed","c":"cancelled","d":"completed"})
    def test_five_plus_tasks_are_preserved(self):
        tasks=[TaskSpec(f"task {i}",task_id=str(i)) for i in range(7)]; results=self.orch.run("r5",tasks,lambda task:{"ok":True,"verified":True},max_parallel=3)
        self.assertEqual(len(results),7); self.assertEqual({x["state"] for x in results},{"completed"}); self.assertEqual(len(self.store.get_request("r5")),7)
    def test_retry_then_success(self):
        attempts={"x":0}; x=TaskSpec("temporary",task_id="x",max_retries=2)
        def run(task):
            attempts["x"]+=1
            return {"ok":True,"verified":True} if attempts["x"]>=2 else {"ok":False,"verified":False,"error":"temporary","retryable":True}
        result=self.orch.run("r3",[x],run)[0]; self.assertEqual(attempts["x"],2); self.assertEqual(result["state"],"completed")
    def test_timeout_does_not_wait_for_executor(self):
        started=threading.Event(); x=TaskSpec("slow",task_id="x",timeout_seconds=1,max_retries=3)
        def run(task): started.set(); time.sleep(2); return {"ok":True,"verified":True}
        start=time.monotonic(); result=self.orch.run("rt",[x],run)[0]; elapsed=time.monotonic()-start
        self.assertTrue(started.is_set()); self.assertLess(elapsed,1.8); self.assertEqual(result["state"],"failed"); self.assertEqual(result["attempts"],1)
    def test_resource_conflict_serializes_shared_device(self):
        active=0; maximum=0; lock=threading.Lock()
        started={"audio":threading.Event(),"window":threading.Event()}
        tasks=[TaskSpec("one",task_id="a",resources=["device:audio"]),TaskSpec("two",task_id="b",resources=["device:audio"]),TaskSpec("three",task_id="c",resources=["device:window"])]
        def run(task):
            nonlocal active,maximum
            kind="window" if task.task_id=="c" else "audio"
            other="audio" if kind=="window" else "window"
            started[kind].set()
            self.assertTrue(started[other].wait(timeout=2), f"{kind} task did not overlap with independent resource task")
            with lock: active+=1; maximum=max(maximum,active)
            time.sleep(.05)
            with lock: active-=1
            return {"ok":True,"verified":True}
        results=self.orch.run("rr",tasks,run,max_parallel=3); self.assertEqual({x["state"] for x in results},{"completed"}); self.assertEqual(maximum,2)
    def test_confirmation_is_persisted_and_does_not_crash(self):
        tasks=[TaskSpec("send message",task_id="a"),TaskSpec("follow up",task_id="b",dependencies=["a"])]
        states={x["task_id"]:x["state"] for x in self.orch.run("rc",tasks,lambda task:{"ok":False,"verified":False,"requires_confirmation":True})}; self.assertEqual(states,{"a":"waiting_confirmation","b":"waiting_confirmation"})

    def test_request_status_and_cancel(self):
        self.store.put("rcancel", TaskSpec("pending", task_id="p"), "queued")
        self.store.put("rcancel", TaskSpec("done", task_id="d"), "completed")
        status = self.store.request_status("rcancel")
        self.assertEqual(status["state"], "running")
        result = self.store.cancel_request("rcancel")
        self.assertEqual(result["cancelled"], 1)
        self.assertEqual(self.store.get_request("rcancel")[0]["state"], "cancelled")

    def test_stale_running_task_is_recovered(self):
        task=TaskSpec("recover me",task_id="recover"); self.store.put("recovery",task,"running")
        import datetime,core.task_orchestrator as mod
        stamp=datetime.datetime.fromtimestamp(time.time()-600,datetime.timezone.utc).isoformat()
        conn=mod.sqlite3.connect(mod.DB)
        try:
            conn.execute("UPDATE nexo_tasks SET updated_at=?, attempts=1 WHERE task_id=?",(stamp,"recover")); conn.commit()
        finally: conn.close()
        recovered=self.store.recover_stale(max_age_seconds=300); self.assertEqual(recovered[0]["to"],"retrying"); self.assertEqual(self.store.get_request("recovery")[0]["state"],"retrying")
    def test_cycle_and_missing_dependency_are_rejected(self):
        with self.assertRaises(ValueError): self.orch.enqueue("r4",[TaskSpec("a",task_id="a",dependencies=["b"]),TaskSpec("b",task_id="b",dependencies=["a"])])
        with self.assertRaises(ValueError): self.orch.enqueue("r4b",[TaskSpec("a",task_id="a",dependencies=["missing"])])

if __name__=="__main__": unittest.main()
