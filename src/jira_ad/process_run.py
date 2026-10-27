"""Điều phối giai đoạn 2: `jira-ad process` ghi `outputs/process/<UTC>-<hash8>/` có manifest.

Mỗi bước là một thư mục con (`a_quant/<cohort>/`, …). Thư mục run không bao giờ bị ghi đè; mọi bảng
là CSV/JSON tất định (chạy lại cùng cấu hình cho cùng nội dung). Fingerprint các input khóa (dataset,
cấu hình giai đoạn 1, run cũ) được đo trước và sau khi chạy; khác nhau ⇒ run `failed`.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import pandas as pd

from jira_ad import bpr, ranking
from jira_ad.centrality import (
    BOUNDARY,
    activity_dfg_train,
    centrality_table,
    centrality_vs_delay,
    improvement_priorities,
    status_dfg,
)
from jira_ad.conformance import (
    ReferenceModel,
    arc_table,
    compare_replays,
    deviation_breakdown,
    discover,
    flag_cases,
    flag_summary,
    quality,
    reference_bpmn_xml,
    reference_net,
    replay_cases,
    state_lanes,
    status_event_log,
    unobserved_arc_precision,
    work_system_table,
)
from jira_ad.data import find_input_file, fingerprint_file
from jira_ad.norms import (
    fit_norms,
    late_by_case,
    late_by_role,
    late_by_state,
    late_visits,
    top_late,
)
from jira_ad.pipeline import write_json_atomic
from jira_ad.process_config import ProcessConfig, load_process_config, process_config_hash
from jira_ad.process_figures import bpmn_dot, petri_dot, render_dot, status_dfg_dot
from jira_ad.process_metrics import (
    dwell_by_state,
    fpy,
    gate_roles,
    kpi_asis,
    little_window,
    pt_wt_ranges,
    rejected_cost,
    weekly_little,
)
from jira_ad.status_log import base_config_for, build_status_log, case_table, load_cohort

FROZEN_FILES = ("configs/baseline.yaml", "configs/actions.yaml", "configs/experiments.yaml",
                "configs/improvement_plan.yaml")
FROZEN_TREES = ("dataset", "outputs/runs", "outputs/improvement")
PACKAGES = ("numpy", "pandas", "networkx", "scikit-learn", "gensim", "pm4py")


class RunExistsError(FileExistsError):
    """Thư mục run đã tồn tại; không ghi đè."""


class FrozenInputChanged(RuntimeError):
    """Một input bị khóa (dataset, cấu hình giai đoạn 1, run cũ) đổi trong lúc chạy."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_fingerprint(root: Path) -> dict[str, Any]:
    """sha256 các file khóa; với cây thư mục: số file, băm danh sách (đường dẫn, kích thước) và manifest."""
    out: dict[str, Any] = {}
    for rel in FROZEN_FILES:
        path = root / rel
        out[rel] = _sha256(path) if path.is_file() else None
    for rel in FROZEN_TREES:
        base = root / rel
        if not base.is_dir():
            out[rel] = None
            continue
        files = sorted(p for p in base.rglob("*") if p.is_file() and p.name != ".DS_Store")
        listing = hashlib.sha256()
        content = hashlib.sha256()
        for p in files:
            r = p.relative_to(base).as_posix()
            listing.update(f"{r}\t{p.stat().st_size}\n".encode())
            if rel == "dataset" or p.name == "manifest.json":
                content.update(f"{r}\t{_sha256(p)}\n".encode())
        out[rel] = {"n_files": len(files), "listing_sha256": listing.hexdigest(),
                    "content_sha256": content.hexdigest()}
    return out


def _versions() -> dict[str, str | None]:
    found: dict[str, str | None] = {"python": platform.python_version()}
    for name in PACKAGES:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = None
    return found


def code_fingerprint() -> dict[str, Any]:
    """sha256 từng file nguồn của package `jira_ad` và băm tổng (để phân biệt run cùng cấu hình khác mã)."""
    package = Path(__file__).resolve().parent
    files = {f"jira_ad/{p.relative_to(package).as_posix()}": _sha256(p)
             for p in sorted(package.rglob("*.py"))}
    total = hashlib.sha256("".join(f"{k}\t{v}\n" for k, v in files.items()).encode()).hexdigest()
    return {"sha256": total, "files": files}


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_json(payload: dict, path: Path) -> None:
    write_json_atomic(path, payload)


