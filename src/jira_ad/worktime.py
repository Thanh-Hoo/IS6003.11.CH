"""Thời gian ngày làm việc: giây thuộc T2–T6 (chu kỳ 24 giờ) theo giờ địa phương hoặc UTC.

Giờ địa phương lấy từ offset gốc trong `timestamp_raw` (vd `-0700`), không đoán múi giờ. Không có
giờ hành chính hay lịch nghỉ lễ (giả định dữ liệu của giai đoạn 2, Ruling 70).
"""

from __future__ import annotations

import re
from datetime import timedelta

import pandas as pd

WORKDAYS: tuple[int, ...] = (0, 1, 2, 3, 4)  # Thứ Hai = 0 theo `datetime.weekday()`
DAY_SECONDS = 86_400
_OFFSET = re.compile(r"([+-])(\d{2}):?(\d{2})$")


def parse_offset_minutes(timestamp_raw: str) -> int:
    """Offset (phút) ở cuối chuỗi timestamp gốc: `-0700` → -420."""
    match = _OFFSET.search(str(timestamp_raw).strip())
    if match is None:
        raise ValueError(f"Timestamp {timestamp_raw!r} không có offset múi giờ ở cuối")
    sign = -1 if match.group(1) == "-" else 1
    return sign * (int(match.group(2)) * 60 + int(match.group(3)))


def work_seconds(
    start_utc: pd.Timestamp, end_utc: pd.Timestamp, offset_minutes: int, workdays: tuple[int, ...]
) -> float:
    """Số giây của [start, end) rơi vào các ngày `workdays` khi nhìn theo giờ UTC + offset."""
    if end_utc < start_utc:
        raise ValueError(f"end {end_utc} đứng trước start {start_utc}")
    shift = timedelta(minutes=offset_minutes)
    start = (pd.Timestamp(start_utc).tz_convert("UTC") + shift).tz_localize(None)
    end = (pd.Timestamp(end_utc).tz_convert("UTC") + shift).tz_localize(None)
    total = 0.0
    day = start.normalize()
    while day < end:
        nxt = day + pd.Timedelta(days=1)
        if day.weekday() in workdays:
            total += (min(end, nxt) - max(start, day)).total_seconds()
        day = nxt
    return total
