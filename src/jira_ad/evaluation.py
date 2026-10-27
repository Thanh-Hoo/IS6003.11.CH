"""Đánh giá bán tổng hợp: trace gốc so với mutant (spec §6.2).

Nhãn `is_injected`: 0 = trace gốc chưa xác nhận là bình thường, 1 = mutant được chèn. Đây KHÔNG
phải nhãn bất thường thật. Mỗi benchmark theo loại chỉ dùng các parent tạo được mutant hợp lệ
(một bản gốc + một mutant mỗi parent nên tỷ lệ thiết kế luôn 0,5), và các phương pháp được so
trên cùng giao tập parent. Tỷ lệ 0,5 là tỷ lệ thiết kế, không phải tỷ lệ bất thường thực tế.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.metrics import average_precision_score, roc_auc_score

LABEL_DEFINITION = (
    "is_injected: 0 = trace gốc chưa xác nhận bình thường, 1 = mutant được chèn; "
    "không phải nhãn bất thường thật"
)
SCORE_COLUMNS = ["method", "trace_id", "parent_case_id", "anomaly_score"]
LEDGER_REQUIRED = ["mutation_id", "parent_case_id", "mutation_type", "status", "skip_reason"]
METRIC_KEYS = (
    "method", "mutation_type", "n_original", "n_mutant", "injected_rate", "auroc",
    "average_precision", "ap_constant_predictor", "paired_win_rate", "mean_delta_score",
    "median_delta_score", "null_reason",
)


def _check_columns(frame: pd.DataFrame, required: list[str], name: str) -> None:
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise ValueError(f"{name}: thiếu cột {missing}")


def _check_scores(frame: pd.DataFrame, name: str) -> None:
    _check_columns(frame, SCORE_COLUMNS, name)
    if not np.isfinite(frame["anomaly_score"].to_numpy(dtype=float)).all():
        raise ValueError(f"{name}: anomaly_score không hữu hạn (NaN/Inf)")
    duplicated = frame[frame.duplicated(["method", "trace_id"], keep=False)]
    if len(duplicated):
        raise ValueError(
            f"{name}: điểm trùng (duplicate) theo (method, trace_id): "
            f"{sorted(set(duplicated['trace_id']))[:5]}"
        )


def _null_row(method: str, mutation_type: str, reason: str) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(METRIC_KEYS)
    row.update(method=method, mutation_type=mutation_type, n_original=0, n_mutant=0,
               null_reason=reason)
    return row


def _metric_row(
    method: str, mutation_type: str, orig: pd.Series, mut: pd.Series
) -> dict[str, Any]:
    """`orig` và `mut` là điểm theo parent_case_id, cùng chỉ số (đã ghép cặp theo parent)."""
    n = len(orig)
    labels = np.r_[np.zeros(n), np.ones(n)]
    scores = np.r_[orig.to_numpy(float), mut.to_numpy(float)]
    delta = mut.to_numpy(float) - orig.to_numpy(float)
    wins = np.where(delta > 0, 1.0, np.where(delta == 0, 0.5, 0.0))
    return {
        "method": method, "mutation_type": mutation_type, "n_original": n, "n_mutant": n,
        "injected_rate": 0.5,
        "auroc": float(roc_auc_score(labels, scores)),
        "average_precision": float(average_precision_score(labels, scores)),
        "ap_constant_predictor": 0.5,  # AP của bộ dự đoán hằng = tỷ lệ thiết kế
        "paired_win_rate": float(wins.mean()),
        "mean_delta_score": float(delta.mean()),
        "median_delta_score": float(np.median(delta)),
        "null_reason": None,
    }


def evaluate_semisynthetic(
    original_scores: pd.DataFrame, mutant_scores: pd.DataFrame, ledger: pd.DataFrame
) -> dict[str, Any]:
    """AUROC, Average Precision và paired win rate riêng từng (phương pháp, loại mutation).

    `original_scores` / `mutant_scores`: cột `method, trace_id, parent_case_id, anomaly_score`;
    `trace_id` của mutant là `mutation_id` trong `ledger`. Ghép cặp theo `parent_case_id`, không
    theo thứ tự dòng. Tập thiếu một lớp cho metric null kèm lý do (không trả 0).
    """
    _check_scores(original_scores, "original_scores")
    _check_scores(mutant_scores, "mutant_scores")
    _check_columns(ledger, LEDGER_REQUIRED, "ledger")

    type_of = dict(zip(ledger["mutation_id"], ledger["mutation_type"], strict=True))
    unknown = sorted(set(mutant_scores["trace_id"]) - set(type_of))
    if unknown:
        raise ValueError(f"mutant không có trong ledger: {unknown[:5]}")
    mutants = mutant_scores.assign(mutation_type=mutant_scores["trace_id"].map(type_of))
    methods = sorted(set(original_scores["method"]) | set(mutants["method"]))

    orig_by_method = {
        m: original_scores[original_scores["method"] == m].set_index("parent_case_id")[
            "anomaly_score"] for m in methods
    }
    for method in methods:
        ghosts = sorted(set(mutants.loc[mutants["method"] == method, "parent_case_id"])
                        - set(orig_by_method[method].index))
        if ghosts:
            raise ValueError(f"[{method}] mutant của parent không có điểm gốc: {ghosts[:5]}")

    types = sorted(set(ledger["mutation_type"]))
    rows: list[dict[str, Any]] = []
    paired: list[dict[str, Any]] = []
    intersection: dict[str, Any] = {}
    for mutation_type in types:
        per_method = {
            m: mutants[(mutants["method"] == m) & (mutants["mutation_type"] == mutation_type)]
            .set_index("parent_case_id") for m in methods
        }
        index_sets = [set(f.index) for f in per_method.values()]
        common = set.intersection(*index_sets) if index_sets else set()
        any_created = any(len(f) for f in per_method.values())
        intersection[mutation_type] = {"n_parents": len(common), "methods": methods}
        for method in methods:
            if not common:
                reason = "no_common_parents" if any_created else "no_valid_mutants"
                rows.append(_null_row(method, mutation_type, reason))
                continue
            parents = sorted(common)
            orig = orig_by_method[method].loc[parents]
            mut = per_method[method].loc[parents, "anomaly_score"]
            rows.append(_metric_row(method, mutation_type, orig, mut))
            for parent in parents:
                paired.append({
                    "method": method, "mutation_type": mutation_type,
                    "parent_case_id": parent,
                    "mutation_id": per_method[method].loc[parent, "trace_id"],
                    "original_score": float(orig.loc[parent]),
                    "mutant_score": float(mut.loc[parent]),
                    "delta_score": float(mut.loc[parent] - orig.loc[parent]),
                })

    return {
        "label_definition": LABEL_DEFINITION,
        "design": {
            "injected_rate": 0.5,
            "note": "tỷ lệ thiết kế, không phải tỷ lệ bất thường thật",
        },
        "methods": methods,
        "metrics_by_type": rows,
        "paired_scores": paired,
        "intersection": intersection,
        "macro_by_method": _macro(rows, methods),
        "mutation_summary": _mutation_summary(ledger),
    }


def _macro(rows: list[dict[str, Any]], methods: list[str]) -> dict[str, Any]:
    out = {}
    for method in methods:
        scored = [r for r in rows if r["method"] == method and r["auroc"] is not None]
        out[method] = {
            "n_types_scored": len(scored),
            "macro_auroc": float(np.mean([r["auroc"] for r in scored])) if scored else None,
            "macro_average_precision": (
                float(np.mean([r["average_precision"] for r in scored])) if scored else None),
            "macro_paired_win_rate": (
                float(np.mean([r["paired_win_rate"] for r in scored])) if scored else None),
        }
    return out


def _mutation_summary(ledger: pd.DataFrame) -> dict[str, Any]:
    summary = {}
    for mutation_type, part in ledger.groupby("mutation_type", sort=True):
        skipped = part[part["status"] == "skipped"]
        summary[str(mutation_type)] = {
            "created": int((part["status"] == "created").sum()),
            "skipped": int(len(skipped)),
            "skip_reasons": {str(k): int(v) for k, v in skipped["skip_reason"].value_counts()
                             .sort_index().items()},
        }
    return summary


def metrics_frame(result: dict[str, Any]) -> pd.DataFrame:
    """`metrics_by_type` dưới dạng bảng (metrics_by_type.csv)."""
    return pd.DataFrame(result["metrics_by_type"], columns=list(METRIC_KEYS))


def paired_frame(result: dict[str, Any]) -> pd.DataFrame:
    """Điểm gốc/mutant theo parent và `delta_score` (paired_scores.csv)."""
    columns = ["method", "mutation_type", "parent_case_id", "mutation_id", "original_score",
               "mutant_score", "delta_score"]
    return pd.DataFrame(result["paired_scores"], columns=columns)


# ================================================================== bootstrap theo parent (spec §6.2)

PAIRED_REQUIRED = ["method", "mutation_type", "parent_case_id", "original_score", "mutant_score"]
INTERVAL_COLUMNS = ["method", "scope", "metric", "estimate", "ci_low", "ci_high", "se",
                    "n_parents", "null_reason"]
DIFFERENCE_COLUMNS = ["method_a", "method_b", "scope", "metric", "estimate", "ci_low", "ci_high",
                      "prob_positive", "n_parents", "null_reason"]
MACRO = "macro"
BOOTSTRAP_METRICS = ("auroc", "paired_win_rate")
MIN_PARENTS = 2
BOOTSTRAP_NOTE = (
    "Resample theo parent_case_id (có hoàn lại), mang theo bản gốc và mọi bản con của parent; "
    "mọi phương pháp và loại mutation dùng chung một lần resample nên chênh lệch giữa phương pháp "
    "là chênh lệch ghép cặp. Khoảng percentile mô tả độ bất định do chọn ca, không phải độ bất định "
    "của mô hình theo seed, và không biến tỷ lệ thiết kế 0,5 thành tỷ lệ bất thường thực tế."
)


def paired_auroc(
    original: np.ndarray, mutant: np.ndarray, weights: np.ndarray | None = None
) -> float:
    """AUROC của `mutant` (lớp 1) so với `original` (lớp 0), điểm trùng tính trung bình hạng.

    `weights` là số lần mỗi cặp được chọn khi resample (số nguyên >= 0); bằng với lặp lại cặp đó.
    Cùng giá trị với `sklearn.metrics.roc_auc_score` nhưng nhanh hơn cho hàng nghìn lần resample.
    """
    orig, mut = np.asarray(original, dtype=float), np.asarray(mutant, dtype=float)
    if weights is not None:
        counts = np.asarray(weights, dtype=int)
        orig, mut = np.repeat(orig, counts), np.repeat(mut, counts)
    n = len(orig)
    if n == 0:
        return float("nan")
    ranks = rankdata(np.concatenate([orig, mut]))
    return float((ranks[n:].sum() - n * (n + 1) / 2) / (n * n))


def _wins(original: np.ndarray, mutant: np.ndarray) -> np.ndarray:
    delta = mutant - original
    return np.where(delta > 0, 1.0, np.where(delta == 0, 0.5, 0.0))


def _statistics(
    orig: np.ndarray, mut: np.ndarray, wins: np.ndarray, present: np.ndarray, counts: np.ndarray
) -> np.ndarray:
    """Mảng [resample, metric, method, type] cho các lần chọn parent `counts` ([resample, parent]).

    AUROC có trọng số tính chính xác bằng ma trận cặp (Mann–Whitney, hòa tính 0,5): với trọng số w
    (số lần parent được chọn, 0 nếu parent vắng ở loại đó), AUROC = Σ w_i w_j G_ij / (Σ w)², trong
    đó G_ij = 1 nếu mutant của parent j có điểm cao hơn bản gốc của parent i (0,5 nếu bằng).
    """
    n_resamples = counts.shape[0]
    n_methods, n_types, _ = orig.shape
    out = np.full((n_resamples, len(BOOTSTRAP_METRICS), n_methods, n_types), np.nan)
    for m in range(n_methods):
        for t in range(n_types):
            weights = counts * present[m, t]
            total = weights.sum(axis=1).astype(float)
            ok = total > 0
            pair = (mut[m, t][None, :] > orig[m, t][:, None]) + 0.5 * (
                mut[m, t][None, :] == orig[m, t][:, None])
            numerator = np.einsum("bi,ij,bj->b", weights, pair, weights)
            win_sum = (weights * wins[m, t]).sum(axis=1)
            out[ok, 0, m, t] = numerator[ok] / total[ok] ** 2
            out[ok, 1, m, t] = win_sum[ok] / total[ok]
    return out


def _with_macro(stats: np.ndarray) -> np.ndarray:
    """Thêm 'macro' (trung bình các loại có số liệu) làm phần tử cuối của trục loại (cuối cùng)."""
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # nanmean của hàng toàn NaN
        macro = np.nanmean(stats, axis=-1, keepdims=True)
    return np.concatenate([stats, macro], axis=-1)


def _aggregate_methods(
    aggregate: dict[str, list[str]], m_of: dict[str, int], estimate: np.ndarray, boot: np.ndarray,
    present: np.ndarray,
) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
    """Gộp trục phương pháp theo nhãn: trung bình thành viên (bỏ NaN) trong từng lần resample."""
    seen: set[str] = set()
    for label, members in aggregate.items():
        if not members:
            raise ValueError(f"aggregate[{label!r}] không có thành viên nào")
        for member in members:
            if member not in m_of:
                raise ValueError(f"aggregate[{label!r}]: thành viên {member!r} không có trong methods")
            if member in seen:
                raise ValueError(f"aggregate: thành viên {member!r} nằm trong nhiều nhãn")
            seen.add(member)
    labels = list(aggregate)
    index = [[m_of[member] for member in aggregate[label]] for label in labels]
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # nanmean của nhóm toàn NaN
        est = np.stack([np.nanmean(estimate[:, idx, :], axis=1) for idx in index], axis=1)
        agg = np.stack([np.nanmean(boot[:, :, idx, :], axis=2) for idx in index], axis=2)
    pres = np.stack([present[idx].max(axis=0) for idx in index])
    return labels, est, agg, pres


def bootstrap_by_parent(
    paired: pd.DataFrame, *, methods: list[str] | None = None, n_resamples: int, seed: int,
    confidence: float, aggregate: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Khoảng tin cậy percentile cho AUROC và paired win rate, resample theo `parent_case_id`.

    `paired` là `paired_scores` của MỘT split (cột `method, mutation_type, parent_case_id,
    original_score, mutant_score`). Trả `meta`, `intervals` (theo phương pháp × loại + macro) và
    `differences` (mọi cặp phương pháp: phương pháp đứng sau trừ phương pháp đứng trước theo
    `methods`; kèm `prob_positive`). Parent thiếu một loại mutation chỉ vắng ở loại đó.

    `aggregate` (tùy chọn) gộp nhiều "phương pháp" thành một nhãn bằng trung bình số liệu của chúng
    trong CÙNG mỗi lần resample, ví dụ ba run theo model seed của cùng một cấu hình; kết quả khi đó
    chỉ có các nhãn. Dùng để so ghép cặp ablation với baseline qua các run mà không coi seed là mẫu.
    """
    missing = [c for c in PAIRED_REQUIRED if c not in paired.columns]
    if missing:
        raise ValueError(f"paired_scores: thiếu cột {missing}")
    if paired.empty:
        raise ValueError("paired_scores rỗng (empty): không có parent nào để resample")
    if paired.duplicated(["method", "mutation_type", "parent_case_id"]).any():
        raise ValueError("paired_scores: trùng (method, mutation_type, parent_case_id)")
    if n_resamples < 1 or not 0 < confidence < 1:
        raise ValueError("n_resamples phải >= 1 và confidence trong (0, 1)")
    methods = list(methods) if methods is not None else sorted(set(paired["method"]))
    types = sorted(set(paired["mutation_type"]))
    parents = sorted(set(paired["parent_case_id"]))
    index = {name: i for i, name in enumerate(parents)}
    shape = (len(methods), len(types), len(parents))
    orig, mut = np.zeros(shape), np.zeros(shape)
    present = np.zeros(shape, dtype=int)
    m_of, t_of = {m: i for i, m in enumerate(methods)}, {t: i for i, t in enumerate(types)}
    for row in paired[paired["method"].isin(methods)].itertuples(index=False):
        m, t, p = m_of[row.method], t_of[row.mutation_type], index[row.parent_case_id]
        orig[m, t, p], mut[m, t, p], present[m, t, p] = row.original_score, row.mutant_score, 1
    wins = _wins(orig, mut)

    n_parents = len(parents)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n_parents, size=(n_resamples, n_parents))
    estimate = _with_macro(
        _statistics(orig, mut, wins, present, np.ones((1, n_parents), dtype=int)))[0]
    counts = np.stack([np.bincount(draw, minlength=n_parents) for draw in draws])
    # boot: [resample, metric, method, loại + macro]
    boot = _with_macro(_statistics(orig, mut, wins, present, counts))
    if aggregate is not None:
        methods, estimate, boot, present = _aggregate_methods(
            aggregate, m_of, estimate, boot, present)
    scopes = [*types, MACRO]
    low, high = (1 - confidence) / 2, 1 - (1 - confidence) / 2

    def quantiles(values: np.ndarray) -> tuple[float, float, float]:
        finite = values[np.isfinite(values)]
        if len(finite) < 2:
            return float("nan"), float("nan"), float("nan")
        return (float(np.quantile(finite, low)), float(np.quantile(finite, high)),
                float(np.std(finite, ddof=1)))

    def n_for(m: int, s: int) -> int:
        if s < len(types):
            return int(present[m, s].sum())
        return int(present[m].max(axis=0).sum())

    intervals = []
    for m, method in enumerate(methods):
        for s, scope in enumerate(scopes):
            n = n_for(m, s)
            for k, metric in enumerate(BOOTSTRAP_METRICS):
                point = float(estimate[k, m, s])
                if n < MIN_PARENTS or not np.isfinite(point):
                    ci_low = ci_high = se = float("nan")
                    reason = "too_few_parents" if n < MIN_PARENTS else "no_data"
                else:
                    ci_low, ci_high, se = quantiles(boot[:, k, m, s])
                    reason = None
                intervals.append({"method": method, "scope": scope, "metric": metric,
                                  "estimate": point, "ci_low": ci_low, "ci_high": ci_high,
                                  "se": se, "n_parents": n, "null_reason": reason})
    differences = []
    for j in range(len(methods)):
        for i in range(j):
            for s, scope in enumerate(scopes):
                n = min(n_for(i, s), n_for(j, s))
                for k, metric in enumerate(BOOTSTRAP_METRICS):
                    point = float(estimate[k, j, s] - estimate[k, i, s])
                    delta = boot[:, k, j, s] - boot[:, k, i, s]
                    if n < MIN_PARENTS or not np.isfinite(point):
                        ci_low = ci_high = prob = float("nan")
                        reason = "too_few_parents" if n < MIN_PARENTS else "no_data"
                    else:
                        ci_low, ci_high, _ = quantiles(delta)
                        finite = delta[np.isfinite(delta)]
                        prob = float((finite > 0).mean() + 0.5 * (finite == 0).mean())
                        reason = None
                    differences.append({
                        "method_a": methods[j], "method_b": methods[i], "scope": scope,
                        "metric": metric, "estimate": point, "ci_low": ci_low, "ci_high": ci_high,
                        "prob_positive": prob, "n_parents": n, "null_reason": reason})
    return {
        "meta": {"unit": "parent_case_id", "interval": "percentile", "n_resamples": n_resamples,
                 "seed": seed, "confidence": confidence, "n_parents": n_parents,
                 "methods": methods, "mutation_types": types, "note": BOOTSTRAP_NOTE,
                 **({"aggregate": aggregate} if aggregate is not None else {})},
        "intervals": intervals,
        "differences": differences,
    }


