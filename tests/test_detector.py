from __future__ import annotations

import json
import re
from pathlib import Path

import joblib
import numpy as np
import pytest

from jira_ad.config import load_config
from jira_ad.detector import (
    DetectorBundle,
    fit_detector,
    load_bundle,
    save_bundle,
    score_traces,
)
from jira_ad.types import Trace

REPO_ROOT = Path(__file__).resolve().parents[1]
METHODS = ("A_stats", "B_ngrams", "C_embedding", "D_hybrid")


def _trace(trace_id, activities):
    return Trace(
        trace_id=trace_id, parent_case_id=trace_id, issue_type="bug",
        activities=tuple(activities), roles=tuple("PO" for _ in activities),
        event_ids=tuple(f"{trace_id}-e{i}" for i in range(len(activities))),
        timestamps=None, terminal_status="DONE",
    )


@pytest.fixture(scope="module")
def cfg():
    return load_config(REPO_ROOT / "configs" / "smoke.yaml")  # run nhỏ: chỉ kiểm tra phần mềm


@pytest.fixture(scope="module")
def corpus():
    """Train có một quy trình điển hình; probe có một trace lệch rõ và một chỉ có ở test."""
    typical = ["CREATE", "STATUS_A", "STATUS_B", "STATUS_DONE"]
    train = []
    for i in range(24):
        acts = list(typical)
        if i % 3 == 0:
            acts.insert(2, "EDIT")
        if i % 4 == 0:
            acts.insert(1, "LINK")
        train.append(_trace(f"train{i}", acts))
    normal = _trace("normal", typical)
    odd = _trace("odd", ["STATUS_DONE", "EDIT", "EDIT", "EDIT", "LINK", "EDIT", "CREATE"])
    novel = _trace("novel", ["CREATE", "ONLY_TEST", "STATUS_DONE"])
    return train, normal, odd, novel


@pytest.fixture(scope="module")
def bundles(cfg, corpus):
    train, *_ = corpus
    return {method: fit_detector(train, cfg, method) for method in METHODS}


@pytest.mark.parametrize("method", METHODS)
def test_score_is_the_negated_isolation_forest_score_samples(bundles, corpus, method):
    _, normal, odd, _ = corpus
    bundle = bundles[method]

    scores = score_traces(bundle, [normal, odd])

    features = bundle.encoder.transform([normal, odd]).values
    assert np.allclose(scores["anomaly_score"], -bundle.model.score_samples(features))
    assert list(scores["trace_id"]) == ["normal", "odd"]
    assert (scores["method"] == method).all()
    assert np.isfinite(scores["anomaly_score"]).all()


# C_embedding chỉ pooling nên không thấy thứ tự: spec không hứa nó bắt được trace lệch kiểu này.
@pytest.mark.parametrize("method", ("A_stats", "B_ngrams", "D_hybrid"))
def test_a_structurally_odd_trace_scores_higher_than_a_typical_one(bundles, corpus, method):
    _, normal, odd, _ = corpus

    scores = score_traces(bundles[method], [normal, odd]).set_index("trace_id")["anomaly_score"]

    assert scores["odd"] > scores["normal"]  # lớn hơn nghĩa là khác thường hơn


@pytest.mark.parametrize("method", METHODS)
def test_fit_uses_only_the_given_train_and_scoring_never_changes_the_state(
    bundles, corpus, method
):
    train, normal, odd, novel = corpus
    bundle = bundles[method]
    encoder_before = bundle.encoder.state_fingerprint()
    probe = bundle.encoder.transform([normal]).values
    model_before = bundle.model.score_samples(probe).copy()

    scores = score_traces(bundle, [normal, odd, novel])

    assert "ONLY_TEST" not in bundle.encoder.vocabulary
    assert "ONLY_TEST" not in bundle.encoder.graph
    assert bundle.encoder.train_ids == tuple(sorted(t.trace_id for t in train))
    assert bundle.encoder.state_fingerprint() == encoder_before
    assert np.array_equal(bundle.model.score_samples(probe), model_before)
    novel_row = scores.loc[scores.trace_id == "novel"].iloc[0]
    assert novel_row["unseen_node_ratio"] == pytest.approx(1 / 3)


@pytest.mark.parametrize("method", METHODS)
def test_save_then_load_reproduces_the_scores_within_1e8(bundles, corpus, method, tmp_path):
    _, normal, odd, novel = corpus
    bundle = bundles[method]
    before = score_traces(bundle, [normal, odd, novel])

    save_bundle(bundle, tmp_path / "bundle.joblib")
    loaded = load_bundle(tmp_path / "bundle.joblib")
    after = score_traces(loaded, [normal, odd, novel])

    assert isinstance(loaded, DetectorBundle)
    assert np.allclose(before["anomaly_score"], after["anomaly_score"], atol=1e-8, rtol=0)
    assert loaded.encoder.state_fingerprint() == bundle.encoder.state_fingerprint()
    assert loaded.metadata == bundle.metadata


