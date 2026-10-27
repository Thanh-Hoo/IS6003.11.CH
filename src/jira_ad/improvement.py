"""Điều phối giai đoạn cải tiến (2026-10-22): chọn phương án, cross-validation, đánh giá khả năng ứng dụng.

`configs/improvement_plan.yaml` khóa trước: cấu hình dùng, model seed, quy tắc quyết định (chọn trên
validation, Bonferroni theo số ứng viên), giao thức cross-validation và ngưỡng của ba mức ứng dụng.

- Giao thức 1: `run_experiment` cho mỗi model seed (split và mutant V1). A–D chạy lại trong cùng run nên
  chính là phương án cũ để so sánh. Phán quyết chỉ dựa trên validation; test là khám phá.
- Giao thức 2: `run_crossval` trên mọi issue (khám phá), có thêm mutant `skip_status`, `multi_edit`.
- Ứng dụng: từ điểm out-of-fold của mọi issue (inference), đo độ ổn định top-k giữa các seed, thời gian
  chấm, liên hệ với độ dài/nhánh, rồi xếp mức theo ngưỡng khóa trước. Không phải nhãn bất thường thật.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy.stats import spearmanr

from jira_ad import plots
from jira_ad.analysis import run_macro_metrics
from jira_ad.config import (
    MUTATION_TYPES,
    ConfigError,
    RunConfig,
    config_from_dict,
    config_hash,
    load_config,
    resolve_project_root,
)
from jira_ad.crossval import CrossvalResult, run_crossval
from jira_ad.detector import package_versions
from jira_ad.evaluation import (
    MACRO,
    bootstrap_by_parent,
    bootstrap_differences_frame,
    bootstrap_intervals_frame,
)
from jira_ad.graph import build_dfg, trace_tokens, trace_transitions, transition_info
from jira_ad.pipeline import _sha256_file, prepare, run_experiment, write_json_atomic
from jira_ad.types import Trace

PLAN_KEYS = {"config", "model_seeds", "decision", "crossval", "applicability"}
DECISION_KEYS = {"reference", "candidates", "selection_split", "family_alpha"}
CROSSVAL_KEYS = {"folds", "mutation_types"}
CRITERIA_KEYS = {"alert_auroc_lower", "alert_skip_status_auroc", "triage_auroc_lower",
                 "triage_top_fraction", "triage_jaccard", "triage_ms_per_case"}
IMPROVEMENT = "ứng viên cải thiện"
NO_EVIDENCE = "không có bằng chứng"
ALERT, TRIAGE, NOT_READY = "tự động cảnh báo", "bộ lọc ưu tiên rà soát", "chưa đủ để ứng dụng"
REPORT_CONFIDENCE = 0.95


@dataclass(frozen=True)
class MethodDecisionRule:
    reference: str
    candidates: tuple[str, ...]
    selection_split: str
    family_alpha: float

    @property
    def confidence(self) -> float:
        return 1 - self.family_alpha / len(self.candidates)


@dataclass(frozen=True)
class ImprovementPlan:
    path: Path
    sha256: str
    base: RunConfig
    model_seeds: tuple[int, ...]
    decision: MethodDecisionRule
    folds: int
    mutation_types: tuple[str, ...]
    criteria: dict[str, float]


def _keys(raw: Any, allowed: set[str], where: str) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: cần một ánh xạ (mapping)")
    extra, missing = sorted(set(raw) - allowed), sorted(allowed - set(raw))
    if extra:
        raise ConfigError(f"{where}: khóa không hợp lệ {extra}; hợp lệ: {sorted(allowed)}")
    if missing:
        raise ConfigError(f"{where}: thiếu khóa {missing}")
    return raw


def load_improvement_plan(path: Path) -> ImprovementPlan:
    """Đọc và kiểm tra nghiêm ngặt kế hoạch cải tiến; mọi tên phương pháp phải có trong cấu hình."""
    path = Path(path).resolve()
    try:
        text = path.read_bytes()
        raw = _keys(yaml.safe_load(text), PLAN_KEYS, str(path))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Không đọc được {path}: {exc}") from exc
    base = load_config(resolve_project_root(path) / raw["config"])
    seeds = raw["model_seeds"]
    if (not isinstance(seeds, list) or not seeds or len(set(seeds)) != len(seeds)
            or not all(isinstance(s, int) and not isinstance(s, bool) for s in seeds)):
        raise ConfigError(f"model_seeds: cần danh sách số nguyên không lặp, nhận {seeds!r}")
    d = _keys(raw["decision"], DECISION_KEYS, "decision")
    names = [d["reference"], *(d["candidates"] or [])]
    unknown = [n for n in names if n not in base.features.methods]
    if unknown or not d["candidates"]:
        raise ConfigError(f"decision: phương pháp {unknown} không có trong features.methods "
                          f"{list(base.features.methods)} (cần ít nhất một ứng viên)")
    if d["selection_split"] != "validation":
        raise ConfigError("decision.selection_split: chỉ chọn trên validation (không chọn theo test)")
    alpha = d["family_alpha"]
    if isinstance(alpha, bool) or not isinstance(alpha, int | float) or not 0 < alpha < 1:
        raise ConfigError(f"decision.family_alpha={alpha!r}: cần số trong (0, 1)")
    cv = _keys(raw["crossval"], CROSSVAL_KEYS, "crossval")
    if not isinstance(cv["folds"], int) or cv["folds"] < 2:
        raise ConfigError(f"crossval.folds={cv['folds']!r}: cần số nguyên >= 2")
    bad = [t for t in cv["mutation_types"] or [] if t not in MUTATION_TYPES]
    if bad or not cv["mutation_types"]:
        raise ConfigError(f"crossval.mutation_types: {bad} không thuộc {MUTATION_TYPES}")
    criteria = _keys(raw["applicability"], CRITERIA_KEYS, "applicability")
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in criteria.values()):
        raise ConfigError("applicability: mọi ngưỡng phải là số")
    return ImprovementPlan(
        path=path, sha256=hashlib.sha256(text).hexdigest(), base=base, model_seeds=tuple(seeds),
        decision=MethodDecisionRule(d["reference"], tuple(d["candidates"]), d["selection_split"],
                                    float(alpha)),
        folds=cv["folds"], mutation_types=tuple(cv["mutation_types"]),
        criteria={k: float(v) for k, v in criteria.items()},
    )


# ========================================================================== suy luận gộp model seed


def seed_bootstrap(
    frames: dict[str, pd.DataFrame], methods: list[str], *, split: str | None, n_resamples: int,
    seed: int, confidence: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bootstrap theo parent, mỗi phương pháp = trung bình các model seed TRONG từng lần resample.

    `frames` ánh xạ nhãn (run/seed) sang `paired_scores` cùng tập parent. Trả (khoảng, chênh lệch ghép cặp);
    chênh lệch là phương pháp đứng sau trừ phương pháp đứng trước theo thứ tự `methods`.
    """
    parts, aggregate = [], {m: [] for m in methods}
    for label, table in frames.items():
        if split is not None:
            table = table[table["split"] == split]
        table = table[table["method"].isin(methods)]
        parts.append(table.assign(method=table["method"] + "|" + label))
        for method in methods:
            aggregate[method].append(f"{method}|{label}")
    result = bootstrap_by_parent(
        pd.concat(parts, ignore_index=True), methods=[x for v in aggregate.values() for x in v],
        n_resamples=n_resamples, seed=seed, confidence=confidence, aggregate=aggregate)
    return bootstrap_intervals_frame(result), bootstrap_differences_frame(result)


