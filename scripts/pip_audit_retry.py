from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NETWORK_ERROR_MARKERS = (
    "connection reset",
    "connectionerror",
    "connecttimeout",
    "readtimeout",
    "remotedisconnected",
    "temporary failure in name resolution",
    "name or service not known",
    "network is unreachable",
    "sslerror",
    "status code 429",
    "status code 502",
    "status code 503",
    "status code 504",
)


def is_transient_network_failure(output: str) -> bool:
    normalized = output.casefold()
    return any(marker in normalized for marker in NETWORK_ERROR_MARKERS)


def run_audit(
    *,
    attempts: int = 3,
    retry_delay_seconds: int = 10,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    command = [sys.executable, "-m", "pip_audit", "-r", "requirements.txt"]
    for attempt in range(1, attempts + 1):
        result = runner(
            command,
            cwd=PROJECT_ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output = result.stdout or ""
        print(output, end="" if output.endswith("\n") or not output else "\n")
        if result.returncode == 0:
            return 0
        if not is_transient_network_failure(output) or attempt == attempts:
            return result.returncode
        delay = retry_delay_seconds * attempt
        print(f"pip-audit network failure; retrying in {delay}s ({attempt}/{attempts})")
        sleeper(delay)
    return 1


if __name__ == "__main__":
    raise SystemExit(run_audit())
