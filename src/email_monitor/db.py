from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from email_monitor.models import Rule

_CST = timezone(timedelta(hours=8))


def _now_text() -> str:
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


def init_db(database_path: str | Path) -> None:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                senders TEXT NOT NULL,
                subject_keyword TEXT,
                attachment_pattern TEXT,
                save_path TEXT NOT NULL,
                execution_type TEXT NOT NULL DEFAULT 'command',
                output_path TEXT,
                command TEXT NOT NULL DEFAULT '',
                timeout_seconds INTEGER NOT NULL DEFAULT 600,
                template_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                spec_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                rule_name TEXT NOT NULL,
                mail_subject TEXT NOT NULL,
                sender TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                error_detail TEXT,
                output_detail TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS processed_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT NOT NULL,
                message_id TEXT NOT NULL,
                rule_id INTEGER,
                processed_at TEXT NOT NULL,
                UNIQUE(uid, message_id, rule_id)
            );
            """
        )
        _migrate_rules_schema(conn)
        _migrate_execution_logs_sender(conn)
        _migrate_execution_logs_deleted(conn)
        _migrate_execution_logs_output_detail(conn)


def connect(database_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(database_path))
    conn.row_factory = sqlite3.Row
    return conn


def create_rule(database_path: str | Path, values: dict[str, Any]) -> int:
    payload = _rule_payload(values)
    now = _now_text()
    with connect(database_path) as conn:
        cursor = conn.execute(
            """
                INSERT INTO rules (
                    name, enabled, senders, subject_keyword, attachment_pattern,
                    save_path, execution_type, output_path, command,
                    timeout_seconds, template_id, created_at, updated_at
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*payload, now, now),
        )
        return int(cursor.lastrowid)


def update_rule(database_path: str | Path, rule_id: int, values: dict[str, Any]) -> None:
    payload = _rule_payload(values)
    with connect(database_path) as conn:
        conn.execute(
            """
            UPDATE rules
            SET name = ?, enabled = ?, senders = ?, subject_keyword = ?,
                attachment_pattern = ?, save_path = ?, execution_type = ?,
                output_path = ?, command = ?, timeout_seconds = ?, template_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (*payload, _now_text(), rule_id),
        )


def delete_rule(database_path: str | Path, rule_id: int) -> None:
    with connect(database_path) as conn:
        conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))


def get_rules(database_path: str | Path) -> list[Rule]:
    with connect(database_path) as conn:
        rows = conn.execute("SELECT * FROM rules ORDER BY id").fetchall()
    return [_row_to_rule(row) for row in rows]


def get_rule(database_path: str | Path, rule_id: int) -> Rule | None:
    with connect(database_path) as conn:
        row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
    return _row_to_rule(row) if row else None


def create_template(
    database_path: str | Path,
    name: str,
    file_path: str | Path,
    spec: dict[str, Any],
) -> int:
    with connect(database_path) as conn:
        cursor = conn.execute(
            "INSERT INTO templates (name, file_path, spec_json, created_at) VALUES (?, ?, ?, ?)",
            (name, str(file_path), json.dumps(spec, ensure_ascii=False), _now_text()),
        )
        return int(cursor.lastrowid)


def get_templates(database_path: str | Path) -> list[dict[str, Any]]:
    with connect(database_path) as conn:
        rows = conn.execute("SELECT * FROM templates ORDER BY id DESC").fetchall()
    return [_template_row(row) for row in rows]


def get_template(database_path: str | Path, template_id: int | None) -> dict[str, Any] | None:
    if template_id is None:
        return None
    with connect(database_path) as conn:
        row = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
    return _template_row(row) if row else None


def count_rules_using_template(database_path: str | Path, template_id: int) -> int:
    with connect(database_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM rules WHERE template_id = ?",
            (template_id,),
        ).fetchone()
    return int(row["count"])


def delete_template(database_path: str | Path, template_id: int) -> None:
    with connect(database_path) as conn:
        conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))


def add_execution_log(
    database_path: str | Path,
    *,
    rule_name: str,
    mail_subject: str,
    status: str,
    error_detail: str,
    duration_ms: int,
    sender: str = "",
    output_detail: str = "",
    created_at: str | None = None,
) -> None:
    with connect(database_path) as conn:
        conn.execute(
            """
            INSERT INTO execution_logs (
                created_at, rule_name, mail_subject, sender, status, error_detail,
                output_detail, duration_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at or _now_text(),
                rule_name,
                mail_subject,
                sender,
                status,
                error_detail,
                output_detail,
                duration_ms,
            ),
        )


