"""Đọc event log Jira thô: tìm file, kiểm tra schema, parse timestamp, fingerprint, audit.

Dữ liệu gốc chỉ được mở để đọc. Mỗi lần gọi `load_raw_events` chỉ đọc đúng một cohort (bug hoặc
story); hai cohort không bao giờ bị gộp vào một bảng (spec §2).
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from jira_ad.config import DataConfig, RunConfig

RAW_COLUMNS = ("issueKey", "timestamp", "role", "action")
RAW_EVENT_COLUMNS = [
    "event_id", "case_id", "issue_key", "issue_type", "timestamp_utc", "timestamp_raw",
    "source_file", "source_row", "raw_action", "role",
]
MAX_PROBLEMS_IN_MESSAGE = 20

_TS_WITH_ZONE = r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})"
_TS_WITHOUT_ZONE = r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?"
_ZONE_SUFFIX = r"(Z|[+-]\d{2}:?\d{2})$"


class DataError(Exception):
    """Gốc của mọi lỗi dữ liệu đầu vào."""


class SchemaError(DataError):
    """Header CSV không đúng schema issueKey, timestamp, role, action."""


class InputNotFoundError(DataError):
    """Không tìm thấy file input cấu hình."""


class AmbiguousInputError(DataError):
    """Nhiều file cùng tên; phải cấu hình đường dẫn rõ ràng, không tự chọn file đầu tiên."""


class RowDataError(DataError):
    """Một số dòng dữ liệu không đọc được; `problems` liệt kê source_row và nguyên nhân."""

    def __init__(self, source: str, problems: list[dict[str, Any]]) -> None:
        self.problems = problems
        shown = [
            f"  source_row={p['source_row']}: {p['cause']}: {p['value']!r}"
            for p in problems[:MAX_PROBLEMS_IN_MESSAGE]
        ]
        extra = len(problems) - len(shown)
        if extra > 0:
            shown.append(f"  ... và {extra} dòng khác")
        super().__init__(f"{source}: {len(problems)} dòng không đọc được\n" + "\n".join(shown))


def _relative(path: Path, project_root: Path) -> str:
    return Path(os.path.relpath(path, project_root)).as_posix()


def find_input_file(data_cfg: DataConfig, project_root: Path, cohort: str) -> Path:
    """Tìm file CSV của `cohort`; báo lỗi khi thiếu hoặc có nhiều ứng viên cùng tên."""
    if cohort not in data_cfg.files:
        raise InputNotFoundError(f"cohort {cohort!r} không có trong data.files")
    base = project_root / data_cfg.root
    if not base.is_dir():
        raise InputNotFoundError(f"Thư mục dữ liệu không tồn tại: {data_cfg.root}")
    name = data_cfg.files[cohort]
    if "/" in name:  # đường dẫn tường minh dưới data.root: không tìm kiếm
        explicit = base / name
        if not explicit.is_file():
            raise InputNotFoundError(f"Không tìm thấy {_relative(explicit, project_root)}")
        return explicit
    if data_cfg.recursive_discovery:
        candidates = sorted(
            Path(dirpath) / filename
            for dirpath, _, filenames in os.walk(base)
            for filename in filenames
            if filename == name
        )
    else:
        candidates = [base / name] if (base / name).is_file() else []
    if not candidates:
        where = "(đệ quy)" if data_cfg.recursive_discovery else "(không đệ quy)"
        raise InputNotFoundError(f"Không tìm thấy {name} dưới {data_cfg.root} {where}")
    if len(candidates) > 1:
        listed = ", ".join(_relative(c, project_root) for c in candidates)
        raise AmbiguousInputError(
            f"Có {len(candidates)} file tên {name}: {listed}. Đặt data.files.{cohort} thành "
            "đường dẫn tương đối dưới data.root (ví dụ 'thu_muc/" + name + "')."
        )
    return candidates[0]


def discover_input_files(data_cfg: DataConfig, project_root: Path) -> dict[str, Path]:
    """Tìm file của mọi cohort đã cấu hình, mỗi cohort một file."""
    return {cohort: find_input_file(data_cfg, project_root, cohort) for cohort in data_cfg.files}


def fingerprint_file(path: Path, project_root: Path) -> dict[str, Any]:
    """SHA-256, kích thước, đường dẫn tương đối và số dòng dữ liệu (không tính header)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        n_records = sum(1 for _ in csv.reader(fh))
    return {
        "relative_path": _relative(path, project_root),
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
        "n_rows": max(n_records - 1, 0),
    }