def method_decision(
    paired_by_run: dict[str, pd.DataFrame], *, reference: str, candidates: list[str], split: str,
    confidence: float, n_resamples: int, seed: int,
) -> pd.DataFrame:
    """Phán quyết khóa trước: (ứng viên − reference) về macro AUROC, gộp model seed, bootstrap theo parent."""
    methods = [reference, *candidates]
    intervals, differences = seed_bootstrap(paired_by_run, methods, split=split, n_resamples=n_resamples,
                                            seed=seed, confidence=confidence)
    point = intervals[(intervals.scope == MACRO) & (intervals.metric == "auroc")].set_index("method")
    rows = differences[(differences.scope == MACRO) & (differences.metric == "auroc")
                       & (differences.method_b == reference) & differences.method_a.isin(candidates)]
    out = pd.DataFrame({
        "candidate": rows.method_a.to_numpy(), "reference": reference, "split": split,
        "reference_auroc": point.loc[reference, "estimate"],
        "candidate_auroc": rows.method_a.map(point["estimate"]).to_numpy(),
        "estimate": rows.estimate.to_numpy(), "ci_low": rows.ci_low.to_numpy(),
        "ci_high": rows.ci_high.to_numpy(), "prob_positive": rows.prob_positive.to_numpy(),
        "n_parents": rows.n_parents.to_numpy(), "n_seeds": len(paired_by_run), "confidence": confidence,
    })
    out["verdict"] = np.where(out.ci_low > 0, IMPROVEMENT, NO_EVIDENCE)
    return out