def step_a_quant(cfg: ProcessConfig, out: Path) -> None:
    """Bước A (Ch2): status log + phân tích định lượng, từng cohort riêng (không trộn)."""
    for cohort_name in cfg.cohorts:
        cohort = load_cohort(cfg, cohort_name)
        log = build_status_log(cohort.events, cohort.traces, cfg)
        cases = case_table(log, cohort.traces)
        d = out / "a_quant" / cohort_name
        _write_csv(log, d / "status_log.csv")
        _write_csv(cases, d / "cases.csv")
        _write_csv(pt_wt_ranges(log, cfg), d / "pt_wt_ranges.csv")
        _write_csv(dwell_by_state(log), d / "dwell_by_state.csv")
        _write_csv(weekly_little(cases), d / "weekly_little.csv")
        _write_json(little_window(cases), d / "little.json")
        _write_json(fpy(log), d / "fpy.json")
        _write_csv(rejected_cost(cases), d / "rejected_cost.csv")
        _write_csv(gate_roles(log), d / "gate_roles.csv")
        _write_csv(kpi_asis(log, cases, cfg), d / "kpi_asis.csv")


def step_b_norms(cfg: ProcessConfig, out: Path) -> None:
    """Bước B (Ch3): định mức, trễ theo trạng thái/vai trò/ca; centrality DFG trạng thái và activity."""
    cohort = load_cohort(cfg, cfg.primary_cohort)
    log = build_status_log(cohort.events, cohort.traces, cfg)
    cases = case_table(log, cohort.traces)
    n = cfg.norms
    norms = fit_norms(log, percentile=n.percentile, min_visits=n.min_visits,
                      explicit_days=dict(n.explicit_days))
    late = late_visits(log, norms)
    by_state = late_by_state(late)
    d = out / "b_norms"
    _write_csv(norms, d / "norms.csv")
    _write_csv(late, d / "late_visits.csv")
    _write_csv(by_state, d / "late_by_state.csv")
    _write_csv(late_by_role(late), d / "late_by_role.csv")
    _write_csv(late_by_case(late, cases, percentile=n.percentile), d / "late_by_case.csv")
    _write_csv(top_late(late, cfg.centrality.top_late), d / "top_late.csv")
    alpha = cfg.centrality.pagerank_alpha
    sdfg = status_dfg(log)
    cent_status = centrality_table(sdfg, pagerank_alpha=alpha)
    _write_csv(cent_status, d / "centrality_status.csv")
    adfg, train_ids = activity_dfg_train(cohort)
    _write_csv(pd.DataFrame({"case_id": sorted(train_ids)}), d / "train_ids.csv")
    _write_csv(centrality_table(adfg, pagerank_alpha=alpha, drop_nodes=BOUNDARY),
               d / "centrality_activity.csv")
    joined = centrality_vs_delay(cent_status, by_state)
    _write_csv(joined, d / "centrality_vs_delay.csv")
    _write_csv(improvement_priorities(joined, gate_roles(log), late,
                                      top_n_cases=cfg.centrality.example_cases), d / "priorities.csv")
    render_dot(status_dfg_dot(sdfg, title="DFG trạng thái — số lần, trung vị thời gian nằm ở trạng thái "
                                          "nguồn (ngày làm việc)"), d / "status_dfg")


BPMN_NAMES = {"CREATE": "Bug được tạo", "DONE": "Đã sửa (DONE)", "Rejected": "Từ chối (Rejected)"}
WAITING_APPROVAL = "chờ duyệt mô hình chuẩn (reference_model.approved: false)"