def get_execution_logs(
    database_path: str | Path,
    *,
    limit: int = 100,
    status: str | None = None,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM execution_logs WHERE deleted = 0"
    params: list[Any] = []
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with connect(database_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def mark_processed(
    database_path: str | Path,
    uid: str,
    message_id: str,
    rule_id: int | None,
) -> None:
    with connect(database_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO processed_messages (uid, message_id, rule_id, processed_at)
            VALUES (?, ?, ?, ?)
            """,
            (uid, message_id, rule_id, _now_text()),
        )


def was_processed(
    database_path: str | Path,
    uid: str,
    message_id: str,
    rule_id: int | None = None,
) -> bool:
    if rule_id is None:
        query = "SELECT 1 FROM processed_messages WHERE uid = ? OR message_id = ? LIMIT 1"
        params: tuple[Any, ...] = (uid, message_id)
    else:
        query = """
            SELECT 1 FROM processed_messages
            WHERE (uid = ? OR message_id = ?) AND rule_id = ?
            LIMIT 1
        """
        params = (uid, message_id, rule_id)
    with connect(database_path) as conn:
        return conn.execute(query, params).fetchone() is not None


def _rule_payload(values: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(values["name"]),
        1 if values.get("enabled", True) else 0,
        json.dumps(list(values.get("senders", [])), ensure_ascii=False),
        _empty_to_none(values.get("subject_keyword")),
        _empty_to_none(values.get("attachment_pattern")),
        str(values["save_path"]),
        _normalize_execution_type(values.get("execution_type")),
        _empty_to_none(values.get("output_path")),
        str(values.get("command") or ""),
        int(values.get("timeout_seconds", 600)),
        values.get("template_id"),
    )


def _row_to_rule(row: sqlite3.Row) -> Rule:
    return Rule(
        id=int(row["id"]),
        name=row["name"],
        enabled=bool(row["enabled"]),
        senders=json.loads(row["senders"]),
        subject_keyword=row["subject_keyword"],
        attachment_pattern=row["attachment_pattern"],
        save_path=row["save_path"],
        command=row["command"],
        timeout_seconds=int(row["timeout_seconds"]),
        template_id=row["template_id"],
        execution_type=row["execution_type"],
        output_path=row["output_path"],
    )


def _template_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "file_path": row["file_path"],
        "spec": json.loads(row["spec_json"]),
        "created_at": row["created_at"],
    }


def _empty_to_none(value: Any) -> Any:
    if value == "":
        return None
    return value


def _normalize_execution_type(value: Any) -> str:
    execution_type = str(value or "command")
    if execution_type not in {"command", "organize_file"}:
        raise ValueError(f"unsupported execution type: {execution_type}")
    return execution_type


def _migrate_rules_schema(conn: sqlite3.Connection) -> None:
    current_columns = _table_columns(conn, "rules")
    obsolete_columns = {
        "transform_config",
        "script_path",
        "api_endpoint",
        "api_method",
        "api_auth_secret_key",
    }
    if "command" in current_columns and not obsolete_columns.intersection(current_columns):
        if "execution_type" not in current_columns:
            conn.execute(
                "ALTER TABLE rules ADD COLUMN execution_type TEXT NOT NULL DEFAULT 'command'"
            )
        if "output_path" not in current_columns:
            conn.execute("ALTER TABLE rules ADD COLUMN output_path TEXT")
        return
    rows = [dict(row) for row in conn.execute("SELECT * FROM rules").fetchall()]
    conn.execute("ALTER TABLE rules RENAME TO rules_legacy")
    _create_current_rules_table(conn)
    for row in rows:
        command = row.get("command") or row.get("script_path") or ""
        conn.execute(
            """
            INSERT INTO rules (
                id, name, enabled, senders, subject_keyword, attachment_pattern,
                save_path, execution_type, output_path, command, timeout_seconds,
                template_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("id"),
                row.get("name"),
                row.get("enabled", 1),
                row.get("senders", "[]"),
                row.get("subject_keyword"),
                row.get("attachment_pattern"),
                row.get("save_path", "downloads"),
                row.get("execution_type", "command"),
                row.get("output_path"),
                command,
                row.get("timeout_seconds", 600),
                row.get("template_id"),
                row.get("created_at"),
                row.get("updated_at"),
            ),
        )
    conn.execute("DROP TABLE rules_legacy")


def _create_current_rules_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            senders TEXT NOT NULL,
            subject_keyword TEXT,
            attachment_pattern TEXT,
            save_path TEXT NOT NULL,
            execution_type TEXT NOT NULL DEFAULT 'command',
            output_path TEXT,
            command TEXT NOT NULL DEFAULT '',
            timeout_seconds INTEGER NOT NULL DEFAULT 600,
            template_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    return columns


def _migrate_execution_logs_sender(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "execution_logs")
    if "sender" not in columns:
        conn.execute("ALTER TABLE execution_logs ADD COLUMN sender TEXT NOT NULL DEFAULT ''")


def _migrate_execution_logs_deleted(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "execution_logs")
    if "deleted" not in columns:
        conn.execute("ALTER TABLE execution_logs ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")


def _migrate_execution_logs_output_detail(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "execution_logs")
    if "output_detail" not in columns:
        conn.execute("ALTER TABLE execution_logs ADD COLUMN output_detail TEXT NOT NULL DEFAULT ''")


def soft_delete_all_logs(database_path: str | Path) -> int:
    with connect(database_path) as conn:
        cursor = conn.execute("UPDATE execution_logs SET deleted = 1 WHERE deleted = 0")
        return cursor.rowcount
