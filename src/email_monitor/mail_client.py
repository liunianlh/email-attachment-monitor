from __future__ import annotations

import imaplib
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from email_monitor.config import ImapConfig


class MailLoginError(RuntimeError):
    pass


@dataclass
class ParsedAttachment:
    filename: str
    content: bytes


@dataclass
class ParsedMessage:
    uid: str
    message_id: str
    sender: str
    subject: str
    attachments: list[ParsedAttachment]
    raw: EmailMessage | None
    seen: bool = False


class ImapMailClient:
    def __init__(self, config: ImapConfig) -> None:
        self.config = config
        self.connection: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None

    def connect(self) -> None:
        if self.config.use_ssl:
            self.connection = imaplib.IMAP4_SSL(self.config.host, self.config.port)
        else:
            self.connection = imaplib.IMAP4(self.config.host, self.config.port)
        try:
            self.connection.login(self.config.username, self.config.password)
            self.connection.select(self.config.mailbox)
        except imaplib.IMAP4.error as exc:
            raise MailLoginError(_imap_error_message(exc)) from exc

    def fetch_unread_messages(self) -> list[ParsedMessage]:
        return [
            message
            for uid in self.list_message_uids("UNSEEN")
            if (message := self.fetch_message(uid)) is not None
        ]

    def list_message_uids(self, *criteria: str) -> list[str]:
        conn = self._conn()
        status, data = conn.uid("search", None, *(criteria or ("ALL",)))
        if status != "OK" or not data:
            return []
        return [uid.decode("ascii") for uid in data[0].split()]

    def fetch_message_header(self, uid: str) -> ParsedMessage | None:
        fetch_status, fetch_data = self._conn().uid(
            "fetch",
            uid,
            "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)] FLAGS)",
        )
        if fetch_status != "OK":
            return None
        raw_bytes = _first_message_bytes(fetch_data)
        if raw_bytes is None:
            return None
        return parse_message(uid, raw_bytes, seen=_has_seen_flag(fetch_data))

    def fetch_message(self, uid: str) -> ParsedMessage | None:
        fetch_status, fetch_data = self._conn().uid("fetch", uid, "(RFC822 FLAGS)")
        if fetch_status != "OK":
            return None
        raw_bytes = _first_message_bytes(fetch_data)
        if raw_bytes is None:
            return None
        return parse_message(uid, raw_bytes, seen=_has_seen_flag(fetch_data))

    def mark_seen(self, message: ParsedMessage) -> None:
        self._conn().uid("store", message.uid, "+FLAGS", "(\\Seen)")

    def close(self) -> None:
        if self.connection is None:
            return
        try:
            self.connection.close()
        except imaplib.IMAP4.error:
            pass
        self.connection.logout()
        self.connection = None

    def _conn(self) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
        if self.connection is None:
            raise RuntimeError("IMAP client is not connected")
        return self.connection


def parse_message(uid: str, raw_bytes: bytes, *, seen: bool = False) -> ParsedMessage:
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    attachments = []
    for part in message.iter_attachments():
        filename = part.get_filename()
        if not filename:
            continue
        content = part.get_payload(decode=True)
        if content is None:
            continue
        attachments.append(ParsedAttachment(filename=Path(filename).name, content=content))
    message_id = message.get("Message-ID") or uid
    return ParsedMessage(
        uid=uid,
        message_id=str(message_id),
        sender=str(message.get("From", "")),
        subject=str(message.get("Subject", "")),
        attachments=attachments,
        raw=message,
        seen=seen,
    )


def _first_message_bytes(fetch_data: list[Any]) -> bytes | None:
    for item in fetch_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def _has_seen_flag(fetch_data: list[Any]) -> bool:
    for item in fetch_data:
        if isinstance(item, tuple) and item and isinstance(item[0], bytes):
            flags_text = item[0].decode("utf-8", errors="replace")
            if "\\Seen" in flags_text:
                return True
    return False


def _imap_error_message(error: imaplib.IMAP4.error) -> str:
    if not error.args:
        return "IMAP 登录失败"
    first = error.args[0]
    if isinstance(first, bytes):
        detail = first.decode("utf-8", errors="replace")
    else:
        detail = str(first)
    return f"IMAP 登录失败: {detail}"
