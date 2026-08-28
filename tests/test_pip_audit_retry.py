from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

from scripts.pip_audit_retry import is_transient_network_failure, run_audit


def _result(returncode: int, output: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=output)


def test_network_failure_is_retried() -> None:
    runner = MagicMock(
        side_effect=[
            _result(1, "requests.exceptions.ConnectionError: Connection reset by peer"),
            _result(0, "No known vulnerabilities found"),
        ]
    )
    sleeper = MagicMock()

    assert run_audit(runner=runner, sleeper=sleeper) == 0
    assert runner.call_count == 2
    sleeper.assert_called_once_with(10)


def test_vulnerability_failure_is_not_retried() -> None:
    runner = MagicMock(return_value=_result(1, "Found 1 known vulnerability"))
    sleeper = MagicMock()

    assert run_audit(runner=runner, sleeper=sleeper) == 1
    runner.assert_called_once()
    sleeper.assert_not_called()


def test_network_failure_stops_after_limit() -> None:
    runner = MagicMock(return_value=_result(1, "ReadTimeout"))
    sleeper = MagicMock()

    assert run_audit(runner=runner, sleeper=sleeper) == 1
    assert runner.call_count == 3
    assert [call.args[0] for call in sleeper.call_args_list] == [10, 20]


def test_network_error_detection_is_case_insensitive() -> None:
    assert is_transient_network_failure("SSLERROR") is True
    assert is_transient_network_failure("Found 1 known vulnerability") is False
