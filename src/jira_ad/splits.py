"""Chia issue thành train/validation/test, ghi và đọc split manifest (spec §5.1).

Đơn vị chia là issue (trace), không phải event. Gán split chỉ phụ thuộc `(seed, case_id)` và
`terminal_status`, không phụ thuộc nội dung trace, thứ tự đầu vào hay noise policy, nên đổi
model/encoding/p/q/noise policy không làm đổi split.

`split.strategy: temporal` (mở rộng, thay cho holdout ngẫu nhiên): xếp các ca theo thời điểm kết thúc
(event terminal cuối) và lấy train = các ca kết thúc sớm nhất, rồi validation, rồi test. Mọi ca train
đã kết thúc trước mọi ca held-out, nên không có lịch sử train nào đi vào tương lai; nhưng một ca
held-out có thể đã bắt đầu trước khi train kết thúc, nên `temporal_report` đếm các ca đó.
"""

from __future__ import annotations

import hashlib
from datetime import UTC
from pathlib import Path
from typing import Any

import pandas as pd

from jira_ad.config import SplitConfig
from jira_ad.types import CaseSplits, Trace

SPLIT_NAMES = ("train", "validation", "test")
MANIFEST_COLUMNS = ["case_id", "split", "terminal_status", "stratum", "split_seed"]
NO_STATUS = "__NO_TERMINAL_STATUS__"
ALL_STRATUM = "all"
TEMPORAL_STRATUM = "temporal"
MIN_CASES_PER_STRATUM = len(SPLIT_NAMES)


class SplitError(ValueError):
    """Không chia được issue (quá ít case, nhánh stratify quá nhỏ, trace_id trùng)."""


class SplitManifestError(SplitError):
    """Split manifest sai cột, sai nhãn split, hoặc một case xuất hiện hai lần."""


def _allocate(n: int, fractions: tuple[float, float, float]) -> tuple[int, int, int]:
    """Chia n case theo tỷ lệ bằng phần dư lớn nhất; mỗi split có ít nhất một case."""
    raw = [n * f for f in fractions]
    sizes = [int(x) for x in raw]
    order = sorted(range(3), key=lambda i: (-round(raw[i] - sizes[i], 9), i))
    for i in order[: n - sum(sizes)]:
        sizes[i] += 1
    for i in range(3):  # bảo đảm không rỗng: lấy từ split lớn nhất
        if sizes[i] == 0:
            donor = max(range(3), key=lambda j: (sizes[j], -j))
            sizes[donor] -= 1
            sizes[i] += 1
    return sizes[0], sizes[1], sizes[2]


def _rank(case_id: str, seed: int) -> str:
    """Thứ tự giả ngẫu nhiên ổn định theo (seed, case_id); không phụ thuộc phiên bản NumPy/OS."""
    return hashlib.sha256(f"{seed}:{case_id}".encode()).hexdigest()


def _stratum(trace: Trace, cfg: SplitConfig) -> str:
    if cfg.strategy == "temporal":
        return TEMPORAL_STRATUM
    if cfg.stratify == "none":
        return ALL_STRATUM
    return trace.terminal_status if trace.terminal_status is not None else NO_STATUS


def make_case_splits(traces: list[Trace], cfg: SplitConfig) -> CaseSplits:
    """Holdout theo issue, stratify theo terminal_status khi mỗi nhánh đủ mẫu; nếu không thì lỗi."""
    ids = [t.trace_id for t in traces]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise SplitError(f"trace_id trùng lặp: {duplicated[:5]}")
    if len(ids) < MIN_CASES_PER_STRATUM:
        raise SplitError(
            f"Cần ít nhất {MIN_CASES_PER_STRATUM} case để chia train/validation/test, có {len(ids)}"
        )
    if cfg.strategy == "temporal":
        return _temporal_splits(traces, cfg)
    strata: dict[str, list[str]] = {}
    for trace in traces:
        strata.setdefault(_stratum(trace, cfg), []).append(trace.trace_id)
    small = {label: len(members) for label, members in strata.items()
             if len(members) < MIN_CASES_PER_STRATUM}
    if small:
        raise SplitError(
            f"Nhánh stratify theo terminal_status quá ít case (cần >= {MIN_CASES_PER_STRATUM} "
            f"mỗi nhánh): {small}. Đặt split.stratify: none hoặc bổ sung dữ liệu."
        )
    fractions = (cfg.train_fraction, cfg.validation_fraction, cfg.test_fraction)
    parts: tuple[list[str], list[str], list[str]] = ([], [], [])
    for label in sorted(strata):
        members = sorted(strata[label], key=lambda cid: (_rank(cid, cfg.seed), cid))
        n_train, n_val, _ = _allocate(len(members), fractions)
        parts[0].extend(members[:n_train])
        parts[1].extend(members[n_train:n_train + n_val])
        parts[2].extend(members[n_train + n_val:])
    return CaseSplits(*(tuple(sorted(p)) for p in parts))


