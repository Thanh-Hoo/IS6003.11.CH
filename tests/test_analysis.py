from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from jira_ad.analysis import (
    REVIEW_COLUMNS,
    ablation_vs_baseline,
    build_case_review,
    case_event_table,
    create_to_terminal,
    describe_case,
    dfg_edge_table,
    embedding_pca,
    order_blindness_demo,
    run_macro_metrics,
    status_durations,
    trace_variants,
)
from jira_ad.config import load_config
from jira_ad.data import load_raw_events
from jira_ad.detector import fit_detector
from jira_ad.features import H_FEATURE_NAMES
from jira_ad.graph import build_dfg
from jira_ad.preprocess import build_core_view, normalize_events

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg():
    return load_config(REPO_ROOT / "configs" / "smoke.yaml")


@pytest.fixture
def bundle(cfg, trace_of):
    train = [trace_of(f"t{i}", ["A", "B", "C", "D"]) for i in range(8)]
    train += [trace_of(f"u{i}", ["A", "B", "B", "C", "D"]) for i in range(3)]
    return fit_detector(train, cfg, "A_stats")


def test_description_ranks_transitions_by_surprisal_and_matches_the_encoder(bundle, trace_of):
    trace = trace_of("probe", ["A", "C", "B", "B", "D", "NEW"],
                     roles=["PO", "bot", "unknown", "__MISSING_ROLE__", "Eng", "PO"])

    d = describe_case(trace, bundle, top_k=100)

    surprisals = [t["surprisal"] for t in d["transitions"]]
    assert surprisals == sorted(surprisals, reverse=True)
    assert len(d["transitions"]) == 7  # __START__→A … NEW→__END__
    h = dict(zip(H_FEATURE_NAMES, bundle.encoder.transform([trace]).values[0], strict=True))
    assert np.mean(surprisals) == pytest.approx(h["mean_transition_surprisal"])
    assert max(surprisals) == pytest.approx(h["max_transition_surprisal"])
    assert d["coverage"]["unseen_node_ratio"] == pytest.approx(h["unseen_node_ratio"])
    assert d["coverage"]["unseen_transition_ratio"] == pytest.approx(h["unseen_transition_ratio"])


def test_description_flags_unseen_tokens_repeats_and_roles(bundle, trace_of):
    trace = trace_of("probe", ["A", "C", "B", "B", "D", "NEW"],
                     roles=["PO", "bot", "unknown", "__MISSING_ROLE__", "Eng", "PO"])

    d = describe_case(trace, bundle)

    assert d["coverage"]["unseen_tokens"] == ["NEW"]
    assert {"activity": "B", "start": 2, "length": 2} in d["repeats"]
    assert d["roles"] == {"n_missing": 1, "n_unknown": 1, "n_bot": 1}
    assert d["n_events"] == 6 and d["trace_id"] == "probe"
    unseen = [t for t in d["transitions"] if t["unseen_transition"]]
    assert unseen and all(t["count"] == 0 for t in unseen)


def test_top_k_limits_the_listed_transitions_but_not_the_summary(bundle, trace_of):
    trace = trace_of("probe", ["A", "C", "B", "B", "D", "NEW"])

    short = describe_case(trace, bundle, top_k=2)
    full = describe_case(trace, bundle, top_k=100)

    assert len(short["transitions"]) == 2
    assert short["transitions"] == full["transitions"][:2]
    assert short["mean_transition_surprisal"] == pytest.approx(full["mean_transition_surprisal"])


def test_description_is_behavioural_evidence_not_a_causal_explanation(bundle, trace_of):
    d = describe_case(trace_of("probe", ["A", "B", "C", "D"]), bundle)

    assert "nhân quả" in d["note"]
    json.dumps(d, allow_nan=False)


def test_a_known_flow_has_no_unseen_evidence(bundle, trace_of):
    d = describe_case(trace_of("probe", ["A", "B", "C", "D"]), bundle)

    assert d["coverage"]["unseen_tokens"] == [] and d["repeats"] == []
    assert not any(t["unseen_transition"] for t in d["transitions"])


# ----------------------------------------------------------------------- bộ rà soát mù


@pytest.fixture
def scored(trace_of):
    traces = [trace_of(f"bug:T{i:02d}", ["CREATE", f"X{i}", "S_DONE"],
                       roles=["SQA", "unknown" if i % 3 == 0 else "PO", "PO"]) for i in range(30)]
    scores = pd.DataFrame({"trace_id": [t.trace_id for t in traces],
                           "anomaly_score": np.linspace(0.3, 0.7, 30)[::-1]})  # T00 cao nhất
    return traces, scores


