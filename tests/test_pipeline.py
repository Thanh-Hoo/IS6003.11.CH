from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import pytest
import yaml
from helpers import Project, timed_rows, varied_rows, write_raw_csv

from jira_ad import cli
from jira_ad.config import load_config
from jira_ad.data import DataError, read_events_csv
from jira_ad.detector import load_bundle, score_traces
from jira_ad.pipeline import (
    RunExistsError,
    compare_runs,
    config_hash,
    prepare,
    run_experiment,
)
from jira_ad.preprocess import build_core_view, normalize_events, parse_action_rules
from jira_ad.splits import read_split_manifest, split_hash

FAST = {
    "embedding.dimensions": 4, "embedding.epochs": 1, "walk.walks_per_node": 3,
    "walk.length": 8, "detector.n_estimators": 12,
}
METHODS = ("A_stats", "B_ngrams", "C_embedding", "D_hybrid")
NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_project(root: Path, rows=None, overrides=None) -> tuple[Project, object]:
    project = Project(root)
    project.write_bug(varied_rows(30) if rows is None else rows)
    cfg = load_config(project.write_config(project.config({**FAST, **(overrides or {})})))
    return project, cfg


@pytest.fixture(scope="module")
def finished(tmp_path_factory):
    project, cfg = make_project(tmp_path_factory.mktemp("e2e"))
    return project, cfg, run_experiment(cfg, now=NOW)


# --------------------------------------------------------------------------- prepare


def test_prepared_traces_are_partitioned_exactly_like_the_saved_manifest(project, terminal_cases):
    project.write_bug(terminal_cases(n=12))
    cfg = load_config(project.write_config())

    result = prepare(cfg)

    on_disk = read_split_manifest(result.directory / "split_manifest.csv")
    assert on_disk == result.splits
    for name, ids in (("train", on_disk.train_ids), ("validation", on_disk.validation_ids),
                      ("test", on_disk.test_ids)):
        assert sorted(t.trace_id for t in result.traces_for(name)) == sorted(ids)
    assert sum(len(result.traces_for(n)) for n in ("train", "validation", "test")) == 12


def test_unknown_split_name_is_an_error(project, terminal_cases):
    project.write_bug(terminal_cases(n=6))
    result = prepare(load_config(project.write_config()))

    with pytest.raises(ValueError, match="holdout"):
        result.traces_for("holdout")


# ------------------------------------------------------------------------- run: manifest


def test_manifest_is_completed_and_carries_provenance(finished):
    project, cfg, run_dir = finished
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    bug = project.root / "dataset" / "TIeventlogBug.csv"
    actions = project.root / "configs" / "actions.yaml"

    assert manifest["status"] == "completed" and "error" not in manifest
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", manifest["run_id"])
    assert manifest["run_id"] == run_dir.name == f"20261016T120000Z-{config_hash(cfg)[:8]}"
    assert manifest["config_hash"] == config_hash(cfg) and len(manifest["config_hash"]) == 64
    assert manifest["action_rules_hash"] == sha(actions)
    saved = read_split_manifest(run_dir / "split_manifest.csv")
    assert manifest["split_hash"] == split_hash(saved)
    (inputs,) = [i for i in manifest["input_files"] if i.get("cohort") == "bug"]
    assert inputs["sha256"] == sha(bug) and inputs["relative_path"] == "dataset/TIeventlogBug.csv"
    assert manifest["seeds"] == {"split": 42, "model": 42, "validation_mutation": 1042,
                                 "test_mutation": 2042}
    assert manifest["methods"] == list(METHODS) and manifest["cohort"] == "bug"
    assert manifest["git"] is None  # thư mục thử nghiệm không phải repo Git
    assert manifest["config_path"] == "configs/test.yaml"  # để in đúng lệnh tạo lại run
    assert {"python", "numpy", "pandas", "scikit-learn", "gensim", "platform"} <= set(
        manifest["environment"])
    assert {"prepare", "fit", "mutate", "score", "evaluate", "review", "finalize"} <= set(
        manifest["stage_timings"])
    assert manifest["started_at_utc"] <= manifest["finished_at_utc"]


