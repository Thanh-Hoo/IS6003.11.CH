"""Điều phối các giai đoạn: `prepare`, `run_experiment`, `compare_runs`, `score_raw_csv`."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
import yaml

from jira_ad.analysis import build_case_review, describe_case
from jira_ad.config import RunConfig, config_hash
from jira_ad.data import (
    find_input_file,
    fingerprint_file,
    load_raw_events,
    read_events_csv,
)
from jira_ad.detector import (
    DetectorBundle,
    fit_detector,
    package_versions,
    save_bundle,
    score_traces,
)
from jira_ad.evaluation import (
    CHANCE_NOTE,
    bootstrap_by_parent,
    bootstrap_differences_frame,
    bootstrap_intervals_frame,
    evaluate_semisynthetic,
    metrics_frame,
    paired_chance_test,
    paired_frame,
)
from jira_ad.mutations import (
    POSITIVE_CONTROL_SPLIT,
    POSITIVE_CONTROL_TYPE,
    generate_mutations,
    generate_positive_control,
)
from jira_ad.preprocess import (
    build_core_view,
    build_traces,
    load_action_rules,
    mapping_coverage,
    normalize_events,
    parse_action_rules,
)
from jira_ad.splits import make_case_splits, split_hash, temporal_report, write_split_manifest
from jira_ad.types import CaseSplits, Trace

PREPARE_SCHEMA_VERSION = 1


class PrepareError(RuntimeError):
    """Thư mục prepare đã có nhưng nội dung khác bản tính lại (không ghi đè)."""


@dataclass(frozen=True)
class PrepareResult:
    directory: Path
    reused: bool
    audit: dict[str, Any]
    splits: CaseSplits
    traces: list[Trace]

    def traces_for(self, split: str) -> list[Trace]:
        """Trace của một split (`train`, `validation`, `test`), theo thứ tự id trong manifest."""
        ids = {"train": self.splits.train_ids, "validation": self.splits.validation_ids,
               "test": self.splits.test_ids}
        if split not in ids:
            raise ValueError(f"split {split!r} không hợp lệ; hợp lệ: {sorted(ids)}")
        by_id = {t.trace_id: t for t in self.traces}
        return [by_id[case_id] for case_id in ids[split]]


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Ghi JSON qua file tạm rồi đổi tên; NaN/Inf bị từ chối thay vì ghi âm thầm."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _prepare_key(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _files_equal(left: Path, right: Path) -> bool:
    names_left = sorted(p.name for p in left.iterdir())
    names_right = sorted(p.name for p in right.iterdir())
    return names_left == names_right and all(
        (left / n).read_bytes() == (right / n).read_bytes() for n in names_left
    )


def prepare(cfg: RunConfig) -> PrepareResult:
    """Chuẩn hóa -> core view -> split cố định cho cohort đã cấu hình, ghi artifact trước khi học.

    Thư mục đích `outputs/prepared/<cohort>-<key>/` được đặt tên theo fingerprint input, hash quy
    tắc action, chính sách tiền xử lý và cấu hình split. Chạy lại với cùng đầu vào tính lại và so
    byte với bản có sẵn (an toàn, không ghi đè); đầu vào khác tạo thư mục khác.
    """
    cohort = cfg.data.cohort
    rules = load_action_rules(_require_path(cfg))
    path = find_input_file(cfg.data, cfg.project_root, cohort)
    fingerprint = {"cohort": cohort, **fingerprint_file(path, cfg.project_root)}
    events = normalize_events(load_raw_events(cfg.data, cfg.project_root), cfg.preprocess, rules)
    core = build_core_view(events, cfg.preprocess, rules)
    splits = make_case_splits(core.traces, cfg.split)

    pre, sp = cfg.preprocess, cfg.split
    settings = {
        "preprocess": {"view": pre.view, "terminal_statuses": list(pre.terminal_statuses),
                       "noise_policy": pre.noise_policy},
        "split": {"seed": sp.seed, "train_fraction": sp.train_fraction,
                  "validation_fraction": sp.validation_fraction,
                  "test_fraction": sp.test_fraction, "stratify": sp.stratify},
    }
    if sp.strategy != "random":  # chỉ ghi khi khác mặc định: khóa prepare của V1 giữ nguyên
        settings["split"]["strategy"] = sp.strategy
    key = _prepare_key({
        "schema": PREPARE_SCHEMA_VERSION, "input_sha256": fingerprint["sha256"],
        "cohort": cohort, "actions_sha256": rules.sha256, **settings,
    })
    by_id = {t.trace_id: t for t in core.traces}
    sizes = {"train": splits.train_ids, "validation": splits.validation_ids,
             "test": splits.test_ids}
    audit = {
        "stage": "prepare",
        "prepare_key": key,
        "cohort": cohort,
        "input": fingerprint,
        "action_rules": {"relative_path": pre.actions_file, "sha256": rules.sha256},
        "settings": settings,
        **core.audit,
        "split": {
            "split_hash": split_hash(splits),
            "sizes": {name: len(ids) for name, ids in sizes.items()},
            "terminal_status_by_split": {
                name: {s: sum(by_id[i].terminal_status == s for i in ids)
                       for s in sorted({by_id[i].terminal_status for i in ids})}
                for name, ids in sizes.items()
            },
            **({"temporal": temporal_report(splits, core.traces)}
               if sp.strategy == "temporal" else {}),
        },
        "mapping": _mapping_summary(mapping_coverage(events)),
    }

    final = cfg.output_dir / "prepared" / f"{cohort}-{key}"
    temp = final.parent / f".tmp-{final.name}-{os.getpid()}"
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True)
    try:
        write_split_manifest(splits, core.traces, cfg.split, temp / "split_manifest.csv")
        core.case_exclusions.to_csv(temp / "exclusions.csv", index=False, lineterminator="\n")
        core.event_exclusions.to_csv(temp / "event_exclusions.csv", index=False,
                                     lineterminator="\n")
        mapping_coverage(events).to_csv(temp / "mapping_coverage.csv", index=False,
                                        lineterminator="\n")
        write_json_atomic(temp / "preprocess_audit.json", audit)
        if final.exists():
            if not _files_equal(temp, final):
                raise PrepareError(
                    f"{final} đã có nhưng khác nội dung tính lại; không ghi đè. "
                    "Xóa thư mục này nếu muốn tạo lại."
                )
            return PrepareResult(final, True, audit, splits, core.traces)
        os.replace(temp, final)
        return PrepareResult(final, False, audit, splits, core.traces)
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def _require_path(cfg: RunConfig) -> Path:
    if cfg.preprocess.actions_path is None:  # load_config luôn gán; chỉ xảy ra khi dựng tay
        raise PrepareError("preprocess.actions_path chưa được resolve")
    return cfg.preprocess.actions_path


def _mapping_summary(coverage) -> dict[str, Any]:
    fallback = coverage[coverage["is_fallback"]]
    return {
        "n_distinct_raw_actions": int(len(coverage)),
        "n_fallback_raw_actions": int(len(fallback)),
        "n_fallback_events": int(fallback["n_events"].sum()),
        "fallback_raw_actions": sorted(fallback["raw_action"].tolist()),
    }


# =============================================================================== run_experiment

PRIMARY_SPLIT = "test"
CONTROL_NOTE = (
    "Đối chứng dương: xáo toàn bộ phần nội bộ của parent thuộc validation để kiểm tra bộ máy phát "
    "hiện được thứ tự bị phá; không phải loại mutation V1, không chạy trên test và không dùng để "
    "chọn cấu hình."
)
REQUIRED_STAGES = ("prepare", "fit", "mutate", "score", "evaluate", "review", "finalize")


class RunError(RuntimeError):
    """Run không hoàn tất đúng nghĩa (ví dụ không tính được metric)."""


class RunExistsError(RunError):
    """Thư mục run đã tồn tại; không ghi đè mặc định."""


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_info(root: Path) -> dict[str, Any] | None:
    """Commit và cờ dirty nếu thư mục nằm trong repo Git; không thì None (không báo giả)."""
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              check=False)
    try:
        head = git("rev-parse", "HEAD")
    except OSError:
        return None
    if head.returncode != 0:
        return None
    dirty = bool(git("status", "--porcelain").stdout.strip())
    return {"commit": head.stdout.strip(), "dirty": dirty}


def _create_run_dir(runs_root: Path, run_id: str, fail_on_existing: bool) -> Path:
    """Tạo thư mục run mới; va chạm thì lỗi hoặc (nếu cho phép) thêm hậu tố, không ghi đè."""
    runs_root.mkdir(parents=True, exist_ok=True)
    candidate, suffix = runs_root / run_id, 1
    while True:
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            if fail_on_existing:
                raise RunExistsError(
                    f"Thư mục run đã tồn tại: {candidate}; không ghi đè "
                    "(đặt run.fail_on_existing_output: false để tạo thư mục có hậu tố)"
                ) from None
            suffix += 1
            candidate = runs_root / f"{run_id}-{suffix}"


class _RunLog:
    """run.log: mỗi dòng `thời điểm UTC | giai đoạn | thông điệp`, ghi và flush ngay."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def write(self, stage: str, message: str) -> None:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} | {stage} | {message}\n")


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")


