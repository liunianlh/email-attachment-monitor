from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Rule:
    id: int | None
    name: str
    enabled: bool
    senders: list[str]
    subject_keyword: str | None
    attachment_pattern: str | None
    save_path: str
    command: str
    timeout_seconds: int
    template_id: int | None
    execution_type: str = "command"
    output_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "senders": self.senders,
            "subject_keyword": self.subject_keyword,
            "attachment_pattern": self.attachment_pattern,
            "save_path": self.save_path,
            "command": self.command,
            "timeout_seconds": self.timeout_seconds,
            "template_id": self.template_id,
            "execution_type": self.execution_type,
            "output_path": self.output_path,
        }


@dataclass
class PipelineSummary:
    success_count: int = 0
    failure_count: int = 0
    skipped_count: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "skipped_count": self.skipped_count,
        }
