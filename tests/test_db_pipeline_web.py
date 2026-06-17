from __future__ import annotations

import time
import sys
from threading import Event
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

from email_monitor.app import create_app
from email_monitor.db import (
    add_execution_log,
    create_rule,
    create_template,
    get_execution_logs,
    get_rules,
    get_template,
    get_templates,
    init_db,
    mark_processed,
    was_processed,
)
from email_monitor.db import connect
from email_monitor.mail_client import ParsedAttachment, ParsedMessage
from email_monitor.pipeline import Pipeline
from email_monitor.validation import parse_template


def test_db_rule_template_logs_and_processed_messages(db_path: Path, tmp_path: Path) -> None:
    rule_id = create_rule(
        db_path,
        {
            "name": "supplier",
            "enabled": True,
            "senders": ["supplier@example.com"],
            "subject_keyword": "日报",
            "attachment_pattern": "*.xlsx",
            "save_path": str(tmp_path),
            "command": "python script.py",
            "timeout_seconds": 600,
            "template_id": None,
        },
    )
    template_id = create_template(
        db_path,
        "orders",
        tmp_path / "template.xlsx",
        {"columns": []},
    )
    add_execution_log(
        db_path,
        rule_name="supplier",
        mail_subject="日报",
        status="success",
        error_detail="",
        duration_ms=12,
    )
    mark_processed(db_path, "uid-1", "message-1", rule_id)

    assert get_rules(db_path)[0].name == "supplier"
    assert get_rules(db_path)[0].command == "python script.py"
    assert get_rules(db_path)[0].execution_type == "command"
    assert get_rules(db_path)[0].output_path is None
    assert get_template(db_path, template_id)["name"] == "orders"
    assert get_execution_logs(db_path)[0]["status"] == "success"
    assert was_processed(db_path, "uid-1", "message-1")
    with connect(db_path) as conn:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(rules)").fetchall()
        }
    assert "command" in columns
    assert "execution_type" in columns
    assert "output_path" in columns
    assert "api_endpoint" not in columns
    assert "api_method" not in columns
    assert "api_auth_secret_key" not in columns
    assert "transform_config" not in columns
    assert "script_path" not in columns


