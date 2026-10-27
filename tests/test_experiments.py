from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from helpers import Project, varied_rows

from jira_ad import cli
from jira_ad.analysis import MissingArtifactError, open_run
from jira_ad.config import ConfigError, load_config
from jira_ad.experiments import (
    DecisionRule,
    ExperimentPlan,
    build_config,
    load_plan,
    run_plan,
)
from jira_ad.pipeline import compare_runs

FAST = {
    "embedding.dimensions": 4, "embedding.epochs": 1, "walk.walks_per_node": 3,
    "walk.length": 8, "detector.n_estimators": 12,
}
NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)


def write_plan(project: Project, plan: dict, name: str = "experiments.yaml") -> Path:
    path = project.root / "configs" / name
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def small(tmp_path):
    project = Project(tmp_path / "repo")
    project.write_bug(varied_rows(30))
    project.write_config(project.config(FAST), rel="configs/base.yaml")
    return project


def plan_dict(**overrides) -> dict:
    plan = {
        "base": "configs/base.yaml",
        "model_seeds": [42, 43],
        "experiments": [
            {"name": "baseline", "changes": {}},
            {"name": "q_half", "changes": {"walk.q": 0.5}, "note": "q = 0,5, p = 1"},
        ],
    }
    plan.update(overrides)
    return plan


def test_a_valid_plan_loads_with_its_experiments_and_default_seeds(small):
    plan = load_plan(write_plan(small, plan_dict()))

    assert isinstance(plan, ExperimentPlan)
    assert plan.model_seeds == (42, 43)
    assert [e.name for e in plan.experiments] == ["baseline", "q_half"]
    assert plan.experiments[1].changes == {"walk.q": 0.5}
    assert plan.experiments[0].seeds == (42, 43)  # mặc định lấy từ model_seeds
    assert plan.base.data.cohort == "bug"


def test_an_experiment_may_override_the_seed_list(small):
    raw = plan_dict()
    raw["experiments"][1]["seeds"] = [42]

    plan = load_plan(write_plan(small, raw))

    assert plan.experiments[1].seeds == (42,)


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda p: p.update(base="configs/nope.yaml"), "nope.yaml"),
        (lambda p: p["experiments"].append({"name": "baseline", "changes": {}}), "baseline"),
        (lambda p: p["experiments"][1]["changes"].update({"walk.zzz": 1}), "walk.zzz"),
        (lambda p: p["experiments"][1]["changes"].update({"walk.q": -1.0}), "q_half"),
        (lambda p: p["experiments"][1]["changes"].update({"walk.p": 2.0}), "một yếu tố|single|nhiều"),
        (lambda p: p.update(model_seeds=[]), "model_seeds"),
        (lambda p: p.update(model_seeds=[42, 42]), "model_seeds"),
        (lambda p: p["experiments"][0].update(seeds=["a"]), "baseline"),
        (lambda p: p.update(surprise=1), "surprise"),
        (lambda p: p["experiments"][1].pop("changes"), "changes"),
    ],
)
def test_malformed_plans_are_rejected_with_the_culprit_named(small, mutate, expected):
    raw = plan_dict()
    mutate(raw)

    with pytest.raises(ConfigError, match=expected):
        load_plan(write_plan(small, raw))


def test_more_than_one_change_needs_an_explicit_justification(small):
    raw = plan_dict()
    raw["experiments"][1] = {
        "name": "two_changes", "changes": {"walk.q": 0.5, "walk.p": 2.0},
        "allow_multiple_changes": "lý do: kiểm thử",
    }

    plan = load_plan(write_plan(small, raw))

    assert plan.experiments[1].changes == {"walk.q": 0.5, "walk.p": 2.0}


def test_build_config_applies_exactly_the_change_and_the_seed(small):
    plan = load_plan(write_plan(small, plan_dict()))

    cfg = build_config(plan, plan.experiments[1], seed=43)

    assert cfg.walk.q == 0.5 and cfg.run.seed == 43
    assert cfg.walk.p == plan.base.walk.p and cfg.embedding == plan.base.embedding
    assert plan.base.walk.q == 1.0 and plan.base.run.seed == 42  # cấu hình gốc không bị sửa


def test_an_experiment_can_switch_on_an_optional_setting_the_base_leaves_at_its_default(small):
    raw = plan_dict()
    raw["experiments"][1] = {"name": "cross_fit", "changes": {"features.cross_fit_folds": 3}}
    raw["experiments"].append(
        {"name": "few_resamples", "changes": {"evaluation.bootstrap_resamples": 50}})
    plan = load_plan(write_plan(small, raw))

    cross_fit = build_config(plan, plan.experiments[1], seed=42)
    few = build_config(plan, plan.experiments[2], seed=42)

    assert cross_fit.features.cross_fit_folds == 3 and plan.base.features.cross_fit_folds == 0
    assert cross_fit.as_dict()["features"]["cross_fit_folds"] == 3
    assert few.evaluation.bootstrap_resamples == 50
    assert plan.base.evaluation.bootstrap_resamples != 50


def test_a_typo_in_an_optional_setting_is_still_rejected(small):
    raw = plan_dict()
    raw["experiments"][1] = {"name": "typo", "changes": {"features.cross_fit_fold": 3}}

    with pytest.raises(ConfigError, match="cross_fit_fold"):
        load_plan(write_plan(small, raw))


