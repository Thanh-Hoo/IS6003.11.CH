"""Cross-validation theo issue cho đánh giá bán tổng hợp (giao thức cải tiến, 2026-10-22).

Mọi issue lần lượt nằm trong một fold held-out đúng một lần; mô hình của fold chỉ fit trên các fold còn
lại (không bao giờ thấy ca held-out của nó). Nhờ vậy cả 161 issue đều làm parent cho mutant, thay vì
31 ca test của holdout V1, nên khoảng tin cậy hẹp hơn. Điểm của mỗi fold được chuẩn hóa z theo phân bố
điểm TRAIN của chính mô hình fold đó trước khi gộp, vì điểm Isolation Forest của các mô hình khác nhau
không cùng thang. Mutant giống nhau cho mọi phương pháp và mọi model seed.

Giao thức này dùng cả ca test V1 (đã được xem nhiều lần) nên kết quả của nó là KHÁM PHÁ, không phải xác
nhận; việc chọn phương án vẫn theo quy tắc khóa trước trên validation của V1.
"""

from __future__ import annotations

import dataclasses
import hashlib
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from jira_ad.config import RunConfig
from jira_ad.detector import fit_detector, score_traces
from jira_ad.evaluation import evaluate_semisynthetic, metrics_frame, paired_frame
from jira_ad.mutations import generate_mutations
from jira_ad.types import Trace

FOLD_SEED_STEP = 100  # seed mutation của fold f = mutation.test_seed + 100 * f


@dataclass
class CrossvalResult:
    originals: pd.DataFrame  # điểm z của mọi issue (out-of-fold) theo (model_seed, method)
    mutants: pd.DataFrame
    ledger: pd.DataFrame
    paired: pd.DataFrame  # paired_scores + model_seed
    metrics: pd.DataFrame  # metrics_by_type + model_seed
    timings: pd.DataFrame
    folds: dict[str, int]


def cv_folds(traces: list[Trace], folds: int, seed: int) -> dict[str, int]:
    """Gán fold: trong từng nhánh `terminal_status`, sắp theo SHA-256 của `seed:cv:case_id` rồi chia vòng tròn
    (bộ đếm nối tiếp giữa các nhánh), nên fold cân bằng cả tổng lẫn theo nhánh và không phụ thuộc thứ tự."""
    if folds < 2:
        raise ValueError(f"folds={folds}: cần ít nhất 2 fold")
    if folds > len(traces):
        raise ValueError(f"folds={folds} lớn hơn số issue ({len(traces)})")
    strata: dict[str, list[str]] = {}
    for trace in traces:
        strata.setdefault(str(trace.terminal_status), []).append(trace.trace_id)
    out, counter = {}, 0
    for label in sorted(strata):
        for case_id in sorted(strata[label], key=lambda c: hashlib.sha256(
                f"{seed}:cv:{c}".encode()).hexdigest()):
            out[case_id] = counter % folds
            counter += 1
    return out


def _standardise(scores: pd.DataFrame, train_raw: np.ndarray) -> pd.DataFrame:
    std = float(train_raw.std()) or 1.0
    out = scores.rename(columns={"anomaly_score": "raw_score"})
    out["anomaly_score"] = (out["raw_score"] - float(train_raw.mean())) / std
    return out


def run_crossval(
    cfg: RunConfig, traces: list[Trace], *, methods: list[str], folds: int, model_seeds: list[int],
    mutation_types: list[str],
) -> CrossvalResult:
    """Chạy k-fold theo issue cho mọi (model seed, fold, phương pháp) và đánh giá trên toàn bộ issue."""
    assignment = cv_folds(traces, folds, cfg.split.seed)
    held = {f: [t for t in traces if assignment[t.trace_id] == f] for f in range(folds)}
    mcfg = dataclasses.replace(cfg.mutation, types=tuple(mutation_types))
    mutated = {f: generate_mutations(held[f], mcfg, cfg.mutation.test_seed + FOLD_SEED_STEP * f,
                                     split=f"fold{f}") for f in range(folds)}
    ledger = pd.concat([mutated[f].ledger for f in range(folds)], ignore_index=True)

    originals, mutants, timings, metrics, paired = [], [], [], [], []
    for seed in model_seeds:
        seed_orig, seed_mut = [], []
        for fold in range(folds):
            train = [t for t in traces if assignment[t.trace_id] != fold]
            for method in methods:
                started = time.perf_counter()
                bundle = fit_detector(train, cfg, method, seed)
                fit_seconds = time.perf_counter() - started
                train_raw = score_traces(bundle, train)["anomaly_score"].to_numpy()
                started = time.perf_counter()
                orig = score_traces(bundle, held[fold])
                mut = score_traces(bundle, mutated[fold].traces)
                n_scored = len(orig) + len(mut)
                score_ms = 1000 * (time.perf_counter() - started) / max(n_scored, 1)
                for frame, sink in ((orig, seed_orig), (mut, seed_mut)):
                    sink.append(_standardise(frame, train_raw).assign(fold=fold, model_seed=seed))
                timings.append({"model_seed": seed, "fold": fold, "method": method,
                                "n_train": len(train), "n_scored": n_scored,
                                "fit_seconds": fit_seconds, "score_ms_per_trace": score_ms})
        o, m = pd.concat(seed_orig, ignore_index=True), pd.concat(seed_mut, ignore_index=True)
        result = evaluate_semisynthetic(o, m, ledger)
        metrics.append(metrics_frame(result).assign(model_seed=seed))
        paired.append(paired_frame(result).assign(model_seed=seed))
        originals.append(o)
        mutants.append(m)
    return CrossvalResult(
        originals=pd.concat(originals, ignore_index=True),
        mutants=pd.concat(mutants, ignore_index=True), ledger=ledger,
        paired=pd.concat(paired, ignore_index=True), metrics=pd.concat(metrics, ignore_index=True),
        timings=pd.DataFrame(timings), folds=assignment,
    )
