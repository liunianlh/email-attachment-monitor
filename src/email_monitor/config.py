from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    pass


@dataclass
class ImapConfig:
    host: str
    port: int
    username: str
    password: str
    mailbox: str = "INBOX"
    use_ssl: bool = True


@dataclass
class AppConfig:
    database_path: Path
    data_dir: Path
    imap: ImapConfig
    schedule_time: str = "17:00"
    timezone: str = "Asia/Shanghai"
    web_host: str = "127.0.0.1"
    web_port: int = 5000
    config_path: Path = Path("config.local.json")


DEFAULT_CONFIG: dict[str, Any] = {
    "database_path": "data/email_monitor.sqlite3",
    "data_dir": "data",
    "imap": {
        "host": "imap.qiye.163.com",
        "port": 993,
        "username": "",
        "password": "",
        "mailbox": "INBOX",
        "use_ssl": True,
    },
    "schedule_time": "17:00",
    "timezone": "Asia/Shanghai",
    "web": {"host": "127.0.0.1", "port": 5000},
}


def load_config(path: str | Path = "config.local.json") -> AppConfig:
    config_path = _effective_config_path(Path(path))
    base_dir = config_path.parent if config_path.parent != Path("") else Path.cwd()
    data = _deep_merge(DEFAULT_CONFIG, _read_json(config_path))
    imap_data = data["imap"]
    web_data = data.get("web", {})
    return AppConfig(
        database_path=_resolve_path(data["database_path"], base_dir),
        data_dir=_resolve_path(data["data_dir"], base_dir),
        imap=ImapConfig(
            host=str(imap_data.get("host", "")),
            port=int(imap_data.get("port", 993)),
            username=str(imap_data.get("username", "")),
            password=str(imap_data.get("password", "")),
            mailbox=str(imap_data.get("mailbox", "INBOX")),
            use_ssl=bool(imap_data.get("use_ssl", True)),
        ),
        schedule_time=str(data.get("schedule_time", "17:00")),
        timezone=str(data.get("timezone", "Asia/Shanghai")),
        web_host=str(web_data.get("host", "127.0.0.1")),
        web_port=int(web_data.get("port", 5000)),
        config_path=config_path,
    )


def validate_runtime_config(config: AppConfig) -> None:
    errors = _runtime_config_errors(config)
    if errors:
        raise ConfigError("；".join(errors))


def describe_config_health(config: AppConfig) -> dict[str, Any]:
    errors = _runtime_config_errors(config)
    return {
        "ok": not errors,
        "message": "配置正常" if not errors else "；".join(errors),
        "imap_host": config.imap.host,
        "imap_port": config.imap.port,
        "imap_username": config.imap.username or "未配置",
        "imap_mailbox": config.imap.mailbox,
        "imap_use_ssl": config.imap.use_ssl,
        "config_path": str(_writable_config_path(config)),
    }


def save_email_config(
    config: AppConfig,
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    mailbox: str,
    use_ssl: bool,
) -> Path:
    target_path = _writable_config_path(config)
    source_path = config.config_path
    source_data = _deep_merge(DEFAULT_CONFIG, _read_json(source_path))
    existing_password = config.imap.password
    next_password = password if password else existing_password
    source_data["imap"] = {
        "host": host,
        "port": port,
        "username": username,
        "password": next_password,
        "mailbox": mailbox,
        "use_ssl": use_ssl,
    }
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(source_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    config.imap = ImapConfig(
        host=host,
        port=port,
        username=username,
        password=next_password,
        mailbox=mailbox,
        use_ssl=use_ssl,
    )
    config.config_path = target_path
    return target_path


def _runtime_config_errors(config: AppConfig) -> list[str]:
    errors: list[str] = []
    username = config.imap.username.strip()
    password = config.imap.password.strip()
    placeholder_values = {
        "",
        "your-email@example.com",
        "your-email-password-or-app-password",
    }
    if username in placeholder_values or password in placeholder_values:
        errors.append("请先配置真实的邮箱账号和密码，建议复制 config.example.json 为 config.local.json 后修改")
    if not config.imap.host.strip():
        errors.append("请配置 IMAP 主机")
    return errors


def _writable_config_path(config: AppConfig) -> Path:
    if config.config_path.name == "config.example.json":
        return config.config_path.with_name("config.local.json")
    return config.config_path


def _effective_config_path(path: Path) -> Path:
    if path.name == "config.example.json":
        local_path = path.with_name("config.local.json")
        if local_path.exists():
            return local_path
    return path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base_dir / path)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
