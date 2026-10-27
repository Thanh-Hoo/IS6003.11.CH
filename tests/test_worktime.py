"""Giây ngày làm việc (T2–T6, chu kỳ 24 giờ) theo offset địa phương gốc hoặc theo UTC."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from jira_ad.worktime import WORKDAYS, parse_offset_minutes, work_seconds


def utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def test_parse_offset_minutes_reads_the_raw_suffix():
    assert parse_offset_minutes("2022-06-21T22:40:38.856-0700") == -420
    assert parse_offset_minutes("2022-01-05T10:00:00.000-0800") == -480
    assert parse_offset_minutes("2022-01-05T10:00:00.000+0530") == 330


def test_parse_offset_minutes_rejects_text_without_offset():
    with pytest.raises(ValueError, match="offset"):
        parse_offset_minutes("2022-01-05T10:00:00.000")


def test_friday_noon_to_monday_noon_local_counts_one_working_day():
    # 2022-06-17 là Thứ Sáu. 12:00 giờ −0700 = 19:00Z.
    start, end = utc("2022-06-17T19:00:00"), utc("2022-06-20T19:00:00")
    assert (end - start).total_seconds() == 259_200
    assert work_seconds(start, end, -420, WORKDAYS) == 86_400


def test_interval_inside_local_weekend_is_zero():
    # Thứ Bảy 10:00 → Chủ Nhật 20:00 giờ −0700.
    assert work_seconds(utc("2022-06-18T17:00:00"), utc("2022-06-20T03:00:00"), -420, WORKDAYS) == 0


def test_local_and_utc_weekday_boundary_differ():
    # Thứ Sáu 20:00 −0700 = Thứ Bảy 03:00Z: một giờ cuối Thứ Sáu chỉ là ngày làm việc theo giờ địa phương.
    start, end = utc("2022-06-18T03:00:00"), utc("2022-06-18T04:00:00")
    assert work_seconds(start, end, -420, WORKDAYS) == 3_600
    assert work_seconds(start, end, 0, WORKDAYS) == 0


def test_zero_and_reversed_intervals():
    t = utc("2022-06-15T10:00:00")
    assert work_seconds(t, t, -420, WORKDAYS) == 0
    with pytest.raises(ValueError, match="trước"):
        work_seconds(t, t - pd.Timedelta(seconds=1), -420, WORKDAYS)


def test_work_seconds_never_exceeds_calendar_and_is_additive():
    rng = np.random.default_rng(7)
    base = utc("2022-01-01T00:00:00")
    for _ in range(200):
        a, b, c = sorted(rng.integers(0, 40 * 86_400, size=3))
        ta, tb, tc = (base + pd.Timedelta(seconds=int(x)) for x in (a, b, c))
        offset = int(rng.choice([-480, -420, 0]))
        ab = work_seconds(ta, tb, offset, WORKDAYS)
        bc = work_seconds(tb, tc, offset, WORKDAYS)
        assert 0 <= ab <= (tb - ta).total_seconds()
        assert ab + bc == pytest.approx(work_seconds(ta, tc, offset, WORKDAYS))


def test_full_week_has_five_working_days():
    start = utc("2022-06-13T07:00:00")  # Thứ Hai 00:00 −0700
    assert work_seconds(start, start + pd.Timedelta(days=7), -420, WORKDAYS) == 5 * 86_400