def step_c_conformance(cfg: ProcessConfig, out: Path) -> None:
    """Bước C (Ch1, Ch5): Work System, mô hình chuẩn (BPMN + Petri net), khai phá, cờ quy tắc, replay."""
    cohort = load_cohort(cfg, cfg.primary_cohort)
    log = build_status_log(cohort.events, cohort.traces, cfg)
    cases = case_table(log, cohort.traces)
    model = cfg.reference
    d = out / "c_conformance"
    _write_csv(work_system_table(cohort, log, cases), d / "work_system.csv")
    lanes = state_lanes(log, model)
    _write_json(lanes, d / "lanes.json")
    (d / "reference_model.bpmn").write_text(reference_bpmn_xml(model, lanes, BPMN_NAMES), encoding="utf-8")
    render_dot(bpmn_dot(model, lanes, title="Mô hình chuẩn (giả định của tác giả) — lane theo vai trò"),
               d / "reference_model")
    net, im, fm = reference_net(model)
    render_dot(petri_dot(net, im, fm, title="Petri net của mô hình chuẩn"), d / "reference_net")
    _write_csv(arc_table(log, model), d / "arc_table.csv")
    flags = flag_cases(log, cfg.flags)
    _write_csv(flags, d / "flags.csv")
    _write_csv(flag_summary(flags, n_cases=len(cases)), d / "flag_summary.csv")
    events = status_event_log(log)
    rows = []
    for spec in cfg.discovery:
        dnet, dim, dfm = discover(events, spec.miner, dict(spec.params))
        rows.append({"id": spec.id, "miner": spec.miner, "params": json.dumps(dict(spec.params)),
                     **quality(events, dnet, dim, dfm)})
        render_dot(petri_dot(dnet, dim, dfm, title=f"Mô hình khai phá: {spec.id}"), d / "models" / spec.id)
    _write_csv(pd.DataFrame(rows), d / "discovery_quality.csv")
    if not cfg.reference_model.approved:
        _write_json({"reference_replay": WAITING_APPROVAL}, d / "status.json")
        return
    branch = cases[["case_id", "terminal_status"]]
    replay = replay_cases(events, net, im, fm).merge(branch, on="case_id", how="left")
    _write_csv(replay, d / "replay_cases.csv")
    _write_json(replay_summary(replay, quality(events, net, im, fm)), d / "replay_summary.json")
    replays = {"reference": replay}
    for spec in cfg.alternative_models:
        alt = cfg.alternative(spec.id)
        anet, aim, afm = reference_net(alt)
        replays[spec.id] = replay_cases(events, anet, aim, afm).merge(branch, on="case_id", how="left")
        _write_csv(replays[spec.id], d / f"replay_cases_{spec.id}.csv")
        render_dot(petri_dot(anet, aim, afm, title=f"Mô hình phụ (KHÔNG phải mô hình chuẩn): {spec.label}"),
                   d / "models" / spec.id)
    comparison, gained = compare_replays(replays, reference="reference")
    _write_csv(comparison, d / "replay_comparison.csv")
    _write_csv(gained.merge(branch, on="case_id", how="left"), d / "replay_gained_cases.csv")
    _write_csv(unobserved_arc_precision(log, model), d / "unobserved_arc_precision.csv")
    _write_csv(deviation_breakdown(log, arcs=ReferenceModel.parse_arcs(cfg.deviation_report.arcs)),
               d / "deviation_breakdown.csv")
    arcs = arc_table(log, model, example_cases=5)
    _write_csv(arcs[~arcs["in_model"]].head(cfg.centrality.top_late), d / "deviations_top.csv")
    _write_json({"reference_replay": "đã chạy (reference_model.approved: true)"}, d / "status.json")


def replay_summary(replay: pd.DataFrame, model_quality: dict) -> dict:
    by = {}
    for branch, g in [("all", replay), *replay.groupby("terminal_status")]:
        by[branch] = {"n_cases": len(g), "mean_trace_fitness": float(g["trace_fitness"].mean()),
                      "n_fit": int(g["is_fit"].sum()), "share_fit": float(g["is_fit"].mean())}
    unfit = replay.loc[~replay["is_fit"], "trace_fitness"]
    nan = float("nan")
    return {"by_branch": by, "model_quality": model_quality,
            "unfit": {"n_cases": len(unfit), "mean_trace_fitness": float(unfit.mean()) if len(unfit) else nan,
                      "min_trace_fitness": float(unfit.min()) if len(unfit) else nan}}


AUTOMATED_LABEL = "tự động (commit/MR đầu tiên)"