def _read_csv(path: Path, project_root: Path) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False,
                            encoding="utf-8-sig")
    except pd.errors.EmptyDataError as exc:
        raise SchemaError(f"{_relative(path, project_root)}: file rỗng, không có header") from exc
    missing = [c for c in RAW_COLUMNS if c not in frame.columns]
    unexpected = [c for c in frame.columns if c not in RAW_COLUMNS]
    if missing or unexpected:
        raise SchemaError(
            f"{_relative(path, project_root)}: schema sai, thiếu cột {missing}, "
            f"cột lạ {unexpected}; cần đúng {list(RAW_COLUMNS)}"
        )
    return frame


def _parse_timestamps(raw: pd.Series) -> tuple[pd.Series, list[tuple[int, str]]]:
    """Parse ISO 8601 có timezone sang UTC; trả (UTC, [(vị trí, nguyên nhân)]) cho dòng lỗi."""
    has_zone = raw.str.fullmatch(_TS_WITH_ZONE)
    without_zone = raw.str.fullmatch(_TS_WITHOUT_ZONE)
    parsed = pd.to_datetime(raw.where(has_zone, None), format="ISO8601", utc=True, errors="coerce")
    errors = []
    for pos in range(len(raw)):
        if not has_zone.iloc[pos]:
            cause = (
                "thiếu timezone (không suy đoán múi giờ)"
                if without_zone.iloc[pos]
                else "không phải timestamp ISO 8601"
            )
            errors.append((pos, cause))
        elif pd.isna(parsed.iloc[pos]):
            errors.append((pos, "giá trị ngày giờ không hợp lệ"))
    return parsed, errors


def load_raw_events(data_cfg: DataConfig, project_root: Path) -> pd.DataFrame:
    """Đọc CSV của `data_cfg.cohort` (tìm file theo cấu hình) thành bảng event thô đã sắp."""
    path = find_input_file(data_cfg, project_root, data_cfg.cohort)
    return read_events_csv(path, data_cfg.cohort, project_root)


def read_events_csv(path: Path, cohort: str, display_root: Path) -> pd.DataFrame:
    """Đọc MỘT file CSV Jira thô thành bảng event, đã sắp ổn định theo thời gian.

    Giữ nguyên mọi dòng (kể cả trùng hệt) và role trống. `source_row` là vị trí 1-based của dòng
    dữ liệu trong CSV (không tính header). `event_id` = fingerprint file + source_row, nên cùng
    nội dung file cho cùng id và không phụ thuộc giá trị ngẫu nhiên. Thứ tự: case_id,
    timestamp_utc, source_row; khi trùng thời điểm, source_row chỉ là quy tắc kỹ thuật chứ không
    phải thứ tự nghiệp vụ đã biết. `display_root` chỉ dùng để in đường dẫn tương đối.
    """
    fingerprint = fingerprint_file(path, display_root)
    frame = _read_csv(path, display_root).rename(
        columns={"issueKey": "issue_key", "timestamp": "timestamp_raw", "action": "raw_action"}
    )
    frame["source_row"] = range(1, len(frame) + 1)

    parsed, ts_errors = _parse_timestamps(frame["timestamp_raw"])
    problems = [
        {"source_row": int(frame["source_row"].iloc[pos]), "cause": cause,
         "value": frame["timestamp_raw"].iloc[pos]}
        for pos, cause in ts_errors
    ]
    blank_key = frame["issue_key"].str.strip() == ""
    problems += [
        {"source_row": int(row), "cause": "issueKey trống", "value": ""}
        for row in frame.loc[blank_key, "source_row"]
    ]
    if problems:
        problems.sort(key=lambda p: p["source_row"])
        raise RowDataError(fingerprint["relative_path"], problems)

    frame["timestamp_utc"] = parsed
    frame["issue_type"] = cohort
    frame["case_id"] = cohort + ":" + frame["issue_key"]
    frame["source_file"] = fingerprint["relative_path"]
    prefix = fingerprint["sha256"][:12]
    frame["event_id"] = [f"{prefix}-{row:06d}" for row in frame["source_row"]]

    frame = frame.sort_values(["case_id", "timestamp_utc", "source_row"], kind="stable")
    return frame[RAW_EVENT_COLUMNS].reset_index(drop=True)


