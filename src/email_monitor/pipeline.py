from __future__ import annotations

import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable

import pandas as pd

from email_monitor.config import AppConfig, validate_runtime_config
from email_monitor.command_runner import run_command
from email_monitor.db import (
    add_execution_log,
    get_rules,
    get_template,
    init_db,
    mark_processed,
    was_processed,
)
from email_monitor.mail_client import ImapMailClient, ParsedAttachment, ParsedMessage
from email_monitor.models import PipelineSummary, Rule
from email_monitor.organizer import organize_attachment_files
from email_monitor.rules import matches_rule
from email_monitor.validation import validate_dataframe


class Pipeline:
    def __init__(
        self,
        *,
        database_path: str | Path,
        data_dir: str | Path,
        rule_id: int | None = None,
        mark_success_callback: Callable[[ParsedMessage], None] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.data_dir = Path(data_dir)
        self.rule_id = rule_id
        self.mark_success_callback = mark_success_callback

    def process_messages(self, messages: list[ParsedMessage]) -> PipelineSummary:
        summary = PipelineSummary()
        rules = [
            rule
            for rule in get_rules(self.database_path)
            if self.rule_id is None or rule.id == self.rule_id
        ]
        organize_batches: dict[int | None, dict[str, object]] = {}
        for message in messages:
            attachment_names = [attachment.filename for attachment in message.attachments]
            matched_rules = [
                rule
                for rule in rules
                if matches_rule(
                    rule,
                    sender=message.sender,
                    subject=message.subject,
                    attachment_names=attachment_names,
                )
            ]
            if not matched_rules:
                summary.skipped_count += 1
                _log_skipped(
                    self.database_path,
                    rule_name="未匹配规则",
                    message=message,
                    reason="发件人/主题/附件未命中任何规则",
                )
                continue
            message_success = True
            message_processed = False
            for rule in matched_rules:
                if was_processed(self.database_path, message.uid, message.message_id, rule.id):
                    summary.skipped_count += 1
                    _log_skipped(
                        self.database_path,
                        rule_name=rule.name,
                        message=message,
                        reason="该邮件已成功处理过",
                    )
                    continue
                attachments = _matching_attachments(rule, message.attachments)
                if not attachments:
                    summary.skipped_count += 1
                    _log_skipped(
                        self.database_path,
                        rule_name=rule.name,
                        message=message,
                        reason="没有符合规则附件匹配条件的附件",
                    )
                    continue
                for attachment in attachments:
                    if rule.execution_type == "organize_file":
                        try:
                            attachment_path = self._save_attachment(rule, attachment)
                        except Exception as exc:
                            summary.failure_count += 1
                            message_success = False
                            _log_failure(
                                self.database_path,
                                rule,
                                message,
                                error=exc,
                                duration_ms=0,
                            )
                        else:
                            batch = organize_batches.setdefault(
                                rule.id,
                                {"rule": rule, "items": []},
                            )
                            batch["items"].append((message, attachment_path))
                        continue
                    try:
                        self._process_attachment(message, rule, attachment)
                    except Exception as exc:
                        summary.failure_count += 1
                        message_success = False
                        _log_failure(
                            self.database_path,
                            rule,
                            message,
                            error=exc,
                            duration_ms=0,
                        )
                    else:
                        summary.success_count += 1
                        message_processed = True
                        mark_processed(
                            self.database_path,
                            message.uid,
                            message.message_id,
                            rule.id,
                        )
            if message_success and message_processed and self.mark_success_callback:
                self.mark_success_callback(message)
        self._process_organize_batches(organize_batches, summary)
        return summary

    def _process_organize_batches(
        self,
        organize_batches: dict[int | None, dict[str, object]],
        summary: PipelineSummary,
    ) -> None:
        for batch in organize_batches.values():
            rule = batch["rule"]
            items = batch["items"]
            if not isinstance(rule, Rule) or not isinstance(items, list) or not items:
                continue
            started = time.monotonic()
            messages = [item[0] for item in items]
            attachment_paths = [item[1] for item in items]
            try:
                if not rule.output_path:
                    raise RuntimeError("整理文件规则需要填写输出地址")
                organize_attachment_files(attachment_paths, rule.output_path)
            except Exception as exc:
                for message, _attachment_path in items:
                    summary.failure_count += 1
                    _log_failure(
                        self.database_path,
                        rule,
                        message,
                        error=exc,
                        duration_ms=0,
                    )
                continue
            duration_ms = int((time.monotonic() - started) * 1000)
            marked_messages = set()
            for message, _attachment_path in items:
                summary.success_count += 1
                mark_processed(
                    self.database_path,
                    message.uid,
                    message.message_id,
                    rule.id,
                )
                _log_success(
                    self.database_path,
                    rule,
                    message,
                    duration_ms=duration_ms,
                )
                if self.mark_success_callback and message.uid not in marked_messages:
                    self.mark_success_callback(message)
                    marked_messages.add(message.uid)

    def _process_attachment(
        self,
        message: ParsedMessage,
        rule: Rule,
        attachment: ParsedAttachment,
    ) -> None:
        started = time.monotonic()
        attachment_path = self._save_attachment(rule, attachment)
        template = get_template(self.database_path, rule.template_id)
        if template and rule.execution_type == "command":
            validate_dataframe(_read_attachment_dataframe(attachment_path), template["spec"])
        if rule.execution_type == "command":
            run_command(
                command=rule.command,
                attachment_path=attachment_path,
                save_dir=attachment_path.parent,
                rule_name=rule.name,
                timeout_seconds=rule.timeout_seconds,
            )
        elif rule.execution_type == "organize_file":
            if not rule.output_path:
                raise RuntimeError("整理文件规则需要填写输出地址")
            organize_attachment_files([attachment_path], rule.output_path)
        else:
            raise RuntimeError(f"unsupported execution type: {rule.execution_type}")
        duration_ms = int((time.monotonic() - started) * 1000)
        _log_success(self.database_path, rule, message, duration_ms=duration_ms)

    def _save_attachment(self, rule: Rule, attachment: ParsedAttachment) -> Path:
        save_dir = _resolve_dir(rule.save_path)
        save_dir.mkdir(parents=True, exist_ok=True)
        attachment_path = save_dir / _safe_filename(attachment.filename)
        attachment_path.write_bytes(attachment.content)
        return attachment_path


def run_pipeline_once(config: AppConfig, *, rule_id: int | None = None) -> dict[str, int]:
    validate_runtime_config(config)
    init_db(config.database_path)
    client = ImapMailClient(config.imap)
    client.connect()
    try:
        rules = [
            rule
            for rule in get_rules(config.database_path)
            if rule_id is None or rule.id == rule_id
        ]
        messages: list[ParsedMessage] = []
        needs_attachment_only_match = any(
            rule.attachment_pattern and not rule.senders and not rule.subject_keyword
            for rule in rules
        )
        for uid in client.list_message_uids("ALL"):
            header = client.fetch_message_header(uid)
            if header is None:
                continue
            if not needs_attachment_only_match and not _has_unprocessed_header_match(
                config.database_path,
                rules,
                header,
            ):
                continue
            message = client.fetch_message(uid)
            if message is not None:
                messages.append(message)
        pipeline = Pipeline(
            database_path=config.database_path,
            data_dir=config.data_dir,
            rule_id=rule_id,
            mark_success_callback=client.mark_seen,
        )
        return pipeline.process_messages(messages).to_dict()
    finally:
        client.close()


def _has_unprocessed_header_match(
    database_path: Path,
    rules: list[Rule],
    message: ParsedMessage,
) -> bool:
    for rule in rules:
        if was_processed(database_path, message.uid, message.message_id, rule.id):
            continue
        if matches_rule(
            rule,
            sender=message.sender,
            subject=message.subject,
            attachment_names=[],
        ):
            return True
    return False


def _matching_attachments(rule: Rule, attachments: list[ParsedAttachment]) -> list[ParsedAttachment]:
    if not rule.attachment_pattern:
        return attachments
    matched = [
        attachment
        for attachment in attachments
        if fnmatch(attachment.filename, rule.attachment_pattern)
    ]
    return matched or attachments


def _safe_filename(filename: str) -> str:
    return Path(filename).name.replace("/", "_").replace("\\", "_")


def _resolve_dir(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def _extract_email_address(sender: str) -> str:
    from email.utils import parseaddr
    name, addr = parseaddr(sender)
    return addr or sender


def _read_attachment_dataframe(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    raise RuntimeError(f"unsupported attachment type: {path.suffix}")


def _log_success(
    database_path: Path,
    rule: Rule,
    message: ParsedMessage,
    *,
    duration_ms: int,
) -> None:
    add_execution_log(
        database_path,
        rule_name=rule.name,
        mail_subject=message.subject,
        sender=_extract_email_address(message.sender),
        status="success",
        error_detail="",
        duration_ms=duration_ms,
    )


def _log_failure(
    database_path: Path,
    rule: Rule,
    message: ParsedMessage,
    *,
    error: Exception,
    duration_ms: int,
) -> None:
    add_execution_log(
        database_path,
        rule_name=rule.name,
        mail_subject=message.subject,
        sender=_extract_email_address(message.sender),
        status="failure",
        error_detail=str(error),
        duration_ms=duration_ms,
    )


def _log_skipped(
    database_path: Path,
    *,
    rule_name: str,
    message: ParsedMessage,
    reason: str,
) -> None:
    sender_info = _extract_email_address(message.sender)
    add_execution_log(
        database_path,
        rule_name=rule_name,
        mail_subject=message.subject,
        sender=sender_info,
        status="skipped",
        error_detail=reason,
        duration_ms=0,
    )