# ============================================================================== khả năng ứng dụng


def applicability_verdicts(summary: pd.DataFrame, criteria: dict[str, float]) -> pd.DataFrame:
    """Xếp mức ứng dụng theo ngưỡng khóa trước; giá trị thiếu (NaN) luôn KHÔNG đạt ngưỡng."""
    out = summary.copy()
    low, skip = out["cv_macro_auroc_ci_low"], out["cv_skip_status_auroc"]
    alert = (low >= criteria["alert_auroc_lower"]) & (skip >= criteria["alert_skip_status_auroc"])
    triage = ((low > criteria["triage_auroc_lower"]) & (out["topk_jaccard"] >= criteria["triage_jaccard"])
              & (out["score_ms_per_case"] < criteria["triage_ms_per_case"]))
    out["verdict"] = np.where(alert, ALERT, np.where(triage, TRIAGE, NOT_READY))
    return out


def _top_ids(part: pd.DataFrame, k: int) -> set[str]:
    ranked = part.sort_values(["anomaly_score", "trace_id"], ascending=[False, True], kind="stable")
    return set(ranked.trace_id.head(k))


def inference_profile(
    cv: CrossvalResult, terminal: dict[str, str], intervals: pd.DataFrame, top_fraction: float
) -> pd.DataFrame:
    """Hồ sơ inference từng phương pháp trên điểm out-of-fold của mọi issue (không có nhãn thật)."""
    rows = []
    n_cases = cv.originals.trace_id.nunique()
    k = max(1, math.ceil(top_fraction * n_cases))
    for method, part in cv.originals.groupby("method", sort=False):
        tops = [_top_ids(p, k) for _, p in part.groupby("model_seed")]
        jaccard = (float(np.mean([len(a & b) / len(a | b) for a, b in combinations(tops, 2)]))
                   if len(tops) > 1 else float("nan"))
        mean_score = part.groupby("trace_id").agg(score=("anomaly_score", "mean"),
                                                  n_events=("n_events", "first"))
        top = mean_score.sort_values("score", ascending=False, kind="stable").head(k)
        ci = intervals[(intervals.method == method) & (intervals.metric == "auroc")].set_index("scope")
        timing = cv.timings[cv.timings.method == method]
        rejected = mean_score.index.map(lambda c: terminal.get(c) == "Rejected")
        rows.append({
            "method": method,
            "cv_macro_auroc": ci.loc[MACRO, "estimate"],
            "cv_macro_auroc_ci_low": ci.loc[MACRO, "ci_low"],
            "cv_macro_auroc_ci_high": ci.loc[MACRO, "ci_high"],
            "cv_skip_status_auroc": ci["estimate"].get("skip_status", float("nan")),
            "topk": k, "topk_jaccard": jaccard,
            "score_ms_per_case": float(timing.score_ms_per_trace.mean()),
            "fit_seconds": float(timing.fit_seconds.mean()),
            "spearman_score_length": float(spearmanr(mean_score.score, mean_score.n_events).statistic),
            "rejected_share_topk": float(np.mean([terminal.get(c) == "Rejected" for c in top.index])),
            "rejected_share_all": float(np.mean(rejected)),
            "median_events_topk": float(top.n_events.median()),
            "median_events_all": float(mean_score.n_events.median()),
        })
    return pd.DataFrame(rows)


