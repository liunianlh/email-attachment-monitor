from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, flash, redirect, render_template, request, url_for

from email_monitor.config import (
    AppConfig,
    describe_config_health,
    load_config,
    save_email_config,
)
from email_monitor.db import (
    count_rules_using_template,
    create_rule,
    create_template,
    delete_rule,
    delete_template,
    get_execution_logs,
    get_rule,
    get_rules,
    get_templates,
    init_db,
    soft_delete_all_logs,
    update_rule,
)
from email_monitor.pipeline import run_pipeline_once
from email_monitor.scheduler import create_scheduler
from email_monitor.tasks import TaskManager
from email_monitor.validation import parse_template


def create_app(config: AppConfig | None = None, *, start_scheduler: bool = True) -> Flask:
    app_config = config or load_config()
    init_db(app_config.database_path)
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "email-monitor-local"
    app.config["EMAIL_MONITOR_CONFIG"] = app_config
    task_manager = TaskManager(timezone=app_config.timezone)
    app.config["EMAIL_MONITOR_TASK_MANAGER"] = task_manager

    scheduler = None
    if start_scheduler:
        scheduler = create_scheduler(app_config, task_manager)
        scheduler.start()
    app.config["EMAIL_MONITOR_SCHEDULER"] = scheduler

    @app.get("/")
    def index() -> Any:
        return redirect(url_for("status_page"))

    @app.get("/status")
    def status_page() -> str:
        return render_template(
            "status.html",
            active_page="status",
            schedule_time=app_config.schedule_time,
            next_run_time=_next_run_time(scheduler),
            config_health=describe_config_health(app_config),
        )

    @app.get("/rules")
    def rules_page() -> str:
        return render_template(
            "rules.html",
            active_page="rules",
            rules=get_rules(app_config.database_path),
            templates=get_templates(app_config.database_path),
            editing_rule=None,
        )

    @app.get("/rules/<int:rule_id>/edit")
    def edit_rule_page(rule_id: int) -> str:
        return render_template(
            "rules.html",
            active_page="rules",
            rules=get_rules(app_config.database_path),
            templates=get_templates(app_config.database_path),
            editing_rule=get_rule(app_config.database_path, rule_id),
        )

    @app.get("/templates")
    def templates_page() -> str:
        return render_template(
            "templates.html",
            active_page="templates",
            templates=get_templates(app_config.database_path),
        )

    @app.get("/logs")
    def logs_page() -> str:
        status_filter = request.args.get("status") or None
        return render_template(
            "logs.html",
            active_page="logs",
            logs=get_execution_logs(
                app_config.database_path,
                status=status_filter,
                limit=100,
            ),
            status_filter=status_filter or "",
        )

    @app.post("/logs/delete-all")
    def delete_all_logs() -> Any:
        count = soft_delete_all_logs(app_config.database_path)
        flash(f"已删除 {count} 条日志记录（数据仍保留在数据库）", "success")
        return redirect(url_for("logs_page"))

    @app.get("/tasks")
    def tasks_page() -> str:
        return render_template(
            "tasks.html",
            active_page="tasks",
            tasks=task_manager.list_tasks(),
        )

    @app.post("/rules")
    def save_rule() -> Any:
        try:
            values = _rule_values_from_form(request.form, app_config.database_path)
        except ValueError as exc:
            flash(str(exc), "danger")
            rule_id = request.form.get("rule_id")
            if rule_id:
                return redirect(url_for("edit_rule_page", rule_id=int(rule_id)))
            return redirect(url_for("rules_page"))
        rule_id = request.form.get("rule_id")
        if rule_id:
            update_rule(app_config.database_path, int(rule_id), values)
            flash("规则已更新", "success")
        else:
            create_rule(app_config.database_path, values)
            flash("规则已创建", "success")
        return redirect(url_for("rules_page"))

    @app.post("/rules/<int:rule_id>/delete")
    def remove_rule(rule_id: int) -> Any:
        delete_rule(app_config.database_path, rule_id)
        flash("规则已删除", "success")
        return redirect(url_for("rules_page"))

    @app.post("/rules/<int:rule_id>/run")
    def run_rule_once(rule_id: int) -> Any:
        rule = get_rule(app_config.database_path, rule_id)
        if rule is None:
            flash("规则不存在", "danger")
            return redirect(url_for("rules_page"))
        task_manager.submit(
            name=f"单独运行规则: {rule.name}",
            func=lambda: run_pipeline_once(app_config, rule_id=rule_id),
        )
        flash("规则任务已提交", "success")
        return redirect(url_for("tasks_page"))

    @app.post("/templates")
    def upload_template() -> Any:
        upload = request.files.get("template_file")
        name = request.form.get("name") or (upload.filename if upload else "")
        if not upload or not upload.filename:
            flash("请选择模板文件", "danger")
            return redirect(url_for("templates_page"))
        template_dir = app_config.data_dir / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        file_path = template_dir / Path(upload.filename).name
        upload.save(file_path)
        spec = parse_template(file_path)
        create_template(app_config.database_path, name, file_path, spec)
        flash("模板已解析并保存", "success")
        return redirect(url_for("templates_page"))

    @app.post("/templates/<int:template_id>/delete")
    def remove_template(template_id: int) -> Any:
        usage_count = count_rules_using_template(app_config.database_path, template_id)
        if usage_count:
            flash("模板正在被规则使用，不能删除", "danger")
            return redirect(url_for("templates_page"))
        delete_template(app_config.database_path, template_id)
        flash("模板已删除", "success")
        return redirect(url_for("templates_page"))

    @app.post("/config/email")
    def save_email_settings() -> Any:
        save_email_config(
            app_config,
            host=request.form.get("imap_host", "").strip(),
            port=int(request.form.get("imap_port", "993")),
            username=request.form.get("imap_username", "").strip(),
            password=request.form.get("imap_password", ""),
            mailbox=request.form.get("imap_mailbox", "INBOX").strip() or "INBOX",
            use_ssl=request.form.get("imap_use_ssl") == "on",
        )
        flash("邮箱配置已保存", "success")
        return redirect(url_for("status_page"))

    @app.post("/run-once")
    def run_once() -> Any:
        task_manager.submit(
            name="手动邮件巡检",
            func=lambda: run_pipeline_once(app_config),
        )
        flash("任务已提交", "success")
        return redirect(url_for("tasks_page"))

    return app


