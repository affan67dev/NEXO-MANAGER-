"""Persistent request/task orchestration for NEXO.

This is deliberately execution-oriented: tasks are durable SQLite records, dependencies
are explicit, retries are bounded, and a failed task does not erase unrelated work.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

DB = Path(__file__).resolve().parent.parent / "data" / "memory.db"
TERMINAL = {"completed", "failed", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskSpec:
    objective: str
    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:10]}")
    priority: str = "normal"
    dependencies: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    expected_result: str = ""
    kind: str = "sequential"
    timeout_seconds: int = 90
    max_retries: int = 2
    parameters: dict[str, Any] = field(default_factory=dict)


class TaskStore:
    """Small durable state store sharing the existing NEXO SQLite database."""
    _lock = threading.RLock()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def init(self) -> None:
        with self._lock, self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS nexo_tasks(
                task_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, objective TEXT NOT NULL,
                priority TEXT NOT NULL, dependencies TEXT NOT NULL, required_tools TEXT NOT NULL,
                expected_result TEXT NOT NULL, kind TEXT NOT NULL, parameters TEXT NOT NULL,
                state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 2, timeout_seconds INTEGER NOT NULL DEFAULT 90,
                result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_nexo_tasks_request ON nexo_tasks(request_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_nexo_tasks_state ON nexo_tasks(state)")

    def put(self, request_id: str, spec: TaskSpec, state: str = "queued") -> None:
        self.init()
        with self._lock, self._conn() as c:
            now = _now()
            c.execute("""INSERT OR REPLACE INTO nexo_tasks
                (task_id,request_id,objective,priority,dependencies,required_tools,expected_result,kind,parameters,state,attempts,max_retries,timeout_seconds,result,error,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (spec.task_id, request_id, spec.objective, spec.priority, json.dumps(spec.dependencies),
                 json.dumps(spec.required_tools), spec.expected_result, spec.kind, json.dumps(spec.parameters),
                 state, 0, max(0, spec.max_retries), max(1, spec.timeout_seconds), None, None, now, now))

    def update(self, task_id: str, state: str, *, result: Any = None, error: str | None = None, attempts: int | None = None) -> None:
        self.init()
        with self._lock, self._conn() as c:
            fields = ["state=?", "updated_at=?", "result=?", "error=?"]
            values: list[Any] = [state, _now(), json.dumps(result, ensure_ascii=False) if result is not None else None, error]
            if attempts is not None:
                fields.append("attempts=?"); values.append(attempts)
            values.append(task_id)
            c.execute(f"UPDATE nexo_tasks SET {','.join(fields)} WHERE task_id=?", values)

    def get_request(self, request_id: str) -> list[dict[str, Any]]:
        self.init()
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM nexo_tasks WHERE request_id=? ORDER BY created_at", (request_id,)).fetchall()
            cols = [x[0] for x in c.execute("PRAGMA table_info(nexo_tasks)").fetchall()]
        return [dict(zip(cols, row)) for row in rows]