def _clean_dfg(graph: nx.DiGraph) -> nx.DiGraph:
    """Bản DFG chỉ gồm thuộc tính GraphML-serializable (bỏ thuộc tính cấp đồ thị)."""
    clean = nx.DiGraph()
    for node, data in graph.nodes(data=True):
        clean.add_node(node, count=int(data["count"]), out_count=int(data["out_count"]),
                       boundary=bool(data["boundary"]))
    for u, v, weight in graph.edges(data="weight"):
        clean.add_edge(u, v, weight=int(weight))
    return clean


def _split_frame(frame: pd.DataFrame, split_of: dict[str, str], key: str) -> pd.DataFrame:
    out = frame.copy()
    out.insert(3, "split", out[key].map(split_of))
    return out


def run_experiment(
    cfg: RunConfig, *, now: datetime | None = None, experiment: dict[str, Any] | None = None,
    rerun_command: str | None = None,
) -> Path:
    """prepare → fit A–D trên train → mutant holdout → score → evaluate → artifact có provenance.

    Trả thư mục run chứa `manifest.json`. Lỗi giữa chừng để `status: failed` kèm giai đoạn và lỗi
    (rồi ném lại lỗi gốc); `status: completed` chỉ khi mọi artifact đã ghi và metric tính được.
    `now` chỉ để test cố định thời điểm bắt đầu (run_id). `experiment`/`rerun_command` do bộ điều
    phối thực nghiệm cấp để manifest ghi rõ nguồn gốc. Không ghi đè run có sẵn.
    """
    clock = time.perf_counter
    t_start = clock()
    started = (now or datetime.now(UTC)).astimezone(UTC)
    chash = config_hash(cfg)
    run_dir = _create_run_dir(cfg.output_dir / "runs", f"{started:%Y%m%dT%H%M%SZ}-{chash[:8]}",
                              cfg.run.fail_on_existing_output)
    log = _RunLog(run_dir / "run.log")
    manifest: dict[str, Any] = {
        "run_id": run_dir.name,
        "status": "running",
        "started_at_utc": _utc(started),
        "finished_at_utc": None,
        "config_hash": chash,
        "cohort": cfg.data.cohort,
        "config_path": cfg.config_path.relative_to(cfg.project_root).as_posix(),
        "rerun_command": rerun_command or (
            "uv run jira-ad run --config "
            f"{cfg.config_path.relative_to(cfg.project_root).as_posix()}"),
        "methods": list(cfg.features.methods),
        "seeds": {"split": cfg.split.seed, "model": cfg.run.seed,
                  "validation_mutation": cfg.mutation.validation_seed,
                  "test_mutation": cfg.mutation.test_seed},
        "git": _git_info(cfg.project_root),
        "environment": package_versions(),
        "stage_timings": {},
    }
    if experiment is not None:
        manifest["experiment"] = experiment
    manifest_path = run_dir / "manifest.json"
    write_json_atomic(manifest_path, manifest)
    log.write("run", f"bắt đầu {run_dir.name}")
    stage = "prepare"
    stage_start = t_start
    try:
        def finish(name: str) -> None:
            nonlocal stage_start
            now_t = clock()
            manifest["stage_timings"][name] = round(now_t - stage_start, 4)
            stage_start = now_t
            write_json_atomic(manifest_path, manifest)
            log.write(name, f"xong trong {manifest['stage_timings'][name]}s")

        # ------------------------------------------------------------------ prepare
        prepared = prepare(cfg)
        rules = load_action_rules(cfg.preprocess.actions_path)
        for name in ("split_manifest.csv", "exclusions.csv", "preprocess_audit.json"):
            shutil.copy2(prepared.directory / name, run_dir / name)
        for name in ("event_exclusions.csv", "mapping_coverage.csv"):
            (run_dir / "tables").mkdir(exist_ok=True)
            shutil.copy2(prepared.directory / name, run_dir / "tables" / name)
        (run_dir / "config.resolved.yaml").write_text(
            yaml.safe_dump(cfg.as_dict(), sort_keys=True, allow_unicode=True), encoding="utf-8")
        event_log = {"kind": "event_log", **prepared.audit["input"]}
        rules_file = cfg.preprocess.actions_path
        action_rules = {"kind": "action_rules", "relative_path": cfg.preprocess.actions_file,
                        "sha256": rules.sha256, "size_bytes": rules_file.stat().st_size}
        write_json_atomic(run_dir / "input_files.json", [event_log, action_rules])  # type: ignore[arg-type]
        manifest.update(
            input_files=[event_log, action_rules],
            action_rules_hash=rules.sha256,
            split_hash=prepared.audit["split"]["split_hash"],
            prepared_dir=prepared.directory.relative_to(cfg.project_root).as_posix(),
        )
        train, validation, test = (prepared.traces_for(s) for s in ("train", "validation", "test"))
        manifest["counts"] = {"train": len(train), "validation": len(validation), "test": len(test)}
        split_of = {t.trace_id: s for s, ts in (("train", train), ("validation", validation),
                                                  ("test", test)) for t in ts}
        finish("prepare")

        # ---------------------------------------------------------------------- fit
        stage = "fit"
        bundles: dict[str, DetectorBundle] = {}
        for method in cfg.features.methods:
            bundle = fit_detector(train, cfg, method)
            bundles[method] = bundle
            model_dir = run_dir / "models" / method
            save_bundle(bundle, model_dir / "bundle.joblib")
            write_json_atomic(model_dir / "feature_schema.json", bundle.encoder.schema())
            write_json_atomic(model_dir / "fit_metadata.json", bundle.metadata)
            log.write("fit", f"{method}: {bundle.metadata['n_features']} feature, "
                             f"{bundle.metadata['fit_seconds']:.2f}s")
        first = next(iter(bundles.values())).encoder
        nx.write_graphml(_clean_dfg(first.graph), run_dir / "graph.graphml")
        embedders = [b.encoder for b in bundles.values() if b.encoder.embedding is not None]
        if embedders:
            lead = embedders[0]
            matrix = lead.embedding.matrix
            vectors = pd.DataFrame(matrix, columns=[f"d{i:02d}" for i in range(matrix.shape[1])])
            vectors.insert(0, "node", list(lead.embedding.vocabulary))
            vectors.to_parquet(run_dir / "node_vectors.parquet", index=False)
            write_json_atomic(run_dir / "walk_sample.json",
                              {"walks": lead.walk_sample, "summary": lead.walk_summary})  # type: ignore[arg-type]
            write_json_atomic(run_dir / "embedding_diagnostics.json", {
                "embedding": lead.embedding_summary, "walks": lead.walk_summary,
                "provenance": lead.embedding.provenance})
            manifest["embedding_shared"] = all(
                np.array_equal(e.embedding.matrix, matrix) for e in embedders)
        else:
            manifest["embedding_shared"] = None
        finish("fit")

        # -------------------------------------------------------------------- mutate
        stage = "mutate"
        mutated = {
            "validation": generate_mutations(validation, cfg.mutation, cfg.mutation.validation_seed,
                                             split="validation"),
            "test": generate_mutations(test, cfg.mutation, cfg.mutation.test_seed, split="test"),
        }
        ledger = pd.concat([mutated[s].ledger for s in ("validation", "test")], ignore_index=True)
        _write_csv(ledger, run_dir / "mutation_ledger.csv")
        mutant_traces = [t for s in ("validation", "test") for t in mutated[s].traces]
        mutant_split = {t.trace_id: s for s in ("validation", "test") for t in mutated[s].traces}
        pd.DataFrame([{
            "mutation_id": t.trace_id, "parent_case_id": t.parent_case_id,
            "split": mutant_split[t.trace_id], "n_events": len(t),
            "terminal_status": t.terminal_status,
            "activities": json.dumps(list(t.activities), ensure_ascii=False),
            "roles": json.dumps(list(t.roles), ensure_ascii=False),
            "event_ids": json.dumps(list(t.event_ids), ensure_ascii=False),
        } for t in mutant_traces]).to_parquet(run_dir / "mutations.parquet", index=False)
        control = generate_positive_control(
            validation, cfg.evaluation.positive_control_seed, POSITIVE_CONTROL_SPLIT)
        _write_csv(control.ledger, run_dir / "positive_control_ledger.csv")
        manifest["counts"].update(
            mutants_validation=len(mutated["validation"].traces),
            mutants_test=len(mutated["test"].traces),
            positive_control_mutants=len(control.traces))
        finish("mutate")

        # --------------------------------------------------------------------- score
        stage = "score"
        holdout = validation + test
        originals_by, mutants_by = [], []
        for bundle in bundles.values():
            originals_by.append(score_traces(bundle, holdout))
            mutants_by.append(score_traces(bundle, mutant_traces))
        originals = _split_frame(pd.concat(originals_by, ignore_index=True), split_of, "trace_id")
        mutants = _split_frame(pd.concat(mutants_by, ignore_index=True), mutant_split, "trace_id")
        for name, frame in (("originals", originals), ("mutants", mutants)):
            ids = {m: frozenset(frame.loc[frame.method == m, "trace_id"]) for m in bundles}
            if len(set(ids.values())) != 1:
                raise RunError(f"Các phương pháp không chấm cùng một tập {name}")
        control_scores = _split_frame(
            pd.concat([score_traces(b, control.traces) for b in bundles.values()],
                      ignore_index=True),
            {t.trace_id: POSITIVE_CONTROL_SPLIT for t in control.traces}, "trace_id")
        (run_dir / "scores").mkdir(exist_ok=True)
        originals.to_parquet(run_dir / "scores" / "originals.parquet", index=False)
        mutants.to_parquet(run_dir / "scores" / "mutants.parquet", index=False)
        finish("score")

        # ------------------------------------------------------------------- evaluate
        stage = "evaluate"
        results = {}
        for split in ("validation", "test"):
            results[split] = evaluate_semisynthetic(
                originals[originals.split == split], mutants[mutants.split == split],
                ledger[ledger.split == split])
            for method in bundles:
                rows = [r for r in results[split]["metrics_by_type"] if r["method"] == method]
                if not any(r["auroc"] is not None for r in rows):
                    reasons = sorted({str(r["null_reason"]) for r in rows})
                    raise RunError(
                        f"Không tính được metric nào cho {method} trên {split}: {reasons}")
        frames = [metrics_frame(results[s]).assign(split=s) for s in results]
        _write_csv(pd.concat(frames, ignore_index=True)[["split", *frames[0].columns[:-1]]],
                   run_dir / "metrics_by_type.csv")
        pframes = [paired_frame(results[s]).assign(split=s) for s in results]
        _write_csv(pd.concat(pframes, ignore_index=True)[["split", *pframes[0].columns[:-1]]],
                   run_dir / "paired_scores.csv")
        ev = cfg.evaluation
        boot = {s: bootstrap_by_parent(
            paired_frame(results[s]), methods=list(bundles), n_resamples=ev.bootstrap_resamples,
            seed=ev.bootstrap_seed, confidence=ev.confidence) for s in results}
        for name, build in (("bootstrap_intervals.csv", bootstrap_intervals_frame),
                            ("bootstrap_differences.csv", bootstrap_differences_frame)):
            tables = [build(boot[s]).assign(split=s) for s in boot]
            _write_csv(pd.concat(tables, ignore_index=True)[["split", *tables[0].columns[:-1]]],
                       run_dir / name)
        chance_tables = [paired_chance_test(
            paired_frame(results[s]), n_permutations=ev.permutations, seed=ev.bootstrap_seed,
            methods=list(bundles)).assign(split=s) for s in results]
        _write_csv(pd.concat(chance_tables, ignore_index=True)[["split", *chance_tables[0].columns[:-1]]],
                   run_dir / "chance_test.csv")
        control_result = evaluate_semisynthetic(
            originals[originals.split == POSITIVE_CONTROL_SPLIT], control_scores, control.ledger)
        control_table = metrics_frame(control_result)
        control_paired = paired_frame(control_result)
        control_table["auroc_ci_low"] = control_table["auroc_ci_high"] = np.nan
        if len(control_paired):
            control_boot = bootstrap_by_parent(
                control_paired, methods=list(bundles), n_resamples=ev.bootstrap_resamples,
                seed=ev.bootstrap_seed, confidence=ev.confidence)
            ci = bootstrap_intervals_frame(control_boot)
            ci = ci[(ci.scope == POSITIVE_CONTROL_TYPE) & (ci.metric == "auroc")].set_index("method")
            control_table["auroc_ci_low"] = control_table["method"].map(ci["ci_low"])
            control_table["auroc_ci_high"] = control_table["method"].map(ci["ci_high"])
        _write_csv(control_table, run_dir / "positive_control.csv")
        _write_csv(control_paired, run_dir / "positive_control_paired_scores.csv")
        write_json_atomic(run_dir / "metrics.json", {
            "label_definition": results["test"]["label_definition"],
            "primary_split": PRIMARY_SPLIT,
            "model_seeds": [cfg.run.seed],
            "protocol": {**manifest["seeds"], "design_injected_rate": 0.5,
                         "note": "validation chỉ để kiểm tra/chọn cấu hình; test là holdout cuối"},
            "splits": {s: {k: v for k, v in r.items() if k != "paired_scores"}
                       for s, r in results.items()},
            "bootstrap": {s: boot[s]["meta"] for s in boot},
            "chance_test": {"n_permutations": ev.permutations, "seed": ev.bootstrap_seed,
                            "note": CHANCE_NOTE},
            "positive_control": {
                "split": POSITIVE_CONTROL_SPLIT, "seed": ev.positive_control_seed,
                "mutation_type": POSITIVE_CONTROL_TYPE,
                "n_parents": int((control.ledger.status == "created").sum()),
                "n_skipped": int((control.ledger.status == "skipped").sum()),
                "note": CONTROL_NOTE},
        })
        finish("evaluate")

        # ---------------------------------------------------------------------- review
        stage = "review"
        primary = "D_hybrid" if "D_hybrid" in bundles else list(bundles)[-1]
        primary_scores = originals[(originals.method == primary) & (originals.split == "test")]
        blinded, key = build_case_review(primary_scores[["trace_id", "anomaly_score"]], test,
                                         seed=cfg.run.seed, method=primary)
        _write_csv(blinded, run_dir / "case_review_blinded.csv")
        _write_csv(key, run_dir / "case_review_key.csv")
        by_id = {t.trace_id: t for t in test}
        (run_dir / "tables").mkdir(exist_ok=True)
        write_json_atomic(run_dir / "tables" / "case_evidence.json", {
            row.review_id: describe_case(by_id[row.case_id], bundles[primary])
            for row in key.itertuples()})
        manifest["review"] = {"method": primary, "n_cases": len(key),
                              "n_top": int((key.group == "top").sum()),
                              "n_random": int((key.group == "random").sum()), "seed": cfg.run.seed}
        finish("review")

        # --------------------------------------------------------------------- finalize
        stage = "finalize"
        summary = []
        for method, bundle in bundles.items():
            part = originals[(originals.method == method) & (originals.split == "test")]
            summary.append({
                "method": method, "n_features": bundle.metadata["n_features"],
                "n_constant_features": bundle.metadata["n_constant_features"],
                "fit_seconds": bundle.metadata["fit_seconds"],
                "test_score_mean": part.anomaly_score.mean(),
                "test_score_std": part.anomaly_score.std(),
                "test_unseen_node_ratio_mean": part.unseen_node_ratio.mean(),
                "test_unseen_transition_ratio_mean": part.unseen_transition_ratio.mean(),
            })
        _write_csv(pd.DataFrame(summary), run_dir / "tables" / "model_summary.csv")
        write_json_atomic(run_dir / "tables" / "graph_diagnostics.json",
                          bundles[next(iter(bundles))].encoder.schema()["graph"])
        for directory in ("figures", "notebooks_executed"):
            (run_dir / directory).mkdir(exist_ok=True)
        finish("finalize")
        missing = [s for s in REQUIRED_STAGES if s not in manifest["stage_timings"]]
        if missing:
            raise RunError(f"Thiếu giai đoạn: {missing}")
        log.write("run", "completed")
        manifest["artifacts"] = {
            p.relative_to(run_dir).as_posix(): {
                "sha256": _sha256_file(p), "size_bytes": p.stat().st_size}
            for p in sorted(run_dir.rglob("*")) if p.is_file() and p.name != "manifest.json"
        }
        manifest.update(status="completed",
                        finished_at_utc=_utc(started + timedelta(seconds=clock() - t_start)))
        write_json_atomic(manifest_path, manifest)
        return run_dir
    except BaseException as exc:
        manifest.update(
            status="failed",
            finished_at_utc=_utc(started + timedelta(seconds=clock() - t_start)),
            error={"stage": stage, "type": type(exc).__name__, "message": str(exc)},
        )
        log.write(stage, f"FAILED {type(exc).__name__}: {exc}")
        write_json_atomic(manifest_path, manifest)
        raise


