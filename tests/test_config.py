from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from jira_ad.config import (
    ConfigError,
    RunConfig,
    config_from_dict,
    load_config,
    resolve_project_root,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_config_returns_typed_sections(project):
    cfg = load_config(project.write_config())

    assert isinstance(cfg, RunConfig)
    assert cfg.split.seed == 42
    assert cfg.split.train_fraction == pytest.approx(0.6)
    assert isinstance(cfg.walk.p, float)
    assert cfg.preprocess.terminal_statuses == ("DONE", "Rejected")
    assert cfg.features.methods == ("A_stats", "B_ngrams", "C_embedding", "D_hybrid")
    assert cfg.detector.max_samples == "auto"
    assert cfg.project_root == project.root
    assert cfg.resolve(cfg.data.root) == project.root / "dataset"


def test_int_is_accepted_where_float_is_declared(project):
    cfg = load_config(project.write_config(project.config({"walk.p": 2, "walk.q": 1})))

    assert cfg.walk.p == 2.0
    assert isinstance(cfg.walk.p, float)


def test_project_root_is_found_by_walking_up_to_pyproject(project):
    nested = project.write_config(rel="configs/deep/nested/run.yaml")

    assert resolve_project_root(nested) == project.root
    assert load_config(nested).project_root == project.root


def test_missing_pyproject_is_an_error(tmp_path):
    orphan = tmp_path / "no_project" / "cfg.yaml"
    orphan.parent.mkdir()
    orphan.write_text(yaml.safe_dump({"x": 1}), encoding="utf-8")

    with pytest.raises(ConfigError, match="pyproject.toml"):
        resolve_project_root(orphan)


def test_split_fractions_must_sum_to_one(project):
    path = project.write_config(project.config({"split.test_fraction": 0.30}))

    with pytest.raises(ConfigError, match="split"):
        load_config(path)


def test_unknown_key_is_rejected_and_named(project):
    path = project.write_config(project.config({"split.train_fractoin": 0.6}))

    with pytest.raises(ConfigError, match="train_fractoin"):
        load_config(path)


def test_unknown_section_is_rejected(project):
    path = project.write_config(project.config({"extras": {"a": 1}}))

    with pytest.raises(ConfigError, match="extras"):
        load_config(path)


def test_missing_key_is_rejected_and_named(project, delete):
    path = project.write_config(project.config({"walk.q": delete}))

    with pytest.raises(ConfigError, match=r"walk.*q|q.*walk"):
        load_config(path)


@pytest.mark.parametrize(
    "key, value",
    [
        ("walk.p", "high"),
        ("embedding.dimensions", 16.5),
        ("embedding.dimensions", True),
        ("run.seed", "42"),
        ("data.recursive_discovery", "yes"),
        ("preprocess.terminal_statuses", "DONE"),
        ("graph.transition_alpha", None),
    ],
)
def test_wrong_type_is_rejected(project, key, value):
    path = project.write_config(project.config({key: value}))

    with pytest.raises(ConfigError, match=key.split(".")[-1]):
        load_config(path)


@pytest.mark.parametrize(
    "key, value",
    [
        ("walk.p", 0),
        ("walk.q", -1.0),
        ("walk.length", 1),
        ("walk.walks_per_node", 0),
        ("embedding.dimensions", 0),
        ("embedding.workers", 0),
        ("embedding.epochs", 0),
        ("graph.transition_alpha", 0.0),
        ("split.train_fraction", 0.0),
        ("detector.n_estimators", 0),
        ("detector.n_jobs", 0),
        ("notebooks.timeout_seconds", 0),
        ("mutation.max_per_type_per_parent", 2),
        ("mutation.duplicate_block_max_length", 0),
    ],
)
def test_out_of_range_values_are_rejected(project, key, value):
    path = project.write_config(project.config({key: value}))

    with pytest.raises(ConfigError):
        load_config(path)


@pytest.mark.parametrize(
    "key, value",
    [
        ("preprocess.view", "weird"),
        ("preprocess.noise_policy", "delete_everything"),
        ("graph.encoding", "bad"),
        ("split.stratify", "label"),
        ("features.methods", ["A_stats", "Z_unknown"]),
        ("features.methods", ["A_stats", "A_stats"]),
        ("features.methods", []),
        ("mutation.types", ["rotate"]),
        ("detector.max_samples", "many"),
        ("detector.contamination", 0.9),
    ],
)
def test_unsupported_choices_are_rejected(project, key, value):
    path = project.write_config(project.config({key: value}))

    with pytest.raises(ConfigError):
        load_config(path)


def test_include_time_is_rejected_while_mutations_have_no_timestamps(project):
    path = project.write_config(project.config({"features.include_time": True}))

    with pytest.raises(ConfigError, match="include_time"):
        load_config(path)


@pytest.mark.parametrize(
    "key", ["data.root", "preprocess.actions_file", "project.output_root"]
)
def test_absolute_paths_are_rejected(project, key):
    path = project.write_config(project.config({key: "/etc/somewhere"}))

    with pytest.raises(ConfigError, match="tuyệt đối|absolute"):
        load_config(path)


def test_cohort_must_name_a_configured_file(project):
    path = project.write_config(project.config({"data.cohort": "epic"}))

    with pytest.raises(ConfigError, match="cohort"):
        load_config(path)


def test_reference_counts_are_optional_and_validated(project):
    ok = project.config({"data.reference_counts": {"bug": {"events": 10, "issues": 2}}})
    assert load_config(project.write_config(ok)).data.reference_counts == {
        "bug": {"events": 10, "issues": 2}
    }

    bad = project.config({"data.reference_counts": {"epic": {"events": 10, "issues": 2}}})
    with pytest.raises(ConfigError, match="epic"):
        load_config(project.write_config(bad, rel="configs/bad.yaml"))


def test_actions_path_is_resolved_against_the_project_root(project):
    cfg = load_config(project.write_config())

    assert cfg.preprocess.actions_path == project.root / "configs" / "actions.yaml"


def test_actions_path_cannot_be_set_from_yaml(project):
    path = project.write_config(project.config({"preprocess.actions_path": "elsewhere.yaml"}))

    with pytest.raises(ConfigError, match="actions_path"):
        load_config(path)


def test_a_config_can_be_rebuilt_exactly_from_its_resolved_dict(project):
    cfg = load_config(project.write_config())

    rebuilt = config_from_dict(cfg.as_dict(), cfg.project_root, cfg.config_path)

    assert rebuilt == cfg


def test_rebuilding_from_a_dict_is_as_strict_as_loading_a_file(project):
    cfg = load_config(project.write_config())
    broken = cfg.as_dict()
    broken["split"]["test_fraction"] = 0.5

    with pytest.raises(ConfigError, match="split"):
        config_from_dict(broken, cfg.project_root, cfg.config_path)


def test_non_mapping_yaml_is_rejected(project):
    path = project.root / "configs" / "list.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("- a\n- b\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="mapping|ánh xạ"):
        load_config(path)