def test_same_seed_is_reproducible_and_another_seed_changes_the_forest(cfg, corpus):
    train, normal, odd, novel = corpus
    probe = [normal, odd, novel]

    first = score_traces(fit_detector(train, cfg, "D_hybrid", seed=7), probe)
    again = score_traces(fit_detector(train, cfg, "D_hybrid", seed=7), probe)
    other = score_traces(fit_detector(train, cfg, "D_hybrid", seed=8), probe)

    assert np.array_equal(first["anomaly_score"], again["anomaly_score"])
    assert not np.array_equal(first["anomaly_score"], other["anomaly_score"])


def test_default_seed_comes_from_the_run_config(cfg, bundles):
    bundle = bundles["A_stats"]

    assert bundle.metadata["seed"] == cfg.run.seed
    assert bundle.model.random_state == cfg.run.seed


def test_detector_hyperparameters_come_from_the_config(cfg, bundles):
    model = bundles["A_stats"].model

    assert model.n_estimators == cfg.detector.n_estimators
    assert model.max_samples == cfg.detector.max_samples
    assert model.contamination == cfg.detector.contamination
    assert model.n_jobs == cfg.detector.n_jobs


def test_metadata_is_self_contained_and_json_friendly(cfg, corpus, bundles):
    train, *_ = corpus

    meta = bundles["D_hybrid"].metadata

    assert meta["method"] == "D_hybrid" and meta["n_train"] == len(train)
    assert meta["n_features"] == 2 * cfg.embedding.dimensions + 10
    assert re.fullmatch(r"[0-9a-f]{64}", meta["train_ids_sha256"])
    # nội dung quy tắc nằm trong bundle, không chỉ đường dẫn YAML
    assert meta["action_rules_sha256"] and "rules:" in meta["action_rules_text"]
    assert meta["preprocess"]["noise_policy"] == cfg.preprocess.noise_policy
    assert meta["preprocess"]["terminal_statuses"] == list(cfg.preprocess.terminal_statuses)
    assert meta["config"]["embedding"]["dimensions"] == cfg.embedding.dimensions
    assert {"python", "numpy", "scikit-learn", "gensim", "pandas"} <= set(meta["packages"])
    assert meta["fit_seconds"] >= 0
    json.dumps(meta, allow_nan=False)  # ghi được ra fit_metadata.json


def test_metadata_reports_features_that_are_constant_on_train(bundles):
    meta = bundles["A_stats"].metadata

    # fit→transform in-sample: unseen_* luôn 0 trên train nên Isolation Forest không dùng được chúng
    assert "unseen_node_ratio" in meta["constant_feature_names"]
    assert "unseen_transition_ratio" in meta["constant_feature_names"]
    assert meta["n_constant_features"] == len(meta["constant_feature_names"])


def test_empty_train_is_rejected(cfg):
    with pytest.raises(ValueError, match="rỗng|empty"):
        fit_detector([], cfg, "A_stats")


def test_unknown_method_is_rejected(cfg, corpus):
    train, *_ = corpus

    with pytest.raises(ValueError, match="Z_unknown"):
        fit_detector(train, cfg, "Z_unknown")


def test_non_finite_scores_are_an_error_not_a_silent_value(cfg, corpus, monkeypatch):
    train, normal, *_ = corpus
    bundle = fit_detector(train, cfg, "A_stats")
    monkeypatch.setattr(bundle.model, "score_samples", lambda x: np.full(len(x), np.nan))

    with pytest.raises(ValueError, match="NaN|Inf|hữu hạn"):
        score_traces(bundle, [normal])


def test_load_refuses_files_that_are_not_detector_bundles(tmp_path):
    path = tmp_path / "other.joblib"
    joblib.dump({"not": "a bundle"}, path)

    with pytest.raises(TypeError, match="DetectorBundle"):
        load_bundle(path)
    with pytest.raises(FileNotFoundError):
        load_bundle(tmp_path / "missing.joblib")


def test_scoring_an_empty_list_returns_an_empty_frame(bundles):
    scores = score_traces(bundles["A_stats"], [])

    assert len(scores) == 0
    assert {"trace_id", "method", "anomaly_score"} <= set(scores.columns)


# ================================================ cross-fit trên train (Task 12)

import dataclasses  # noqa: E402

from sklearn.ensemble import IsolationForest  # noqa: E402


def _cross_fit_cfg(cfg, folds=4):
    return dataclasses.replace(cfg, features=dataclasses.replace(cfg.features, cross_fit_folds=folds))


def test_cross_fit_gives_the_forest_graph_features_that_vary_on_train(cfg, corpus):
    train, *_ = corpus
    train = [*train, _trace("rare", ["CREATE", "ONLY_HERE", "STATUS_DONE"])]

    plain = fit_detector(train, cfg, "A_stats").metadata
    crossed = fit_detector(train, _cross_fit_cfg(cfg), "A_stats").metadata

    assert "unseen_node_ratio" in plain["constant_feature_names"]  # V1: in-sample ⇒ hằng
    assert "unseen_node_ratio" not in crossed["constant_feature_names"]
    assert crossed["n_constant_features"] < plain["n_constant_features"]
    assert crossed["config"]["features"]["cross_fit_folds"] == 4
    assert "cross_fit_folds" not in plain["config"]["features"]  # baseline không đổi dạng ghi nhận