def step_d_bpr(cfg: ProcessConfig, out: Path) -> None:
    """Bước D (Ch4): kiểm chứng ứng viên, what-if trên log, KPI AS-IS/TO-BE, BPMN TO-BE, pilot."""
    cohort = load_cohort(cfg, cfg.primary_cohort)
    log = build_status_log(cohort.events, cohort.traces, cfg)
    cases = case_table(log, cohort.traces)
    b, day = cfg.bpr, 86_400.0
    norms = fit_norms(log, percentile=cfg.norms.percentile, min_visits=cfg.norms.min_visits,
                      explicit_days=dict(cfg.norms.explicit_days))
    late = late_visits(log, norms)
    checks = pd.DataFrame([
        bpr.check_early_triage(cases, log, min_share=b.early_triage_min_share,
                               min_median_days=b.early_triage_min_median_days),
        bpr.check_auto_transition(log, cohort.events, min_share=b.auto_transition_min_share),
        bpr.check_merge(log, source="INVESTIGATED", target="To Do", max_days=b.merge_max_days,
                        min_share=b.merge_min_share),
        bpr.check_role_dependency(log, state=b.po_state, role="PO", n_boot=b.bootstrap_n, seed=b.seed),
        bpr.check_duplicate(cohort.events_full, cases, pattern=b.duplicate_pattern,
                            min_cases=b.duplicate_min_cases, min_median_days=b.duplicate_min_median_days),
        bpr.check_investigating_state(pt_wt_ranges(log, cfg), min_width_pp=b.investigating_min_width_pp),
        bpr.check_fast_track(cases, flag_cases(log, cfg.flags), max_fpy_drop=b.fast_track_max_fpy_drop),
    ])
    d = out / "d_bpr"
    _write_csv(checks, d / "checks.csv")
    _write_csv(bpr.problem_table(cfg.bpr_candidates, checks), d / "problems.csv")
    _write_csv(bpr.state_excess_by_role(late, state=b.po_state), d / "todo_excess_by_role.csv")
    _write_csv(bpr.state_excess_by_role_and_target(late, log, state=b.po_state),
               d / "todo_excess_by_role_target.csv")
    cap = float(norms.set_index("state").loc[b.po_state, "norm_days"])
    capped = bpr.whatif_cap_state(log, state=b.po_state, cap_days=cap).set_index("case_id")["ct_work_s_tobe"]
    capped_cases = cases.assign(ct_work_s=cases["case_id"].map(capped))
    # Kịch bản khả thi (nhất quán TO-BE: vẫn có Investigating → Rejected) và cận trên (rà soát độc lập I2).
    feasible = bpr.whatif_reject_at_investigation_end(cases, log)
    upper = bpr.whatif_early_triage(cases, log)
    feasible_ct = bpr.whatif_reject_at_investigation_end(capped_cases, log)["per_case"]["ct_work_s_tobe"]
    upper_ct = bpr.whatif_early_triage(capped_cases, log)["per_case"]["ct_work_s_tobe"]
    auto = bpr.whatif_auto_transition(log, cohort.events, work_states=cfg.states.work)
    reference, tobe_states = cfg.reference.activities, cfg.tobe.activities
    new_states = tobe_states - reference
    path = bpr.whatif_tobe_path(
        log, drop=tuple(sorted(reference - tobe_states - {cfg.tobe.start})),
        insert_after={a: t for a, t in cfg.tobe.arcs if t in new_states and a in reference},
        entry=next(t for a, t in cfg.tobe.arcs if a == cfg.tobe.start))
    cap_text = f"chờ ở {b.po_state} không quá định mức P75 ({cap:.2f} ngày làm việc)"
    feasible_text = ("Ca Rejected đã qua điều tra được quyết ngay khi rời To Investigate (bỏ chờ ở "
                     f"INVESTIGATED và sau đó), ca không qua điều tra giữ nguyên; {cap_text}")
    upper_text = (f"CẬN TRÊN: mọi ca Rejected được quyết ở lần đổi trạng thái đầu (kể cả ca cần điều tra); "
                  f"{cap_text}")
    rows = [
        {"kpi": "ct_work_median_days", "asis": cases["ct_work_s"].median() / day,
         "tobe": feasible_ct.median() / day, "unit": "ngày làm việc",
         "scenario": "từ chối khi kết thúc điều tra + giới hạn chờ To Do", "assumption": feasible_text},
        {"kpi": "ct_work_p90_days", "asis": cases["ct_work_s"].quantile(0.9) / day,
         "tobe": feasible_ct.quantile(0.9) / day, "unit": "ngày làm việc",
         "scenario": "từ chối khi kết thúc điều tra + giới hạn chờ To Do", "assumption": feasible_text},
        {"kpi": "ct_work_median_days_upper", "asis": cases["ct_work_s"].median() / day,
         "tobe": upper_ct.median() / day, "unit": "ngày làm việc",
         "scenario": "early_triage cận trên + giới hạn chờ To Do", "assumption": upper_text},
        {"kpi": "rejected_issue_days_work", "asis": feasible["asis_rejected_issue_days"],
         "tobe": feasible["tobe_rejected_issue_days"], "unit": "ngày-issue làm việc",
         "scenario": "từ chối khi kết thúc điều tra",
         "assumption": "Ca Rejected đã qua điều tra được quyết ngay khi rời To Investigate; "
                       "ca không qua điều tra giữ nguyên"},
        {"kpi": "rejected_issue_days_work_upper", "asis": upper["asis_rejected_issue_days"],
         "tobe": upper["tobe_rejected_issue_days"], "unit": "ngày-issue làm việc",
         "scenario": "early_triage cận trên",
         "assumption": "CẬN TRÊN: thông tin để từ chối đã có từ lần đổi trạng thái đầu cho mọi ca"},
        {"kpi": "pt_share_main", "asis": auto["pt_share_asis"], "tobe": auto["pt_share_tobe"],
         "unit": "tỉ lệ", "scenario": "auto_transition",
         "assumption": "Chỉ phần To Do sau liên kết commit/MR đầu tiên được tính là làm (cải thiện ĐO LƯỜNG, "
                       "CT không đổi); chưa tính phần Investigating vì chưa đo được"},
        {"kpi": "status_changes_per_case", "asis": path["changes_per_case_asis"],
         "tobe": path["changes_per_case_tobe"], "unit": "lần/ca", "scenario": "đường TO-BE",
         "assumption": "Đường AS-IS của mỗi ca chuyển sang đường TO-BE: bỏ " + ", ".join(sorted(
             reference - tobe_states - {cfg.tobe.start})) + ", thêm " + ", ".join(sorted(new_states))
                       + ", đi qua Inbox tường minh; thời gian không đổi"},
    ]
    comparison_path = out / "c_conformance" / "replay_comparison.csv"
    if comparison_path.is_file():
        comparison = pd.read_csv(comparison_path).set_index("model")
        if len(cfg.alternative_models):
            alt = cfg.alternative_models[0].id
            rows.append({"kpi": "conformance_share_fit", "asis": comparison.loc["reference", "share_fit"],
                         "tobe": comparison.loc[alt, "share_fit"], "unit": "tỉ lệ ca khớp",
                         "scenario": "fast_track",
                         "assumption": "Mô hình chính thức cho phép luồng nhanh CREATE → To Do; "
                                       "hành vi thực tế "
                                       "không đổi, chỉ đổi chuẩn so sánh"})
    kpi = bpr.kpi_asis_tobe(rows)
    _write_csv(kpi, d / "kpi_asis_tobe.csv")
    _write_csv(bpr.pilot_plan(cfg.pilot, kpi), d / "pilot.csv")
    tobe, tm = cfg.tobe, cfg.tobe_model
    automated = set(type(tobe).parse_arcs(tm.automated_arcs))
    labels = {arc: AUTOMATED_LABEL for arc in automated}
    (d / "tobe_model.bpmn").write_text(reference_bpmn_xml(tobe, dict(tm.lanes), BPMN_NAMES, labels),
                                       encoding="utf-8")
    render_dot(bpmn_dot(tobe, dict(tm.lanes), title="Mô hình TO-BE (thiết kế đề xuất, chưa triển khai)",
                        automated=automated), d / "tobe_model")