def test_review_set_is_top_10_plus_10_random_from_the_rest_without_overlap(scored):
    traces, scores = scored

    blinded, key = build_case_review(scores, traces, seed=5)

    assert len(blinded) == len(key) == 20
    assert key.case_id.is_unique and blinded.case_id.is_unique
    top = key[key.group == "top"]
    random_group = key[key.group == "random"]
    assert sorted(top.case_id) == [f"bug:T{i:02d}" for i in range(10)]  # 10 điểm cao nhất
    assert len(random_group) == 10
    assert set(random_group.case_id).isdisjoint(top.case_id)
    assert set(random_group.case_id) <= {f"bug:T{i:02d}" for i in range(10, 30)}


def test_the_blinded_table_hides_scores_ranks_and_models_and_its_order_is_shuffled(scored):
    traces, scores = scored

    blinded, key = build_case_review(scores, traces, seed=5, method="D_hybrid")

    assert list(blinded.columns) == REVIEW_COLUMNS
    assert not any(word in " ".join(blinded.columns).lower()
                   for word in ("score", "rank", "method", "model", "group", "anomal"))
    for column in REVIEW_COLUMNS[REVIEW_COLUMNS.index("explainable"):]:
        assert (blinded[column] == "").all()  # cột rà soát để trống, không có 'nhãn chuyên gia'
    assert set(key.method) == {"D_hybrid"}
    assert {"review_id", "case_id", "group", "rank", "anomaly_score", "method"} <= set(key.columns)
    assert list(blinded.review_id) == list(key.review_id)
    ranks_in_blinded_order = list(key.set_index("review_id").loc[blinded.review_id, "rank"])
    assert ranks_in_blinded_order != sorted(ranks_in_blinded_order)  # thứ tự không lộ hạng


def test_blinded_rows_show_the_trace_and_role_counts_but_nothing_model_derived(scored):
    traces, scores = scored

    blinded, _ = build_case_review(scores, traces, seed=5)

    row = blinded.set_index("case_id").loc["bug:T00"]
    assert row.n_events == 3 and row.n_roles_undetermined == 1
    assert "CREATE" in row.trace_text and "S_DONE" in row.trace_text and "SQA" in row.trace_text


def test_review_is_reproducible_and_takes_what_exists_when_there_are_few_cases(scored):
    traces, scores = scored
    one = build_case_review(scores, traces, seed=5)
    again = build_case_review(scores, traces, seed=5)
    other = build_case_review(scores, traces, seed=6)

    assert one[0].equals(again[0]) and one[1].equals(again[1])
    assert set(one[1][one[1].group == "random"].case_id) != set(
        other[1][other[1].group == "random"].case_id)

    few = build_case_review(scores.head(14), traces[:14], seed=5)[1]
    assert (few.group == "top").sum() == 10 and (few.group == "random").sum() == 4
    tiny = build_case_review(scores.head(6), traces[:6], seed=5)[1]
    assert (tiny.group == "top").sum() == 6 and (tiny.group == "random").sum() == 0


# ------------------------------------------------------------------ bảng phân tích


DONE_ROW = "update resolution to Done, update status to DONE"


def normalized_events(project, rows):
    project.write_bug(rows)
    cfg = load_config(project.write_config())
    return cfg, normalize_events(load_raw_events(cfg.data, cfg.project_root), cfg.preprocess)


def test_variants_count_identical_activity_sequences_and_shares_sum_to_one(trace_of):
    traces = [trace_of(f"a{i}", ["A", "B"]) for i in range(3)]
    traces += [trace_of("b", ["A", "C"], terminal_status="Rejected")]

    table = trace_variants(traces)

    assert list(table.n_cases) == [3, 1] and list(table.length) == [2, 2]
    assert table.share.sum() == pytest.approx(1.0)
    assert list(table.variant) == ["A → B", "A → C"]
    assert list(table.variant_id) == ["V01", "V02"]
    assert list(table["Rejected"]) == [0, 1] and list(table["DONE"]) == [3, 0]
    assert len(trace_variants(traces, top=1)) == 1


def test_status_durations_measure_only_between_consecutive_status_updates(project, case_rows):
    rows = case_rows("TI-1", [
        ("SQA", "Issue created"), ("PO", "edit summary"), ("PO", "update status to To Do"),
        ("PO", "edit description"), ("PO", "update status to In Progress"),
        ("PO", DONE_ROW), ("PO", "edit summary"),
    ])
    _, events = normalized_events(project, rows)

    table = status_durations(events)

    # Đoạn trước status đầu tiên chưa biết; status cuối không bị gán thời lượng đến hiện tại.
    assert list(zip(table.status, table.next_status, table.seconds, strict=True)) == [
        ("To Do", "In Progress", 120.0), ("In Progress", "DONE", 60.0)]


