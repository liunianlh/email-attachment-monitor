from __future__ import annotations

import sys
from pathlib import Path

import pytest

from email_monitor.command_runner import CommandExecutionError, run_command


def test_run_command_exposes_attachment_environment(tmp_path: Path) -> None:
    script = tmp_path / "script.py"
    marker = tmp_path / "marker.txt"
    attachment = tmp_path / "orders.xlsx"
    attachment.write_text("data", encoding="utf-8")
    script.write_text(
        "import os, pathlib\n"
        "pathlib.Path(os.environ['MARKER']).write_text("
        "os.environ['EMAIL_MONITOR_ATTACHMENT'], encoding='utf-8')\n",
        encoding="utf-8",
    )

    run_command(
        command=f"{sys.executable} {script}",
        attachment_path=attachment,
        save_dir=tmp_path,
        rule_name="supplier",
        timeout_seconds=5,
        extra_env={"MARKER": str(marker)},
    )

    assert marker.read_text(encoding="utf-8") == str(attachment)


def test_run_command_fails_on_nonzero_exit(tmp_path: Path) -> None:
    with pytest.raises(CommandExecutionError, match="exit code 7"):
        run_command(
            command=f"{sys.executable} -c 'import sys; sys.exit(7)'",
            attachment_path=tmp_path / "orders.xlsx",
            save_dir=tmp_path,
            rule_name="supplier",
            timeout_seconds=5,
        )
