"""Durable request/task orchestration for NEXO."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

DB = Path(__file__).resolve().parent.parent / "data" / "memory.db"
TERMINAL = {"completed", "failed", "cancelled"}
ACTIVE = {"planning", "queued", "waiting", "running", "retrying", "waiting_confirmation"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskSpec:
    objective: str
    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:10]}")
    intent: str = "unknown"
    priority: str = "normal"
    dependencies: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    expected_result: str = ""
    kind: str = "sequential"
    timeout_seconds: int = 90
    max_retries: int = 2
    parameters: dict[str, Any] = field(default_factory=dict)
    resources: list[str] = field(default_factory=list)


class TaskStore:
    _lock = threading.RLock()

    def _conn(self):
        DB.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB, timeout=10)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=10000")
        return c

    def init(self):
        with self._lock, self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS nexo_tasks(" 
                "task_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,objective TEXT NOT NULL,"
                "intent TEXT NOT NULL DEFAULT 'unknown',priority TEXT NOT NULL,dependencies TEXT NOT NULL,"
                "required_tools TEXT NOT NULL,expected_result TEXT NOT NULL,kind TEXT NOT NULL,"
                "parameters TEXT NOT NULL,resources TEXT NOT NULL DEFAULT '[]',state TEXT NOT NULL,"
                "attempts INTEGER NOT NULL DEFAULT 0,max_retries INTEGER NOT NULL DEFAULT 2,"
                "timeout_seconds INTEGER NOT NULL DEFAULT 90,result TEXT,error TEXT,"
                "created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"
            )
            cols = {row[1] for row in c.execute("PRAGMA table_info(nexo_tasks)")}
            migrations = {
                "intent": "ALTER TABLE nexo_tasks ADD COLUMN intent TEXT NOT NULL DEFAULT 'unknown'",
                "resources": "ALTER TABLE nexo_tasks ADD COLUMN resources TEXT NOT NULL DEFAULT '[]'",
            }
            for name, sql in migrations.items():
                if name not in cols:
                    c.execute(sql)
            c.execute("CREATE INDEX IF NOT EXISTS idx_nexo_tasks_request ON nexo_tasks(request_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_nexo_tasks_state ON nexo_tasks(state)")

    def put(self, request_id: str, spec: TaskSpec, state: str = "queued"):
        self.init()
        with self._lock, self._conn() as c:
            n = _now()
            c.execute(
                "INSERT OR REPLACE INTO nexo_tasks(task_id,request_id,objective,intent,priority,dependencies,"
                "required_tools,expected_result,kind,parameters,resources,state,attempts,max_retries,timeout_seconds,"
                "result,error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    spec.task_id, request_id, spec.objective, spec.intent, spec.priority,
                    json.dumps(spec.dependencies), json.dumps(spec.required_tools), spec.expected_result,
                    spec.kind, json.dumps(spec.parameters), json.dumps(spec.resources), state, 0,
                    max(0, spec.max_retries), max(1, spec.timeout_seconds), None, None, n, n,
                ),
            )

    def update(self, task_id: str, state: str, *, result=None, error=None, attempts=None):
        self.init()
        with self._lock, self._conn() as c:
            fields = ["state=?", "updated_at=?", "result=?", "error=?"]
            values = [state, _now(), json.dumps(result, ensure_ascii=False) if result is not None else None, error]
            if attempts is not None:
                fields.append("attempts=?")
                values.append(attempts)
            values.append(task_id)
            c.execute(f"UPDATE nexo_tasks SET {','.join(fields)} WHERE task_id=?", values)

    def get_request(self, request_id: str):
        self.init()
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM nexo_tasks WHERE request_id=? ORDER BY created_at", (request_id,)).fetchall()
            cols = [x[1] for x in c.execute("PRAGMA table_info(nexo_tasks)").fetchall()]
        return [dict(zip(cols, row)) for row in rows]

    def recover_stale(self, *, max_age_seconds: int = 300):
        """Move abandoned active executions back to queued/retryable state after a crash."""
        self.init()
        cutoff = datetime.fromtimestamp(datetime.now().timestamp() - max(1, max_age_seconds), tz=timezone.utc).isoformat()
        recovered = []
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT task_id,attempts,state FROM nexo_tasks WHERE state IN ('running','retrying','planning') AND updated_at<?",
                (cutoff,),
            ).fetchall()
            for task_id, attempts, state in rows:
                new_state = "retrying" if int(attempts or 0) > 0 else "queued"
                c.execute("UPDATE nexo_tasks SET state=?,updated_at=? WHERE task_id=?", (new_state, _now(), task_id))
                recovered.append({"task_id": task_id, "from": state, "to": new_state})
        return recovered


class TaskOrchestrator:
    PRIORITY = {"critical": 0, "high": 1, "normal": 2, "low": 3}

    def __init__(self, store: TaskStore | None = None):
        self.store = store or TaskStore()
        self.store.init()
        self.store.recover_stale()

    @staticmethod
    def validate(tasks):
        items = list(tasks)
        ids = {t.task_id for t in items}
        if len(ids) != len(items):
            raise ValueError("duplicate_task_id")
        for t in items:
            missing = set(t.dependencies) - ids
            if missing:
                raise ValueError(f"missing_dependencies:{','.join(sorted(missing))}")
        graph = {t.task_id: set(t.dependencies) for t in items}
        visiting, visited = set(), set()

        def dfs(node):
            if node in visiting:
                raise ValueError("task_dependency_cycle")
            if node in visited:
                return
            visiting.add(node)
            for dep in graph[node]:
                dfs(dep)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            dfs(node)
        return items

    def enqueue(self, request_id: str, tasks):
        items = self.validate(tasks)
        for task in items:
            self.store.put(request_id, task, "planning")
        for task in items:
            self.store.update(task.task_id, "queued")
        return items

    @staticmethod
    def _resource_conflict(a: TaskSpec, b: TaskSpec) -> bool:
        return bool(set(a.resources) & set(b.resources))

    def run(self, request_id: str, tasks, executor: Callable[[TaskSpec], dict[str, Any]], max_parallel: int = 3):
        items = self.enqueue(request_id, tasks)
        pending = {t.task_id: t for t in items}
        done: dict[str, dict[str, Any]] = {}
        running: dict[Any, TaskSpec] = {}
        workers = max(1, min(int(max_parallel), 4))

        def ready(task):
            return all(dep in done and done[dep].get("state") == "completed" for dep in task.dependencies)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            while pending or running:
                for task in list(pending.values()):
                    failed_dep = any(dep in done and done[dep].get("state") in {"failed", "cancelled"} for dep in task.dependencies)
                    if failed_dep:
                        self.store.update(task.task_id, "cancelled", error="dependency_failed")
                        done[task.task_id] = {"task_id": task.task_id, "state": "cancelled", "error": "dependency_failed"}
                        pending.pop(task.task_id, None)

                for task in pending.values():
                    if not ready(task):
                        self.store.update(task.task_id, "waiting")

                active_tasks = list(running.values())
                candidates = sorted(
                    (task for task in pending.values() if ready(task)),
                    key=lambda t: (self.PRIORITY.get(str(t.priority).lower(), 2), t.task_id),
                )
                for task in candidates:
                    if len(running) >= workers:
                        break
                    if any(self._resource_conflict(task, active) for active in active_tasks):
                        continue
                    self.store.update(task.task_id, "running", attempts=0)
                    future = pool.submit(self._execute_with_retry, task, executor)
                    running[future] = task
                    active_tasks.append(task)
                    pending.pop(task.task_id, None)

                if not running:
                    if pending:
                        raise RuntimeError("task_orchestration_stalled")
                    break

                for future in as_completed(list(running)):
                    task = running.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"ok": False, "verified": False, "error": f"orchestrator_error:{type(exc).__name__}", "attempts": 1}
                    result = dict(result or {})
                    state = "waiting_confirmation" if result.get("requires_confirmation") else ("completed" if result.get("ok") and result.get("verified") else "failed")
                    self.store.update(task.task_id, state, result=result, error=None if state in {"completed", "waiting_confirmation"} else str(result.get("error") or "unverified_result"), attempts=int(result.get("attempts", 1)))
                    done[task.task_id] = {"task_id": task.task_id, "state": state, **result}
                    break

        return [done[t.task_id] for t in items]

    def _execute_with_retry(self, task: TaskSpec, executor):
        attempts = 0
        last = {"ok": False, "verified": False, "error": "not_executed"}
        while attempts <= max(0, task.max_retries):
            attempts += 1
            self.store.update(task.task_id, "retrying" if attempts > 1 else "running", attempts=attempts)
            future = ThreadPoolExecutor(max_workers=1).submit(executor, task)
            try:
                result = future.result(timeout=max(1, task.timeout_seconds))
                result = result or {"ok": False, "verified": False, "error": "empty_executor_result"}
            except TimeoutError:
                future.cancel()
                result = {"ok": False, "verified": False, "error": "task_timeout", "permanent": False}
            except Exception as exc:
                result = {"ok": False, "verified": False, "error": f"executor_error:{type(exc).__name__}"}
            result = dict(result)
            result["attempts"] = attempts
            if result.get("ok") and result.get("verified"):
                return result
            last = result
            if result.get("permanent") or result.get("requires_confirmation"):
                break
        return last


def specs_from_plan(plan):
    tasks = []
    for item in plan:
        if not isinstance(item, dict) or not str(item.get("objective", "")).strip():
            continue
        try:
            timeout = int(item.get("timeout_seconds") or 90)
            retries = int(item.get("max_retries") if item.get("max_retries") is not None else 2)
        except (TypeError, ValueError):
            timeout, retries = 90, 2
        resources = item.get("resources") if isinstance(item.get("resources"), list) else []
        tasks.append(TaskSpec(
            objective=str(item["objective"]).strip(),
            task_id=str(item.get("task_id") or f"task-{uuid.uuid4().hex[:10]}"),
            intent=str(item.get("intent") or "unknown"),
            priority=str(item.get("priority") or "normal"),
            dependencies=[str(d) for d in item.get("dependencies", [])],
            required_tools=[str(d) for d in item.get("required_tools", [])],
            expected_result=str(item.get("expected_result") or ""),
            kind=str(item.get("kind") or "sequential"),
            timeout_seconds=max(1, min(timeout, 600)),
            max_retries=max(0, min(retries, 5)),
            parameters=item.get("parameters") if isinstance(item.get("parameters"), dict) else {},
            resources=[str(r) for r in resources if str(r).strip()],
        ))
    return tasks
