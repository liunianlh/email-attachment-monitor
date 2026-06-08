from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from email_monitor.config import AppConfig
from email_monitor.pipeline import run_pipeline_once
from email_monitor.tasks import TaskManager


def create_scheduler(
    config: AppConfig,
    task_manager: TaskManager | None = None,
) -> BackgroundScheduler:
    task_manager = task_manager or TaskManager(timezone=config.timezone)
    hour, minute = _parse_schedule_time(config.schedule_time)
    scheduler = BackgroundScheduler(timezone=config.timezone)
    scheduler.add_job(
        _submit_scheduled_task,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=config.timezone),
        args=[task_manager, config],
        id="daily-email-monitor",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler


def _submit_scheduled_task(task_manager: TaskManager, config: AppConfig):
    return task_manager.submit(
        name="自动邮件巡检",
        func=lambda: run_pipeline_once(config),
    )


def _parse_schedule_time(value: str) -> tuple[int, int]:
    hour_text, minute_text = value.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"invalid schedule time: {value}")
    return hour, minute