def test_every_documented_artifact_exists_and_is_fingerprinted(finished):
    _, _, run_dir = finished
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = [
        "config.resolved.yaml", "input_files.json", "split_manifest.csv", "exclusions.csv",
        "preprocess_audit.json", "graph.graphml", "node_vectors.parquet", "walk_sample.json",
        "embedding_diagnostics.json", "scores/originals.parquet", "scores/mutants.parquet",
        "mutations.parquet", "mutation_ledger.csv", "metrics.json", "metrics_by_type.csv",
        "paired_scores.csv", "case_review_blinded.csv", "case_review_key.csv", "run.log",
        *[f"models/{m}/{f}" for m in METHODS
          for f in ("bundle.joblib", "feature_schema.json", "fit_metadata.json")],
    ]
    for relative in expected:
        assert (run_dir / relative).is_file(), relative
        assert relative in manifest["artifacts"], relative
        assert manifest["artifacts"][relative]["sha256"] == sha(run_dir / relative)
    for directory in ("figures", "tables", "notebooks_executed"):
        assert (run_dir / directory).is_dir()
    assert "manifest.json" not in manifest["artifacts"]


def test_resolved_config_and_input_files_record_exactly_what_was_used(finished):
    project, cfg, run_dir = finished

    resolved = yaml.safe_load((run_dir / "config.resolved.yaml").read_text(encoding="utf-8"))
    files = json.loads((run_dir / "input_files.json").read_text(encoding="utf-8"))

    assert resolved == cfg.as_dict()
    assert "project_root" not in json.dumps(resolved)
    kinds = {f["kind"]: f for f in files}
    assert kinds["event_log"]["sha256"] == sha(project.root / "dataset" / "TIeventlogBug.csv")
    assert kinds["action_rules"]["sha256"] == sha(project.root / "configs" / "actions.yaml")


# ------------------------------------------------------------------ run: split / scores


def test_mutants_exist_only_for_validation_and_test_parents(finished):
    _, _, run_dir = finished
    splits = read_split_manifest(run_dir / "split_manifest.csv")
    ledger = pd.read_csv(run_dir / "mutation_ledger.csv")

    assert set(ledger.split) == {"validation", "test"}
    assert set(ledger.parent_case_id).isdisjoint(splits.train_ids)
    for name, ids in (("validation", splits.validation_ids), ("test", splits.test_ids)):
        assert set(ledger[ledger.split == name].parent_case_id) <= set(ids)
    mutants = pd.read_parquet(run_dir / "scores" / "mutants.parquet")
    assert set(mutants.parent_case_id).isdisjoint(splits.train_ids)


def test_every_method_scores_the_same_originals_and_the_same_mutant_ids(finished):
    _, _, run_dir = finished
    splits = read_split_manifest(run_dir / "split_manifest.csv")
    originals = pd.read_parquet(run_dir / "scores" / "originals.parquet")
    mutants = pd.read_parquet(run_dir / "scores" / "mutants.parquet")

    for frame in (originals, mutants):
        assert {"method", "trace_id", "parent_case_id", "split", "anomaly_score"} <= set(frame)
        assert np.isfinite(frame.anomaly_score).all()
    ids = {m: set(originals[originals.method == m].trace_id) for m in METHODS}
    assert len({frozenset(v) for v in ids.values()}) == 1
    assert ids["A_stats"] == set(splits.validation_ids) | set(splits.test_ids)
    mutant_ids = {m: frozenset(mutants[mutants.method == m].trace_id) for m in METHODS}
    assert len(set(mutant_ids.values())) == 1 and len(mutant_ids["A_stats"]) > 0


def test_every_saved_bundle_was_fitted_on_exactly_the_train_split(finished):
    _, _, run_dir = finished
    splits = read_split_manifest(run_dir / "split_manifest.csv")

    for method in METHODS:
        bundle = load_bundle(run_dir / "models" / method / "bundle.joblib")
        assert bundle.encoder.train_ids == tuple(sorted(splits.train_ids))
        held_out = set(splits.validation_ids) | set(splits.test_ids)
        assert held_out.isdisjoint(bundle.encoder.train_ids)
        assert bundle.metadata["n_train"] == len(splits.train_ids)


def test_saved_bundles_reproduce_the_saved_scores_after_loading(finished):
    project, cfg, run_dir = finished
    originals = pd.read_parquet(run_dir / "scores" / "originals.parquet")
    traces = {t.trace_id: t for t in prepare(cfg).traces}

    for method in METHODS:
        bundle = load_bundle(run_dir / "models" / method / "bundle.joblib")
        saved = originals[originals.method == method].set_index("trace_id").anomaly_score
        rescored = score_traces(bundle, [traces[i] for i in saved.index])
        assert np.allclose(rescored.anomaly_score.to_numpy(), saved.to_numpy(), atol=1e-8, rtol=0)