# ==================================================================================== compare


def _protocol_and_model(run_dir: Path, manifest: dict[str, Any]) -> tuple[dict[str, Any], str]:
    resolved = yaml.safe_load((run_dir / "config.resolved.yaml").read_text(encoding="utf-8"))
    event_log = next(i for i in manifest["input_files"] if i["kind"] == "event_log")
    protocol = {
        "input_sha256": event_log["sha256"], "cohort": manifest["cohort"],
        "split_hash": manifest["split_hash"], "action_rules_hash": manifest["action_rules_hash"],
        "preprocess": {k: resolved["preprocess"][k]
                       for k in ("view", "terminal_statuses", "noise_policy")},
        "split": resolved["split"], "mutation": resolved["mutation"],
        "methods": manifest["methods"],
    }
    model = {k: v for k, v in resolved.items() if k not in ("run", "notebooks", "project")}
    model["run"] = {k: v for k, v in resolved["run"].items()
                    if k not in ("seed", "fail_on_existing_output")}
    return protocol, _hash_obj(model)


def _hash_obj(obj: Any) -> str:
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _stat(values: list[float]) -> tuple[float | None, float | None]:
    clean = [v for v in values if v is not None and not pd.isna(v)]
    if not clean:
        return None, None
    return float(np.mean(clean)), (float(np.std(clean, ddof=1)) if len(clean) > 1 else None)


