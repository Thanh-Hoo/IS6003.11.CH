from __future__ import annotations

import json

import pandas as pd
import pytest

from jira_ad.evaluation import evaluate_semisynthetic, metrics_frame, paired_frame


def originals(rows, method="M"):
    """rows: [(parent_id, score)]; bản gốc có trace_id == parent_case_id."""
    return pd.DataFrame(
        [{"method": method, "trace_id": p, "parent_case_id": p, "anomaly_score": s}
         for p, s in rows]
    )


def mutants(rows, method="M"):
    """rows: [(mutation_id, parent_id, score)]."""
    return pd.DataFrame(
        [{"method": method, "trace_id": m, "parent_case_id": p, "anomaly_score": s}
         for m, p, s in rows]
    )


def ledger(rows):
    """rows: [(mutation_id, parent_id, type, status, skip_reason)]."""
    return pd.DataFrame(
        [{"mutation_id": m, "parent_case_id": p, "mutation_type": t, "status": st,
          "skip_reason": r} for m, p, t, st, r in rows]
    )


def only_row(result, **where):
    frame = metrics_frame(result)
    for key, value in where.items():
        frame = frame[frame[key] == value]
    assert len(frame) == 1, frame
    return frame.iloc[0]


def swap_ledger(parents):
    return ledger([(f"m{p}", p, "swap_adjacent", "created", None) for p in parents])


def test_perfect_separation_gives_auroc_one_and_the_documented_counts():
    result = evaluate_semisynthetic(
        originals([("a", 0.1), ("b", 0.2)]),
        mutants([("ma", "a", 0.8), ("mb", "b", 0.9)]),
        swap_ledger(["a", "b"]),
    )

    row = only_row(result, mutation_type="swap_adjacent")
    assert row["auroc"] == 1.0 and row["average_precision"] == 1.0
    assert row["n_original"] == 2 and row["n_mutant"] == 2
    assert row["injected_rate"] == 0.5 and row["ap_constant_predictor"] == 0.5
    assert row["paired_win_rate"] == 1.0 and pd.isna(row["null_reason"])


def test_inverted_scores_report_the_bad_result_honestly():
    result = evaluate_semisynthetic(
        originals([("a", 0.8), ("b", 0.9)]),
        mutants([("ma", "a", 0.1), ("mb", "b", 0.2)]),
        swap_ledger(["a", "b"]),
    )

    row = only_row(result, mutation_type="swap_adjacent")
    assert row["auroc"] == 0.0 and row["paired_win_rate"] == 0.0


def test_paired_ties_count_half_and_auroc_ties_are_neutral():
    result = evaluate_semisynthetic(
        originals([("a", 0.5), ("b", 0.5), ("c", 0.1)]),
        mutants([("ma", "a", 0.5), ("mb", "b", 0.9), ("mc", "c", 0.05)]),
        swap_ledger(["a", "b", "c"]),
    )

    row = only_row(result, mutation_type="swap_adjacent")
    assert row["paired_win_rate"] == pytest.approx((0.5 + 1.0 + 0.0) / 3)


def test_pairing_uses_the_parent_id_not_the_row_order():
    orig = originals([("a", 0.1), ("b", 0.5), ("c", 0.9)])
    muts = mutants([("ma", "a", 0.3), ("mb", "b", 0.4), ("mc", "c", 0.95)])
    led = swap_ledger(["a", "b", "c"])

    straight = evaluate_semisynthetic(orig, muts, led)
    shuffled = evaluate_semisynthetic(
        orig.sample(frac=1.0, random_state=1), muts.sample(frac=1.0, random_state=2), led
    )

    assert paired_frame(shuffled).sort_values("parent_case_id").reset_index(drop=True).equals(
        paired_frame(straight).sort_values("parent_case_id").reset_index(drop=True))
    paired = paired_frame(straight).set_index("parent_case_id")
    assert paired.loc["a", "delta_score"] == pytest.approx(0.2)
    assert paired.loc["b", "delta_score"] == pytest.approx(-0.1)
    assert paired.loc["c", "delta_score"] == pytest.approx(0.05)
    row = only_row(straight, mutation_type="swap_adjacent")
    assert row["paired_win_rate"] == pytest.approx(2 / 3)