def test_graph_and_vectors_are_the_shared_train_artifacts(finished):
    _, cfg, run_dir = finished
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    graph = nx.read_graphml(run_dir / "graph.graphml")
    vectors = pd.read_parquet(run_dir / "node_vectors.parquet")
    diag = json.loads((run_dir / "embedding_diagnostics.json").read_text(encoding="utf-8"))

    assert "__START__" in graph and "__END__" in graph
    assert set(vectors.node) == set(graph.nodes)
    assert vectors.shape[1] == 1 + cfg.embedding.dimensions
    assert manifest["embedding_shared"] is True  # C và D học cùng một embedding
    assert diag["embedding"]["node_coverage"] == 1.0 and diag["walks"]["n_walks"] > 0


# ------------------------------------------------------------------------ run: metrics


def test_metrics_cover_every_method_and_type_for_validation_and_test(finished):
    _, cfg, run_dir = finished
    by_type = pd.read_csv(run_dir / "metrics_by_type.csv")
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    paired = pd.read_csv(run_dir / "paired_scores.csv")

    assert set(by_type.split) == {"validation", "test"}
    for split in ("validation", "test"):
        part = by_type[by_type.split == split]
        assert set(part.method) == set(METHODS)
        assert set(part.mutation_type) == set(cfg.mutation.types)
        assert (part.injected_rate == 0.5).all()
        assert (part.n_original == part.n_mutant).all()
    assert "validation" in metrics["splits"] and "test" in metrics["splits"]
    assert "is_injected" in metrics["label_definition"]
    assert metrics["primary_split"] == "test" and metrics["model_seeds"] == [42]
    assert {"split", "method", "mutation_type", "parent_case_id", "delta_score"} <= set(paired)
    json.dumps(metrics, allow_nan=False)


# ------------------------------------------- run: bootstrap theo parent và đối chứng dương (Task 10-11)

BOOTSTRAP_ARTIFACTS = (
    "bootstrap_intervals.csv", "bootstrap_differences.csv", "chance_test.csv", "positive_control.csv",
    "positive_control_ledger.csv", "positive_control_paired_scores.csv",
)


def test_bootstrap_and_control_artifacts_are_written_and_fingerprinted(finished):
    _, _, run_dir = finished
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    for relative in BOOTSTRAP_ARTIFACTS:
        assert (run_dir / relative).is_file(), relative
        assert manifest["artifacts"][relative]["sha256"] == sha(run_dir / relative)


def test_bootstrap_estimates_equal_the_ordinary_metrics_and_intervals_contain_them(finished):
    _, cfg, run_dir = finished
    by_type = pd.read_csv(run_dir / "metrics_by_type.csv")
    intervals = pd.read_csv(run_dir / "bootstrap_intervals.csv")

    assert set(intervals.split) == {"validation", "test"}
    auroc = intervals[intervals.metric == "auroc"]
    for row in by_type.itertuples():
        match = auroc[(auroc.split == row.split) & (auroc.method == row.method)
                      & (auroc.scope == row.mutation_type)]
        assert len(match) == 1 and match.iloc[0].estimate == pytest.approx(row.auroc)
    assert set(auroc[auroc.scope == "macro"].method) == set(METHODS)
    scored = intervals.dropna(subset=["ci_low"])
    assert (scored.ci_low <= scored.estimate + 1e-12).all()
    assert (scored.estimate <= scored.ci_high + 1e-12).all()
    differences = pd.read_csv(run_dir / "bootstrap_differences.csv")
    assert {("D_hybrid", "A_stats")} <= set(zip(differences.method_a, differences.method_b,
                                                 strict=True))


def test_chance_test_matches_the_ordinary_auroc_and_uses_the_configured_permutations(finished):
    _, cfg, run_dir = finished
    by_type = pd.read_csv(run_dir / "metrics_by_type.csv")
    chance = pd.read_csv(run_dir / "chance_test.csv")

    assert set(chance.split) == {"validation", "test"} and len(chance) == len(by_type)
    assert (chance.n_permutations == cfg.evaluation.permutations).all()
    assert chance.p_value.between(0, 1).all() and (chance.p_value > 0).all()
    for row in by_type.itertuples():
        match = chance[(chance.split == row.split) & (chance.method == row.method)
                       & (chance.scope == row.mutation_type)]
        assert len(match) == 1 and match.iloc[0].auroc == pytest.approx(row.auroc)
    assert chance.null_sd.between(0, 0.5).all()