@pytest.mark.parametrize("method", ["A_stats", "D_hybrid"])
def test_the_forest_is_fitted_on_exactly_the_train_feature_matrix_of_the_encoder(
    cfg, corpus, method
):
    train, *_ = corpus
    train = [*train, _trace("rare", ["CREATE", "ONLY_HERE", "STATUS_DONE"])]
    crossed_cfg = _cross_fit_cfg(cfg)
    bundle = fit_detector(train, crossed_cfg, method)
    d = crossed_cfg.detector

    matrix = bundle.encoder.transform_train(train).values
    reference = IsolationForest(
        n_estimators=d.n_estimators, max_samples=d.max_samples, contamination=d.contamination,
        random_state=bundle.metadata["seed"], n_jobs=d.n_jobs).fit(matrix)

    probe = bundle.encoder.transform(train).values  # ma trận in-sample: khác ma trận cross-fit
    assert not np.array_equal(matrix, probe)
    assert np.array_equal(bundle.model.score_samples(probe), reference.score_samples(probe))


def test_scoring_held_out_traces_is_unchanged_by_the_cross_fit_flag_in_the_encoder(cfg, corpus):
    train, normal, odd, novel = corpus
    plain = fit_detector(train, cfg, "A_stats").encoder.transform([normal, odd, novel]).values
    crossed = fit_detector(train, _cross_fit_cfg(cfg), "A_stats").encoder.transform(
        [normal, odd, novel]).values

    assert np.array_equal(plain, crossed)


# ======================================================= bộ chấm điểm của E/F/M (2026-10-22)

from jira_ad.features import H_FEATURE_NAMES  # noqa: E402

NEW_METHODS = ("E_score_fusion", "F_edge_hybrid", "M_markov")


@pytest.fixture(scope="module")
def new_bundles(cfg, corpus):
    train, *_ = corpus
    return {method: fit_detector(train, cfg, method) for method in NEW_METHODS}


def test_markov_score_is_the_mean_transition_surprisal(new_bundles, corpus):
    _, normal, odd, novel = corpus
    bundle = new_bundles["M_markov"]
    index = H_FEATURE_NAMES.index("mean_transition_surprisal")

    scores = score_traces(bundle, [normal, odd, novel])

    expected = bundle.encoder.transform([normal, odd, novel]).values[:, index]
    assert np.allclose(scores.anomaly_score, expected)
    assert scores.anomaly_score[1] > scores.anomaly_score[0]


def test_fusion_score_is_the_mean_of_train_standardised_forest_scores(new_bundles, corpus, cfg):
    train, normal, odd, _ = corpus
    bundle = new_bundles["E_score_fusion"]
    names = bundle.encoder.feature_names
    h_cols = [i for i, n in enumerate(names) if n in H_FEATURE_NAMES]
    e_cols = [i for i, n in enumerate(names) if n not in H_FEATURE_NAMES]
    x_train = bundle.encoder.transform(train).values
    x_probe = bundle.encoder.transform([normal, odd]).values
    z = []
    for cols in (h_cols, e_cols):
        forest = IsolationForest(n_estimators=cfg.detector.n_estimators, max_samples="auto",
                                 contamination="auto", random_state=cfg.run.seed, n_jobs=1)
        forest.fit(x_train[:, cols])
        train_scores = -forest.score_samples(x_train[:, cols])
        std = train_scores.std() or 1.0
        z.append((-forest.score_samples(x_probe[:, cols]) - train_scores.mean()) / std)

    scores = score_traces(bundle, [normal, odd])

    assert np.allclose(scores.anomaly_score, np.mean(z, axis=0))


def test_fusion_with_constant_train_scores_stays_finite(cfg):
    same = [_trace(f"s{i}", ["CREATE", "A", "DONE"]) for i in range(6)]
    bundle = fit_detector(same, cfg, "E_score_fusion")

    scores = score_traces(bundle, [same[0], _trace("x", ["CREATE", "Q", "Q", "DONE"])])

    assert np.isfinite(scores.anomaly_score).all()


@pytest.mark.parametrize("method", NEW_METHODS)
def test_new_bundles_give_the_same_scores_after_save_and_load(new_bundles, corpus, tmp_path, method):
    _, normal, odd, novel = corpus
    path = tmp_path / method / "bundle.joblib"
    before = score_traces(new_bundles[method], [normal, odd, novel])

    save_bundle(new_bundles[method], path)
    after = score_traces(load_bundle(path), [normal, odd, novel])

    assert np.allclose(before.anomaly_score, after.anomaly_score, atol=1e-8, rtol=0)


@pytest.mark.parametrize("method", NEW_METHODS)
def test_new_methods_are_fitted_on_train_only(cfg, corpus, method):
    train, normal, *_ = corpus
    bundle = fit_detector(train, cfg, method)
    state = bundle.metadata["encoder_state_sha256"]

    score_traces(bundle, [_trace("held", ["CREATE", "ONLY_TEST", "STATUS_DONE"]), normal])

    assert bundle.encoder.state_fingerprint() == state
    assert bundle.metadata["n_train"] == len(train)
