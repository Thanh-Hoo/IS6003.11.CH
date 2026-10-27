from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from helpers import Project, varied_rows

from jira_ad import cli
from jira_ad.config import ConfigError, config_hash, load_config
from jira_ad.improvement import (
    applicability_verdicts,
    load_improvement_plan,
    method_decision,
    run_improvement,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 22, 9, 0, 0, tzinfo=UTC)
FAST = {
    "embedding.dimensions": 4, "embedding.epochs": 1, "walk.walks_per_node": 3,
    "walk.length": 8, "detector.n_estimators": 12,
    "features.methods": ["A_stats", "B_ngrams", "C_embedding", "D_hybrid",
                         "E_score_fusion", "F_edge_hybrid", "M_markov"],
}
CRITERIA = {"alert_auroc_lower": 0.80, "alert_skip_status_auroc": 0.80, "triage_auroc_lower": 0.5,
            "triage_top_fraction": 0.10, "triage_jaccard": 0.6, "triage_ms_per_case": 100.0}


def plan_dict(**overrides) -> dict:
    plan = {
        "config": "configs/improvements.yaml",
        "model_seeds": [42, 43],
        "decision": {"reference": "D_hybrid", "candidates": ["E_score_fusion", "F_edge_hybrid", "M_markov"],
                     "selection_split": "validation", "family_alpha": 0.05},
        "crossval": {"folds": 3, "mutation_types": ["swap_adjacent", "delete_internal", "skip_status",
                                                    "multi_edit"]},
        "applicability": dict(CRITERIA),
    }
    plan.update(overrides)
    return plan


@pytest.fixture
def small(tmp_path):
    project = Project(tmp_path / "repo")
    project.write_bug(varied_rows(40, seed=5))
    project.write_config(project.config(FAST), rel="configs/improvements.yaml")
    return project


def write_plan(project, plan) -> Path:
    path = project.root / "configs" / "improvement_plan.yaml"
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    return path


def test_the_shipped_plan_loads_and_keeps_the_baseline_hash():
    plan = load_improvement_plan(REPO_ROOT / "configs" / "improvement_plan.yaml")

    assert plan.decision.reference == "D_hybrid"
    assert plan.decision.confidence == pytest.approx(1 - 0.05 / 3)
    assert config_hash(load_config(REPO_ROOT / "configs" / "baseline.yaml")).startswith("930f8a85")


@pytest.mark.parametrize("change, match", [
    ({"surprise": 1}, "surprise"),
    ({"decision": {"reference": "D_hybrid", "candidates": ["Z"], "selection_split": "validation",
                   "family_alpha": 0.05}}, "Z"),
    ({"decision": {"reference": "D_hybrid", "candidates": ["M_markov"], "selection_split": "test",
                   "family_alpha": 0.05}}, "validation"),
])
def test_bad_plans_are_rejected_with_the_offending_key(small, change, match):
    with pytest.raises(ConfigError, match=match):
        load_improvement_plan(write_plan(small, plan_dict(**change)))


