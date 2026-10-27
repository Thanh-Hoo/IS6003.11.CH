from __future__ import annotations

import random
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

import jira_ad.crossval as crossval
from jira_ad.config import load_config
from jira_ad.crossval import cv_folds, run_crossval
from jira_ad.detector import fit_detector, score_traces

REPO_ROOT = Path(__file__).resolve().parents[1]
STEPS = ["EDIT", "LINK", "STATUS_In Progress", "STATUS_In Test", "ASSIGN", "COMMENT"]


@pytest.fixture(scope="module")
def cfg():
    return load_config(REPO_ROOT / "configs" / "smoke.yaml")  # run nhỏ: chỉ kiểm tra phần mềm


@pytest.fixture
def corpus(trace_of):
    rng = random.Random(3)
    traces = []
    for i in range(20):
        middle = rng.sample(STEPS, rng.randint(2, 5))
        status = "Rejected" if i % 3 == 0 else "DONE"
        traces.append(trace_of(f"bug:T{i:02d}", ["CREATE", *middle, f"STATUS_{status}"],
                               terminal_status=status))
    return traces


def test_folds_cover_every_trace_once_are_balanced_and_stratified(corpus):
    folds = cv_folds(corpus, 4, seed=42)

    assert set(folds) == {t.trace_id for t in corpus}
    sizes = Counter(folds.values())
    assert set(sizes) == {0, 1, 2, 3} and max(sizes.values()) - min(sizes.values()) <= 1
    for status in ("DONE", "Rejected"):
        per = Counter(folds[t.trace_id] for t in corpus if t.terminal_status == status)
        assert max(per.values()) - min(per.values()) <= 1


def test_folds_are_deterministic_independent_of_order_and_depend_on_the_seed(corpus):
    shuffled = corpus[:]
    random.Random(1).shuffle(shuffled)

    assert cv_folds(corpus, 4, seed=42) == cv_folds(shuffled, 4, seed=42)
    assert cv_folds(corpus, 4, seed=42) != cv_folds(corpus, 4, seed=7)


def test_more_folds_than_cases_or_fewer_than_two_is_rejected(corpus):
    with pytest.raises(ValueError):
        cv_folds(corpus[:3], 4, seed=42)
    with pytest.raises(ValueError):
        cv_folds(corpus, 1, seed=42)


def test_each_fold_model_is_fitted_only_on_the_other_folds(corpus, cfg, monkeypatch):
    calls = []
    real = crossval.fit_detector

    def spy(train, cfg_, method, seed=None):
        calls.append({t.trace_id for t in train})
        return real(train, cfg_, method, seed)

    monkeypatch.setattr(crossval, "fit_detector", spy)
    folds = cv_folds(corpus, 4, seed=cfg.split.seed)

    run_crossval(cfg, corpus, methods=["A_stats"], folds=4, model_seeds=[42],
                 mutation_types=["delete_internal"])

    assert len(calls) == 4
    for fold, train_ids in enumerate(calls):
        held = {cid for cid, f in folds.items() if f == fold}
        assert not train_ids & held and train_ids | held == set(folds)


def test_every_trace_is_scored_once_per_seed_and_method(corpus, cfg):
    result = run_crossval(cfg, corpus, methods=["A_stats", "M_markov"], folds=4, model_seeds=[42, 43],
                          mutation_types=["delete_internal", "skip_status"])

    counts = result.originals.groupby(["model_seed", "method"]).trace_id.agg(["size", "nunique"])
    assert (counts["size"] == len(corpus)).all() and (counts["nunique"] == len(corpus)).all()
    assert set(result.metrics.mutation_type) == {"delete_internal", "skip_status"}
    assert set(result.metrics.model_seed) == {42, 43}
    assert np.isfinite(result.originals.anomaly_score).all()
    assert {"fold", "model_seed", "raw_score"} <= set(result.originals.columns)
    assert {"method", "fit_seconds", "score_ms_per_trace"} <= set(result.timings.columns)


def test_scores_are_standardised_by_the_fold_models_own_train_scores(corpus, cfg):
    result = run_crossval(cfg, corpus, methods=["M_markov"], folds=4, model_seeds=[42],
                          mutation_types=["delete_internal"])
    folds = cv_folds(corpus, 4, seed=cfg.split.seed)
    fold = 2
    train = [t for t in corpus if folds[t.trace_id] != fold]
    train_raw = score_traces(fit_detector(train, cfg, "M_markov", 42), train).anomaly_score.to_numpy()
    part = result.originals[result.originals.fold == fold]

    expected = (part.raw_score - train_raw.mean()) / train_raw.std()

    assert np.allclose(part.anomaly_score, expected)


def test_mutants_are_identical_across_methods_and_model_seeds(corpus, cfg):
    result = run_crossval(cfg, corpus, methods=["A_stats", "M_markov"], folds=4, model_seeds=[42, 43],
                          mutation_types=["multi_edit"])

    ids = result.mutants.groupby(["model_seed", "method"]).trace_id.apply(frozenset)
    assert ids.nunique() == 1
    assert (result.ledger.split.str.startswith("fold")).all()