STRUCTURAL = ["in_degree", "out_degree", "in_strength", "out_strength", "betweenness", "closeness_undirected",
              "eigenvector_undirected", "pagerank"]


def _representations(cfg: ProcessConfig, cohort, d: Path) -> str:
    """So Node2Vec (run V1, không fit lại) với đặc trưng cấu trúc trên bài toán nhóm nghiệp vụ activity."""
    rk = cfg.ranking
    adfg, _ = activity_dfg_train(cohort)
    structure = centrality_table(adfg, pagerank_alpha=cfg.centrality.pagerank_alpha,
                                 drop_nodes=BOUNDARY).set_index("node")[STRUCTURAL]
    labels = ranking.group_labels(structure.index, {g: tuple(a) for g, a in rk.activity_groups.items()})
    _write_csv(labels.rename_axis("activity").reset_index(), d / "groups.csv")
    v1 = cfg.resolve(cfg.paths.v1_run)
    if not (v1 / "manifest.json").is_file():
        return f"không có run V1 ở {cfg.paths.v1_run}: bỏ phần Node2Vec"
    vectors = ranking.load_v1_vectors(v1)
    nodes = [n for n in structure.index if n in vectors.index]
    reps = {"node2vec_v1": vectors.loc[nodes], "structural": ranking.standardize(structure.loc[nodes])}
    clusters, classify = [], []
    for name, x in reps.items():
        clusters.append(ranking.cluster_scan(x, labels, k_min=rk.k_min, k_max=rk.k_max, seed=rk.seed)
                        .assign(representation=name))
        classify.append({"representation": name, "n_nodes": len(nodes),
                         **ranking.loo_knn(x, labels,
                                           metric="cosine" if name == "node2vec_v1" else "euclidean")})
    classify.append({"representation": "majority_baseline", "n_nodes": len(nodes),
                     **ranking.majority_baseline(labels.loc[nodes])})
    _write_csv(pd.concat(clusters, ignore_index=True), d / "clusters.csv")
    _write_csv(pd.DataFrame(classify), d / "classify.csv")
    return f"đã dùng embedding của {cfg.paths.v1_run} (đã kiểm fingerprint, không fit lại)"