def synthetic_paired(gap: float, n: int = 40, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        base = rng.normal()
        for method, lift in (("REF", 0.0), ("CAND", gap)):
            rows.append({"split": "validation", "method": method, "mutation_type": "swap_adjacent",
                         "parent_case_id": f"p{i}", "original_score": base,
                         "mutant_score": base + lift + 0.01 * rng.normal()})
    return pd.DataFrame(rows)


def test_a_clearly_better_candidate_is_an_improvement_and_an_identical_one_is_not():
    better = method_decision({"r1": synthetic_paired(1.0, seed=1), "r2": synthetic_paired(1.0, seed=2)},
                             reference="REF", candidates=["CAND"], split="validation",
                             confidence=0.95, n_resamples=300, seed=0)
    same = method_decision({"r1": synthetic_paired(0.0, seed=1)}, reference="REF", candidates=["CAND"],
                           split="validation", confidence=0.95, n_resamples=300, seed=0)

    assert better.iloc[0].verdict == "ứng viên cải thiện" and better.iloc[0].ci_low > 0
    assert same.iloc[0].verdict == "không có bằng chứng"
    assert int(better.iloc[0].n_seeds) == 2


def test_applicability_applies_the_locked_thresholds():
    summary = pd.DataFrame([
        {"method": "alert", "cv_macro_auroc_ci_low": 0.85, "cv_skip_status_auroc": 0.90,
         "topk_jaccard": 0.9, "score_ms_per_case": 1.0},
        {"method": "triage", "cv_macro_auroc_ci_low": 0.52, "cv_skip_status_auroc": 0.60,
         "topk_jaccard": 0.7, "score_ms_per_case": 1.0},
        {"method": "unstable", "cv_macro_auroc_ci_low": 0.52, "cv_skip_status_auroc": 0.60,
         "topk_jaccard": 0.3, "score_ms_per_case": 1.0},
        {"method": "chance", "cv_macro_auroc_ci_low": 0.49, "cv_skip_status_auroc": np.nan,
         "topk_jaccard": 0.9, "score_ms_per_case": 1.0},
    ])

    verdicts = applicability_verdicts(summary, CRITERIA).set_index("method").verdict

    assert verdicts.to_dict() == {"alert": "tự động cảnh báo", "triage": "bộ lọc ưu tiên rà soát",
                                  "unstable": "chưa đủ để ứng dụng", "chance": "chưa đủ để ứng dụng"}


def test_run_improvement_end_to_end_writes_every_artifact(small):
    out = run_improvement(write_plan(small, plan_dict()), now=NOW)

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed" and len(manifest["standard_runs"]) == 2
    for name in ("decision_validation.csv", "exploratory_test.csv", "standard_metrics.csv",
                 "cv_metrics.csv", "cv_bootstrap_intervals.csv", "cv_bootstrap_differences.csv",
                 "applicability.csv", "inference_profile.csv", "method_agreement.csv"):
        assert (out / name).is_file(), name
    decision = pd.read_csv(out / "decision_validation.csv")
    assert sorted(decision.candidate) == ["E_score_fusion", "F_edge_hybrid", "M_markov"]
    assert (decision.split == "validation").all()
    assert set(pd.read_csv(out / "applicability.csv").method) == set(FAST["features.methods"])
    assert any((out / "figures").glob("*.png"))
    for path in manifest["artifacts"]:
        assert (out / path).is_file()


def test_run_improvement_never_overwrites_and_cli_reports(small, capsys):
    path = write_plan(small, plan_dict(model_seeds=[42]))

    assert cli.main(["improve", "--plan", str(path)]) == 0
    printed = capsys.readouterr().out
    assert "decision" in printed.lower() or "phán quyết" in printed.lower()
    with pytest.raises(FileExistsError):
        run_improvement(path, now=NOW) and run_improvement(path, now=NOW)


def test_case_drivers_report_the_rarest_transitions_against_the_fold_train_graph(trace_of):
    from jira_ad.improvement import case_drivers

    cfg = load_config(REPO_ROOT / "configs" / "smoke.yaml")
    train = [trace_of(f"bug:T{i}", ["CREATE", "EDIT", "STATUS_DONE"]) for i in range(6)]
    odd = trace_of("bug:ODD", ["CREATE", "STATUS_DONE", "EDIT", "STATUS_DONE"])
    folds = {t.trace_id: 0 for t in train} | {"bug:ODD": 1}

    table = case_drivers(cfg, [*train, odd], folds, ["bug:ODD"], top_n=2)

    row = table.iloc[0]
    assert row.case_id == "bug:ODD" and row.fold == 1 and row.n_events == 4
    top = [part.split(" (")[0] for part in row.top_transitions.split(" | ")]
    assert set(top) == {"CREATE → STATUS_DONE", "STATUS_DONE → EDIT"}  # hai chuyển tiếp chưa thấy ở train
    assert row.n_unseen_transitions == 2