class TaskOrchestrator:
    def __init__(self, store: TaskStore | None = None):
        self.store = store or TaskStore()
        self.store.init()

    @staticmethod
    def validate(tasks: Iterable[TaskSpec]) -> list[TaskSpec]:
        items = list(tasks)
        ids = {t.task_id for t in items}
        if len(ids) != len(items):
            raise ValueError("duplicate_task_id")
        for t in items:
            missing = set(t.dependencies) - ids
            if missing:
                raise ValueError(f"missing_dependencies:{','.join(sorted(missing))}")
        graph = {t.task_id: set(t.dependencies) for t in items}
        visiting: set[str] = set(); visited: set[str] = set()
        def dfs(node: str) -> None:
            if node in visiting: raise ValueError("task_dependency_cycle")
            if node in visited: return
            visiting.add(node)
            for dep in graph[node]: dfs(dep)
            visiting.remove(node); visited.add(node)
        for node in graph: dfs(node)
        return items

    def enqueue(self, request_id: str, tasks: Iterable[TaskSpec]) -> list[TaskSpec]:
        items = self.validate(tasks)
        for task in items: self.store.put(request_id, task)
        return items

    def run(self, request_id: str, tasks: Iterable[TaskSpec], executor: Callable[[TaskSpec], dict[str, Any]], max_parallel: int = 3) -> list[dict[str, Any]]:
        items = self.enqueue(request_id, tasks)
        pending = {t.task_id: t for t in items}
        done: dict[str, dict[str, Any]] = {}
        running: dict[Any, TaskSpec] = {}
        workers = max(1, min(int(max_parallel), 4))

        def ready(t: TaskSpec) -> bool:
            return all(d in done and done[d].get("state") == "completed" for d in t.dependencies)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            while pending or running:
                blocked = [t for t in pending.values() if any(d in done and done[d].get("state") in {"failed", "cancelled"} for d in t.dependencies)]
                for t in blocked:
                    self.store.update(t.task_id, "cancelled", error="dependency_failed")
                    done[t.task_id] = {"task_id": t.task_id, "state": "cancelled", "error": "dependency_failed"}
                    pending.pop(t.task_id, None)
                for t in list(pending.values()):
                    if ready(t):
                        self.store.update(t.task_id, "running", attempts=1)
                        running[pool.submit(self._execute_with_retry, t, executor)] = t
                        pending.pop(t.task_id, None)
                if not running:
                    if pending:
                        raise RuntimeError("task_orchestration_stalled")
                    break
                for future in as_completed(list(running)):
                    task = running.pop(future)
                    try: result = future.result()
                    except Exception as exc: result = {"ok": False, "verified": False, "error": str(exc)}
                    state = "completed" if result.get("ok") and result.get("verified") else "failed"
                    self.store.update(task.task_id, state, result=result, error=None if state == "completed" else str(result.get("error") or "unverified_result"), attempts=int(result.get("attempts", 1)))
                    done[task.task_id] = {"task_id": task.task_id, "state": state, **result}
                    break
        return [done[t.task_id] for t in items]

    def _execute_with_retry(self, task: TaskSpec, executor: Callable[[TaskSpec], dict[str, Any]]) -> dict[str, Any]:
        attempts = 0
        last: dict[str, Any] = {"ok": False, "verified": False, "error": "not_executed"}
        while attempts <= max(0, task.max_retries):
            attempts += 1
            try:
                result = executor(task) or {"ok": False, "verified": False, "error": "empty_executor_result"}
            except Exception as exc:
                result = {"ok": False, "verified": False, "error": f"executor_error:{type(exc).__name__}"}
            result = dict(result); result["attempts"] = attempts
            if result.get("ok") and result.get("verified"):
                return result
            last = result
            if result.get("permanent") or result.get("requires_confirmation"):
                break
        return last


def specs_from_plan(plan: list[dict[str, Any]]) -> list[TaskSpec]:
    """Convert a LLaMA-produced plan into validated durable task records."""
    tasks: list[TaskSpec] = []
    for item in plan:
        if not isinstance(item, dict) or not str(item.get("objective", "")).strip():
            continue
        tasks.append(TaskSpec(
            objective=str(item["objective"]).strip(),
            task_id=str(item.get("task_id") or f"task-{uuid.uuid4().hex[:10]}"),
            priority=str(item.get("priority") or "normal"),
            dependencies=[str(x) for x in (item.get("dependencies") or [])],
            required_tools=[str(x) for x in (item.get("required_tools") or [])],
            expected_result=str(item.get("expected_result") or ""),
            kind=str(item.get("kind") or "sequential"),
            timeout_seconds=int(item.get("timeout_seconds") or 90),
            max_retries=int(item.get("max_retries") if item.get("max_retries") is not None else 2),
            parameters=item.get("parameters") if isinstance(item.get("parameters"), dict) else {},
        ))
    return tasks