def test_a_type_without_valid_mutants_is_null_with_a_reason_not_zero():
    result = evaluate_semisynthetic(
        originals([("a", 0.1), ("b", 0.2)]),
        mutants([("ma", "a", 0.8), ("mb", "b", 0.9)]),
        ledger([("ma", "a", "swap_adjacent", "created", None),
                ("mb", "b", "swap_adjacent", "created", None),
                ("xa", "a", "delete_internal", "skipped", "no_internal_events"),
                ("xb", "b", "delete_internal", "skipped", "no_internal_events")]),
    )

    row = only_row(result, mutation_type="delete_internal")
    assert row["n_mutant"] == 0 and row["n_original"] == 0
    assert pd.isna(row["auroc"]) and pd.isna(row["average_precision"])
    assert pd.isna(row["paired_win_rate"])
    assert row["null_reason"] == "no_valid_mutants"
    assert result["mutation_summary"]["delete_internal"]["skipped"] == 2
    assert result["mutation_summary"]["delete_internal"]["skip_reasons"] == {
        "no_internal_events": 2}


def test_originals_without_a_mutant_of_that_type_do_not_enter_the_benchmark():
    result = evaluate_semisynthetic(
        originals([("a", 0.1), ("b", 0.2), ("c", 0.3)]),
        mutants([("ma", "a", 0.8)]),
        ledger([("ma", "a", "swap_adjacent", "created", None),
                ("xb", "b", "swap_adjacent", "skipped", "no_distinct_adjacent_pair"),
                ("xc", "c", "swap_adjacent", "skipped", "no_distinct_adjacent_pair")]),
    )

    row = only_row(result, mutation_type="swap_adjacent")
    assert row["n_original"] == 1 and row["n_mutant"] == 1 and row["injected_rate"] == 0.5


def test_methods_are_compared_on_the_intersection_of_valid_pairs():
    orig = pd.concat([originals([("a", 0.1), ("b", 0.2), ("c", 0.3)], "M1"),
                      originals([("a", 0.1), ("b", 0.2), ("c", 0.3)], "M2")])
    muts = pd.concat([
        mutants([("ma", "a", 0.8), ("mb", "b", 0.9), ("mc", "c", 0.95)], "M1"),
        mutants([("ma", "a", 0.8), ("mb", "b", 0.9)], "M2"),  # M2 thiếu mutant của c
    ])

    result = evaluate_semisynthetic(orig, muts, swap_ledger(["a", "b", "c"]))

    n = {m: int(only_row(result, method=m, mutation_type="swap_adjacent")["n_mutant"])
         for m in ("M1", "M2")}
    assert n == {"M1": 2, "M2": 2}  # cùng giao tập a, b cho mọi phương pháp
    assert result["intersection"]["swap_adjacent"] == {"n_parents": 2, "methods": ["M1", "M2"]}


def test_every_method_and_type_gets_its_own_row_and_the_result_is_json_safe():
    orig = pd.concat([originals([("a", 0.1), ("b", 0.2)], m) for m in ("M1", "M2")])
    muts = pd.concat([mutants([("ma", "a", 0.8), ("mb", "b", 0.3),
                               ("da", "a", 0.2), ("db", "b", 0.9)], m) for m in ("M1", "M2")])
    led = ledger([("ma", "a", "swap_adjacent", "created", None),
                  ("mb", "b", "swap_adjacent", "created", None),
                  ("da", "a", "delete_internal", "created", None),
                  ("db", "b", "delete_internal", "created", None)])

    result = evaluate_semisynthetic(orig, muts, led)

    frame = metrics_frame(result)
    assert sorted(zip(frame.method, frame.mutation_type, strict=True)) == [
        ("M1", "delete_internal"), ("M1", "swap_adjacent"),
        ("M2", "delete_internal"), ("M2", "swap_adjacent")]
    json.dumps(result, allow_nan=False)  # không NaN/Inf âm thầm


