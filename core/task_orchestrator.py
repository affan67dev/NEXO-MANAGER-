"""Durable dependency-aware orchestration for NEXO."""
from __future__ import annotations
import json, sqlite3, threading, uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable

DB=Path(__file__).resolve().parent.parent/"data"/"memory.db"
TERMINAL={"completed","failed","cancelled"}


def _now(): return datetime.now(timezone.utc).isoformat()

@dataclass
class TaskSpec:
    objective:str
    task_id:str=field(default_factory=lambda:f"task-{uuid.uuid4().hex[:10]}")
    intent:str="unknown"
    priority:str="normal"
    dependencies:list[str]=field(default_factory=list)
    required_tools:list[str]=field(default_factory=list)
    expected_result:str=""
    kind:str="sequential"
    timeout_seconds:int=90
    max_retries:int=2
    parameters:dict[str,Any]=field(default_factory=dict)
    resources:list[str]=field(default_factory=list)

class TaskStore:
    _lock=threading.RLock()
    @contextmanager
    def _conn(self):
        DB.parent.mkdir(parents=True,exist_ok=True)
        c=sqlite3.connect(DB,timeout=10)
        try:
            c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=10000"); yield c
        finally: c.close()
    def init(self):
        with self._lock,self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS nexo_tasks(task_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,objective TEXT NOT NULL,intent TEXT NOT NULL DEFAULT 'unknown',priority TEXT NOT NULL,dependencies TEXT NOT NULL,required_tools TEXT NOT NULL,expected_result TEXT NOT NULL,kind TEXT NOT NULL,parameters TEXT NOT NULL,resources TEXT NOT NULL DEFAULT '[]',state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,max_retries INTEGER NOT NULL DEFAULT 2,timeout_seconds INTEGER NOT NULL DEFAULT 90,result TEXT,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)")
            cols={r[1] for r in c.execute("PRAGMA table_info(nexo_tasks)")}
            if "intent" not in cols: c.execute("ALTER TABLE nexo_tasks ADD COLUMN intent TEXT NOT NULL DEFAULT 'unknown'")
            if "resources" not in cols: c.execute("ALTER TABLE nexo_tasks ADD COLUMN resources TEXT NOT NULL DEFAULT '[]'")
            c.execute("CREATE INDEX IF NOT EXISTS idx_nexo_tasks_request ON nexo_tasks(request_id)"); c.execute("CREATE INDEX IF NOT EXISTS idx_nexo_tasks_state ON nexo_tasks(state)")
    def put(self,rid,spec,state="queued"):
        self.init()
        with self._lock,self._conn() as c:
            n=_now(); c.execute("INSERT OR REPLACE INTO nexo_tasks(task_id,request_id,objective,intent,priority,dependencies,required_tools,expected_result,kind,parameters,resources,state,attempts,max_retries,timeout_seconds,result,error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(spec.task_id,rid,spec.objective,spec.intent,spec.priority,json.dumps(spec.dependencies),json.dumps(spec.required_tools),spec.expected_result,spec.kind,json.dumps(spec.parameters),json.dumps(spec.resources),state,0,max(0,spec.max_retries),max(1,spec.timeout_seconds),None,None,n,n))
    def update(self,tid,state,*,result=None,error=None,attempts=None):
        self.init()
        with self._lock,self._conn() as c:
            fields=["state=?","updated_at=?","result=?","error=?"]; vals=[state,_now(),json.dumps(result,ensure_ascii=False) if result is not None else None,error]
            if attempts is not None: fields.append("attempts=?"); vals.append(attempts)
            vals.append(tid); c.execute(f"UPDATE nexo_tasks SET {','.join(fields)} WHERE task_id=?",vals)
    def get_request(self,rid):
        self.init()
        with self._lock,self._conn() as c:
            rows=c.execute("SELECT * FROM nexo_tasks WHERE request_id=? ORDER BY created_at",(rid,)).fetchall(); cols=[x[1] for x in c.execute("PRAGMA table_info(nexo_tasks)")]
        return [dict(zip(cols,r)) for r in rows]
    def recover_stale(self,max_age_seconds=300):
        self.init(); cutoff=(datetime.now(timezone.utc)-timedelta(seconds=max(1,max_age_seconds))).isoformat(); out=[]
        with self._lock,self._conn() as c:
            rows=c.execute("SELECT task_id,attempts,state FROM nexo_tasks WHERE state IN ('running','retrying','planning') AND updated_at<?",(cutoff,)).fetchall()
            for tid,attempts,state in rows:
                new="retrying" if int(attempts or 0)>0 else "queued"; c.execute("UPDATE nexo_tasks SET state=?,updated_at=? WHERE task_id=?",(new,_now(),tid)); out.append({"task_id":tid,"from":state,"to":new})
        return out

class TaskOrchestrator:
    PRIORITY={"critical":0,"high":1,"normal":2,"low":3}
    def __init__(self,store=None): self.store=store or TaskStore(); self.store.init(); self.store.recover_stale()
    @staticmethod
    def validate(tasks):
        items=list(tasks); ids={t.task_id for t in items}
        if len(ids)!=len(items): raise ValueError("duplicate_task_id")
        for t in items:
            missing=set(t.dependencies)-ids
            if missing: raise ValueError(f"missing_dependencies:{','.join(sorted(missing))}")
        graph={t.task_id:set(t.dependencies) for t in items}; visiting=set(); visited=set()
        def dfs(n):
            if n in visiting: raise ValueError("task_dependency_cycle")
            if n in visited:return
            visiting.add(n)
            for d in graph[n]: dfs(d)
            visiting.remove(n); visited.add(n)
        for n in graph: dfs(n)
        return items
    def enqueue(self,rid,tasks):
        items=self.validate(tasks)
        for t in items:self.store.put(rid,t,"planning")
        for t in items:self.store.update(t.task_id,"queued")
        return items
    @staticmethod
    def _conflict(a,b): return bool(set(a.resources)&set(b.resources))
    def run(self,rid,tasks,executor:Callable[[TaskSpec],dict[str,Any]],max_parallel=3):
        items=self.enqueue(rid,tasks); pending={t.task_id:t for t in items}; done={}; running={}; workers=max(1,min(int(max_parallel),4))
        def ready(t): return all(d in done and done[d].get("state")=="completed" for d in t.dependencies)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while pending or running:
                for t in list(pending.values()):
                    ds={done[d].get("state") for d in t.dependencies if d in done}
                    if "failed" in ds or "cancelled" in ds:
                        self.store.update(t.task_id,"cancelled",error="dependency_failed"); done[t.task_id]={"task_id":t.task_id,"state":"cancelled","error":"dependency_failed"}; pending.pop(t.task_id,None)
                    elif "waiting_confirmation" in ds:
                        self.store.update(t.task_id,"waiting_confirmation",error="dependency_confirmation_required"); done[t.task_id]={"task_id":t.task_id,"state":"waiting_confirmation","error":"dependency_confirmation_required"}; pending.pop(t.task_id,None)
                for t in pending.values():
                    if not ready(t): self.store.update(t.task_id,"waiting")
                active=list(running.values()); candidates=sorted((t for t in pending.values() if ready(t)),key=lambda t:(self.PRIORITY.get(str(t.priority).lower(),2),t.task_id))
                for t in candidates:
                    if len(running)>=workers: break
                    if any(self._conflict(t,a) for a in active): continue
                    self.store.update(t.task_id,"running",attempts=0); running[pool.submit(self._execute_with_retry,t,executor)]=t; active.append(t); pending.pop(t.task_id,None)
                if not running:
                    if pending and not all(any(d in done and done[d].get("state")=="waiting_confirmation" for d in t.dependencies) or any(d not in done for d in t.dependencies) for t in pending.values()): raise RuntimeError("task_orchestration_stalled")
                    break
                for f in as_completed(list(running)):
                    t=running.pop(f)
                    try:r=dict(f.result() or {})
                    except Exception as e:r={"ok":False,"verified":False,"error":f"orchestrator_error:{type(e).__name__}","attempts":1}
                    state="waiting_confirmation" if r.get("requires_confirmation") else ("completed" if r.get("ok") and r.get("verified") else "failed")
                    self.store.update(t.task_id,state,result=r,error=None if state in {"completed","waiting_confirmation"} else str(r.get("error") or "unverified_result"),attempts=int(r.get("attempts",1))); done[t.task_id]={"task_id":t.task_id,"state":state,**r}; break
        return [done[t.task_id] for t in items]
    @staticmethod
    def _with_timeout(executor,task,seconds):
        holder={}; event=threading.Event()
        def target():
            try: holder["result"]=executor(task)
            except Exception as e: holder["exception"]=e
            finally: event.set()
        threading.Thread(target=target,name=f"nexo-task-{task.task_id}",daemon=True).start()
        if not event.wait(max(1,seconds)): return {"ok":False,"verified":False,"error":"task_timeout","retryable":False}
        if "exception" in holder: raise holder["exception"]
        return holder.get("result") or {"ok":False,"verified":False,"error":"empty_executor_result"}
    def _execute_with_retry(self,t,executor):
        last={"ok":False,"verified":False,"error":"not_executed"}
        for attempt in range(1,max(0,t.max_retries)+2):
            self.store.update(t.task_id,"retrying" if attempt>1 else "running",attempts=attempt)
            try:r=dict(self._with_timeout(executor,t,t.timeout_seconds))
            except Exception as e:r={"ok":False,"verified":False,"error":f"executor_error:{type(e).__name__}","retryable":True}
            r["attempts"]=attempt
            if r.get("ok") and r.get("verified"): return r
            last=r
            if r.get("permanent") or r.get("requires_confirmation") or r.get("retryable") is False: break
        return last

def specs_from_plan(plan):
    out=[]
    for x in plan:
        if not isinstance(x,dict) or not str(x.get("objective","")).strip(): continue
        try: timeout=int(x.get("timeout_seconds") or 90); retries=int(x.get("max_retries") if x.get("max_retries") is not None else 2)
        except (TypeError,ValueError): timeout,retries=90,2
        resources=x.get("resources") if isinstance(x.get("resources"),list) else []
        out.append(TaskSpec(objective=str(x["objective"]).strip(),task_id=str(x.get("task_id") or f"task-{uuid.uuid4().hex[:10]}"),intent=str(x.get("intent") or "unknown"),priority=str(x.get("priority") or "normal"),dependencies=[str(d) for d in x.get("dependencies",[])],required_tools=[str(d) for d in x.get("required_tools",[])],expected_result=str(x.get("expected_result") or ""),kind=str(x.get("kind") or "sequential"),timeout_seconds=max(1,min(timeout,600)),max_retries=max(0,min(retries,5)),parameters=x.get("parameters") if isinstance(x.get("parameters"),dict) else {},resources=[str(r) for r in resources if str(r).strip()]))
    return out