def step_e_ranking(cfg: ProcessConfig, out: Path) -> None:
    """Bước E (Ch6): học biểu diễn (tái sử dụng V1), hồ sơ nhiều chiều, xếp hạng nên xem trước."""
    rk = cfg.ranking
    cohort = load_cohort(cfg, cfg.primary_cohort)
    log = build_status_log(cohort.events, cohort.traces, cfg)
    cases = case_table(log, cohort.traces)
    d = out / "e_ranking"
    status = {"representation": _representations(cfg, cohort, d)}
    replay_path = out / "c_conformance" / "replay_cases.csv"
    replay = pd.read_csv(replay_path) if replay_path.is_file() else None
    flags = pd.read_csv(out / "c_conformance" / "flags.csv")
    late = pd.read_csv(out / "b_norms" / "late_by_case.csv")
    imp = cfg.resolve(cfg.paths.improvement_dir)
    oof = None
    if (imp / "cv_original_scores.csv").is_file():
        oof = ranking.load_oof_scores(imp, rk.oof_method)
        status["markov"] = (f"điểm out-of-fold {rk.oof_method} từ {cfg.paths.improvement_dir} (sha256 "
                            f"{_sha256(imp / 'cv_original_scores.csv')[:16]}…)")
    else:
        status["markov"] = f"không có {cfg.paths.improvement_dir}/cv_original_scores.csv: bỏ chiều M_markov"
    status["replay"] = "có" if replay is not None else "không có (replay chưa duyệt): bỏ chiều lệch mô hình"
    profile, dims = ranking.build_profile(cases, replay, flags, late, cohort.events, oof,
                                         assignee_activities=rk.assignee_activities)
    groups = ranking.peer_groups(cases, bins=rk.length_bins)
    ranked = ranking.rank_cases(profile, dims, groups, p=rk.peer_percentile, labels=ranking.DIMENSION_LABELS)
    k = max(1, math.ceil(rk.top_share * len(ranked)))
    _write_csv(profile, d / "profile.csv")
    _write_csv(ranked, d / "ranking.csv")
    _write_csv(ranked.head(k), d / "top.csv")
    _write_json(ranking.topk_stability(profile, dims, groups, p=rk.peer_percentile, top_share=rk.top_share,
                                       n_boot=rk.n_boot, seed=rk.seed), d / "stability.json")
    consensus = ranking.topk_consensus(profile, dims, groups, p=rk.peer_percentile, top_share=rk.top_share,
                                       n_boot=rk.n_boot, seed=rk.seed, threshold=rk.consensus_share)
    cols = ["case_id", "rank", "terminal_status", "n_events", "n_exceed", "reasons"]
    _write_csv(consensus.merge(ranked[cols], on="case_id", how="left"), d / "consensus.csv")
    score = ranked["n_exceed"] + ranked["mean_pct"]
    top = ranked.head(k)
    corr = {"dims": dims, "k": k,
            "spearman_score_vs_n_events": float(score.corr(ranked["n_events"], method="spearman")),
            "spearman_n_exceed_vs_n_events": float(ranked["n_exceed"].corr(ranked["n_events"],
                                                                           method="spearman")),
            "share_rejected_top": float((top["terminal_status"] == "Rejected").mean()),
            "share_rejected_all": float((ranked["terminal_status"] == "Rejected").mean()),
            "median_events_top": float(top["n_events"].median()),
            "median_events_all": float(ranked["n_events"].median())}
    if "markov_raw" in ranked:
        corr["spearman_markov_raw_vs_n_events"] = float(ranked["markov_raw"].corr(ranked["n_events"],
                                                                                  method="spearman"))
        corr["spearman_markov_adj_vs_n_events"] = float(ranked["markov_adj"].corr(ranked["n_events"],
                                                                                  method="spearman"))
    _write_json(corr, d / "correlations.json")
    sequences = {c: v for c, v in zip(cases["case_id"], cases["variant"], strict=True)}
    by_trace = {t.trace_id: " > ".join(t.activities) for t in cohort.traces}
    text = {c: f"Trạng thái: CREATE > {sequences[c]} | Hoạt động: {by_trace[c]}" for c in sequences}
    blinded, key = ranking.blind_review(ranked, text, n_top=rk.blind_top, n_random=rk.blind_random,
                                        seed=rk.seed)
    _write_csv(blinded, d / "blind_review.csv")
    _write_csv(key, d / "blind_review_key.csv")
    _write_json(status, d / "status.json")