def test_metrics_json_records_the_bootstrap_and_control_settings(finished):
    _, cfg, run_dir = finished
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))

    for split in ("validation", "test"):
        meta = metrics["bootstrap"][split]
        assert meta["n_resamples"] == cfg.evaluation.bootstrap_resamples
        assert meta["seed"] == cfg.evaluation.bootstrap_seed and meta["unit"] == "parent_case_id"
        assert meta["confidence"] == cfg.evaluation.confidence
    chance = metrics["chance_test"]
    assert chance["n_permutations"] == cfg.evaluation.permutations and "hoán vị" in chance["note"]
    control = metrics["positive_control"]
    assert control["split"] == "validation" and control["seed"] == cfg.evaluation.positive_control_seed
    assert control["mutation_type"] == "shuffle_internal"
    assert "kiểm tra bộ máy" in control["note"]


def test_the_positive_control_is_validation_only_and_never_mixed_into_the_v1_benchmark(finished):
    _, cfg, run_dir = finished
    splits = read_split_manifest(run_dir / "split_manifest.csv")
    ledger = pd.read_csv(run_dir / "positive_control_ledger.csv")
    control = pd.read_csv(run_dir / "positive_control.csv")
    v1_ledger = pd.read_csv(run_dir / "mutation_ledger.csv")
    mutants = pd.read_parquet(run_dir / "scores" / "mutants.parquet")
    by_type = pd.read_csv(run_dir / "metrics_by_type.csv")

    assert set(ledger.split) == {"validation"} and set(ledger.mutation_type) == {"shuffle_internal"}
    assert set(ledger.parent_case_id) <= set(splits.validation_ids)
    assert set(control.method) == set(METHODS) and set(control.mutation_type) == {"shuffle_internal"}
    assert control.n_original.min() > 0 and (control.injected_rate == 0.5).all()
    assert "shuffle_internal" not in set(v1_ledger.mutation_type)
    assert "shuffle_internal" not in set(by_type.mutation_type)
    assert not any("shuffle_internal" in t for t in mutants.trace_id)
    assert {"auroc_ci_low", "auroc_ci_high"} <= set(control.columns)


# ------------------------------------------------------------ holdout theo thời gian (Task 14)


def temporal_rows(n=30):
    """n issue kết thúc lần lượt cách nhau 1 ngày (issue k kết thúc ngày k, bắt đầu 3 ngày trước đó)."""
    rows = []
    for i in range(n):
        start = f"2022-03-{1 + max(i - 3, 0):02d}T08:00:00" if i < 28 else f"2022-04-{i - 27:02d}T08:00:00"
        steps = [("SQA", "Issue created"), ("PO", "edit summary"), ("PO", "edit description"),
                 ("PO", "update resolution to Done, update status to DONE" if i % 2
                  else "update resolution to Canceled, update status to Rejected")]
        rows += timed_rows(f"TI-{i + 1}", steps, start=start, step_seconds=86400 if i < 28 else 3600)
    return rows


def test_prepare_with_temporal_strategy_orders_splits_by_end_time_and_reports_the_overlap(tmp_path):
    project, _ = make_project(tmp_path / "t", rows=temporal_rows())
    raw = project.config(FAST)
    raw["split"]["strategy"] = "temporal"
    cfg = load_config(project.write_config(raw, rel="configs/temporal.yaml"))

    result = prepare(cfg)

    report = result.audit["split"]["temporal"]
    by_id = {t.trace_id: t for t in result.traces}
    ends = {name: [by_id[i].timestamps[-1] for i in ids] for name, ids in (
        ("train", result.splits.train_ids), ("validation", result.splits.validation_ids),
        ("test", result.splits.test_ids))}
    assert max(ends["train"]) <= min(ends["validation"]) and max(ends["validation"]) <= min(ends["test"])
    assert report["by_split"]["train"]["n"] == len(result.splits.train_ids)
    assert report["n_heldout_started_before_train_end"] >= 0 and "train_end_utc" in report
    manifest = pd.read_csv(result.directory / "split_manifest.csv")
    assert set(manifest.stratum) == {"temporal"}


def test_the_default_strategy_keeps_its_prepare_key_and_adds_no_temporal_block(tmp_path):
    project, cfg = make_project(tmp_path / "r", rows=temporal_rows())

    random_result = prepare(cfg)
    raw = project.config(FAST)
    raw["split"]["strategy"] = "temporal"
    temporal = prepare(load_config(project.write_config(raw, rel="configs/temporal.yaml")))

    assert "strategy" not in random_result.audit["settings"]["split"]  # khóa prepare của V1 không đổi
    assert "temporal" not in random_result.audit["split"]
    assert temporal.audit["settings"]["split"]["strategy"] == "temporal"
    assert temporal.directory != random_result.directory  # protocol khác ⇒ thư mục khác
    assert random_result.splits != temporal.splits