def case_drivers(
    cfg: RunConfig, traces: list[Trace], folds: dict[str, int], case_ids: list[str], top_n: int = 3
) -> pd.DataFrame:
    """Với mỗi ca: các chuyển tiếp hiếm nhất so với DFG của các fold train KHÁC fold của nó.

    Mô tả hành vi (surprisal theo đồ thị train), không phải lời giải thích nhân quả của mô hình.
    """
    by_id = {t.trace_id: t for t in traces}
    graphs: dict[int, Any] = {}
    gcfg = cfg.graph
    rows = []
    for case_id in case_ids:
        fold = folds[case_id]
        if fold not in graphs:
            graphs[fold] = build_dfg([t for t in traces if folds[t.trace_id] != fold], gcfg)
        trace = by_id[case_id]
        infos = [(i, s, t, transition_info(graphs[fold], s, t, gcfg.transition_alpha)) for i, (s, t)
                 in enumerate(trace_transitions(trace_tokens(trace, gcfg.encoding), gcfg.add_boundaries))]
        ranked = sorted(infos, key=lambda x: (-x[3].surprisal, x[0]))[:top_n]
        rows.append({
            "case_id": case_id, "fold": fold, "terminal_status": trace.terminal_status,
            "n_events": len(trace), "n_unseen_transitions": sum(x[3].unseen_transition for x in infos),
            "top_transitions": " | ".join(f"{s} → {t} ({info.surprisal:.2f})" for _, s, t, info in ranked),
        })
    return pd.DataFrame(rows)


def method_agreement(cv: CrossvalResult) -> pd.DataFrame:
    """Spearman giữa điểm (trung bình các seed) của các phương pháp trên cùng các issue."""
    wide = cv.originals.groupby(["trace_id", "method"]).anomaly_score.mean().unstack()
    return wide.corr(method="spearman").reset_index()


# ======================================================================================= điều phối


def _write(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, lineterminator="\n")


def _standard_metrics(run_dirs: dict[str, Path]) -> pd.DataFrame:
    runs_dir = next(iter(run_dirs.values())).parent
    frames = [run_macro_metrics(runs_dir, list(run_dirs), split=s).assign(split=s)
              for s in ("validation", "test")]
    macro = pd.concat(frames, ignore_index=True)
    return (macro.groupby(["split", "method"], sort=False)
            .agg(macro_auroc_mean=("macro_auroc", "mean"), macro_auroc_std=("macro_auroc", "std"),
                 macro_ap_mean=("macro_average_precision", "mean"),
                 macro_paired_win_mean=("macro_paired_win_rate", "mean"), n_seeds=("run_id", "nunique"))
            .reset_index())