def test_shipped_baseline_and_smoke_configs_load():
    baseline = load_config(REPO_ROOT / "configs" / "baseline.yaml")
    smoke = load_config(REPO_ROOT / "configs" / "smoke.yaml")

    assert baseline.project_root == REPO_ROOT
    assert baseline.data.cohort == "bug"
    assert baseline.split.seed == 42
    assert (baseline.split.train_fraction, baseline.split.validation_fraction,
            baseline.split.test_fraction) == (0.60, 0.20, 0.20)
    assert baseline.run.seed == 42
    assert smoke.data.cohort == "bug"


def test_smoke_config_only_shrinks_the_declared_hyperparameters():
    baseline = load_config(REPO_ROOT / "configs" / "baseline.yaml")
    smoke = load_config(REPO_ROOT / "configs" / "smoke.yaml")

    def flatten(cfg: RunConfig) -> dict:
        out = {}
        for section in (
            "project", "data", "preprocess", "split", "graph", "walk", "embedding",
            "features", "detector", "mutation", "run", "notebooks",
        ):
            for name, value in vars(getattr(cfg, section)).items():
                out[f"{section}.{name}"] = value
        return out

    base, small = flatten(baseline), flatten(smoke)
    changed = {key for key in base if base[key] != small[key]}

    assert changed == {
        "embedding.dimensions",
        "walk.walks_per_node",
        "embedding.epochs",
        "detector.n_estimators",
    }
    assert small["embedding.dimensions"] == 8
    assert small["walk.walks_per_node"] == 5
    assert small["embedding.epochs"] == 2
    assert small["detector.n_estimators"] == 20