def _terminal_time(trace: Trace):
    if not trace.timestamps:
        raise SplitError(f"{trace.trace_id}: holdout theo thời gian cần timestamps của trace")
    return trace.timestamps[-1]


def _temporal_splits(traces: list[Trace], cfg: SplitConfig) -> CaseSplits:
    """Train = ca kết thúc sớm nhất; hòa thời điểm thì xếp theo `trace_id` (không theo thứ tự đầu vào)."""
    ordered = sorted(traces, key=lambda t: (_terminal_time(t), t.trace_id))
    n_train, n_val, _ = _allocate(
        len(ordered), (cfg.train_fraction, cfg.validation_fraction, cfg.test_fraction))
    ids = [t.trace_id for t in ordered]
    parts = (ids[:n_train], ids[n_train:n_train + n_val], ids[n_train + n_val:])
    return CaseSplits(*(tuple(sorted(p)) for p in parts))


def temporal_report(splits: CaseSplits, traces: list[Trace]) -> dict[str, Any]:
    """Khoảng thời gian của từng split và số ca held-out đã bắt đầu trước khi train kết thúc.

    Ca như vậy không làm rò rỉ lịch sử train vào tương lai (train đã kết thúc hết), nhưng cho thấy
    holdout theo thời gian không tách hẳn hai giai đoạn: cần đọc kèm khi diễn giải kết quả.
    """
    by_id = {t.trace_id: t for t in traces}

    def utc(moment) -> str:
        return moment.astimezone(UTC).isoformat(timespec="seconds")

    groups = (("train", splits.train_ids), ("validation", splits.validation_ids),
              ("test", splits.test_ids))
    ends = {name: [_terminal_time(by_id[i]) for i in ids] for name, ids in groups}
    train_end = max(ends["train"])
    heldout = (*splits.validation_ids, *splits.test_ids)
    return {
        "by_split": {name: {"n": len(ends[name]), "first_terminal_utc": utc(min(ends[name])),
                            "last_terminal_utc": utc(max(ends[name]))} for name, _ in groups},
        "train_end_utc": utc(train_end),
        "n_heldout_started_before_train_end": sum(
            by_id[i].timestamps[0] < train_end for i in heldout),
        "n_heldout": len(heldout),
        "train_validation_boundary_tie": max(ends["train"]) == min(ends["validation"]),
        "validation_test_boundary_tie": max(ends["validation"]) == min(ends["test"]),
    }


def _assignment(splits: CaseSplits) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, ids in zip(SPLIT_NAMES, (splits.train_ids, splits.validation_ids, splits.test_ids),
                         strict=True):
        out.update({case_id: name for case_id in ids})
    return out


def split_hash(splits: CaseSplits) -> str:
    """SHA-256 của phép gán case->split (không phụ thuộc thứ tự dòng)."""
    lines = [f"{case_id},{name}" for case_id, name in sorted(_assignment(splits).items())]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def write_split_manifest(
    splits: CaseSplits, traces: list[Trace], cfg: SplitConfig, path: Path
) -> None:
    """Ghi manifest cố định (một dòng mỗi case) để mọi model/encoding dùng lại đúng split này."""
    by_id = {t.trace_id: t for t in traces}
    rows = [
        {
            "case_id": case_id,
            "split": name,
            "terminal_status": by_id[case_id].terminal_status or "",
            "stratum": _stratum(by_id[case_id], cfg),
            "split_seed": cfg.seed,
        }
        for name, ids in zip(
            SPLIT_NAMES, (splits.train_ids, splits.validation_ids, splits.test_ids), strict=True
        )
        for case_id in ids
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=MANIFEST_COLUMNS).to_csv(path, index=False, lineterminator="\n")


def read_split_manifest(path: Path) -> CaseSplits:
    """Đọc manifest và kiểm tra: đủ cột, nhãn split hợp lệ, mỗi case đúng một lần."""
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in MANIFEST_COLUMNS if c not in frame.columns]
    if missing:
        raise SplitManifestError(f"{path}: thiếu cột {missing}")
    bad = sorted(set(frame["split"]) - set(SPLIT_NAMES))
    if bad:
        raise SplitManifestError(f"{path}: nhãn split không hợp lệ {bad}; hợp lệ {SPLIT_NAMES}")
    repeated = sorted(frame.loc[frame["case_id"].duplicated(), "case_id"])
    if repeated:
        raise SplitManifestError(f"{path}: case xuất hiện nhiều lần: {repeated[:5]}")
    ids = {
        name: tuple(sorted(frame.loc[frame["split"] == name, "case_id"])) for name in SPLIT_NAMES
    }
    return CaseSplits(ids["train"], ids["validation"], ids["test"])