def test_create_to_terminal_uses_the_last_terminal_status_and_is_separate(project, case_rows):
    rows = case_rows("TI-1", [
        ("SQA", "Issue created"), ("PO", "update status to In Progress"), ("PO", DONE_ROW),
        ("PO", "remove resolution, update status to In Progress"), ("PO", DONE_ROW),
        ("PO", "edit summary"),
    ])
    cfg, events = normalized_events(project, rows)

    table = create_to_terminal(events, cfg.preprocess.terminal_statuses)

    row = table.iloc[0]
    assert row.case_id == "bug:TI-1" and row.terminal_status == "DONE"
    assert row.seconds == 4 * 60 and row.n_terminal_updates == 2


def test_dfg_edge_table_lists_heaviest_edges_with_their_empirical_probability(trace_of):
    graph = build_dfg([trace_of("t1", ["A", "B"]), trace_of("t2", ["A", "B"]),
                       trace_of("t3", ["A", "C"])], load_config(
        REPO_ROOT / "configs" / "smoke.yaml").graph)

    table = dfg_edge_table(graph, top=3)

    assert list(table.weight) == sorted(table.weight, reverse=True)
    top = table.iloc[0]
    assert (top.source, top.target, top.weight) == ("__START__", "A", 3)
    ab = table[(table.source == "A") & (table.target == "B")].iloc[0]
    assert ab.probability == pytest.approx(2 / 3) and not ab.self_loop
    assert len(table) == 3


def test_pca_returns_two_coordinates_per_node_and_valid_explained_variance():
    rng = np.random.default_rng(0)
    matrix = rng.normal(size=(7, 5))

    frame, explained = embedding_pca(matrix, tuple("ABCDEFG"))

    assert list(frame.columns) == ["node", "pc1", "pc2"] and len(frame) == 7
    assert 0 < explained[0] <= 1 and 0 < explained[1] <= 1 and sum(explained) <= 1.0 + 1e-9
    assert explained[0] >= explained[1]


def test_order_blindness_demo_shows_identical_pooling_but_different_order_features(trace_of, cfg):
    train = [trace_of(f"t{i}", ["CREATE", "A", "B", "C", "S_DONE"]) for i in range(10)]
    bundle = fit_detector(train, cfg, "D_hybrid")
    trace = trace_of("probe", ["CREATE", "A", "B", "C", "S_DONE"])

    demo = order_blindness_demo(bundle, trace)

    assert demo["original"] != demo["swapped"]
    assert sorted(demo["original"]) == sorted(demo["swapped"])  # cùng histogram
    assert demo["pooled_max_abs_diff"] == pytest.approx(0.0, abs=1e-12)
    changed = {row["feature"] for row in demo["h_features"] if row["original"] != row["swapped"]}
    assert "unseen_transition_ratio" in changed or "mean_transition_surprisal" in changed
    assert demo["score_swapped"] != demo["score_original"] or changed


def test_case_event_table_marks_which_events_survive_in_the_core_view(project, case_rows):
    rows = case_rows("TI-1", [
        ("SQA", "Issue created"), ("bot", "update RemoteIssueLink"), ("PO", "edit summary"),
        ("PO", DONE_ROW), ("bot", "update RemoteIssueLink"), ("PO", "edit description"),
    ])
    cfg, events = normalized_events(project, rows)
    (trace,) = build_core_view(events, cfg.preprocess).traces

    table = case_event_table(events, trace)

    assert list(table.in_core) == [True, False, True, True, False, False]
    assert list(table.dropped_reason) == ["", "noise_policy", "", "", "post_terminal", "post_terminal"]
    assert list(table.activity)[0] == "CREATE" and len(table) == 6


def test_run_macro_metrics_averages_each_run_over_mutation_types(tmp_path):
    def write(name, rows):
        d = tmp_path / name
        d.mkdir()
        pd.DataFrame(rows).to_csv(d / "metrics_by_type.csv", index=False)

    base = {"split": "test", "average_precision": 0.5, "paired_win_rate": 0.6}
    write("r1", [{**base, "method": "A", "mutation_type": t, "auroc": a}
                 for t, a in (("swap", 0.5), ("delete", 0.7))])
    write("r2", [{**base, "method": "A", "mutation_type": t, "auroc": a}
                 for t, a in (("swap", 0.6), ("delete", 0.8))]
          + [{**base, "split": "validation", "method": "A", "mutation_type": "swap", "auroc": 0.99}])

    frame = run_macro_metrics(tmp_path, ["r1", "r2"], split="test")

    assert list(frame.columns) == ["run_id", "method", "macro_auroc", "macro_average_precision",
                                   "macro_paired_win_rate", "n_types"]
    assert dict(zip(frame.run_id, frame.macro_auroc, strict=True)) == pytest.approx(
        {"r1": 0.6, "r2": 0.7})  # chỉ split được chọn; mỗi run trung bình theo loại
    assert set(frame.n_types) == {2}