def _iso(ts: pd.Timestamp) -> str | None:
    return None if pd.isna(ts) else ts.isoformat(timespec="milliseconds")


def audit_events(events: pd.DataFrame) -> dict[str, Any]:
    """Thống kê chất lượng bảng event thô (view raw); không loại hay sửa dòng nào."""
    n_events = len(events)
    per_case = events.groupby("case_id").size()
    previous_case = events["case_id"].shift()
    reordered = (events["case_id"] == previous_case) & (
        events["source_row"] < events["source_row"].shift()
    )
    in_tie = events.duplicated(["case_id", "timestamp_utc"], keep=False)
    roles = events["role"].value_counts().sort_values(ascending=False, kind="stable")
    offsets = events["timestamp_raw"].str.extract(_ZONE_SUFFIX)[0].value_counts()
    n_bot = int((events["role"] == "bot").sum())
    return {
        "n_events": n_events,
        "n_cases": int(per_case.size),
        "issue_types": sorted(events["issue_type"].unique().tolist()),
        "events_per_case": None if per_case.empty else {
            "min": int(per_case.min()),
            "median": float(per_case.median()),
            "max": int(per_case.max()),
            "mean": float(per_case.mean()),
        },
        "n_single_event_cases": int((per_case == 1).sum()),
        "n_blank_role": int((events["role"] == "").sum()),
        "n_role_bot": n_bot,
        "bot_share": None if n_events == 0 else n_bot / n_events,
        "role_counts": {str(k): int(v) for k, v in roles.items()},
        "n_distinct_raw_actions": int(events["raw_action"].nunique()),
        "utc_offsets": {str(k): int(v) for k, v in offsets.items()},
        "n_cases_needing_reorder": int(events.loc[reordered, "case_id"].nunique()),
        "n_tie_groups": int(events[in_tie].groupby(["case_id", "timestamp_utc"]).ngroups),
        "n_events_in_ties": int(in_tie.sum()),
        "n_exact_duplicate_rows": int(
            events.duplicated(["case_id", "timestamp_raw", "role", "raw_action"]).sum()
        ),
        "timestamp_min_utc": _iso(events["timestamp_utc"].min()),
        "timestamp_max_utc": _iso(events["timestamp_utc"].max()),
    }


def _reference_diff(report: dict[str, Any], reference: dict[str, int]) -> dict[str, Any]:
    actual = {"events": report["n_events"], "issues": report["n_cases"]}
    return {
        key: {
            "expected": reference[key],
            "actual": actual[key],
            "delta": actual[key] - reference[key],
        }
        for key in ("events", "issues")
    }


def build_audit_report(cfg: RunConfig) -> dict[str, Any]:
    """Audit raw cho từng cohort trong data.files (riêng rẽ, không gộp), kèm fingerprint input.

    `reference_counts` (nếu có) chỉ để báo sai khác; số liệu báo cáo luôn là số tính từ file.
    """
    inputs = []
    cohorts = {}
    references = cfg.data.reference_counts or {}
    for cohort in cfg.data.files:
        data_cfg = dataclasses.replace(cfg.data, cohort=cohort)
        path = find_input_file(data_cfg, cfg.project_root, cohort)
        inputs.append({"cohort": cohort, **fingerprint_file(path, cfg.project_root)})
        report = audit_events(load_raw_events(data_cfg, cfg.project_root))
        report["reference_diff"] = (
            _reference_diff(report, references[cohort]) if cohort in references else None
        )
        cohorts[cohort] = report
    return {
        "stage": "audit_raw",
        "scope": "analysis_only",
        "view": "raw",
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "config_path": _relative(cfg.config_path, cfg.project_root),
        "inputs": inputs,
        "cohorts": cohorts,
    }