def _run_steps(cfg: ProcessConfig, out: Path) -> None:
    step_a_quant(cfg, out)
    step_b_norms(cfg, out)
    step_c_conformance(cfg, out)
    step_d_bpr(cfg, out)
    step_e_ranking(cfg, out)


def _inputs(cfg: ProcessConfig) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for cohort in cfg.cohorts:
        base = base_config_for(cfg, cohort)
        found[cohort] = fingerprint_file(find_input_file(base.data, base.project_root, cohort),
                                         base.project_root)
    base_path = cfg.resolve(cfg.paths.base_config)
    found["base_config"] = {"path": cfg.paths.base_config, "sha256": _sha256(base_path)}
    return found


def run_process(config_path: Path, *, now: datetime | None = None) -> Path:
    cfg = load_process_config(config_path)
    digest = process_config_hash(cfg)
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    out = cfg.resolve(cfg.paths.output_root) / f"{moment:%Y%m%dT%H%M%SZ}-{digest[:8]}"
    if out.exists():
        raise RunExistsError(f"Thư mục run đã tồn tại, không ghi đè: {out}")
    out.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "run_id": out.name, "status": "running", "created_utc": moment.isoformat(),
        "config_path": Path(config_path).resolve().relative_to(cfg.project_root).as_posix(),
        "config_hash": digest, "config": cfg.as_dict(), "inputs": _inputs(cfg),
        "frozen_before": frozen_fingerprint(cfg.project_root), "versions": _versions(),
        "code": code_fingerprint(),
    }
    _write_json(manifest, out / "manifest.json")
    try:
        _run_steps(cfg, out)
        manifest["frozen_after"] = frozen_fingerprint(cfg.project_root)
        changed = sorted(k for k in manifest["frozen_before"]
                         if manifest["frozen_before"][k] != manifest["frozen_after"][k])
        if changed:
            raise FrozenInputChanged(f"Input bị khóa đã đổi trong lúc chạy: {changed}")
    except BaseException as exc:
        manifest.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
        _write_json(manifest, out / "manifest.json")
        raise
    manifest["files"] = {
        p.relative_to(out).as_posix(): _sha256(p)
        for p in sorted(out.rglob("*")) if p.is_file() and p.name != "manifest.json"
    }
    manifest["status"] = "completed"
    _write_json(manifest, out / "manifest.json")
    return out
