from datetime import datetime, timezone

import pytest

from scripts.schedule_gate import evaluate_schedule


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (datetime(2026, 8, 27, 21, 23, tzinfo=timezone.utc), False),
        (datetime(2026, 8, 27, 21, 24, tzinfo=timezone.utc), True),
        (datetime(2026, 8, 28, 4, 0, tzinfo=timezone.utc), True),
    ],
)
def test_evaluate_schedule_uses_configured_timezone(current: datetime, expected: bool) -> None:
    decision = evaluate_schedule("05:24", "Asia/Shanghai", now=current)

    assert decision.run_date == "2026-08-28"
    assert decision.due is expected


@pytest.mark.parametrize("value", ["5:24", "24:00", "05:60", "bad"])
def test_evaluate_schedule_rejects_invalid_time(value: str) -> None:
    with pytest.raises(ValueError, match="DOUYIN_SCHEDULE_TIME"):
        evaluate_schedule(value, "Asia/Shanghai")


def test_evaluate_schedule_rejects_invalid_timezone() -> None:
    with pytest.raises(ValueError, match="未知时区"):
        evaluate_schedule("05:24", "Invalid/Timezone")