# --------------------------------------------- so ablation với baseline bằng bootstrap ghép cặp (Task 13)


def write_paired(runs_dir, run_id, scores, split="validation", parents=24, types=("swap", "delete")):
    """scores: {method: (shift, rng_seed)}; điểm bản gốc ~ N(0,1), mutant ~ N(shift,1), theo parent."""
    rows = []
    for method, (shift, seed) in scores.items():
        rng = np.random.default_rng(seed)
        for mutation_type in types:
            for i in range(parents):
                rows.append({"split": split, "method": method, "mutation_type": mutation_type,
                             "parent_case_id": f"P{i:02d}", "mutation_id": f"P{i:02d}::{mutation_type}",
                             "original_score": rng.normal(), "mutant_score": rng.normal() + shift,
                             "delta_score": 0.0})
    directory = runs_dir / run_id
    directory.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(directory / "paired_scores.csv", index=False)


def ablation(runs_dir, groups, **kw):
    kw.setdefault("baseline", "base")
    kw.setdefault("split", "validation")
    kw.setdefault("n_resamples", 400)
    kw.setdefault("seed", 3)
    kw.setdefault("confidence", 0.95)
    return ablation_vs_baseline(runs_dir, groups, **kw)


def test_ablation_vs_baseline_detects_a_clearly_better_variant_and_ignores_a_copy(tmp_path):
    for seed in (42, 43):
        write_paired(tmp_path, f"base{seed}", {"M": (0.2, seed)})
        write_paired(tmp_path, f"better{seed}", {"M": (2.5, seed)})
        write_paired(tmp_path, f"copy{seed}", {"M": (0.2, seed)})
    groups = {"base": ["base42", "base43"], "better": ["better42", "better43"],
              "copy": ["copy42", "copy43"]}

    frame = ablation(tmp_path, groups)

    macro = frame[(frame.scope == "macro") & (frame.metric == "auroc")].set_index("experiment")
    assert set(macro.index) == {"better", "copy"}  # baseline không tự so với chính nó
    assert macro.loc["better", "estimate"] > 0.3 and macro.loc["better", "ci_low"] > 0
    assert macro.loc["copy", "estimate"] == 0 and macro.loc["copy", "ci_low"] == 0
    assert macro.loc["better", "experiment_estimate"] == pytest.approx(
        macro.loc["better", "baseline_estimate"] + macro.loc["better", "estimate"])
    assert (frame.n_seeds == 2).all() and (frame.split == "validation").all()
    assert (frame.confidence == 0.95).all()


def test_ablation_vs_baseline_uses_only_the_requested_split(tmp_path):
    write_paired(tmp_path, "b", {"M": (0.2, 1)}, split="validation")
    write_paired(tmp_path, "e", {"M": (0.2, 1)}, split="validation")
    extra = pd.read_csv(tmp_path / "e" / "paired_scores.csv")
    extra.assign(split="test", mutant_score=extra.mutant_score + 9).pipe(
        lambda f: pd.concat([extra, f])).to_csv(tmp_path / "e" / "paired_scores.csv", index=False)

    frame = ablation(tmp_path, {"base": ["b"], "exp": ["e"]})

    assert frame[(frame.scope == "macro") & (frame.metric == "auroc")].estimate.iloc[0] == 0


def test_ablation_vs_baseline_refuses_runs_that_do_not_share_the_same_parents(tmp_path):
    write_paired(tmp_path, "b", {"M": (0.2, 1)}, parents=24)
    write_paired(tmp_path, "e", {"M": (0.2, 1)}, parents=20)

    with pytest.raises(ValueError, match="exp.*parent|parent.*exp"):
        ablation(tmp_path, {"base": ["b"], "exp": ["e"]})


def test_ablation_vs_baseline_needs_the_baseline_group(tmp_path):
    write_paired(tmp_path, "e", {"M": (0.2, 1)})

    with pytest.raises(ValueError, match="base"):
        ablation(tmp_path, {"exp": ["e"]})


def test_ablation_vs_baseline_compares_each_method_with_itself_not_with_other_methods(tmp_path):
    write_paired(tmp_path, "b", {"M": (0.2, 1), "N": (3.0, 2)})
    write_paired(tmp_path, "e", {"M": (0.2, 1), "N": (3.0, 2)})

    frame = ablation(tmp_path, {"base": ["b"], "exp": ["e"]})

    assert set(frame.method) == {"M", "N"}
    assert (frame.estimate == 0).all()  # M vs M và N vs N; không phải M vs N
