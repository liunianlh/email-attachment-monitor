from __future__ import annotations

from pathlib import Path

import pytest

from email_monitor.config import AppConfig, ImapConfig
from email_monitor.db import init_db


@pytest.fixture
def tmp_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        database_path=tmp_path / "email_monitor.sqlite3",
        data_dir=tmp_path / "data",
        imap=ImapConfig(
            host="imap.qiye.163.com",
            port=993,
            username="user@example.com",
            password="secret",
        ),
        schedule_time="17:00",
    )


@pytest.fixture
def db_path(tmp_config: AppConfig) -> Path:
    init_db(tmp_config.database_path)
    return tmp_config.database_path