def test_a_full_run_works_with_the_temporal_strategy_and_is_its_own_protocol(tmp_path):
    project, cfg = make_project(tmp_path / "e", rows=temporal_rows())
    raw = project.config(FAST)
    raw["split"]["strategy"] = "temporal"
    temporal_cfg = load_config(project.write_config(raw, rel="configs/temporal.yaml"))

    random_run = run_experiment(cfg, now=NOW)
    temporal_run = run_experiment(temporal_cfg, now=NOW)

    manifests = [json.loads((d / "manifest.json").read_text()) for d in (random_run, temporal_run)]
    assert all(m["status"] == "completed" for m in manifests)
    assert manifests[0]["split_hash"] != manifests[1]["split_hash"]
    groups = compare_runs(project.root / "outputs" / "runs")["groups"]
    assert len(groups) == 2  # không bao giờ gộp hai protocol chia khác nhau


# -------------------------------------------------------------------- run: case review


def test_case_review_is_blinded_and_the_key_maps_back(finished):
    _, _, run_dir = finished
    blinded = pd.read_csv(run_dir / "case_review_blinded.csv", dtype=str, keep_default_na=False)
    key = pd.read_csv(run_dir / "case_review_key.csv")
    splits = read_split_manifest(run_dir / "split_manifest.csv")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert set(key.case_id) <= set(splits.test_ids)
    assert len(key) == min(20, len(splits.test_ids))  # lấy tối đa có thể khi ít hơn 20
    assert manifest["review"]["n_cases"] == len(key)
    assert not any(w in " ".join(blinded.columns).lower() for w in ("score", "rank", "method"))
    assert (blinded["review_label"] == "").all() and (blinded["reviewer"] == "").all()
    assert list(blinded.review_id) == list(key.review_id)
    assert set(key.method) == {manifest["review"]["method"]}


# ------------------------------------------------------------------ run: reproducibility


def test_same_config_gives_identical_scores_and_a_new_run_id(finished, tmp_path):
    project, cfg, first = finished
    later = datetime(2026, 10, 16, 12, 0, 5, tzinfo=UTC)

    second = run_experiment(cfg, now=later)

    assert second != first and second.parent == first.parent
    for relative in ("scores/originals.parquet", "scores/mutants.parquet", "metrics_by_type.csv",
                     "split_manifest.csv", "mutation_ledger.csv"):
        a, b = first / relative, second / relative
        if a.suffix == ".parquet":
            pd.testing.assert_frame_equal(pd.read_parquet(a), pd.read_parquet(b))
        else:
            assert a.read_bytes() == b.read_bytes(), relative


def test_a_rerun_never_overwrites_an_existing_run(tmp_path):
    project, cfg = make_project(tmp_path / "repo")
    first = run_experiment(cfg, now=NOW)
    snapshot = {p: sha(p) for p in first.rglob("*") if p.is_file()}

    with pytest.raises(RunExistsError, match=first.name):
        run_experiment(cfg, now=NOW)  # cùng run_id ⇒ va chạm ⇒ dừng

    assert {p: sha(p) for p in first.rglob("*") if p.is_file()} == snapshot
    relaxed = load_config(project.write_config(
        project.config({**FAST, "run.fail_on_existing_output": False}), rel="configs/relaxed.yaml"))
    # cờ vận hành không đổi kết quả nên không vào hash
    assert config_hash(relaxed) == config_hash(cfg)
    other = run_experiment(relaxed, now=NOW)
    assert other != first and other.name.startswith(first.name) and other.is_dir()
    # bản đầu không bị ghi đè
    assert {p: sha(p) for p in first.rglob("*") if p.is_file()} == snapshot


def test_changed_input_gets_a_new_split_and_is_not_served_from_a_stale_cache(tmp_path):
    project, cfg = make_project(tmp_path / "repo")
    first = run_experiment(cfg, now=NOW)
    project.write_bug(varied_rows(34, seed=3))
    second = run_experiment(cfg, now=datetime(2026, 10, 16, 13, 0, 0, tzinfo=UTC))

    a = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    b = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
    assert a["input_files"][0]["sha256"] != b["input_files"][0]["sha256"]
    assert a["split_hash"] != b["split_hash"]
    assert a["prepared_dir"] != b["prepared_dir"]


# ---------------------------------------------------------------------- run: failures


