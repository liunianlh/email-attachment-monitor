from __future__ import annotations

import imaplib
import time
from pathlib import Path

import pytest

from email_monitor.app import create_app
from email_monitor.config import (
    AppConfig,
    ConfigError,
    ImapConfig,
    load_config,
    validate_runtime_config,
)
from email_monitor.db import init_db
from email_monitor.mail_client import ImapMailClient, MailLoginError


def test_validate_runtime_config_rejects_placeholder_credentials(tmp_path: Path) -> None:
    config = AppConfig(
        database_path=tmp_path / "email_monitor.sqlite3",
        data_dir=tmp_path / "data",
        imap=ImapConfig(
            host="imap.qiye.163.com",
            port=993,
            username="your-email@example.com",
            password="your-email-password-or-app-password",
        ),
    )

    with pytest.raises(ConfigError, match="请先配置真实的邮箱账号和密码"):
        validate_runtime_config(config)


def test_manual_run_shows_friendly_placeholder_config_error(tmp_path: Path) -> None:
    config = AppConfig(
        database_path=tmp_path / "email_monitor.sqlite3",
        data_dir=tmp_path / "data",
        imap=ImapConfig(
            host="imap.qiye.163.com",
            port=993,
            username="your-email@example.com",
            password="your-email-password-or-app-password",
        ),
    )
    init_db(config.database_path)
    app = create_app(config, start_scheduler=False)
    client = app.test_client()

    response = client.post("/run-once", follow_redirects=True)

    body = response.get_data(as_text=True)
    assert "任务列表" in body
    assert "手动邮件巡检" in body

    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        body = client.get("/tasks").get_data(as_text=True)
        if "请先配置真实的邮箱账号和密码" in body:
            break
        time.sleep(0.01)
    assert "失败" in body
    assert "请先配置真实的邮箱账号和密码" in body
    assert "config.local.json" in body


def test_status_page_shows_email_config_health(tmp_path: Path) -> None:
    config = AppConfig(
        database_path=tmp_path / "email_monitor.sqlite3",
        data_dir=tmp_path / "data",
        imap=ImapConfig(
            host="imap.qiye.163.com",
            port=993,
            username="your-email@example.com",
            password="your-email-password-or-app-password",
        ),
    )
    init_db(config.database_path)
    app = create_app(config, start_scheduler=False)

    response = app.test_client().get("/status")

    body = response.get_data(as_text=True)
    assert "邮箱配置健康" in body
    assert "imap.qiye.163.com" in body
    assert "your-email@example.com" in body
    assert "请先配置真实的邮箱账号和密码" in body


def test_status_page_saves_email_config_to_local_file(tmp_path: Path) -> None:
    example_config = tmp_path / "config.example.json"
    example_config.write_text(
        """
        {
          "database_path": "data/email_monitor.sqlite3",
          "data_dir": "data",
          "imap": {
            "host": "imap.qiye.163.com",
            "port": 993,
            "username": "your-email@example.com",
            "password": "your-email-password-or-app-password",
            "mailbox": "INBOX",
            "use_ssl": true
          },
          "schedule_time": "17:00",
          "timezone": "Asia/Shanghai",
          "web": {"host": "127.0.0.1", "port": 5000}
        }
        """,
        encoding="utf-8",
    )
    config = load_config(example_config)
    init_db(config.database_path)
    app = create_app(config, start_scheduler=False)

    response = app.test_client().post(
        "/config/email",
        data={
            "imap_host": "imap.example-corp.com",
            "imap_port": "993",
            "imap_username": "daily@example-corp.com",
            "imap_password": "mail-secret",
            "imap_mailbox": "Reports",
            "imap_use_ssl": "on",
        },
        follow_redirects=True,
    )

    local_config = tmp_path / "config.local.json"
    body = response.get_data(as_text=True)
    saved_config = load_config(local_config)
    assert response.status_code == 200
    assert local_config.exists()
    assert "邮箱配置已保存" in body
    assert "daily@example-corp.com" in body
    assert "配置正常" in body
    assert saved_config.imap.host == "imap.example-corp.com"
    assert saved_config.imap.port == 993
    assert saved_config.imap.username == "daily@example-corp.com"
    assert saved_config.imap.password == "mail-secret"
    assert saved_config.imap.mailbox == "Reports"
    assert config.config_path == local_config


def test_load_config_prefers_local_file_next_to_example(tmp_path: Path) -> None:
    example_config = tmp_path / "config.example.json"
    local_config = tmp_path / "config.local.json"
    example_config.write_text(
        """
        {
          "imap": {
            "host": "imap.qiye.163.com",
            "port": 993,
            "username": "your-email@example.com",
            "password": "your-email-password-or-app-password"
          }
        }
        """,
        encoding="utf-8",
    )
    local_config.write_text(
        """
        {
          "imap": {
            "host": "imap.qiye.163.com",
            "port": 993,
            "username": "liuhe@ehealthnow.cn",
            "password": "saved-secret"
          }
        }
        """,
        encoding="utf-8",
    )

    config = load_config(example_config)

    assert config.config_path == local_config
    assert config.imap.username == "liuhe@ehealthnow.cn"
    assert config.imap.password == "saved-secret"


def test_fetch_unread_messages_searches_unseen_messages() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        def uid(self, *args: object) -> tuple[str, list[bytes]]:
            self.calls.append(args)
            return "OK", [b""]

    client = ImapMailClient(
        ImapConfig(
            host="imap.qiye.163.com",
            port=993,
            username="user@example.com",
            password="secret",
        )
    )
    connection = FakeConnection()
    client.connection = connection  # type: ignore[assignment]

    assert client.fetch_unread_messages() == []
    assert connection.calls == [("search", None, "UNSEEN")]


def test_imap_login_error_decodes_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeImap:
        def __init__(self, host: str, port: int) -> None:
            self.host = host
            self.port = port

        def login(self, username: str, password: str) -> None:
            raise imaplib.IMAP4.error(b"ERR.LOGIN.DOMAINNOTEXIST")

    monkeypatch.setattr("email_monitor.mail_client.imaplib.IMAP4_SSL", FakeImap)
    client = ImapMailClient(
        ImapConfig(
            host="imap.qiye.163.com",
            port=993,
            username="bad@example.com",
            password="secret",
        )
    )

    with pytest.raises(MailLoginError, match="ERR.LOGIN.DOMAINNOTEXIST") as exc_info:
        client.connect()

    assert "b'ERR" not in str(exc_info.value)