def compare_runs(runs_dir: Path, split: str = PRIMARY_SPLIT) -> dict[str, Any]:
    """Tổng hợp các run đã hoàn tất, nhóm theo protocol dữ liệu/split/đánh giá và cấu hình mô hình.

    Run khác dữ liệu, split, quy tắc, mutation hoặc siêu tham số mô hình (trừ model seed) nằm ở
    nhóm khác và không bao giờ được lấy trung bình chung. Std là độ ổn định theo model seed
    (ddof=1), không phải khoảng tin cậy quần thể; chỉ có khi nhóm có >= 2 model seed khác nhau
    (chạy lại cùng một seed chỉ giữ run mới nhất, các run cũ nằm ở `superseded`).
    """
    runs_dir = Path(runs_dir)
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    skipped = []
    for run_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            skipped.append({"run_id": run_dir.name, "reason": "no_manifest"})
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "completed":
            skipped.append({"run_id": run_dir.name, "reason": f"status={manifest.get('status')}"})
            continue
        protocol, model_id = _protocol_and_model(run_dir, manifest)
        key = (_hash_obj(protocol), model_id)
        group = groups.setdefault(key, {"protocol_id": key[0], "model_config_id": key[1],
                                        "protocol": protocol, "_by_seed": {}, "_experiments": set()})
        group["_experiments"].add(manifest.get("experiment", {}).get("name", "run"))
        table = pd.read_csv(run_dir / "metrics_by_type.csv")
        # Cùng model seed chạy lại cho cùng kết quả: chỉ giữ run mới nhất, không tính là seed độc lập.
        group["_by_seed"].setdefault(manifest["seeds"]["model"], []).append(
            (run_dir.name, table[table["split"] == split]))
    out_groups = []
    for group in groups.values():
        kept, tables, superseded = [], [], []
        for seed in sorted(group.pop("_by_seed").items()):
            *older, (latest, table) = sorted(seed[1], key=lambda item: item[0])
            kept.append(latest)
            tables.append(table)
            superseded += [name for name, _ in older]
        group["runs"], group["superseded"] = kept, superseded
        group["experiments"] = sorted(group.pop("_experiments"))
        stacked = pd.concat(tables, ignore_index=True)
        rows = []
        grouped = stacked.groupby(["method", "mutation_type"], sort=True)
        for (method, mutation_type), part in grouped:
            row: dict[str, Any] = {"method": method, "mutation_type": mutation_type,
                                   "n_runs": int(len(part)), "split": split}
            for column, name in (("auroc", "auroc"), ("average_precision", "average_precision"),
                                 ("paired_win_rate", "paired_win_rate")):
                row[f"{name}_mean"], row[f"{name}_std"] = _stat(part[column].tolist())
            rows.append(row)
        group["rows"] = rows
        out_groups.append(group)
    return {"split": split, "groups": out_groups, "skipped": skipped}