def only_run_dir(project) -> Path:
    (directory,) = sorted((project.root / "outputs" / "runs").iterdir())
    return directory


def test_a_schema_error_leaves_a_failed_manifest_and_never_a_completed_one(tmp_path):
    project, cfg = make_project(tmp_path / "repo")
    project.write_bug([], header=("issueKey", "timestamp", "action"))  # thiếu cột role

    with pytest.raises(DataError, match="role"):
        run_experiment(cfg, now=NOW)

    manifest = json.loads((only_run_dir(project) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["error"]["stage"] == "prepare" and "role" in manifest["error"]["message"]
    assert manifest["finished_at_utc"] is not None
    assert not (only_run_dir(project) / "metrics.json").exists()


def test_too_few_cases_to_split_fails_at_prepare_with_a_clear_reason(tmp_path):
    project, cfg = make_project(tmp_path / "repo", rows=varied_rows(4))

    with pytest.raises(Exception, match="stratify|3"):
        run_experiment(cfg, now=NOW)

    manifest = json.loads((only_run_dir(project) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed" and manifest["error"]["stage"] == "prepare"


def test_metrics_that_cannot_be_computed_fail_the_run_instead_of_completing(tmp_path, monkeypatch):
    project, cfg = make_project(tmp_path / "repo")
    import jira_ad.pipeline as pipeline

    real = pipeline.evaluate_semisynthetic

    def no_common_parents(originals, mutants, ledger):
        return real(originals, mutants.iloc[0:0], ledger)  # mọi loại: không có mutant

    monkeypatch.setattr(pipeline, "evaluate_semisynthetic", no_common_parents)

    with pytest.raises(Exception, match="metric"):
        run_experiment(cfg, now=NOW)

    manifest = json.loads((only_run_dir(project) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed" and manifest["error"]["stage"] == "evaluate"


# ------------------------------------------------------------------------------- CLI


def test_cli_run_prints_the_real_run_dir_and_exits_zero(tmp_path):
    project, _ = make_project(tmp_path / "repo")
    config = project.root / "configs" / "test.yaml"

    result = subprocess.run(
        [sys.executable, "-m", "jira_ad.cli", "run", "--config", str(config)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    run_dir = only_run_dir(project)
    assert f"Run dir: {run_dir.relative_to(project.root).as_posix()}" in result.stdout
    assert json.loads((run_dir / "manifest.json").read_text())["status"] == "completed"


# ------------------------------------------------------------ bất biến đầu-cuối (không rò rỉ)


def read_rows(csv_path: Path) -> list[list[str]]:
    with csv_path.open(newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


def write_rows(csv_path: Path, rows: list[list[str]]) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh, quoting=csv.QUOTE_ALL).writerows(rows)


def fitted_state(run_dir: Path) -> dict[str, tuple[str, str]]:
    out = {}
    for method in METHODS:
        meta = json.loads((run_dir / "models" / method / "fit_metadata.json").read_text("utf-8"))
        out[method] = (meta["encoder_state_sha256"], meta["train_ids_sha256"])
    return out


@pytest.mark.parametrize("held_out", ["validation", "test"])
def test_changing_a_held_out_case_cannot_change_anything_fitted_on_train(tmp_path, held_out):
    project, cfg = make_project(tmp_path / "repo")
    first = run_experiment(cfg, now=NOW)
    splits = read_split_manifest(first / "split_manifest.csv")
    victim = (splits.validation_ids if held_out == "validation" else splits.test_ids)[0]
    issue = victim.split(":", 1)[1]

    csv_path = project.root / "dataset" / "TIeventlogBug.csv"
    rows = read_rows(csv_path)
    for row in rows[1:]:
        if row[0] == issue and "status" not in row[3] and row[3] != "Issue created":
            row[3] = "update ZZZ_ONLY_IN_TEST to 1"  # activity mới, chỉ tồn tại ở một ca test
    write_rows(csv_path, rows)
    second = run_experiment(cfg, now=datetime(2026, 10, 16, 12, 0, 9, tzinfo=UTC))

    assert fitted_state(second) == fitted_state(first)  # DFG, từ vựng, embedding, n-gram: không đổi
    assert read_split_manifest(second / "split_manifest.csv") == read_split_manifest(
        first / "split_manifest.csv")
    a = pd.read_parquet(first / "scores" / "originals.parquet")
    b = pd.read_parquet(second / "scores" / "originals.parquet")
    others = a.trace_id != victim
    key = ["method", "trace_id"]
    merged = a[others].merge(b[b.trace_id != victim], on=key, suffixes=("_a", "_b"))
    # điểm các ca KHÁC không đổi bit nào (mô hình không đọc ca test đã sửa)
    assert (merged.anomaly_score_a - merged.anomaly_score_b).abs().max() < 1e-12
    changed = b[(b.trace_id == victim) & (b.method == "A_stats")].iloc[0]
    assert changed.unseen_node_ratio > 0  # và việc sửa có thật: ca bị sửa nay có nút chưa thấy


def test_shuffling_the_csv_rows_changes_neither_the_split_nor_the_scores(tmp_path):
    project, cfg = make_project(tmp_path / "repo")
    first = run_experiment(cfg, now=NOW)
    csv_path = project.root / "dataset" / "TIeventlogBug.csv"
    header, *body = read_rows(csv_path)
    random.Random(0).shuffle(body)
    write_rows(csv_path, [header, *body])

    second = run_experiment(cfg, now=datetime(2026, 10, 16, 12, 0, 9, tzinfo=UTC))

    assert read_split_manifest(second / "split_manifest.csv") == read_split_manifest(
        first / "split_manifest.csv")
    a = pd.read_parquet(first / "scores" / "originals.parquet").set_index(["method", "trace_id"])
    b = pd.read_parquet(second / "scores" / "originals.parquet").set_index(["method", "trace_id"])
    assert (a.anomaly_score - b.anomaly_score.reindex(a.index)).abs().max() < 1e-12
    assert fitted_state(second)["A_stats"] == fitted_state(first)["A_stats"]


# ------------------------------------------------------------------------------ score


def test_score_loads_the_saved_bundle_scores_valid_cases_and_explains_the_rest(
    finished, tmp_path, monkeypatch
):
    _, _, run_dir = finished
    rows = varied_rows(3, seed=11, prefix="NEW")
    rows += timed_rows("NEW-98", [("SQA", "Issue created"), ("PO", "update status to In Test")])
    rows += timed_rows("NEW-99", [("SQA", "Issue created"), ("PO", "edit description")])
    incoming = write_raw_csv(tmp_path / "incoming.csv", rows)
    bundle_path = run_dir / "models" / "D_hybrid" / "bundle.joblib"
    before = sha(bundle_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("score không được fit lại")

    monkeypatch.setattr("jira_ad.features.FeatureEncoder.fit", forbidden)
    monkeypatch.setattr("sklearn.ensemble.IsolationForest.fit", forbidden)
    output = tmp_path / "scored.csv"

    code = cli.main(["score", "--bundle", str(bundle_path), "--input-csv", str(incoming),
                     "--output", str(output)])

    assert code == 0
    frame = pd.read_csv(output)
    assert set(frame.columns) >= {"case_id", "scored", "reason", "method", "anomaly_score",
                                  "n_events", "unseen_node_ratio", "unseen_transition_ratio"}
    scored, skipped = frame[frame.scored], frame[~frame.scored].set_index("case_id")
    assert set(scored.case_id) == {"bug:NEW-1", "bug:NEW-2", "bug:NEW-3"}  # cohort lấy từ bundle
    assert scored.anomaly_score.notna().all() and set(scored.method) == {"D_hybrid"}
    assert skipped.reason.to_dict() == {
        "bug:NEW-98": "last_status_not_terminal", "bug:NEW-99": "no_status_update"}
    assert skipped.anomaly_score.isna().all()
    assert sha(bundle_path) == before  # không sửa bundle

    bundle = load_bundle(bundle_path)  # đối chiếu bằng đường thư viện khác
    rules = parse_action_rules(bundle.metadata["action_rules_text"], "bundle")
    pre = bundle.encoder.cfg.preprocess
    events = normalize_events(read_events_csv(incoming, "bug", tmp_path), pre, rules)
    traces = build_core_view(events, pre, rules).traces
    expected = score_traces(bundle, traces).set_index("trace_id").anomaly_score
    got = scored.set_index("case_id").anomaly_score
    assert np.allclose(got.loc[expected.index].to_numpy(), expected.to_numpy(), atol=1e-8)


def test_score_rejects_input_with_a_wrong_schema(finished, tmp_path, capsys):
    _, _, run_dir = finished
    bad = write_raw_csv(tmp_path / "bad.csv", [], header=("issueKey", "timestamp", "action"))

    code = cli.main(["score", "--bundle", str(run_dir / "models" / "A_stats" / "bundle.joblib"),
                     "--input-csv", str(bad), "--output", str(tmp_path / "out.csv")])

    assert code != 0 and "role" in capsys.readouterr().err
    assert not (tmp_path / "out.csv").exists()


# ----------------------------------------------------------------------------- compare


def test_compare_groups_by_protocol_and_never_averages_incompatible_runs(tmp_path):
    project, cfg = make_project(tmp_path / "repo")
    first = run_experiment(cfg, now=NOW)
    cfg43 = load_config(project.write_config(
        project.config({**FAST, "run.seed": 43}), rel="configs/seed43.yaml"))
    second = run_experiment(cfg43, now=datetime(2026, 10, 16, 12, 0, 1, tzinfo=UTC))
    wider = load_config(project.write_config(
        project.config({**FAST, "embedding.dimensions": 6}), rel="configs/wider.yaml"))
    third = run_experiment(wider, now=datetime(2026, 10, 16, 12, 0, 2, tzinfo=UTC))
    project.write_bug(varied_rows(34, seed=3))  # dữ liệu khác ⇒ protocol khác
    fourth = run_experiment(cfg, now=datetime(2026, 10, 16, 12, 0, 3, tzinfo=UTC))
    runs_dir = project.root / "outputs" / "runs"
    (runs_dir / "broken").mkdir()
    (runs_dir / "broken" / "manifest.json").write_text('{"status": "failed"}', encoding="utf-8")

    result = compare_runs(runs_dir)

    assert len(result["groups"]) == 3
    assert {s["run_id"] for s in result["skipped"]} == {"broken"}
    by_runs = {tuple(sorted(g["runs"])): g for g in result["groups"]}
    pair = by_runs[tuple(sorted([first.name, second.name]))]
    wider_group, other_data = by_runs[(third.name,)], by_runs[(fourth.name,)]
    # cùng dữ liệu/split/đánh giá nhưng khác siêu tham số mô hình: cùng protocol, khác nhóm mô hình
    assert wider_group["protocol_id"] == pair["protocol_id"]
    assert wider_group["model_config_id"] != pair["model_config_id"]
    # khác dữ liệu: protocol khác
    assert other_data["protocol_id"] != pair["protocol_id"]
    for group in (wider_group, other_data):
        for row in group["rows"]:
            assert row["n_runs"] == 1 and row["auroc_std"] is None
    paired_rows = pd.DataFrame(pair["rows"])
    assert (paired_rows.n_runs == 2).all()
    a = pd.read_csv(first / "metrics_by_type.csv").query("split == 'test'").set_index(
        ["method", "mutation_type"])
    b = pd.read_csv(second / "metrics_by_type.csv").query("split == 'test'").set_index(
        ["method", "mutation_type"])
    for row in paired_rows.itertuples():
        key = (row.method, row.mutation_type)
        values = [a.loc[key, "auroc"], b.loc[key, "auroc"]]
        assert row.auroc_mean == pytest.approx(np.mean(values))
        assert row.auroc_std == pytest.approx(np.std(values, ddof=1))


def test_a_model_seed_that_was_run_twice_counts_once_so_stability_is_not_faked(tmp_path):
    project, cfg = make_project(tmp_path / "repo")
    first = run_experiment(cfg, now=NOW)
    second = run_experiment(cfg, now=datetime(2026, 10, 16, 12, 0, 5, tzinfo=UTC))  # cùng seed 42

    result = compare_runs(project.root / "outputs" / "runs")

    (group,) = result["groups"]
    assert group["runs"] == [second.name]  # chỉ giữ run mới nhất của seed này
    assert group["superseded"] == [first.name]
    assert all(row["n_runs"] == 1 and row["auroc_std"] is None for row in group["rows"])


def test_cli_compare_writes_a_table_and_does_not_touch_the_runs(tmp_path, capsys):
    project, cfg = make_project(tmp_path / "repo")
    run_dir = run_experiment(cfg, now=NOW)
    before = {p: sha(p) for p in run_dir.rglob("*") if p.is_file()}
    runs_dir = project.root / "outputs" / "runs"

    code = cli.main(["compare", "--runs-dir", str(runs_dir)])

    assert code == 0
    table = pd.read_csv(runs_dir / "comparison.csv")
    assert {"protocol_id", "model_config_id", "method", "mutation_type", "n_runs", "auroc_mean",
            "auroc_std", "average_precision_mean", "paired_win_rate_mean"} <= set(table.columns)
    assert len(table) == len(METHODS) * 3 and (table.n_runs == 1).all()
    assert "protocol" in capsys.readouterr().out
    assert {p: sha(p) for p in run_dir.rglob("*") if p.is_file()} == before