def decision_plan(**overrides) -> dict:
    raw = plan_dict()
    raw["experiments"] = [
        {"name": "baseline", "changes": {}},
        {"name": "cross_fit", "changes": {"features.cross_fit_folds": 3}},
        {"name": "dim_8", "changes": {"embedding.dimensions": 8}},
    ]
    raw["decision"] = {
        "primary_method": "D_hybrid", "selection_split": "validation", "family_alpha": 0.05,
        "comparisons": ["cross_fit", "dim_8"], **overrides,
    }
    return raw


def test_a_plan_may_lock_its_decision_rule_before_any_run_exists(small):
    plan = load_plan(write_plan(small, decision_plan()))

    assert plan.decision == DecisionRule(
        primary_method="D_hybrid", selection_split="validation", family_alpha=0.05,
        comparisons=("cross_fit", "dim_8"))
    assert plan.decision.confidence == pytest.approx(1 - 0.05 / 2)  # Bonferroni theo số so sánh


def test_the_decision_rule_is_optional(small):
    assert load_plan(write_plan(small, plan_dict())).decision is None


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"comparisons": ["cross_fit", "nope"]}, "nope"),
        ({"comparisons": ["baseline"]}, "baseline"),
        ({"comparisons": []}, "comparisons"),
        ({"comparisons": ["dim_8", "dim_8"]}, "dim_8"),
        ({"primary_method": "Z_unknown"}, "primary_method"),
        ({"selection_split": "test"}, "selection_split"),
        ({"family_alpha": 0.0}, "family_alpha"),
        ({"family_alpha": 1.0}, "family_alpha"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_a_malformed_decision_rule_is_rejected_with_the_culprit_named(small, overrides, expected):
    with pytest.raises(ConfigError, match=expected):
        load_plan(write_plan(small, decision_plan(**overrides)))


def test_run_plan_creates_one_run_per_experiment_and_seed_with_provenance(small):
    path = write_plan(small, plan_dict())

    results = run_plan(path, now=NOW)

    assert [(r.experiment, r.seed) for r in results] == [
        ("baseline", 42), ("baseline", 43), ("q_half", 42), ("q_half", 43)]
    assert len({r.run_dir for r in results}) == 4
    for r in results:
        manifest = json.loads((r.run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["status"] == "completed"
        assert manifest["experiment"]["name"] == r.experiment
        assert manifest["experiment"]["plan"] == "configs/experiments.yaml"
        assert manifest["seeds"]["model"] == r.seed
        assert manifest["rerun_command"] == (
            f"uv run jira-ad experiments --config configs/experiments.yaml --only {r.experiment}")
    q_half = next(r for r in results if r.experiment == "q_half")
    resolved = yaml.safe_load((q_half.run_dir / "config.resolved.yaml").read_text(encoding="utf-8"))
    assert resolved["walk"]["q"] == 0.5
    assert json.loads((q_half.run_dir / "manifest.json").read_text())["experiment"]["changes"] == {
        "walk.q": 0.5}


def test_only_runs_the_named_experiments_and_a_typo_is_an_error(small):
    path = write_plan(small, plan_dict())

    results = run_plan(path, only=["q_half"], now=NOW)

    assert {r.experiment for r in results} == {"q_half"} and len(results) == 2
    with pytest.raises(ConfigError, match="q_halff"):
        run_plan(path, only=["q_halff"], now=NOW)


def test_same_data_and_split_across_experiments_but_each_group_stays_separate(small):
    path = write_plan(small, plan_dict())
    run_plan(path, now=NOW)

    result = compare_runs(small.root / "outputs" / "runs")

    by_experiment = {tuple(g["experiments"]): g for g in result["groups"]}
    assert set(by_experiment) == {("baseline",), ("q_half",)}
    assert all(len(g["runs"]) == 2 for g in result["groups"])  # hai model seed mỗi nhóm
    assert by_experiment[("baseline",)]["protocol_id"] == by_experiment[("q_half",)]["protocol_id"]
    assert by_experiment[("baseline",)]["model_config_id"] != by_experiment[("q_half",)]["model_config_id"]
    assert all(row["auroc_std"] is not None for g in result["groups"] for row in g["rows"])


def test_a_run_from_an_experiment_tells_you_how_to_recreate_it(small):
    results = run_plan(write_plan(small, plan_dict()), only=["q_half"], now=NOW)
    run_dir = results[0].run_dir
    (run_dir / "metrics.json").unlink()

    with pytest.raises(MissingArtifactError) as excinfo:
        open_run(run_dir)

    assert "uv run jira-ad experiments --config configs/experiments.yaml --only q_half" in str(
        excinfo.value)


def test_cli_experiments_runs_the_plan_and_dry_run_only_lists_it(small, capsys):
    path = write_plan(small, plan_dict())

    assert cli.main(["experiments", "--config", str(path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "baseline" in out and "q_half" in out and "walk.q=0.5" in out
    assert not (small.root / "outputs" / "runs").exists()  # dry-run không chạy gì

    assert cli.main(["experiments", "--config", str(path), "--only", "baseline"]) == 0
    assert len(list((small.root / "outputs" / "runs").iterdir())) == 2
    assert "Run dir:" in capsys.readouterr().out


def test_the_shipped_experiment_plan_is_valid_and_single_factor():
    root = Path(__file__).resolve().parents[1]
    plan = load_plan(root / "configs" / "experiments.yaml")
    names = [e.name for e in plan.experiments]

    assert plan.model_seeds == (42, 43, 44)
    assert names[0] == "baseline" and plan.experiments[0].changes == {}
    assert len(names) == len(set(names))
    for e in plan.experiments:
        assert len(e.changes) <= 1 or e.allow_multiple_changes, e.name
    assert plan.base == load_config(root / "configs" / "baseline.yaml")
