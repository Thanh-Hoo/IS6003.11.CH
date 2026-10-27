"""Học biểu diễn (tái sử dụng V1) và xếp hạng ca nên xem trước (B6)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from jira_ad.analysis import NotebookInputError
from jira_ad.ranking import (
    blind_review,
    cluster_scan,
    group_labels,
    length_adjusted,
    load_oof_scores,
    loo_knn,
    majority_baseline,
    peer_groups,
    rank_cases,
    topk_stability,
)


def blobs(n=10, seed=0):
    rng = np.random.default_rng(seed)
    x = np.vstack([rng.normal(0, 0.1, (n, 3)), rng.normal(5, 0.1, (n, 3))])
    labels = pd.Series(["a"] * n + ["b"] * n, index=[f"n{i}" for i in range(2 * n)])
    return pd.DataFrame(x, index=labels.index), labels


def test_group_labels_default_to_other():
    labels = group_labels(["CREATE", "LINK_COMMIT", "ADD_UNDEFINED"],
                          {"documentation": ("CREATE",), "code": ("LINK_COMMIT",)})
    assert list(labels) == ["documentation", "code", "other"]


def test_cluster_scan_recovers_separated_groups():
    x, labels = blobs()
    table = cluster_scan(x, labels, k_min=2, k_max=4, seed=1).set_index("k")
    assert table.loc[2, "ari"] == pytest.approx(1.0) and table.loc[2, "nmi"] == pytest.approx(1.0)
    assert table.loc[2, "silhouette"] > 0.9 and list(table.index) == [2, 3, 4]


def test_loo_knn_and_majority_baseline():
    x, labels = blobs()
    assert loo_knn(x, labels, metric="cosine")["accuracy"] == pytest.approx(1.0)
    skewed = pd.Series(["a"] * 7 + ["b"] * 3)
    base = majority_baseline(skewed)
    assert base["accuracy"] == pytest.approx(0.7) and base["macro_f1"] == pytest.approx(0.7 / 1.7 * 2 / 2)


def test_length_adjusted_removes_log_length_trend():
    n = pd.Series([4, 8, 16, 32, 64], index=list("abcde"))
    raw = 1.5 * np.log(n) + 2.0
    adj = length_adjusted(raw, n)
    assert np.allclose(adj, 0.0, atol=1e-9)
    bumped = raw.copy()
    bumped["c"] += 1.0
    assert length_adjusted(bumped, n).idxmax() == "c"


def test_peer_groups_combine_branch_and_length_bins():
    cases = pd.DataFrame({"case_id": list("abcdef"), "terminal_status": ["DONE"] * 3 + ["Rejected"] * 3,
                          "n_events": [5, 10, 50, 5, 10, 50]})
    groups = peer_groups(cases, bins=3)
    assert groups["a"] == "DONE·ngắn" and groups["c"] == "DONE·dài" and groups["e"] == "Rejected·vừa"


def test_rank_counts_dimensions_above_peer_percentile_and_explains_in_words():
    ids = [f"c{i}" for i in range(20)]
    profile = pd.DataFrame({"case_id": ids, "late": range(20), "back": [0] * 19 + [5], "bf": [1] * 20})
    groups = pd.Series("DONE·vừa", index=ids)
    ranked = rank_cases(profile, ["late", "back", "bf"], groups, p=0.9,
                        labels={"late": "lượt trễ", "back": "lùi/mở lại", "bf": "đợt bù"})
    top = ranked.iloc[0]
    assert top.case_id == "c19" and top.n_exceed == 2
    assert "lượt trễ" in top.reasons and "lùi/mở lại" in top.reasons and "đợt bù" not in top.reasons
    assert ranked.loc[ranked.case_id == "c0", "n_exceed"].item() == 0
    assert list(ranked["rank"]) == list(range(1, 21))


def test_topk_stability_is_deterministic_and_bounded():
    rng = np.random.default_rng(3)
    ids = [f"c{i}" for i in range(60)]
    profile = pd.DataFrame({"case_id": ids, "a": rng.normal(size=60), "b": rng.normal(size=60)})
    groups = pd.Series(["g1", "g2"] * 30, index=ids)
    s1 = topk_stability(profile, ["a", "b"], groups, p=0.9, top_share=0.1, n_boot=50, seed=1)
    s2 = topk_stability(profile, ["a", "b"], groups, p=0.9, top_share=0.1, n_boot=50, seed=1)
    assert s1 == s2 and 0 <= s1["jaccard_low"] <= s1["jaccard_mean"] <= s1["jaccard_high"] <= 1


def test_blind_review_hides_rank_and_group():
    ranked = pd.DataFrame({"case_id": [f"c{i}" for i in range(10)], "rank": range(1, 11)})
    text = {f"c{i}": f"CREATE > S{i}" for i in range(10)}
    blinded, key = blind_review(ranked, text, n_top=2, n_random=3, seed=7)
    assert len(blinded) == 5 and set(blinded.columns) >= {"review_id", "case_id", "sequence", "label", "note"}
    assert "rank" not in blinded.columns and "group" not in blinded.columns
    assert set(key.group) == {"top", "random"} and (key.group == "top").sum() == 2
    assert set(key[key.group == "top"].case_id) == {"c0", "c1"}
    again, _ = blind_review(ranked, text, n_top=2, n_random=3, seed=7)
    assert again.equals(blinded)


def test_load_oof_scores_requires_completed_run_and_averages_seeds(tmp_path):
    run = tmp_path / "imp"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    pd.DataFrame({"trace_id": ["a", "a", "b", "b", "a"], "method": ["M_markov"] * 4 + ["A_stats"],
                  "model_seed": [42, 43, 42, 43, 42], "anomaly_score": [1.0, 3.0, 2.0, 2.0, 9.0],
                  "n_events": [5, 5, 7, 7, 5]}).to_csv(run / "cv_original_scores.csv", index=False)
    out = load_oof_scores(run, "M_markov").set_index("case_id")
    assert out.loc["a", "oof_score"] == 2.0 and out.loc["b", "n_seeds"] == 2
    (run / "manifest.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
    with pytest.raises(NotebookInputError, match="completed"):
        load_oof_scores(run, "M_markov")


def test_percentile_is_taken_within_the_peer_group_not_globally():
    ids = [f"a{i}" for i in range(10)] + [f"b{i}" for i in range(10)]
    profile = pd.DataFrame({"case_id": ids, "x": list(range(1, 11)) + list(range(100, 110))})
    groups = pd.Series(["A"] * 10 + ["B"] * 10, index=ids)
    ranked = rank_cases(profile, ["x"], groups, p=0.9).set_index("case_id")
    assert ranked.loc["a9", "n_exceed"] == 1  # cao nhất nhóm A dù thấp so với toàn bộ


def test_number_of_exceeded_dimensions_outranks_mean_percentile():
    ids = [f"c{i}" for i in range(20)]
    a = [100, -1] + list(range(2, 20))   # c0 lớn nhất ở a, gần nhỏ nhất ở b
    b = [-1, 100] + list(range(2, 20))   # c1 lớn nhất ở b; c19 đứng nhì ở cả hai chiều
    profile = pd.DataFrame({"case_id": ids, "a": a, "b": b})
    ranked = rank_cases(profile, ["a", "b"], pd.Series("g", index=ids), p=0.99).set_index("case_id")
    assert ranked.loc["c19", "n_exceed"] == 0 and ranked.loc["c19", "mean_pct"] > ranked.loc["c0", "mean_pct"]
    assert set(ranked.index[:2]) == {"c0", "c1"} and ranked.loc["c19", "rank"] == 3


def test_blind_review_random_part_never_repeats_top_cases():
    ranked = pd.DataFrame({"case_id": [f"c{i}" for i in range(10)], "rank": range(1, 11)})
    _, key = blind_review(ranked, {}, n_top=2, n_random=8, seed=3)
    assert key.case_id.is_unique
    assert set(key[key.group == "random"].case_id) == {f"c{i}" for i in range(2, 10)}


def test_build_profile_assembles_dimensions_from_earlier_steps():
    from jira_ad.ranking import build_profile

    cases = pd.DataFrame({"case_id": ["a", "b"], "terminal_status": ["DONE", "Rejected"], "n_events": [10, 5],
                          "n_back": [1, 0], "n_reopen": [1, 0], "n_backfill": [2, 0]})
    replay = pd.DataFrame({"case_id": ["a", "b"], "trace_fitness": [0.8, 1.0]})
    flags = pd.DataFrame({"case_id": ["a", "a", "b"], "flag": ["skip_investigation", "backfill", "backfill"],
                          "n": [1, 2, 0]})
    late = pd.DataFrame({"case_id": ["a", "b"], "n_late": [3, 0]})
    events = pd.DataFrame({"case_id": ["a", "a", "b"],
                           "activity": ["UPDATE_ASSIGNEE", "ADD_ASSIGNEE", "CREATE"]})
    oof = pd.DataFrame({"case_id": ["a", "b"], "oof_score": [2.0, 1.0], "n_events": [10, 5]})
    profile, dims = build_profile(cases, replay, flags, late, events, oof,
                                  assignee_activities=("ADD_ASSIGNEE", "UPDATE_ASSIGNEE"))
    p = profile.set_index("case_id")
    assert dims == ["nonconformance", "n_flags", "n_late", "n_back_reopen", "n_assignee", "n_backfill",
                    "markov_adj"]
    assert p.loc["a", "nonconformance"] == pytest.approx(0.2)
    assert p.loc["a", "n_flags"] == 1  # không tính cờ bù
    assert (p.loc["a", "n_back_reopen"], p.loc["a", "n_assignee"], p.loc["b", "n_assignee"]) == (2, 2, 0)
    without, dims2 = build_profile(cases, None, flags, late, events, None,
                                   assignee_activities=("ADD_ASSIGNEE",))
    assert "markov_adj" not in dims2 and "nonconformance" not in dims2


@pytest.fixture(scope="module")
def v1_run(tmp_path_factory):
    from datetime import UTC, datetime

    from helpers import Project, varied_rows

    from jira_ad.config import load_config
    from jira_ad.pipeline import run_experiment

    project = Project(tmp_path_factory.mktemp("v1"))
    project.write_bug(varied_rows(30))
    fast = {"embedding.dimensions": 4, "embedding.epochs": 1, "walk.walks_per_node": 3, "walk.length": 8,
            "detector.n_estimators": 12}
    return run_experiment(load_config(project.write_config(project.config(fast))),
                          now=datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC))


def test_load_v1_vectors_checks_fingerprint_and_drops_boundary_nodes(v1_run, tmp_path):
    import shutil

    from jira_ad.ranking import load_v1_vectors

    vectors = load_v1_vectors(v1_run)
    assert "__START__" not in vectors.index and vectors.shape[1] == 4
    copy = tmp_path / "repo"
    shutil.copytree(v1_run.parents[2], copy)
    tampered = copy / v1_run.relative_to(v1_run.parents[2])
    frame = pd.read_parquet(tampered / "node_vectors.parquet")
    frame.iloc[0, 1] += 1.0
    frame.to_parquet(tampered / "node_vectors.parquet")
    with pytest.raises(NotebookInputError):
        load_v1_vectors(tampered)


def test_reasons_round_values_for_readers():
    ids = [f"c{i}" for i in range(20)]
    profile = pd.DataFrame({"case_id": ids, "x": [i / 120 for i in range(20)]})
    ranked = rank_cases(profile, ["x"], pd.Series("g", index=ids), p=0.9, labels={"x": "lệch"})
    assert "lệch = 0,158 (" in ranked.iloc[0].reasons


def test_topk_consensus_keeps_cases_that_stay_in_top_across_bootstrap():
    from jira_ad.ranking import topk_consensus

    rng = np.random.default_rng(5)
    ids = [f"c{i}" for i in range(40)]
    a = rng.normal(size=40)
    b = rng.normal(size=40)
    a[0], b[0] = 50.0, 50.0           # c0 luôn đứng đầu
    profile = pd.DataFrame({"case_id": ids, "a": a, "b": b})
    groups = pd.Series("g", index=ids)
    out = topk_consensus(profile, ["a", "b"], groups, p=0.9, top_share=0.1, n_boot=60, seed=2, threshold=0.7)
    row = out.set_index("case_id").loc["c0"]
    assert row.consensus and row.share_top == 1.0 and row.n_drawn < 60  # chỉ đếm lần c0 được rút
    assert out.equals(topk_consensus(profile, ["a", "b"], groups, p=0.9, top_share=0.1, n_boot=60, seed=2,
                                     threshold=0.7))
    assert (out["share_top"] >= 0.7).sum() == out["consensus"].sum()


def test_compare_blind_review_uses_fisher_and_reports_intervals():
    from jira_ad.ranking import compare_blind_review

    key = pd.DataFrame({"review_id": [f"R{i:02d}" for i in range(1, 21)],
                        "case_id": [f"c{i}" for i in range(20)],
                        "group": ["top"] * 10 + ["random"] * 10, "rank": range(1, 21)})
    labels = (["needs_review"] * 8 + ["plausibly_valid"] * 2
              + ["needs_review"] * 1 + ["plausibly_valid"] * 8 + ["insufficient_evidence"])
    filled = pd.DataFrame({"review_id": key.review_id, "case_id": key.case_id, "label": labels})
    out = compare_blind_review(filled, key)
    assert out["top"]["needs_review"] == 8 and out["random"]["needs_review"] == 1
    assert out["fisher_p_two_sided"] < 0.01 and out["odds_ratio_ci"][0] > 1
    assert out["difference"] == pytest.approx(0.7)
    assert out["difference_ci"][0] > 0 and out["top"]["share_ci"][0] < 0.8 < out["top"]["share_ci"][1]


def test_compare_blind_review_rejects_missing_or_unknown_labels():
    from jira_ad.ranking import compare_blind_review

    key = pd.DataFrame({"review_id": ["R01", "R02"], "case_id": ["a", "b"], "group": ["top", "random"],
                        "rank": [1, 2]})
    with pytest.raises(ValueError, match="R02"):
        compare_blind_review(pd.DataFrame({"review_id": ["R01", "R02"], "label": ["needs_review", ""]}), key)
    with pytest.raises(ValueError, match="maybe"):
        bad = pd.DataFrame({"review_id": ["R01", "R02"], "label": ["needs_review", "maybe"]})
        compare_blind_review(bad, key)


def test_consensus_takes_top_share_of_the_cases_drawn_in_each_replicate():
    from jira_ad.ranking import _bootstrap_tops

    ids = [f"c{i}" for i in range(50)]
    profile = pd.DataFrame({"case_id": ids, "a": np.arange(50.0)})
    groups = pd.Series("g", index=ids)
    for drawn, top in _bootstrap_tops(profile, ["a"], groups, p=0.9, k=5, n_boot=10, seed=1, top_share=0.1):
        assert len(top) == int(np.ceil(0.1 * len(drawn)))  # tỉ lệ theo số ca được rút, không cố định k
