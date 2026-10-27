"""Status log (giai đoạn 2): mỗi lượt trạng thái của một issue, dwell theo lịch và ngày làm việc.

Dựng từ bảng event đã chuẩn hóa và core view **có sẵn** của giai đoạn 1 (không chuẩn hóa lại). Một
lượt bắt đầu ở event đổi trạng thái (hoặc CREATE, lượt giả `__CREATED__`) và kết thúc ở event đổi
trạng thái kế tiếp; trạng thái kết thúc cuối cùng không có dwell. Jira chỉ ghi thời điểm đổi trạng
thái, nên dwell là thời gian *nằm ở* trạng thái, không phải thời gian làm việc thật.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np
import pandas as pd

from jira_ad.config import RunConfig, load_config
from jira_ad.data import load_raw_events
from jira_ad.preprocess import build_core_view, normalize_events
from jira_ad.process_config import ProcessConfig
from jira_ad.types import Trace
from jira_ad.worktime import parse_offset_minutes, work_seconds

CREATED = "__CREATED__"
NO_BURST = -1


@dataclass(frozen=True)
class CohortData:
    cohort: str
    base: RunConfig
    events: pd.DataFrame  # event chuẩn hóa, chỉ các event thuộc core view
    traces: list[Trace]
    events_full: pd.DataFrame  # mọi event chuẩn hóa (full view), để mô tả Work System (vd tỉ lệ bot)


def base_config_for(cfg: ProcessConfig, cohort: str) -> RunConfig:
    """Cấu hình giai đoạn 1 (chỉ đọc) với cohort được chọn."""
    base = load_config(cfg.resolve(cfg.paths.base_config))
    return dataclasses.replace(base, data=dataclasses.replace(base.data, cohort=cohort))


def load_cohort(cfg: ProcessConfig, cohort: str) -> CohortData:
    """Loader + chuẩn hóa action + core view của giai đoạn 1; giữ `timestamp_raw` để lấy offset."""
    base = base_config_for(cfg, cohort)
    events = normalize_events(load_raw_events(base.data, base.project_root), base.preprocess)
    traces = build_core_view(events, base.preprocess).traces
    core_ids = {e for t in traces for e in t.event_ids}
    core = events[events["event_id"].isin(core_ids)].reset_index(drop=True)
    return CohortData(cohort, base, core, traces, events)


def _state_class(state: str, cfg: ProcessConfig) -> str:
    st = cfg.states
    if state == CREATED:
        return "created"
    if state in st.terminal:
        return "terminal"
    if state in st.work:
        return "work"
    if state in st.wait:
        return "wait"
    return "other"


def build_status_log(events: pd.DataFrame, traces: list[Trace], cfg: ProcessConfig) -> pd.DataFrame:
    """Một dòng mỗi lượt trạng thái, theo thứ tự event của core view."""
    by_id = events.set_index("event_id")
    order = {s: i for i, s in enumerate(cfg.states.order)}
    terminal = set(cfg.states.terminal)
    workdays = cfg.calendar.workdays
    threshold = cfg.backfill.threshold_seconds
    rows = []
    for trace in traces:
        ev = by_id.loc[list(trace.event_ids)]
        first = ev.iloc[0]
        opened = [(CREATED, first["timestamp_utc"], first["role"], first["timestamp_raw"])]
        for _, e in ev.iloc[1:].iterrows():
            if bool(e["has_status_update"]):
                opened.append((e["status_value"], e["timestamp_utc"], e["role"], e["timestamp_raw"]))
        burst = NO_BURST
        n_bursts = 0
        case_rows = []
        for i, (state, t_enter, role, raw) in enumerate(opened):
            last = i == len(opened) - 1
            t_exit = pd.NaT if last else opened[i + 1][1]
            exit_role = None if last else opened[i + 1][2]
            offset = parse_offset_minutes(raw)
            if last:
                cal = local = utc = np.nan
            else:
                cal = (t_exit - t_enter).total_seconds()
                local = work_seconds(t_enter, t_exit, offset, workdays)
                utc = work_seconds(t_enter, t_exit, 0, workdays)
            prev = opened[i - 1][0] if i > 0 else None
            backfill_entry = (i >= 2 and (t_enter - opened[i - 1][1]).total_seconds() < threshold)
            case_rows.append({
                "case_id": trace.trace_id, "terminal_status": trace.terminal_status,
                "visit_index": i, "state": state, "state_class": _state_class(state, cfg),
                "t_enter": t_enter, "t_exit": t_exit, "offset_min": offset,
                "dwell_cal_s": cal, "dwell_work_local_s": local, "dwell_work_utc_s": utc,
                "enter_role": role, "exit_role": exit_role,
                "is_backfill_entry": backfill_entry,
                "is_back": (prev in order and state in order and order[state] < order[prev]),
                "is_reopen": prev in terminal,
            })
        # Đợt bù: lượt mở bởi một lần đổi bù thuộc cùng đợt với lượt ngay trước nó (nếu là lượt trạng thái).
        for i, row in enumerate(case_rows):
            if row["is_backfill_entry"]:
                if case_rows[i - 1]["burst_id"] == NO_BURST:
                    burst = n_bursts
                    n_bursts += 1
                    case_rows[i - 1]["burst_id"] = burst
                row["burst_id"] = case_rows[i - 1]["burst_id"]
            else:
                row["burst_id"] = NO_BURST
        rows.extend(case_rows)
    log = pd.DataFrame(rows)
    primary = "dwell_work_local_s" if cfg.calendar.primary == "local" else "dwell_work_utc_s"
    log["dwell_work_s"] = log[primary]
    return log


def case_table(status_log: pd.DataFrame, traces: list[Trace]) -> pd.DataFrame:
    """Một dòng mỗi ca: CT theo ba đồng hồ, biến thể trạng thái, số lần lùi/mở lại/đổi bù."""
    n_events = {t.trace_id: len(t) for t in traces}
    rows = []
    for case_id, v in status_log.groupby("case_id", sort=False):
        states = list(v["state"].iloc[1:])
        rows.append({
            "case_id": case_id, "terminal_status": v["terminal_status"].iloc[0],
            "n_events": n_events[case_id], "t_create": v["t_enter"].iloc[0],
            "t_end": v["t_enter"].iloc[-1], "offset_min_create": int(v["offset_min"].iloc[0]),
            "ct_cal_s": float(v["dwell_cal_s"].sum()), "ct_work_s": float(v["dwell_work_s"].sum()),
            "ct_work_local_s": float(v["dwell_work_local_s"].sum()),
            "ct_work_utc_s": float(v["dwell_work_utc_s"].sum()),
            "n_status_changes": len(states), "variant": " > ".join(states),
            "reached_in_progress": "In Progress" in states,
            "n_back": int(v["is_back"].sum()), "n_reopen": int(v["is_reopen"].sum()),
            "n_backfill": int(v["is_backfill_entry"].sum()),
        })
    return pd.DataFrame(rows)