# ------------------------------------------------------- tùy chọn mở rộng (Task 9): mặc định vô hình


def _legacy_hash(raw: dict) -> str:
    """Hash đúng như `config_hash` trước khi có tùy chọn mở rộng, từ dict YAML cũ.

    Dạng đã resolve cũ luôn in `data.reference_counts` (null nếu vắng) và bỏ cờ vận hành.
    """
    import hashlib

    payload = {name: dict(section) for name, section in raw.items()}
    payload["data"].setdefault("reference_counts", None)
    payload["run"] = {k: v for k, v in payload["run"].items() if k != "fail_on_existing_output"}
    return hashlib.sha256(
        yaml.safe_dump(payload, sort_keys=True, allow_unicode=True).encode("utf-8")
    ).hexdigest()


def test_options_left_at_their_default_do_not_change_the_hash_of_an_older_config(project):
    from jira_ad.config import config_hash

    raw = project.config()  # chưa có khóa mở rộng nào
    cfg = load_config(project.write_config(raw))

    assert config_hash(cfg) == _legacy_hash(raw)
    assert "evaluation" not in cfg.as_dict()
    assert "cross_fit_folds" not in cfg.as_dict()["features"]
    assert "strategy" not in cfg.as_dict()["split"]


def test_options_set_to_a_non_default_value_are_recorded_and_change_the_hash(project):
    from jira_ad.config import config_hash

    raw = project.config()
    raw["features"]["cross_fit_folds"] = 5
    raw["evaluation"] = {"bootstrap_resamples": 500}
    cfg = load_config(project.write_config(raw))

    assert cfg.features.cross_fit_folds == 5
    assert cfg.as_dict()["features"]["cross_fit_folds"] == 5
    assert cfg.as_dict()["evaluation"] == {"bootstrap_resamples": 500}
    assert config_hash(cfg) != _legacy_hash(project.config())


def test_as_dict_can_list_every_option_including_defaults(project):
    cfg = load_config(project.write_config())

    full = cfg.as_dict(include_defaults=True)

    assert full["features"]["cross_fit_folds"] == 0
    assert full["split"]["strategy"] == "random"
    assert full["evaluation"]["bootstrap_resamples"] == cfg.evaluation.bootstrap_resamples
    assert config_from_dict(full, cfg.project_root, cfg.config_path) == cfg


@pytest.mark.parametrize("folds", [1, -1])
def test_cross_fit_folds_must_be_zero_or_at_least_two(project, folds):
    raw = project.config()
    raw["features"]["cross_fit_folds"] = folds

    with pytest.raises(ConfigError, match="cross_fit_folds"):
        load_config(project.write_config(raw))


@pytest.mark.parametrize(
    "key, value",
    [
        ("bootstrap_resamples", 0),
        ("permutations", 0),
        ("confidence", 1.0),
        ("confidence", 0.0),
        ("bootstrap_seed", "x"),
        ("not_a_key", 1),
    ],
)
def test_evaluation_section_is_validated(project, key, value):
    raw = project.config()
    raw["evaluation"] = {key: value}

    with pytest.raises(ConfigError, match=key):
        load_config(project.write_config(raw))


def test_split_strategy_accepts_random_or_temporal_only(project):
    raw = project.config()
    raw["split"]["strategy"] = "temporal"
    assert load_config(project.write_config(raw)).split.strategy == "temporal"

    raw["split"]["strategy"] = "shuffled"
    with pytest.raises(ConfigError, match="strategy"):
        load_config(project.write_config(raw, rel="configs/bad.yaml"))