def comparison_frame(result: dict[str, Any]) -> pd.DataFrame:
    """Bảng phẳng của `compare_runs` (comparison.csv); mỗi dòng gắn protocol và model config."""
    records = [{"protocol_id": g["protocol_id"], "model_config_id": g["model_config_id"], **row}
               for g in result["groups"] for row in g["rows"]]
    return pd.DataFrame(records)


# ===================================================================================== score


def score_raw_csv(bundle: DetectorBundle, input_csv: Path, output_csv: Path) -> pd.DataFrame:
    """Chấm điểm CSV thô (schema như dataset) bằng bundle đã lưu; KHÔNG fit, không sửa bundle.

    Cohort, quy tắc action và chính sách tiền xử lý lấy từ bundle (không từ file YAML hiện tại).
    Chỉ ca có core view hợp lệ được chấm; ca khác xuất kèm lý do. Lỗi schema/dữ liệu thì không
    ghi output.
    """
    input_csv, output_csv = Path(input_csv), Path(output_csv)
    cfg = bundle.encoder.cfg
    rules = parse_action_rules(bundle.metadata["action_rules_text"], "bundle")
    events = normalize_events(
        read_events_csv(input_csv, cfg.data.cohort, input_csv.parent), cfg.preprocess, rules)
    if cfg.preprocess.view == "core":
        core = build_core_view(events, cfg.preprocess, rules)
        traces, excluded = core.traces, core.case_exclusions
    else:
        traces, excluded = build_traces(events, cfg.preprocess, rules), None
    scored = score_traces(bundle, traces)
    frame = pd.DataFrame({
        "case_id": scored["trace_id"], "scored": True, "reason": "", "method": bundle.method,
        "anomaly_score": scored["anomaly_score"], "n_events": scored["n_events"],
        "unseen_node_ratio": scored["unseen_node_ratio"],
        "unseen_transition_ratio": scored["unseen_transition_ratio"],
    })
    if excluded is not None and len(excluded):
        skipped = pd.DataFrame({
            "case_id": excluded["case_id"], "scored": False, "reason": excluded["reason"],
            "method": bundle.method, "anomaly_score": np.nan, "n_events": excluded["n_events"],
            "unseen_node_ratio": np.nan, "unseen_transition_ratio": np.nan,
        })
        frame = pd.concat([frame, skipped], ignore_index=True)
    frame = frame.sort_values("case_id", kind="stable").reset_index(drop=True)
    _write_csv(frame, output_csv)
    return frame
