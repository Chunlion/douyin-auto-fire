from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class ScheduleDecision:
    run_date: str
    due: bool
    local_time: str


def evaluate_schedule(
    schedule_time: str,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> ScheduleDecision:
    match = re.fullmatch(r"(\d{2}):(\d{2})", schedule_time)
    if match is None:
        raise ValueError("DOUYIN_SCHEDULE_TIME 必须使用 HH:MM 格式")
    hour, minute = (int(value) for value in match.groups())
    if hour > 23 or minute > 59:
        raise ValueError("DOUYIN_SCHEDULE_TIME 必须是有效时间")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"未知时区: {timezone_name}") from exc

    local_now = (now or datetime.now(timezone)).astimezone(timezone)
    return ScheduleDecision(
        run_date=local_now.date().isoformat(),
        due=local_now.time().replace(tzinfo=None) >= time(hour, minute),
        local_time=local_now.strftime("%H:%M"),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--time", required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--output", default=os.getenv("GITHUB_OUTPUT"))
    args = parser.parse_args()
    try:
        decision = evaluate_schedule(args.time, args.timezone)
    except ValueError as exc:
        parser.error(str(exc))

    if not args.output:
        parser.error("缺少 GitHub Actions 输出文件路径")
    with Path(args.output).open("a", encoding="utf-8") as output:
        output.write(f"run_date={decision.run_date}\n")
        output.write(f"due={str(decision.due).lower()}\n")
    print(
        f"当前时间 {decision.local_time}，计划时间 {args.time}，"
        f"状态: {'到点' if decision.due else '等待'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