def test_a_mutant_pointing_at_an_unscored_parent_is_an_error():
    with pytest.raises(ValueError, match="ghost"):
        evaluate_semisynthetic(
            originals([("a", 0.1)]),
            mutants([("ma", "a", 0.8), ("mg", "ghost", 0.7)]),
            ledger([("ma", "a", "swap_adjacent", "created", None),
                    ("mg", "ghost", "swap_adjacent", "created", None)]),
        )


def test_duplicate_original_scores_are_an_error():
    with pytest.raises(ValueError, match="trùng|duplicate"):
        evaluate_semisynthetic(
            originals([("a", 0.1), ("a", 0.2)]),
            mutants([("ma", "a", 0.8)]),
            swap_ledger(["a"]),
        )


def test_scores_must_be_finite():
    with pytest.raises(ValueError, match="hữu hạn|NaN"):
        evaluate_semisynthetic(
            originals([("a", float("nan"))]),
            mutants([("ma", "a", 0.8)]),
            swap_ledger(["a"]),
        )


def test_prevalence_is_the_design_ratio_and_not_a_real_anomaly_rate():
    result = evaluate_semisynthetic(
        originals([(f"p{i}", 0.1 * i) for i in range(6)]),
        mutants([(f"mp{i}", f"p{i}", 0.1 * i + 0.05) for i in range(6)]),
        swap_ledger([f"p{i}" for i in range(6)]),
    )

    row = only_row(result, mutation_type="swap_adjacent")
    assert row["injected_rate"] == 0.5 and row["ap_constant_predictor"] == 0.5
    assert "is_injected" in result["label_definition"]
    assert "true_anomaly" not in json.dumps(result)


# ===================================================== bootstrap theo parent (Task 10, spec §6.2)

import numpy as np  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from jira_ad.evaluation import (  # noqa: E402
    bootstrap_by_parent,
    bootstrap_differences_frame,
    bootstrap_intervals_frame,
    paired_auroc,
)

TYPES = ("swap_adjacent", "delete_internal", "duplicate_block")


def paired_table(scores, types=TYPES):
    """scores: {method: {parent: (original, mutant)}}, dùng chung cho mọi loại trừ khi types khác nhau."""
    rows = []
    for method, by_parent in scores.items():
        for mutation_type in types:
            for parent, (orig, mut) in by_parent.items():
                rows.append({
                    "method": method, "mutation_type": mutation_type, "parent_case_id": parent,
                    "mutation_id": f"{parent}::{mutation_type}", "original_score": orig,
                    "mutant_score": mut, "delta_score": mut - orig,
                })
    return pd.DataFrame(rows)


def noisy_scores(n=31, seed=0, shift=0.0):
    rng = np.random.default_rng(seed)
    return {f"P{i:02d}": (float(rng.normal()), float(rng.normal() + shift)) for i in range(n)}


def run_bootstrap(paired, **kw):
    kw.setdefault("n_resamples", 300)
    kw.setdefault("seed", 7)
    kw.setdefault("confidence", 0.95)
    return bootstrap_by_parent(paired, **kw)


def interval(result, method, scope, metric="auroc"):
    frame = bootstrap_intervals_frame(result)
    row = frame[(frame.method == method) & (frame.scope == scope) & (frame.metric == metric)]
    assert len(row) == 1, row
    return row.iloc[0]


def test_paired_auroc_matches_sklearn_including_ties():
    rng = np.random.default_rng(3)
    orig = np.round(rng.normal(size=40), 1)  # làm tròn để có nhiều điểm trùng nhau
    mut = np.round(rng.normal(size=40) + 0.3, 1)

    expected = roc_auc_score(np.r_[np.zeros(40), np.ones(40)], np.r_[orig, mut])

    assert paired_auroc(orig, mut) == pytest.approx(expected, abs=1e-12)


def test_paired_auroc_weights_repeat_parents_like_a_resample():
    orig, mut = np.array([0.1, 0.5, 0.2]), np.array([0.4, 0.3, 0.9])
    weights = np.array([2, 0, 1])

    repeated = paired_auroc(np.repeat(orig, weights), np.repeat(mut, weights))

    assert paired_auroc(orig, mut, weights) == pytest.approx(repeated, abs=1e-12)


