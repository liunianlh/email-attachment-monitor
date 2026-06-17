from __future__ import annotations

from email.utils import parseaddr
from fnmatch import fnmatch

from email_monitor.models import Rule


def matches_rule(
    rule: Rule,
    *,
    sender: str,
    subject: str,
    attachment_names: list[str],
) -> bool:
    if not rule.enabled:
        return False
    normalized_sender = parseaddr(sender)[1].lower() or sender.lower()
    configured_senders = {item.lower() for item in rule.senders}
    conditions = []
    if configured_senders:
        conditions.append(normalized_sender in configured_senders)
    if rule.subject_keyword:
        conditions.append(rule.subject_keyword in subject)
    if rule.attachment_pattern:
        conditions.append(any(fnmatch(name, rule.attachment_pattern) for name in attachment_names))
    return any(conditions)
