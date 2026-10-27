"""Sinh sai lệch cấu trúc có kiểm soát cho đánh giá bán tổng hợp (spec §6.1).

Mutant chỉ thay đổi chuỗi activity đã chuẩn hóa của một issue giữ lại (parent), với ba loại:
`swap_adjacent`, `delete_internal`, `duplicate_block`. Event đầu (CREATE) và event cuối (terminal)
luôn được bảo vệ; role và event lineage đi cùng activity; mọi activity của mutant lấy từ parent
(không tạo OOV giả); mutant không có timestamp. Mutant chỉ là sai lệch cấu trúc có kiểm soát để
xếp hạng, KHÔNG chứng minh vi phạm nghiệp vụ.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from jira_ad.config import MutationConfig
from jira_ad.types import MutationResult, Trace

LEDGER_COLUMNS = [
    "mutation_id", "parent_case_id", "split", "mutation_type", "seed", "status", "skip_reason",
    "edited_positions", "original_length", "mutated_length", "original_sequence_hash",
    "mutated_sequence_hash", "n_candidates", "n_rejected_candidates",
]
MIN_LENGTH = 3  # cần ít nhất một event nội bộ giữa CREATE và terminal
# Đối chứng dương (Ruling 31): sai lệch mạnh để kiểm tra bộ máy phát hiện được thứ tự bị phá. Không
# thuộc ba loại V1 (không cấu hình được), chỉ chạy trên validation, không dùng để chọn cấu hình.
POSITIVE_CONTROL_TYPE = "shuffle_internal"
POSITIVE_CONTROL_SPLIT = "validation"
POSITIVE_CONTROL_MAX_ATTEMPTS = 50
# Mutant mở rộng (giao thức cross-validation cải tiến). Tiền tố activity trạng thái do actions.yaml đặt.
STATUS_PREFIX = "STATUS_"
MULTI_EDIT_STEPS = 3
MULTI_EDIT_MAX_ATTEMPTS = 50


def sequence_hash(activities: tuple[str, ...]) -> str:
    payload = json.dumps(list(activities), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def _rng(seed: int, parent_id: str, mutation_type: str) -> np.random.Generator:
    """RNG riêng cho từng (seed, parent, loại): không phụ thuộc thứ tự parent hay parent khác."""
    digest = hashlib.sha256(f"{seed}:{parent_id}:{mutation_type}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


Candidate = tuple[list[int], list[int]]  # (vị trí bị sửa trong parent, thứ tự chỉ số tạo mutant)


def _swap_candidates(activities: tuple[str, ...]) -> list[Candidate]:
    length, out = len(activities), []
    for i in range(1, length - 2):  # cả i và i+1 đều là event nội bộ
        if activities[i] != activities[i + 1]:
            order = list(range(length))
            order[i], order[i + 1] = order[i + 1], order[i]
            out.append(([i, i + 1], order))
    return out


def _delete_candidates(activities: tuple[str, ...]) -> list[Candidate]:
    length = len(activities)
    return [([i], [j for j in range(length) if j != i]) for i in range(1, length - 1)]


def _duplicate_candidates(activities: tuple[str, ...], max_length: int) -> list[Candidate]:
    length, out = len(activities), []
    for k in range(1, min(max_length, length - 2) + 1):
        for i in range(1, length - k):  # khối [i, i+k) nằm hoàn toàn trong phần nội bộ
            order = list(range(length))
            out.append((list(range(i, i + k)), order[: i + k] + order[i : i + k] + order[i + k :]))
    return out


def _skip_status_candidates(activities: tuple[str, ...]) -> list[Candidate]:
    """Xóa một event trạng thái nội bộ (mô phỏng bỏ qua một bước của quy trình)."""
    length = len(activities)
    return [([i], [j for j in range(length) if j != i]) for i in range(1, length - 1)
            if activities[i].startswith(STATUS_PREFIX)]


def _multi_edit(
    trace: Trace, rng: np.random.Generator, originals: set[tuple[str, ...]]
) -> tuple[list[int], list[list[Any]], int, int] | None:
    """`MULTI_EDIT_STEPS` chỉnh sửa ngẫu nhiên liên tiếp (swap/delete/duplicate một event) trên phần nội bộ.

    Event đầu/cuối luôn được bảo vệ và độ dài không xuống dưới 3. Trả `(order, ops, n_thử, n_bị_loại)`
    hoặc None khi mọi lần thử đều trùng một chuỗi gốc trong holdout.
    """
    attempts = rejected = 0
    for _ in range(MULTI_EDIT_MAX_ATTEMPTS):
        attempts += 1
        order, ops = list(range(len(trace))), []
        for _ in range(MULTI_EDIT_STEPS):
            acts = [trace.activities[j] for j in order]
            feasible = []
            swaps = [i for i in range(1, len(order) - 2) if acts[i] != acts[i + 1]]
            if swaps:
                feasible.append(("swap", swaps))
            if len(order) > 3:
                feasible.append(("delete", list(range(1, len(order) - 1))))
            feasible.append(("duplicate", list(range(1, len(order) - 1))))
            kind, positions = feasible[int(rng.integers(len(feasible)))]
            i = positions[int(rng.integers(len(positions)))]
            if kind == "swap":
                order[i], order[i + 1] = order[i + 1], order[i]
            elif kind == "delete":
                del order[i]
            else:
                order.insert(i + 1, order[i])
            ops.append([kind, i])
        activities = tuple(trace.activities[j] for j in order)
        if activities in originals:
            rejected += 1
            continue
        return order, ops, attempts, rejected
    return None


def _candidates(trace: Trace, mutation_type: str, cfg: MutationConfig) -> list[Candidate]:
    if mutation_type == "swap_adjacent":
        return _swap_candidates(trace.activities)
    if mutation_type == "delete_internal":
        return _delete_candidates(trace.activities)
    if mutation_type == "duplicate_block":
        return _duplicate_candidates(trace.activities, cfg.duplicate_block_max_length)
    if mutation_type == "skip_status":
        return _skip_status_candidates(trace.activities)
    raise ValueError(f"Loại mutation không hỗ trợ: {mutation_type!r}")


def _row(
    trace: Trace, mutation_type: str, mutation_id: str, seed: int, split: str
) -> dict[str, Any]:
    return {
        "mutation_id": mutation_id, "parent_case_id": trace.trace_id, "split": split,
        "mutation_type": mutation_type, "seed": seed, "status": "skipped", "skip_reason": None,
        "edited_positions": None, "original_length": len(trace), "mutated_length": None,
        "original_sequence_hash": sequence_hash(trace.activities),
        "mutated_sequence_hash": None, "n_candidates": 0, "n_rejected_candidates": 0,
    }


def _mutant(trace: Trace, mutation_id: str, order: list[int]) -> Trace:
    """Mutant theo thứ tự chỉ số `order` của parent: role/event lineage đi cùng activity, không timestamp."""
    return Trace(
        trace_id=mutation_id,
        parent_case_id=trace.trace_id,
        issue_type=trace.issue_type,
        activities=tuple(trace.activities[j] for j in order),
        roles=tuple(trace.roles[j] for j in order),
        event_ids=tuple(trace.event_ids[j] for j in order),
        timestamps=None,
        terminal_status=trace.terminal_status,
    )


def generate_mutations(
    traces: list[Trace], cfg: MutationConfig, seed: int, split: str = ""
) -> MutationResult:
    """Tối đa một mutant cho mỗi (parent, loại), chọn bằng RNG cố định theo `seed`.

    Ứng viên được thử theo thứ tự ngẫu nhiên; ứng viên trùng một chuỗi activity gốc trong cùng
    holdout (kể cả chính parent) bị loại và ghi số lượng. Hết ứng viên hợp lệ thì ghi `skipped`
    kèm lý do thay vì chèn activity mới. Chỉ gọi với trace của đúng một holdout (validation hoặc
    test), không bao giờ với train.
    """
    originals = {tuple(t.activities) for t in traces}
    kept: list[Trace] = []
    rows: list[dict[str, Any]] = []
    for trace in sorted(traces, key=lambda t: t.trace_id):
        for mutation_type in cfg.types:
            mutation_id = f"{trace.trace_id}::{mutation_type}::{seed}"
            row = _row(trace, mutation_type, mutation_id, seed, split)
            if mutation_type == "multi_edit":
                rows.append(row)
                if len(trace) < MIN_LENGTH:
                    row["skip_reason"] = "no_internal_events"
                    continue
                found = _multi_edit(trace, _rng(seed, trace.trace_id, mutation_type), originals)
                if found is None:
                    row.update(n_candidates=MULTI_EDIT_MAX_ATTEMPTS,
                               n_rejected_candidates=MULTI_EDIT_MAX_ATTEMPTS,
                               skip_reason="all_candidates_match_originals")
                    continue
                order, ops, attempts, rejected = found
                kept.append(_mutant(trace, mutation_id, order))
                row.update(status="created", edited_positions=json.dumps(ops),
                           mutated_length=len(order), n_candidates=attempts,
                           n_rejected_candidates=rejected,
                           mutated_sequence_hash=sequence_hash(kept[-1].activities))
                continue
            candidates = _candidates(trace, mutation_type, cfg) if len(trace) >= MIN_LENGTH else []
            row["n_candidates"] = len(candidates)
            if not candidates:
                row["skip_reason"] = (
                    "no_internal_events" if len(trace) < MIN_LENGTH
                    else "no_internal_status" if mutation_type == "skip_status"
                    else "no_distinct_adjacent_pair"
                )
                rows.append(row)
                continue
            rng = _rng(seed, trace.trace_id, mutation_type)
            for choice in rng.permutation(len(candidates)):
                positions, order = candidates[int(choice)]
                activities = tuple(trace.activities[j] for j in order)
                if activities in originals:
                    row["n_rejected_candidates"] += 1
                    continue
                kept.append(Trace(
                    trace_id=mutation_id,
                    parent_case_id=trace.trace_id,
                    issue_type=trace.issue_type,
                    activities=activities,
                    roles=tuple(trace.roles[j] for j in order),
                    event_ids=tuple(trace.event_ids[j] for j in order),
                    timestamps=None,
                    terminal_status=trace.terminal_status,
                ))
                row.update(
                    status="created", edited_positions=json.dumps(positions),
                    mutated_length=len(activities), mutated_sequence_hash=sequence_hash(activities),
                )
                break
            else:
                row["skip_reason"] = "all_candidates_match_originals"
            rows.append(row)
    ledger = pd.DataFrame(rows, columns=LEDGER_COLUMNS)
    return MutationResult(traces=kept, ledger=ledger)


def generate_positive_control(traces: list[Trace], seed: int, split: str) -> MutationResult:
    """Đối chứng dương: xáo ngẫu nhiên TOÀN BỘ phần nội bộ của parent, giữ nguyên event đầu và cuối.

    Giữ histogram activity và độ dài (chỉ phá thứ tự), role/event lineage đi cùng activity, mutant
    không có timestamp. Thử tối đa `POSITIVE_CONTROL_MAX_ATTEMPTS` hoán vị; hoán vị trùng một chuỗi
    gốc trong holdout (kể cả parent) bị loại. Chỉ chạy trên validation: kiểm tra bộ máy, không phải
    một loại mutation đánh giá của V1 và không dùng để chọn cấu hình.
    """
    if split != POSITIVE_CONTROL_SPLIT:
        raise ValueError(
            f"Đối chứng dương chỉ chạy trên {POSITIVE_CONTROL_SPLIT!r}, nhận split={split!r}")
    originals = {tuple(t.activities) for t in traces}
    kept: list[Trace] = []
    rows: list[dict[str, Any]] = []
    for trace in sorted(traces, key=lambda t: t.trace_id):
        mutation_id = f"{trace.trace_id}::{POSITIVE_CONTROL_TYPE}::{seed}"
        row = _row(trace, POSITIVE_CONTROL_TYPE, mutation_id, seed, split)
        length = len(trace)
        internal = list(range(1, length - 1))
        if len(internal) < 2:
            row["skip_reason"] = "fewer_than_two_internal_events"
        elif len(set(trace.activities[1:-1])) < 2:
            row["skip_reason"] = "no_distinct_internal_events"
        else:
            rng = _rng(seed, trace.trace_id, POSITIVE_CONTROL_TYPE)
            for _ in range(POSITIVE_CONTROL_MAX_ATTEMPTS):
                order = [0, *(int(i) for i in rng.permutation(internal)), length - 1]
                row["n_candidates"] += 1
                activities = tuple(trace.activities[j] for j in order)
                if activities in originals:
                    row["n_rejected_candidates"] += 1
                    continue
                kept.append(Trace(
                    trace_id=mutation_id,
                    parent_case_id=trace.trace_id,
                    issue_type=trace.issue_type,
                    activities=activities,
                    roles=tuple(trace.roles[j] for j in order),
                    event_ids=tuple(trace.event_ids[j] for j in order),
                    timestamps=None,
                    terminal_status=trace.terminal_status,
                ))
                row.update(
                    status="created",
                    edited_positions=json.dumps([i for i, j in enumerate(order) if i != j]),
                    mutated_length=length, mutated_sequence_hash=sequence_hash(activities),
                )
                break
            else:
                row["skip_reason"] = "all_candidates_match_originals"
        rows.append(row)
    return MutationResult(traces=kept, ledger=pd.DataFrame(rows, columns=LEDGER_COLUMNS))
