from __future__ import annotations

from threading import Event

from email_monitor.scheduler import create_scheduler
from email_monitor.tasks import TaskManager


def test_task_manager_tracks_running_and_successful_tasks() -> None:
    manager = TaskManager(max_workers=1)
    started = Event()
    release = Event()

    def run() -> dict[str, int]:
        started.set()
        release.wait(timeout=1)
        return {"success_count": 1}

    future = manager.submit(name="邮件巡检", func=run)

    assert started.wait(timeout=1)

    tasks = manager.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].name == "邮件巡检"
    assert tasks[0].started_at
    assert tasks[0].status == "running"

    release.set()
    future.result(timeout=1)

    tasks = manager.list_tasks()
    assert tasks[0].status == "success"


def test_task_manager_tracks_failed_tasks() -> None:
    manager = TaskManager(max_workers=1)

    def fail() -> dict[str, int]:
        raise RuntimeError("配置错误")

    future = manager.submit(name="邮件巡检", func=fail)

    future.result(timeout=1)

    tasks = manager.list_tasks()
    assert tasks[0].status == "failure"
    assert "配置错误" in tasks[0].error_detail


def test_scheduler_queues_automatic_pipeline_task(tmp_config, monkeypatch) -> None:
    manager = TaskManager(max_workers=1)
    started = Event()
    release = Event()

    def fake_run_pipeline_once(config) -> dict[str, int]:
        started.set()
        release.wait(timeout=1)
        return {"success_count": 1, "failure_count": 0, "skipped_count": 0}

    monkeypatch.setattr("email_monitor.scheduler.run_pipeline_once", fake_run_pipeline_once)

    scheduler = create_scheduler(tmp_config, manager)
    job = scheduler.get_jobs()[0]
    future = job.func(*job.args, **job.kwargs)

    assert started.wait(timeout=1)
    tasks = manager.list_tasks()
    assert tasks[0].name == "自动邮件巡检"
    assert tasks[0].status == "running"

    release.set()
    future.result(timeout=1)
    assert manager.list_tasks()[0].status == "success"
