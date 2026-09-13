"""Persistent request/task orchestration for NEXO."""
from __future__ import annotations
import json, sqlite3, threading, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

DB=Path(__file__).resolve().parent.parent/"data"/"memory.db"
TERMINAL={"completed","failed","cancelled"}
def _now(): return datetime.now(timezone.utc).isoformat()

@dataclass
class TaskSpec:
    objective:str
    task_id:str=field(default_factory=lambda:f"task-{uuid.uuid4().hex[:10]}")
    priority:str="normal"
    dependencies:list[str]=field(default_factory=list)
    required_tools:list[str]=field(default_factory=list)
    expected_result:str=""
    kind:str="sequential"
    timeout_seconds:int=90
    max_retries:int=2
    parameters:dict[str,Any]=field(default_factory=dict)

class TaskStore:
    _lock=threading.RLock()
    def _conn(self):
        c=sqlite3.connect(DB,timeout=10); c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=10000"); return c
    def init(self):
        with self._lock,self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS nexo_tasks(task_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,objective TEXT NOT NULL,priority TEXT NOT NULL,dependencies TEXT NOT NULL,required_tools TEXT NOT NULL,expected_result TEXT NOT NULL,kind TEXT NOT NULL,parameters TEXT NOT NULL,state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,max_retries INTEGER NOT NULL DEFAULT 2,timeout_seconds INTEGER NOT NULL DEFAULT 90,result TEXT,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_nexo_tasks_request ON nexo_tasks(request_id)"); c.execute("CREATE INDEX IF NOT EXISTS idx_nexo_tasks_state ON nexo_tasks(state)")
    def put(self,request_id,spec,state="queued"):
        self.init()
        with self._lock,self._conn() as c:
            n=_now(); c.execute("INSERT OR REPLACE INTO nexo_tasks(task_id,request_id,objective,priority,dependencies,required_tools,expected_result,kind,parameters,state,attempts,max_retries,timeout_seconds,result,error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(spec.task_id,request_id,spec.objective,spec.priority,json.dumps(spec.dependencies),json.dumps(spec.required_tools),spec.expected_result,spec.kind,json.dumps(spec.parameters),state,0,max(0,spec.max_retries),max(1,spec.timeout_seconds),None,None,n,n))
    def update(self,task_id,state,*,result=None,error=None,attempts=None):
        self.init()
        with self._lock,self._conn() as c:
            f=["state=?","updated_at=?","result=?","error=?"]; v=[state,_now(),json.dumps(result,ensure_ascii=False) if result is not None else None,error]
            if attempts is not None:f.append("attempts=?");v.append(attempts)
            v.append(task_id);c.execute(f"UPDATE nexo_tasks SET {','.join(f)} WHERE task_id=?",v)
    def get_request(self,request_id):
        self.init()
        with self._lock,self._conn() as c:
            rows=c.execute("SELECT * FROM nexo_tasks WHERE request_id=? ORDER BY created_at",(request_id,)).fetchall();cols=[x[1] for x in c.execute("PRAGMA table_info(nexo_tasks)").fetchall()]
        return [dict(zip(cols,r)) for r in rows]

class TaskOrchestrator:
    def __init__(self,store=None):self.store=store or TaskStore();self.store.init()
    @staticmethod
    def validate(tasks):
        items=list(tasks);ids={t.task_id for t in items}
        if len(ids)!=len(items):raise ValueError("duplicate_task_id")
        for t in items:
            missing=set(t.dependencies)-ids
            if missing:raise ValueError(f"missing_dependencies:{','.join(sorted(missing))}")
        graph={t.task_id:set(t.dependencies) for t in items};visiting=set();visited=set()
        def dfs(n):
            if n in visiting:raise ValueError("task_dependency_cycle")
            if n in visited:return
            visiting.add(n)
            for d in graph[n]:dfs(d)
            visiting.remove(n);visited.add(n)
        for n in graph:dfs(n)
        return items
    def enqueue(self,request_id,tasks):
        items=self.validate(tasks)
        for t in items:self.store.put(request_id,t,"planning")
        for t in items:self.store.update(t.task_id,"queued")
        return items
    def run(self,request_id,tasks,executor,max_parallel=3):
        items=self.enqueue(request_id,tasks);pending={t.task_id:t for t in items};done={};running={};workers=max(1,min(int(max_parallel),4))
        def ready(t):return all(d in done and done[d].get("state")=="completed" for d in t.dependencies)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while pending or running:
                for t in list(pending.values()):
                    if any(d in done and done[d].get("state") in {"failed","cancelled"} for d in t.dependencies):
                        self.store.update(t.task_id,"cancelled",error="dependency_failed");done[t.task_id]={"task_id":t.task_id,"state":"cancelled","error":"dependency_failed"};pending.pop(t.task_id,None)
                for t in pending.values():
                    if not ready(t):self.store.update(t.task_id,"waiting")
                for t in list(pending.values()):
                    if ready(t):self.store.update(t.task_id,"running",attempts=0);running[pool.submit(self._execute_with_retry,t,executor)]=t;pending.pop(t.task_id,None)
                if not running:
                    if pending:raise RuntimeError("task_orchestration_stalled")
                    break
                for future in as_completed(list(running)):
                    t=running.pop(future)
                    try:r=future.result()
                    except Exception as exc:r={"ok":False,"verified":False,"error":f"orchestrator_error:{type(exc).__name__}","attempts":1}
                    state="completed" if r.get("ok") and r.get("verified") else "failed";self.store.update(t.task_id,state,result=r,error=None if state=="completed" else str(r.get("error") or "unverified_result"),attempts=int(r.get("attempts",1)));done[t.task_id]={"task_id":t.task_id,"state":state,**r};break
        return [done[t.task_id] for t in items]
    def _execute_with_retry(self,t,executor):
        attempts=0;last={"ok":False,"verified":False,"error":"not_executed"}
        while attempts<=max(0,t.max_retries):
            attempts+=1;self.store.update(t.task_id,"retrying" if attempts>1 else "running",attempts=attempts)
            try:
                with ThreadPoolExecutor(max_workers=1) as one:r=one.submit(executor,t).result(timeout=max(1,t.timeout_seconds))
                r=r or {"ok":False,"verified":False,"error":"empty_executor_result"}
            except TimeoutError:r={"ok":False,"verified":False,"error":"task_timeout","permanent":False}
            except Exception as exc:r={"ok":False,"verified":False,"error":f"executor_error:{type(exc).__name__}"}
            r=dict(r);r["attempts"]=attempts
            if r.get("ok") and r.get("verified"):return r
            last=r
            if r.get("permanent") or r.get("requires_confirmation"):break
        return last

def specs_from_plan(plan):
    tasks=[]
    for x in plan:
        if not isinstance(x,dict) or not str(x.get("objective","")).strip():continue
        try:timeout=int(x.get("timeout_seconds") or 90);retries=int(x.get("max_retries") if x.get("max_retries") is not None else 2)
        except (TypeError,ValueError):timeout,retries=90,2
        tasks.append(TaskSpec(objective=str(x["objective"]).strip(),task_id=str(x.get("task_id") or f"task-{uuid.uuid4().hex[:10]}"),priority=str(x.get("priority") or "normal"),dependencies=[str(d) for d in x.get("dependencies",[])],required_tools=[str(d) for d in x.get("required_tools",[])],expected_result=str(x.get("expected_result") or ""),kind=str(x.get("kind") or "sequential"),timeout_seconds=timeout,max_retries=retries,parameters=x.get("parameters") if isinstance(x.get("parameters"),dict) else {}))
    return tasks
