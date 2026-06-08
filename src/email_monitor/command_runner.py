from __future__ import annotations

import os
import subprocess
from pathlib import Path


class CommandExecutionError(RuntimeError):
    pass


def run_command(
    *,
    command: str,
    attachment_path: str | Path,
    save_dir: str | Path,
    rule_name: str,
    timeout_seconds: int,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "EMAIL_MONITOR_ATTACHMENT": str(Path(attachment_path)),
            "EMAIL_MONITOR_SAVE_DIR": str(Path(save_dir)),
            "EMAIL_MONITOR_RULE_NAME": rule_name,
        }
    )
    if extra_env:
        env.update(extra_env)
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandExecutionError(f"command timed out after {timeout_seconds}s") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise CommandExecutionError(
            f"command failed with exit code {completed.returncode}: {detail}"
        )
    return completed
