"""Kiểu dữ liệu chung dùng nhất quán giữa các module (spec §4.3).

Node2VecEmbedding định nghĩa ở embedding.py, FeatureEncoder ở features.py, DetectorBundle ở
detector.py. Ở đây chỉ có các kiểu không phụ thuộc thuật toán.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

# Role sau chuẩn hóa (spec §4.1): role trống thành MISSING_ROLE; "unknown" là giá trị riêng của
# Jira. Cả hai KHÔNG phải vai trò xác định khi tính known_role_* (spec §5.4).
MISSING_ROLE = "__MISSING_ROLE__"
UNKNOWN_ROLE = "unknown"
UNDETERMINED_ROLES = frozenset({MISSING_ROLE, UNKNOWN_ROLE})


@dataclass(frozen=True)
class Trace:
    """Lịch sử một issue đã chuẩn hóa: chuỗi activity, role và event gốc cùng chiều dài.

    Bản gốc có `timestamps`; mutant cấu trúc có `timestamps=None` (không giả tạo thời gian).
    """

    trace_id: str
    parent_case_id: str
    issue_type: str
    activities: tuple[str, ...]
    roles: tuple[str, ...]
    event_ids: tuple[str, ...]
    timestamps: tuple[datetime, ...] | None
    terminal_status: str | None

    def __post_init__(self) -> None:
        sequences = {
            "activities": self.activities,
            "roles": self.roles,
            "event_ids": self.event_ids,
        }
        if self.timestamps is not None:
            sequences["timestamps"] = self.timestamps
        for name, seq in sequences.items():
            if not isinstance(seq, tuple):
                raise TypeError(f"Trace.{name} phải là tuple, nhận {type(seq).__name__}")
        if len(self.activities) == 0:
            raise ValueError(f"Trace {self.trace_id!r} rỗng (empty): cần ít nhất một event")
        for name, seq in sequences.items():
            if len(seq) != len(self.activities):
                raise ValueError(
                    f"Trace {self.trace_id!r}: độ dài {name}={len(seq)} "
                    f"khác activities={len(self.activities)}"
                )

    def __len__(self) -> int:
        return len(self.activities)


@dataclass(frozen=True)
class CaseSplits:
    """Phân vùng case_id thành train/validation/test; ba tập không được giao nhau."""

    train_ids: tuple[str, ...]
    validation_ids: tuple[str, ...]
    test_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        everything = self.train_ids + self.validation_ids + self.test_ids
        if len(set(everything)) != len(everything):
            seen: set[str] = set()
            repeated = sorted({x for x in everything if x in seen or seen.add(x)})
            raise ValueError(f"train/validation/test giao nhau (overlap): {repeated[:5]}")

    @property
    def all_ids(self) -> tuple[str, ...]:
        return self.train_ids + self.validation_ids + self.test_ids


@dataclass(eq=False)
class FeatureSet:
    """Ma trận đặc trưng kèm định danh trace và tên cột (định danh không là feature)."""

    values: np.ndarray
    trace_ids: tuple[str, ...]
    feature_names: tuple[str, ...]

    def __post_init__(self) -> None:
        expected = (len(self.trace_ids), len(self.feature_names))
        if self.values.ndim != 2 or self.values.shape != expected:
            raise ValueError(
                f"FeatureSet shape {self.values.shape} không khớp "
                f"(trace_ids, feature_names)={expected}"
            )


@dataclass
class MutationResult:
    """Các mutant cấu trúc và sổ cái (ledger) mô tả chúng."""

    traces: list[Trace]
    ledger: pd.DataFrame