def bootstrap_intervals_frame(result: dict[str, Any]) -> pd.DataFrame:
    """Khoảng tin cậy bootstrap theo (phương pháp, loại | macro, metric)."""
    return pd.DataFrame(result["intervals"], columns=INTERVAL_COLUMNS)


def bootstrap_differences_frame(result: dict[str, Any]) -> pd.DataFrame:
    """Chênh lệch ghép cặp giữa các phương pháp (a − b) kèm khoảng bootstrap."""
    return pd.DataFrame(result["differences"], columns=DIFFERENCE_COLUMNS)


# ================================================= thử hoán vị trong cặp: AUROC có khác ngẫu nhiên không

CHANCE_COLUMNS = ["method", "scope", "auroc", "null_mean", "null_sd", "p_value", "n_parents",
                  "n_permutations"]
CHANCE_NOTE = (
    "Giả thuyết không: với mỗi parent, bản gốc và mutant cùng phân phối (hoán đổi nhãn trong từng cặp). "
    "Công thức Mann–Whitney/Hanley–McNeil giả định hai mẫu độc lập nên quá rộng cho dữ liệu ghép cặp "
    "này; null hoán vị trong cặp mới là chuẩn so sánh với 0,5. p-value một phía, có hiệu chỉnh +1."
)


def paired_chance_test(
    paired: pd.DataFrame, *, n_permutations: int, seed: int, methods: list[str] | None = None
) -> pd.DataFrame:
    """Thử hoán vị trong cặp cho AUROC của từng (phương pháp, loại mutation).

    Mỗi lần hoán vị đảo ngẫu nhiên (xác suất 1/2) nhãn bản gốc/mutant trong từng parent rồi tính lại
    AUROC; `p_value` = tỷ lệ lần AUROC null >= AUROC quan sát (một phía, cộng 1 ở tử và mẫu). Không
    tính macro vì các loại dùng chung bản gốc của cùng parent (null độc lập giữa loại sẽ sai).
    """
    missing = [c for c in PAIRED_REQUIRED if c not in paired.columns]
    if missing:
        raise ValueError(f"paired_scores: thiếu cột {missing}")
    if paired.empty:
        raise ValueError("paired_scores rỗng (empty): không có parent nào để hoán vị")
    if n_permutations < 1:
        raise ValueError("n_permutations phải >= 1")
    methods = list(methods) if methods is not None else sorted(set(paired["method"]))
    rng = np.random.default_rng(seed)
    rows = []
    for method in methods:
        for mutation_type in sorted(set(paired["mutation_type"])):
            part = paired[(paired["method"] == method) & (paired["mutation_type"] == mutation_type)]
            part = part.sort_values("parent_case_id")
            if part.empty:
                continue
            orig = part["original_score"].to_numpy(float)
            mut = part["mutant_score"].to_numpy(float)
            flips = rng.random((n_permutations, len(orig))) < 0.5
            o = np.where(flips, mut, orig)
            m = np.where(flips, orig, mut)
            pair = (m[:, None, :] > o[:, :, None]) + 0.5 * (m[:, None, :] == o[:, :, None])
            null = pair.mean(axis=(1, 2))
            observed = paired_auroc(orig, mut)
            rows.append({
                "method": method, "scope": mutation_type, "auroc": observed,
                "null_mean": float(null.mean()), "null_sd": float(null.std(ddof=1)) if len(null) > 1
                else float("nan"),
                "p_value": float((1 + (null >= observed - 1e-12).sum()) / (n_permutations + 1)),
                "n_parents": len(orig), "n_permutations": n_permutations})
    return pd.DataFrame(rows, columns=CHANCE_COLUMNS)
