from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any, Callable
from zoneinfo import ZoneInfo


@dataclass
class TaskRecord:
    id: int
    name: str
    started_at: str
    status: str
    error_detail: str = ""


class TaskManager:
    def __init__(self, *, max_workers: int = 1, timezone: str = "Asia/Shanghai") -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._timezone = ZoneInfo(timezone)
        self._lock = Lock()
        self._next_id = 1
        self._tasks: list[TaskRecord] = []

    def submit(self, *, name: str, func: Callable[[], Any]) -> Future[Any]:
        with self._lock:
            task = TaskRecord(
                id=self._next_id,
                name=name,
                started_at=self._now_text(),
                status="running",
            )
            self._next_id += 1
            self._tasks.insert(0, task)
        return self._executor.submit(self._run_task, task.id, func)

    def list_tasks(self) -> list[TaskRecord]:
        with self._lock:
            return list(self._tasks)

    def _run_task(self, task_id: int, func: Callable[[], Any]) -> Any:
        try:
            result = func()
        except Exception as exc:
            self._set_status(task_id, "failure", str(exc))
            return None
        self._set_status(task_id, "success", "")
        return result

    def _set_status(self, task_id: int, status: str, error_detail: str) -> None:
        with self._lock:
            for task in self._tasks:
                if task.id == task_id:
                    task.status = status
                    task.error_detail = error_detail
                    break

    def _now_text(self) -> str:
        return datetime.now(self._timezone).strftime("%Y-%m-%d %H:%M:%S")
