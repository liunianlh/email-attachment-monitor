from __future__ import annotations

from email_monitor.models import Rule
from email_monitor.rules import matches_rule


def test_rule_matches_when_any_configured_condition_matches() -> None:
    rule = Rule(
        id=1,
        name="supplier",
        enabled=True,
        senders=["supplier@example.com", "backup@example.com"],
        subject_keyword="日报",
        attachment_pattern="*.xlsx",
        save_path="./data/supplier",
        command="python scripts/supplier.py",
        timeout_seconds=600,
        template_id=None,
    )

    assert matches_rule(
        rule,
        sender="Supplier <supplier@example.com>",
        subject="周报",
        attachment_names=["orders.xls"],
    )
    assert matches_rule(
        rule,
        sender="other@example.com",
        subject="6月8日 日报",
        attachment_names=["orders.xls"],
    )
    assert matches_rule(
        rule,
        sender="other@example.com",
        subject="周报",
        attachment_names=["orders.xlsx"],
    )


def test_rule_rejects_disabled_or_unmatched_messages() -> None:
    rule = Rule(
        id=1,
        name="supplier",
        enabled=False,
        senders=["supplier@example.com"],
        subject_keyword="日报",
        attachment_pattern="*.csv",
        save_path="./data/supplier",
        command="python scripts/supplier.py",
        timeout_seconds=600,
        template_id=None,
    )

    assert not matches_rule(
        rule,
        sender="supplier@example.com",
        subject="日报",
        attachment_names=["orders.csv"],
    )

    rule.enabled = True
    assert not matches_rule(
        rule,
        sender="other@example.com",
        subject="周报",
        attachment_names=["orders.xlsx"],
    )
