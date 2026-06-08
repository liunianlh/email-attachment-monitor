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
    if normalized_sender not in configured_senders:
        return False
    if rule.subject_keyword and rule.subject_keyword not in subject:
        return False
    if rule.attachment_pattern:
        return any(fnmatch(name, rule.attachment_pattern) for name in attachment_names)
    return True