def run_improvement(plan_path: Path, *, now: datetime | None = None) -> Path:
    """Chạy cả giai đoạn cải tiến, ghi `outputs/improvement/<UTC>-<hash>/` (không ghi đè thư mục có sẵn)."""
    plan = load_improvement_plan(plan_path)
    base, root = plan.base, plan.base.project_root
    plan_rel = plan.path.relative_to(root).as_posix()
    started = (now or datetime.now(UTC)).astimezone(UTC)
    key = hashlib.sha256((plan.sha256 + config_hash(base)).encode()).hexdigest()[:8]
    out = base.output_dir / "improvement" / f"{started:%Y%m%dT%H%M%SZ}-{key}"
    out.mkdir(parents=True, exist_ok=False)
    (out / "figures").mkdir()
    ev = base.evaluation
    manifest: dict[str, Any] = {
        "status": "running", "started_at_utc": started.isoformat(timespec="seconds"),
        "plan": plan_rel, "plan_sha256": plan.sha256,
        "config": base.config_path.relative_to(root).as_posix(), "config_hash": config_hash(base),
        "model_seeds": list(plan.model_seeds), "methods": list(base.features.methods),
        "decision": {"reference": plan.decision.reference, "candidates": list(plan.decision.candidates),
                     "selection_split": plan.decision.selection_split,
                     "confidence": plan.decision.confidence},
        "crossval": {"folds": plan.folds, "mutation_types": list(plan.mutation_types)},
        "criteria": plan.criteria, "environment": package_versions(),
        "rerun_command": f"uv run jira-ad improve --plan {plan_rel}",
    }
    write_json_atomic(out / "manifest.json", manifest)
    try:
        # ------------------------------------------- giao thức 1: split V1, ba model seed
        run_dirs: dict[str, Path] = {}
        for seed in plan.model_seeds:
            raw = base.as_dict(include_defaults=True)
            raw["run"]["seed"] = seed
            cfg = config_from_dict(raw, root, base.config_path)
            run_dir = run_experiment(
                cfg, experiment={"name": "improvement", "plan": plan_rel, "changes": {},
                                 "note": "Giao thức 1 của giai đoạn cải tiến (A–D = phương án cũ)."},
                rerun_command=manifest["rerun_command"])
            run_dirs[run_dir.name] = run_dir
        manifest["standard_runs"] = list(run_dirs)
        paired = {rid: pd.read_csv(d / "paired_scores.csv") for rid, d in run_dirs.items()}
        rule = plan.decision
        common = {"reference": rule.reference, "candidates": list(rule.candidates),
                  "confidence": rule.confidence, "n_resamples": ev.bootstrap_resamples,
                  "seed": ev.bootstrap_seed}
        _write(method_decision(paired, split=rule.selection_split, **common), out / "decision_validation.csv")
        _write(method_decision(paired, split="test", **common), out / "exploratory_test.csv")
        _write(_standard_metrics(run_dirs), out / "standard_metrics.csv")
        methods = list(base.features.methods)
        for split in ("validation", "test"):
            intervals, differences = seed_bootstrap(
                paired, methods, split=split, n_resamples=ev.bootstrap_resamples, seed=ev.bootstrap_seed,
                confidence=REPORT_CONFIDENCE)
            _write(intervals, out / f"standard_bootstrap_intervals_{split}.csv")
            _write(differences, out / f"standard_bootstrap_differences_{split}.csv")

        # ------------------------------------------- giao thức 2: cross-validation (khám phá)
        traces = prepare(base).traces
        cv = run_crossval(base, traces, methods=methods, folds=plan.folds,
                          model_seeds=list(plan.model_seeds), mutation_types=list(plan.mutation_types))
        for name, frame in (("cv_metrics", cv.metrics), ("cv_paired_scores", cv.paired),
                            ("cv_ledger", cv.ledger), ("cv_timings", cv.timings),
                            ("cv_original_scores", cv.originals)):
            _write(frame, out / f"{name}.csv")
        by_seed = {str(s): cv.paired[cv.paired.model_seed == s] for s in plan.model_seeds}
        cv_intervals, cv_differences = seed_bootstrap(
            by_seed, methods, split=None, n_resamples=ev.bootstrap_resamples, seed=ev.bootstrap_seed,
            confidence=REPORT_CONFIDENCE)
        _write(cv_intervals, out / "cv_bootstrap_intervals.csv")
        _write(cv_differences, out / "cv_bootstrap_differences.csv")

        # ------------------------------------------- inference và mức ứng dụng
        terminal = {t.trace_id: t.terminal_status for t in traces}
        profile = inference_profile(cv, terminal, cv_intervals, plan.criteria["triage_top_fraction"])
        _write(profile, out / "inference_profile.csv")
        _write(applicability_verdicts(profile, plan.criteria), out / "applicability.csv")
        _write(method_agreement(cv), out / "method_agreement.csv")
        k = int(profile.topk.iloc[0])
        tops = []
        for method, part in cv.originals.groupby("method", sort=False):
            mean = part.groupby("trace_id").anomaly_score.mean().sort_values(ascending=False, kind="stable")
            drivers = case_drivers(base, traces, cv.folds, list(mean.index[:k]))
            tops.append(drivers.assign(method=method, rank=range(1, len(drivers) + 1),
                                       score=mean.iloc[:k].to_numpy()))
        _write(pd.concat(tops, ignore_index=True), out / "top_cases.csv")

        macro = cv_intervals[(cv_intervals.scope == MACRO) & (cv_intervals.metric == "auroc")]
        plots.plot_interval_forest(macro, "Macro AUROC (cross-validation, 161 issue, khoảng 95%)").savefig(
            out / "figures" / "cv_macro_auroc.png", dpi=130, bbox_inches="tight")
        per_type = cv_intervals[(cv_intervals.scope != MACRO) & (cv_intervals.metric == "auroc")]
        plots.plot_auroc_heatmap(per_type, "AUROC theo loại mutant (cross-validation)").savefig(
            out / "figures" / "cv_auroc_by_type.png", dpi=130, bbox_inches="tight")

        manifest["counts"] = {"n_issues": len(traces), "n_cv_mutants": int(
            (cv.ledger.status == "created").sum())}
        manifest["artifacts"] = {
            p.relative_to(out).as_posix(): {"sha256": _sha256_file(p), "size_bytes": p.stat().st_size}
            for p in sorted(out.rglob("*")) if p.is_file() and p.name != "manifest.json"}
        manifest.update(status="completed", finished_at_utc=datetime.now(UTC).isoformat(timespec="seconds"))
        write_json_atomic(out / "manifest.json", manifest)
        return out
    except BaseException as exc:
        manifest.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
        write_json_atomic(out / "manifest.json", json.loads(json.dumps(manifest, default=str)))
        raise