def test_point_estimates_equal_the_ordinary_metrics():
    scores = {"A": noisy_scores(seed=1, shift=0.4), "B": noisy_scores(seed=2, shift=0.1)}
    paired = paired_table(scores)

    result = run_bootstrap(paired)

    for method, by_parent in scores.items():
        orig = np.array([o for o, _ in by_parent.values()])
        mut = np.array([m for _, m in by_parent.values()])
        row = interval(result, method, "swap_adjacent")
        assert row.estimate == pytest.approx(roc_auc_score(
            np.r_[np.zeros(len(orig)), np.ones(len(mut))], np.r_[orig, mut]))
        win = float(np.where(mut > orig, 1.0, np.where(mut == orig, 0.5, 0.0)).mean())
        assert interval(result, method, "swap_adjacent", "paired_win_rate").estimate == (
            pytest.approx(win))
        assert interval(result, method, "macro").estimate == pytest.approx(row.estimate)


def test_the_estimate_lies_inside_its_interval_and_se_is_positive():
    paired = paired_table({"A": noisy_scores(seed=5, shift=0.5)})

    row = interval(run_bootstrap(paired), "A", "macro")

    assert row.ci_low <= row.estimate <= row.ci_high
    assert row.se > 0 and row.n_parents == 31


def test_same_seed_same_result_and_a_different_seed_moves_the_interval():
    paired = paired_table({"A": noisy_scores(seed=5, shift=0.5)})

    first = bootstrap_intervals_frame(run_bootstrap(paired))
    again = bootstrap_intervals_frame(run_bootstrap(paired))
    other = bootstrap_intervals_frame(run_bootstrap(paired, seed=8))

    pd.testing.assert_frame_equal(first, again)
    assert not np.allclose(first.ci_low, other.ci_low)


def test_the_result_does_not_depend_on_row_order():
    paired = paired_table({"A": noisy_scores(seed=5, shift=0.5), "B": noisy_scores(seed=6)})
    shuffled = paired.sample(frac=1.0, random_state=0).reset_index(drop=True)

    pd.testing.assert_frame_equal(
        bootstrap_intervals_frame(run_bootstrap(paired)),
        bootstrap_intervals_frame(run_bootstrap(shuffled)),
    )


def test_methods_are_resampled_together_so_identical_methods_differ_by_exactly_zero():
    same = noisy_scores(seed=9, shift=0.3)
    paired = paired_table({"A": same, "B": dict(same)})

    diffs = bootstrap_differences_frame(run_bootstrap(paired, methods=["A", "B"]))

    row = diffs[(diffs.scope == "macro") & (diffs.metric == "auroc")].iloc[0]
    assert (row.method_a, row.method_b) == ("B", "A")  # method đứng sau trừ method đứng trước
    assert row.estimate == 0 and row.ci_low == 0 and row.ci_high == 0
    assert row.prob_positive == 0.5  # mọi lần resample hòa ⇒ tính nửa điểm, không phải 0


def test_a_clearly_better_method_wins_almost_every_resample():
    paired = paired_table({"A": noisy_scores(seed=21, shift=0.0), "B": noisy_scores(seed=21, shift=3.0)})

    diffs = bootstrap_differences_frame(run_bootstrap(paired, methods=["A", "B"]))

    row = diffs[(diffs.scope == "macro") & (diffs.metric == "auroc")].iloc[0]
    assert row.estimate > 0.3 and row.ci_low > 0 and row.prob_positive > 0.99


def test_all_children_of_a_parent_travel_together_across_mutation_types():
    # Mọi loại mutation dùng đúng cùng điểm ⇒ nếu cả bản con đi cùng parent, AUROC macro của mỗi
    # lần resample bằng đúng AUROC của từng loại; nếu từng loại bị resample riêng, khoảng macro sẽ hẹp hơn.
    paired = paired_table({"A": noisy_scores(seed=11, shift=0.4)})

    result = run_bootstrap(paired, n_resamples=500)

    per_type = interval(result, "A", "swap_adjacent")
    macro = interval(result, "A", "macro")
    assert macro.ci_low == pytest.approx(per_type.ci_low)
    assert macro.ci_high == pytest.approx(per_type.ci_high)