def _rule_values_from_form(form: Any, database_path: Path) -> dict[str, Any]:
    template_id = _template_id_from_text(form.get("template_id", ""), database_path)
    return {
        "name": form.get("name", "").strip(),
        "enabled": form.get("enabled") == "on",
        "senders": _parse_senders(form.get("senders", "")),
        "subject_keyword": form.get("subject_keyword", "").strip() or None,
        "attachment_pattern": form.get("attachment_pattern", "").strip() or None,
        "save_path": form.get("save_path", "downloads").strip(),
        "execution_type": form.get("execution_type", "command"),
        "output_path": form.get("output_path", "").strip() or None,
        "command": form.get("command", "").strip(),
        "timeout_seconds": int(form.get("timeout_seconds", "600")),
        "template_id": template_id,
    }


def _parse_senders(value: str) -> list[str]:
    return [
        item.strip()
        for chunk in value.splitlines()
        for item in chunk.split(",")
        if item.strip()
    ]


def _template_id_from_text(value: str, database_path: Path) -> int | None:
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    template_path = Path(text).expanduser()
    if not template_path.is_file():
        raise ValueError("模板文件不存在，请填写已有模板 ID 或模板文件路径")
    return create_template(
        database_path,
        template_path.stem,
        template_path,
        parse_template(template_path),
    )


def _next_run_time(scheduler: Any) -> str:
    if scheduler is None:
        return "调度未启动"
    jobs = scheduler.get_jobs()
    if not jobs or not jobs[0].next_run_time:
        return "暂无"
    return jobs[0].next_run_time.strftime("%Y-%m-%d %H:%M:%S")