def test_pipeline_processes_attachment_and_marks_success(
    db_path: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    template_file = tmp_path / "template.xlsx"
    pd.DataFrame(
        {
            "供应商名称": ["A", "B"],
            "金额": [100.0, 200.0],
            "订单日期": ["2026-06-08", "2026-06-09"],
        }
    ).to_excel(template_file, index=False)
    template_id = create_template(db_path, "orders", template_file, parse_template(template_file))

    script = tmp_path / "script.py"
    marker = tmp_path / "marker.txt"
    script.write_text(
        "import os, pathlib\n"
        "pathlib.Path(os.environ['MARKER']).write_text("
        "os.environ['EMAIL_MONITOR_ATTACHMENT'], encoding='utf-8')\n",
        encoding="utf-8",
    )
    source = tmp_path / "orders.xlsx"
    pd.DataFrame(
        {
            "供应商名称": ["A"],
            "金额": ["100"],
            "订单日期": ["2026-06-08"],
        }
    ).to_excel(source, index=False)
    rule_id = create_rule(
        db_path,
        {
            "name": "supplier",
            "enabled": True,
            "senders": ["supplier@example.com"],
            "subject_keyword": "日报",
            "attachment_pattern": "*.xlsx",
            "save_path": str(tmp_path / "downloads"),
            "command": f"MARKER={marker} {sys.executable} {script}",
            "timeout_seconds": 5,
            "template_id": template_id,
        },
    )
    marked: list[ParsedMessage] = []
    message = ParsedMessage(
        uid="uid-1",
        message_id="message-1",
        sender="supplier@example.com",
        subject="日报",
        attachments=[
            ParsedAttachment(filename="orders.xlsx", content=source.read_bytes())
        ],
        raw=None,
    )

    pipeline = Pipeline(
        database_path=db_path,
        data_dir=tmp_path / "data",
        mark_success_callback=lambda msg: marked.append(msg),
    )
    summary = pipeline.process_messages([message])

    assert summary.success_count == 1
    assert summary.failure_count == 0
    assert marked == [message]
    assert marker.read_text(encoding="utf-8").endswith("orders.xlsx")
    assert was_processed(db_path, "uid-1", "message-1")
    assert get_rules(db_path)[0].id == rule_id


def test_pipeline_processes_attachment_when_sender_matches_even_if_attachment_pattern_does_not(
    db_path: Path,
    tmp_path: Path,
) -> None:
    script = tmp_path / "script.py"
    marker = tmp_path / "marker.txt"
    script.write_text(
        "import os, pathlib\n"
        "pathlib.Path(os.environ['MARKER']).write_text("
        "os.environ['EMAIL_MONITOR_ATTACHMENT'], encoding='utf-8')\n",
        encoding="utf-8",
    )
    create_rule(
        db_path,
        {
            "name": "supplier",
            "enabled": True,
            "senders": ["supplier@example.com"],
            "subject_keyword": "日报",
            "attachment_pattern": "*.xlsx",
            "save_path": str(tmp_path / "downloads"),
            "command": f"MARKER={marker} {sys.executable} {script}",
            "timeout_seconds": 5,
            "template_id": None,
        },
    )
    message = ParsedMessage(
        uid="uid-sender-match",
        message_id="message-sender-match",
        sender="supplier@example.com",
        subject="无关键字",
        attachments=[ParsedAttachment(filename="orders.xls", content=b"demo")],
        raw=None,
    )

    summary = Pipeline(
        database_path=db_path,
        data_dir=tmp_path / "data",
    ).process_messages([message])

    assert summary.success_count == 1
    assert summary.skipped_count == 0
    assert marker.read_text(encoding="utf-8").endswith("orders.xls")


def test_pipeline_processes_seen_message_when_it_was_not_processed(
    db_path: Path,
    tmp_path: Path,
) -> None:
    script = tmp_path / "script.py"
    marker = tmp_path / "marker.txt"
    script.write_text(
        "import os, pathlib\n"
        "pathlib.Path(os.environ['MARKER']).write_text("
        "os.environ['EMAIL_MONITOR_ATTACHMENT'], encoding='utf-8')\n",
        encoding="utf-8",
    )
    create_rule(
        db_path,
        {
            "name": "supplier",
            "enabled": True,
            "senders": ["supplier@example.com"],
            "subject_keyword": "",
            "attachment_pattern": "*.xls",
            "save_path": str(tmp_path / "downloads"),
            "command": f"MARKER={marker} {sys.executable} {script}",
            "timeout_seconds": 5,
            "template_id": None,
        },
    )
    message = ParsedMessage(
        uid="uid-seen-unprocessed",
        message_id="message-seen-unprocessed",
        sender="supplier@example.com",
        subject="已读但未处理",
        attachments=[ParsedAttachment(filename="orders.xls", content=b"demo")],
        raw=None,
        seen=True,
    )

    summary = Pipeline(
        database_path=db_path,
        data_dir=tmp_path / "data",
    ).process_messages([message])

    assert summary.success_count == 1
    assert marker.read_text(encoding="utf-8").endswith("orders.xls")


def test_pipeline_organizes_attachment_without_running_command(
    db_path: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "orders.xlsx"
    pd.DataFrame(
        [
            ["职工健康体检意向申报", None, None, None],
            ["序号", "姓名", "身份证号", "联系电话"],
            [1, "李四", "11010519491231002X", "13900139000"],
        ]
    ).to_excel(source, index=False, header=False)
    source_bytes = source.read_bytes()
    save_dir = tmp_path / "downloads"
    output_dir = tmp_path / "organized"
    template_file = tmp_path / "template.xlsx"
    pd.DataFrame(
        {
            "保单号": ["13900139000"],
            "客户姓名": ["李四"],
            "客户身份证号": ["11010519491231002X"],
        }
    ).to_excel(template_file, index=False)
    template_id = create_template(db_path, "整理模板", template_file, parse_template(template_file))
    create_rule(
        db_path,
        {
            "name": "supplier",
            "enabled": True,
            "senders": ["supplier@example.com"],
            "subject_keyword": "日报",
            "attachment_pattern": "*.xlsx",
            "save_path": str(save_dir),
            "execution_type": "organize_file",
            "output_path": str(output_dir),
            "command": "not-a-real-command",
            "timeout_seconds": 5,
            "template_id": template_id,
        },
    )
    message = ParsedMessage(
        uid="uid-organize",
        message_id="message-organize",
        sender="supplier@example.com",
        subject="日报",
        attachments=[
            ParsedAttachment(filename="orders.xlsx", content=source_bytes)
        ],
        raw=None,
    )

    summary = Pipeline(
        database_path=db_path,
        data_dir=tmp_path / "data",
    ).process_messages([message])

    assert summary.success_count == 1
    assert summary.failure_count == 0
    assert (save_dir / "orders.xlsx").read_bytes() == source_bytes
    organized = pd.read_excel(output_dir / "orders.整理后.xlsx", dtype=str)
    assert organized.iloc[0].to_dict() == {
        "保单号": "13900139000",
        "客户姓名": "李四",
        "客户身份证号": "11010519491231002X",
    }


def test_pipeline_combines_multiple_organize_attachments_into_one_output(
    db_path: Path,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.xlsx"
    second = tmp_path / "second.xlsx"
    pd.DataFrame(
        [
            ["序号", "姓名", "身份证号", "联系电话"],
            [1, "张三", "11010519491231002X", "13800138000"],
        ]
    ).to_excel(first, index=False, header=False)
    with pd.ExcelWriter(second) as writer:
        pd.DataFrame(
            [
                ["序号", "姓名", "身份证号", "联系电话"],
                [1, "李四", "110105199001011234", "13900139000"],
            ]
        ).to_excel(writer, sheet_name="一组", index=False, header=False)
        pd.DataFrame(
            [
                ["序号", "姓名", "身份证号", "联系电话"],
                [1, "王五", "110105198806153219", "13700137000"],
            ]
        ).to_excel(writer, sheet_name="二组", index=False, header=False)
    save_dir = tmp_path / "downloads"
    output_dir = tmp_path / "organized"
    create_rule(
        db_path,
        {
            "name": "supplier",
            "enabled": True,
            "senders": ["supplier@example.com"],
            "subject_keyword": "",
            "attachment_pattern": "*.xlsx",
            "save_path": str(save_dir),
            "execution_type": "organize_file",
            "output_path": str(output_dir),
            "command": "",
            "timeout_seconds": 5,
            "template_id": None,
        },
    )
    messages = [
        ParsedMessage(
            uid="uid-first",
            message_id="message-first",
            sender="supplier@example.com",
            subject="第一封",
            attachments=[ParsedAttachment(filename="first.xlsx", content=first.read_bytes())],
            raw=None,
        ),
        ParsedMessage(
            uid="uid-second",
            message_id="message-second",
            sender="supplier@example.com",
            subject="第二封",
            attachments=[ParsedAttachment(filename="second.xlsx", content=second.read_bytes())],
            raw=None,
        ),
    ]

    summary = Pipeline(
        database_path=db_path,
        data_dir=tmp_path / "data",
    ).process_messages(messages)

    assert summary.success_count == 2
    assert (save_dir / "first.xlsx").exists()
    assert (save_dir / "second.xlsx").exists()
    assert not (output_dir / "first.整理后.xlsx").exists()
    assert not (output_dir / "second.整理后.xlsx").exists()
    combined = pd.read_excel(output_dir / "汇总整理后.xlsx", dtype=str)
    assert combined.to_dict("records") == [
        {
            "保单号": "13800138000",
            "客户姓名": "张三",
            "客户身份证号": "11010519491231002X",
        },
        {
            "保单号": "13900139000",
            "客户姓名": "李四",
            "客户身份证号": "110105199001011234",
        },
        {
            "保单号": "13700137000",
            "客户姓名": "王五",
            "客户身份证号": "110105198806153219",
        },
    ]


def test_pipeline_logs_skipped_messages(db_path: Path, tmp_path: Path) -> None:
    create_rule(
        db_path,
        {
            "name": "supplier",
            "enabled": True,
            "senders": ["supplier@example.com"],
            "subject_keyword": "日报",
            "attachment_pattern": "*.xlsx",
            "save_path": str(tmp_path / "downloads"),
            "command": "python script.py",
            "timeout_seconds": 600,
            "template_id": None,
        },
    )
    message = ParsedMessage(
        uid="uid-skip",
        message_id="message-skip",
        sender="other@example.com",
        subject="无关邮件",
        attachments=[],
        raw=None,
    )

    summary = Pipeline(
        database_path=db_path,
        data_dir=tmp_path / "data",
    ).process_messages([message])

    logs = get_execution_logs(db_path)
    assert summary.skipped_count == 1
    assert logs[0]["status"] == "skipped"
    assert logs[0]["rule_name"] == "未匹配规则"
    assert logs[0]["mail_subject"] == "无关邮件"
    assert "发件人/主题/附件未命中任何规则" in logs[0]["error_detail"]


def test_web_dashboard_splits_features_into_separate_pages(tmp_config, monkeypatch) -> None:
    init_db(tmp_config.database_path)
    create_rule(
        tmp_config.database_path,
        {
            "name": "supplier",
            "enabled": True,
            "senders": ["supplier@example.com"],
            "subject_keyword": "日报",
            "attachment_pattern": "*.xlsx",
            "save_path": str(tmp_config.data_dir / "downloads"),
            "command": "python script.py",
            "timeout_seconds": 600,
            "template_id": None,
        },
    )
    started = Event()
    release = Event()

    def fake_run_pipeline_once(config) -> dict[str, int]:
        started.set()
        release.wait(timeout=1)
        return {"success_count": 0, "failure_count": 0, "skipped_count": 0}

    monkeypatch.setattr("email_monitor.app.run_pipeline_once", fake_run_pipeline_once)

    app = create_app(tmp_config, start_scheduler=False)
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/status")

    response = client.get("/status")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "系统状态" in body
    assert "规则管理" not in body
    assert "模板管理" not in body
    assert "执行日志" not in body

    response = client.get("/rules")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "规则管理" in body
    assert "supplier" in body
    assert "执行命令" in body
    assert "API 端点" not in body
    assert "API Secret Key" not in body
    assert "Transform JSON" not in body
    assert "系统状态" not in body
    assert "模板管理" not in body
    assert "执行日志" not in body

    response = client.get("/templates")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "模板管理" in body
    assert "规则管理" not in body
    assert "系统状态" not in body
    assert "执行日志" not in body

    response = client.get("/logs")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "执行日志" in body
    assert "跳过" in body
    assert "规则管理" not in body
    assert "模板管理" not in body
    assert "系统状态" not in body

    response = client.post("/run-once", follow_redirects=True)
    assert response.status_code == 200
    assert started.wait(timeout=1)
    body = response.get_data(as_text=True)
    assert "任务列表" in body
    assert "手动邮件巡检" in body
    assert "运行中" in body

    release.set()
    task_manager = app.config["EMAIL_MONITOR_TASK_MANAGER"]
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if task_manager.list_tasks()[0].status == "success":
            break
        time.sleep(0.01)
    assert task_manager.list_tasks()[0].status == "success"


def test_web_rule_page_creates_and_edits_execution_type(tmp_config) -> None:
    init_db(tmp_config.database_path)
    app = create_app(tmp_config, start_scheduler=False)
    client = app.test_client()

    response = client.post(
        "/rules",
        data={
            "name": "supplier",
            "enabled": "on",
            "senders": "supplier@example.com",
            "subject_keyword": "日报",
            "attachment_pattern": "*.csv",
            "save_path": "downloads",
            "execution_type": "organize_file",
            "output_path": "organized",
            "command": "",
            "timeout_seconds": "600",
            "template_id": "",
        },
        follow_redirects=True,
    )

    rules = get_rules(tmp_config.database_path)
    assert response.status_code == 200
    assert rules[0].execution_type == "organize_file"
    assert rules[0].output_path == "organized"

    response = client.get(f"/rules/{rules[0].id}/edit")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "编辑规则" in body
    assert "整理数据" in body
    assert "输出地址" in body
    assert '<select class="form-select" name="template_id">' not in body
    assert 'name="template_id"' in body

    response = client.post(
        "/rules",
        data={
            "rule_id": str(rules[0].id),
            "name": "supplier-updated",
            "enabled": "on",
            "senders": "supplier@example.com",
            "subject_keyword": "日报",
            "attachment_pattern": "*.csv",
            "save_path": "downloads",
            "execution_type": "command",
            "output_path": "",
            "command": "python scripts/process.py",
            "timeout_seconds": "300",
            "template_id": "",
        },
        follow_redirects=True,
    )

    updated = get_rules(tmp_config.database_path)[0]
    assert response.status_code == 200
    assert updated.name == "supplier-updated"
    assert updated.execution_type == "command"
    assert updated.output_path is None
    assert updated.command == "python scripts/process.py"


def test_web_rule_page_runs_one_rule_as_background_task(tmp_config, monkeypatch) -> None:
    init_db(tmp_config.database_path)
    rule_id = create_rule(
        tmp_config.database_path,
        {
            "name": "single-rule",
            "enabled": True,
            "senders": ["supplier@example.com"],
            "subject_keyword": "日报",
            "attachment_pattern": "*.xlsx",
            "save_path": "downloads",
            "execution_type": "organize_file",
            "output_path": "organized",
            "command": "",
            "timeout_seconds": 600,
            "template_id": None,
        },
    )
    called = Event()
    captured: dict[str, int | None] = {}

    def fake_run_pipeline_once(config, *, rule_id=None) -> dict[str, int]:
        captured["rule_id"] = rule_id
        called.set()
        return {"success_count": 0, "failure_count": 0, "skipped_count": 0}

    monkeypatch.setattr("email_monitor.app.run_pipeline_once", fake_run_pipeline_once)
    app = create_app(tmp_config, start_scheduler=False)
    response = app.test_client().post(f"/rules/{rule_id}/run", follow_redirects=True)

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert called.wait(timeout=1)
    assert captured["rule_id"] == rule_id
    assert "任务列表" in body
    assert "single-rule" in body


def test_template_delete_requires_no_rule_usage(tmp_config, tmp_path: Path) -> None:
    init_db(tmp_config.database_path)
    template_file = tmp_path / "template.xlsx"
    pd.DataFrame({"保单号": ["13800138000"]}).to_excel(template_file, index=False)
    used_template_id = create_template(
        tmp_config.database_path,
        "used",
        template_file,
        parse_template(template_file),
    )
    unused_template_id = create_template(
        tmp_config.database_path,
        "unused",
        template_file,
        parse_template(template_file),
    )
    create_rule(
        tmp_config.database_path,
        {
            "name": "uses-template",
            "enabled": True,
            "senders": ["supplier@example.com"],
            "subject_keyword": "",
            "attachment_pattern": "*.xlsx",
            "save_path": "downloads",
            "execution_type": "organize_file",
            "output_path": "organized",
            "command": "",
            "timeout_seconds": 600,
            "template_id": used_template_id,
        },
    )
    app = create_app(tmp_config, start_scheduler=False)
    client = app.test_client()

    response = client.post(f"/templates/{used_template_id}/delete", follow_redirects=True)
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "模板正在被规则使用" in body
    assert get_template(tmp_config.database_path, used_template_id) is not None

    response = client.post(f"/templates/{unused_template_id}/delete", follow_redirects=True)

    assert response.status_code == 200
    assert get_template(tmp_config.database_path, unused_template_id) is None


def test_web_rule_page_accepts_template_file_path(tmp_config, tmp_path: Path) -> None:
    init_db(tmp_config.database_path)
    template_file = tmp_path / "template.xlsx"
    pd.DataFrame({"供应商名称": ["A"], "金额": [100]}).to_excel(template_file, index=False)
    app = create_app(tmp_config, start_scheduler=False)
    client = app.test_client()

    response = client.post(
        "/rules",
        data={
            "name": "supplier",
            "enabled": "on",
            "senders": "supplier@example.com",
            "subject_keyword": "日报",
            "attachment_pattern": "*.xlsx",
            "save_path": "downloads",
            "execution_type": "command",
            "output_path": "",
            "command": "python scripts/process.py",
            "timeout_seconds": "600",
            "template_id": str(template_file),
        },
        follow_redirects=True,
    )

    rule = get_rules(tmp_config.database_path)[0]
    template = get_template(tmp_config.database_path, rule.template_id)
    assert response.status_code == 200
    assert rule.template_id is not None
    assert template is not None
    assert template["file_path"] == str(template_file)


def test_web_rule_page_rejects_missing_template_file_without_500(tmp_config) -> None:
    init_db(tmp_config.database_path)
    app = create_app(tmp_config, start_scheduler=False)
    client = app.test_client()

    response = client.post(
        "/rules",
        data={
            "name": "supplier",
            "enabled": "on",
            "senders": "supplier@example.com",
            "subject_keyword": "日报",
            "attachment_pattern": "*.xlsx",
            "save_path": "downloads",
            "execution_type": "command",
            "output_path": "",
            "command": "python scripts/process.py",
            "timeout_seconds": "600",
            "template_id": "/missing/template.xlsx",
        },
        follow_redirects=True,
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "模板文件不存在" in body
    assert get_rules(tmp_config.database_path) == []