def test_bootstrap_se_has_the_scale_of_the_mann_whitney_standard_error():
    n = 200
    paired = paired_table({"A": noisy_scores(n=n, seed=13, shift=0.0)}, types=("swap_adjacent",))

    row = interval(run_bootstrap(paired, n_resamples=800), "A", "swap_adjacent")

    expected = np.sqrt((2 * n + 1) / (12 * n * n))  # SE của AUROC dưới giả thuyết không
    assert 0.7 * expected < row.se < 1.4 * expected


def test_a_perfectly_separating_method_has_a_degenerate_interval_at_one():
    scores = {f"P{i}": (0.1 + i * 0.01, 0.9 + i * 0.01) for i in range(10)}

    row = interval(run_bootstrap(paired_table({"A": scores})), "A", "swap_adjacent")

    assert row.estimate == 1.0 and row.ci_low == 1.0 and row.ci_high == 1.0


def test_a_parent_missing_one_mutation_type_still_resamples_by_parent():
    scores = noisy_scores(n=12, seed=17, shift=0.5)
    paired = paired_table({"A": scores})
    paired = paired[~((paired.mutation_type == "delete_internal") & (paired.parent_case_id == "P00"))]

    result = run_bootstrap(paired)

    assert interval(result, "A", "swap_adjacent").n_parents == 12
    assert interval(result, "A", "delete_internal").n_parents == 11


def test_too_few_parents_give_a_null_interval_with_a_reason_not_a_fake_one():
    paired = paired_table({"A": {"P0": (0.1, 0.9)}}, types=("swap_adjacent",))

    row = interval(run_bootstrap(paired), "A", "swap_adjacent")

    assert pd.isna(row.ci_low) and pd.isna(row.ci_high)
    assert row.null_reason == "too_few_parents"


def test_confidence_level_changes_the_width_of_the_interval():
    paired = paired_table({"A": noisy_scores(seed=5, shift=0.5)})

    wide = interval(run_bootstrap(paired, confidence=0.99), "A", "macro")
    narrow = interval(run_bootstrap(paired, confidence=0.5), "A", "macro")

    assert (wide.ci_high - wide.ci_low) > (narrow.ci_high - narrow.ci_low)


def test_empty_input_is_an_error_not_an_empty_success():
    empty = paired_table({"A": noisy_scores(n=3)}).iloc[0:0]  # đủ cột, không có dòng nào

    with pytest.raises(ValueError, match="rỗng|empty"):
        run_bootstrap(empty)


# ------------------------------------- gộp nhiều run (model seed) thành một nhãn để so ablation/baseline


def test_aggregate_labels_average_their_member_runs_and_replace_the_methods():
    paired = paired_table({
        "X|1": noisy_scores(seed=31, shift=0.2), "X|2": noisy_scores(seed=32, shift=0.4),
        "Y|1": noisy_scores(seed=33, shift=0.0), "Y|2": noisy_scores(seed=34, shift=0.1),
    })

    result = run_bootstrap(paired, methods=["X|1", "X|2", "Y|1", "Y|2"],
                           aggregate={"X": ["X|1", "X|2"], "Y": ["Y|1", "Y|2"]})

    assert result["meta"]["methods"] == ["X", "Y"]
    members = run_bootstrap(paired, methods=["X|1", "X|2", "Y|1", "Y|2"])
    expected = np.mean([interval(members, m, "macro").estimate for m in ("X|1", "X|2")])
    assert interval(result, "X", "macro").estimate == pytest.approx(expected)
    assert set(bootstrap_intervals_frame(result).method) == {"X", "Y"}
    diff = bootstrap_differences_frame(result)
    assert set(zip(diff.method_a, diff.method_b, strict=True)) == {("Y", "X")}


def test_aggregate_resamples_all_members_with_the_same_parents():
    same = noisy_scores(seed=41, shift=0.3)
    paired = paired_table({"X|1": same, "X|2": noisy_scores(seed=42), "Y|1": same,
                           "Y|2": noisy_scores(seed=42)})

    result = run_bootstrap(paired, methods=["X|1", "X|2", "Y|1", "Y|2"],
                           aggregate={"X": ["X|1", "X|2"], "Y": ["Y|1", "Y|2"]})

    row = bootstrap_differences_frame(result).query("scope == 'macro' and metric == 'auroc'").iloc[0]
    assert row.estimate == 0 and row.ci_low == 0 and row.ci_high == 0


def test_aggregate_rejects_unknown_members_and_overlapping_labels():
    paired = paired_table({"X|1": noisy_scores(seed=1), "Y|1": noisy_scores(seed=2)})

    with pytest.raises(ValueError, match="Z"):
        run_bootstrap(paired, methods=["X|1", "Y|1"], aggregate={"X": ["X|1"], "Y": ["Z"]})
    with pytest.raises(ValueError, match="X\\|1"):
        run_bootstrap(paired, methods=["X|1", "Y|1"], aggregate={"X": ["X|1"], "Y": ["X|1"]})


# ---------------------------- thử hoán vị trong cặp: AUROC có khác 0,5 không (thiết kế ghép cặp)

from jira_ad.evaluation import paired_chance_test  # noqa: E402


def chance(paired, **kw):
    kw.setdefault("n_permutations", 400)
    kw.setdefault("seed", 5)
    return paired_chance_test(paired, **kw)


def one_row(frame, method, scope):
    row = frame[(frame.method == method) & (frame.scope == scope)]
    assert len(row) == 1, row
    return row.iloc[0]


def test_a_clearly_shifted_method_has_a_tiny_p_value_and_a_null_centred_on_one_half():
    scores = {f"P{i:02d}": (float(i % 7) + 0.1 * i, float(i % 7) + 0.1 * i + 3.0) for i in range(25)}

    row = one_row(chance(paired_table({"A": scores})), "A", "swap_adjacent")

    assert row.auroc > 0.5 and row.p_value <= 2 / 401
    assert row.null_mean == pytest.approx(0.5, abs=0.02) and row.n_parents == 25
    assert row.n_permutations == 400


def test_pairs_with_identical_scores_give_auroc_one_half_and_p_value_one():
    scores = {f"P{i}": (float(i), float(i)) for i in range(12)}

    row = one_row(chance(paired_table({"A": scores})), "A", "delete_internal")

    assert row.auroc == 0.5 and row.p_value == 1.0


def test_the_paired_null_is_far_narrower_than_the_two_independent_samples_formula():
    # Phương sai giữa parent lớn, chênh lệch trong cặp nhỏ ⇒ AUROC của dữ liệu ghép cặp ít dao động hơn nhiều
    # so với công thức Mann–Whitney (giả định hai mẫu độc lập). Đây chính là lý do hàm này tồn tại.
    rng = np.random.default_rng(0)
    base = rng.normal(size=31) * 5
    scores = {f"P{i:02d}": (float(b), float(b + rng.normal() * 0.05)) for i, b in enumerate(base)}

    row = one_row(chance(paired_table({"A": scores}), n_permutations=1000), "A", "swap_adjacent")

    independent_se = np.sqrt((2 * 31 + 1) / (12 * 31 * 31))
    assert row.null_sd < 0.5 * independent_se


def test_chance_test_is_reproducible_and_ignores_row_order():
    paired = paired_table({"A": noisy_scores(seed=1, shift=0.5), "B": noisy_scores(seed=2)})
    shuffled = paired.sample(frac=1.0, random_state=1).reset_index(drop=True)

    first, again = chance(paired), chance(paired)
    pd.testing.assert_frame_equal(first, again)
    pd.testing.assert_frame_equal(first, chance(shuffled))
    assert not np.allclose(first.null_sd, chance(paired, seed=6).null_sd)


def test_chance_test_covers_every_method_and_type_and_rejects_empty_input():
    paired = paired_table({"A": noisy_scores(n=10, seed=1), "B": noisy_scores(n=10, seed=2)})

    frame = chance(paired)

    assert set(zip(frame.method, frame.scope, strict=True)) == {
        (m, t) for m in ("A", "B") for t in TYPES}
    with pytest.raises(ValueError, match="rỗng|empty"):
        chance(paired.iloc[0:0])
