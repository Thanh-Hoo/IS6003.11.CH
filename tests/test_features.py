from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from jira_ad.config import load_config
from jira_ad.features import (
    H_FEATURE_NAMES,
    FeatureEncoder,
    feature_example_table,
)
from jira_ad.graph import END, START, transition_surprisal

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cfg():
    return load_config(REPO_ROOT / "configs" / "baseline.yaml")


def fit(method, traces, cfg, seed=42):
    return FeatureEncoder(method, cfg, seed).fit(traces)


def row(encoder, trace):
    fs = encoder.transform([trace])
    return dict(zip(fs.feature_names, fs.values[0], strict=True))


def test_h_feature_names_are_the_ten_specified_statistics():
    assert H_FEATURE_NAMES == (
        "log1p_length", "distinct_activity_ratio", "adjacent_repeat_ratio", "revisit_ratio",
        "known_role_switch_ratio", "known_role_coverage", "mean_transition_surprisal",
        "max_transition_surprisal", "unseen_node_ratio", "unseen_transition_ratio",
    )


def test_a_stats_values_match_a_hand_computation(trace_of, cfg):
    trace = trace_of("t1", ["A", "B", "B", "A", "C"], roles=["PO", "PO", "Eng", "unknown", "PO"])
    encoder = fit("A_stats", [trace], cfg)

    got = row(encoder, trace)

    assert encoder.transform([trace]).feature_names == H_FEATURE_NAMES
    assert got["log1p_length"] == pytest.approx(math.log1p(5))
    assert got["distinct_activity_ratio"] == pytest.approx(3 / 5)
    assert got["adjacent_repeat_ratio"] == pytest.approx(1 / 4)  # B,B
    assert got["revisit_ratio"] == pytest.approx(1 / 4)  # A quay lại sau B (không kề nhau)
    assert got["known_role_coverage"] == pytest.approx(4 / 5)  # 'unknown' không tính
    assert got["known_role_switch_ratio"] == pytest.approx(2 / 3)  # PO,PO,Eng,PO (bỏ unknown)
    pairs = [(START, "A"), ("A", "B"), ("B", "B"), ("B", "A"), ("A", "C"), ("C", END)]
    surprisals = [transition_surprisal(encoder.graph, s, t, 1.0) for s, t in pairs]
    assert got["mean_transition_surprisal"] == pytest.approx(np.mean(surprisals))
    assert got["max_transition_surprisal"] == pytest.approx(max(surprisals))
    assert got["unseen_node_ratio"] == 0.0 and got["unseen_transition_ratio"] == 0.0


def test_missing_role_is_not_a_known_role(trace_of, cfg):
    trace = trace_of("t1", ["A", "B", "C"], roles=["__MISSING_ROLE__", "unknown", "PO"])
    got = row(fit("A_stats", [trace], cfg), trace)

    assert got["known_role_coverage"] == pytest.approx(1 / 3)
    assert got["known_role_switch_ratio"] == 0.0  # một role xác định: không có cặp để đổi


def test_single_event_trace_has_finite_features_and_zero_for_empty_denominators(trace_of, cfg):
    train = [trace_of("t1", ["A", "B"]), trace_of("t2", ["A"])]
    single = trace_of("t3", ["A"])
    for method in ("A_stats", "B_ngrams"):
        encoder = fit(method, train, cfg)
        values = encoder.transform([single]).values

        assert np.isfinite(values).all()
        got = row(encoder, single)
        assert got["adjacent_repeat_ratio"] == 0.0
        assert got["revisit_ratio"] == 0.0
        assert got["known_role_switch_ratio"] == 0.0
        assert got["log1p_length"] == pytest.approx(math.log1p(1))


def test_test_only_activity_is_unseen_and_fitted_state_is_not_modified(trace_of, cfg):
    train = [trace_of("t1", ["A", "B", "C"]), trace_of("t2", ["A", "C"])]
    only_test = trace_of("t3", ["A", "ONLY_TEST", "C"])
    for method in ("A_stats", "B_ngrams"):
        encoder = fit(method, train, cfg)
        before = encoder.state_fingerprint()

        got = row(encoder, only_test)

        assert "ONLY_TEST" not in encoder.graph
        assert "ONLY_TEST" not in encoder.vocabulary
        assert got["unseen_node_ratio"] == pytest.approx(1 / 3)
        assert got["unseen_transition_ratio"] == pytest.approx(2 / 4)  # A->ONLY_TEST, ONLY_TEST->C
        assert encoder.state_fingerprint() == before
        assert "ONLY_TEST" not in encoder.graph


def test_unseen_transitions_raise_surprisal_over_seen_ones(trace_of, cfg):
    train = [trace_of(f"t{i}", ["A", "B", "C"]) for i in range(5)]
    encoder = fit("A_stats", train, cfg)

    familiar = row(encoder, trace_of("x", ["A", "B", "C"]))
    odd = row(encoder, trace_of("y", ["C", "B", "A"]))

    assert odd["mean_transition_surprisal"] > familiar["mean_transition_surprisal"]
    assert odd["unseen_transition_ratio"] > familiar["unseen_transition_ratio"] == 0.0


def test_ngrams_distinguish_orders_that_unigrams_cannot(trace_of, cfg):
    one = trace_of("t1", ["A", "B", "C", "D"])
    two = trace_of("t2", ["A", "C", "B", "D"])
    encoder = fit("B_ngrams", [one, two], cfg)
    fs = encoder.transform([one, two])
    names = fs.feature_names
    uni = [i for i, n in enumerate(names) if n.startswith("unigram::")]
    bi = [i for i, n in enumerate(names) if n.startswith("bigram::")]

    assert np.array_equal(fs.values[0, uni], fs.values[1, uni])
    assert not np.array_equal(fs.values[0, bi], fs.values[1, bi])
    ab = names.index("bigram::" + json.dumps(["A", "B"]))
    assert fs.values[0, ab] == pytest.approx(1 / 3) and fs.values[1, ab] == 0.0
    # cặp đảo (B, A) không xuất hiện trong train nên không phải feature; thứ tự không bị sort
    assert "bigram::" + json.dumps(["B", "A"]) not in names


def test_a_pair_and_its_reverse_are_two_different_bigram_features(trace_of, cfg):
    forward = trace_of("t1", ["A", "B"])
    backward = trace_of("t2", ["B", "A"])
    encoder = fit("B_ngrams", [forward, backward], cfg)
    ab = "bigram::" + json.dumps(["A", "B"])
    ba = "bigram::" + json.dumps(["B", "A"])

    got_forward, got_backward = row(encoder, forward), row(encoder, backward)

    assert got_forward[ab] == 1.0 and got_forward[ba] == 0.0
    assert got_backward[ab] == 0.0 and got_backward[ba] == 1.0


def test_bigram_keys_are_ordered_and_unambiguous(trace_of, cfg):
    first = trace_of("t1", ["A,B", "C"])
    second = trace_of("t2", ["A", "B,C"])
    encoder = fit("B_ngrams", [first, second], cfg)
    names = [n for n in encoder.transform([first]).feature_names if n.startswith("bigram::")]

    assert len(names) == 2 and len(set(names)) == 2  # không nhập nhằng dù chứa dấu phẩy
    assert json.loads(names[0].split("::", 1)[1]) in (["A,B", "C"], ["A", "B,C"])


def test_ngram_frequencies_use_the_documented_denominators(trace_of, cfg):
    trace = trace_of("t1", ["A", "A", "B"])
    encoder = fit("B_ngrams", [trace], cfg)
    got = row(encoder, trace)

    assert got["unigram::A"] == pytest.approx(2 / 3)  # count / L
    assert got["unigram::B"] == pytest.approx(1 / 3)
    assert got["bigram::" + json.dumps(["A", "A"])] == pytest.approx(1 / 2)  # count / max(L-1, 1)
    assert got["bigram::" + json.dumps(["A", "B"])] == pytest.approx(1 / 2)


def test_b_ngrams_vocabularies_come_from_train_only(trace_of, cfg):
    train = [trace_of("t1", ["A", "B", "C"]), trace_of("t2", ["A", "C"])]
    encoder = fit("B_ngrams", train, cfg)
    names = encoder.transform(train).feature_names

    assert [n for n in names if n.startswith("unigram::")] == [
        "unigram::A", "unigram::B", "unigram::C"]
    assert len([n for n in names if n.startswith("bigram::")]) == 3  # AB, BC, AC
    assert names[: len(H_FEATURE_NAMES)] == H_FEATURE_NAMES  # B dùng cùng H để so sánh công bằng


def test_a_and_b_share_exactly_the_same_h_columns(trace_of, cfg):
    train = [trace_of("t1", ["A", "B", "C"]), trace_of("t2", ["A", "C", "C"])]
    probe = trace_of("t3", ["A", "C", "B", "NEW"], roles=["PO", "bot", "Eng", "unknown"])
    a = fit("A_stats", train, cfg).transform([probe])
    b = fit("B_ngrams", train, cfg).transform([probe])

    assert np.allclose(a.values[0], b.values[0, : a.values.shape[1]])


def test_identifiers_status_and_timestamps_never_leak_into_features(trace_of, cfg):
    left = trace_of("bug:TI-1", ["A", "B", "C"], terminal_status="DONE")
    right = trace_of("bug:TI-999", ["A", "B", "C"], terminal_status="Rejected")
    for method in ("A_stats", "B_ngrams"):
        encoder = fit(method, [left, right], cfg)
        fs = encoder.transform([left, right])

        assert np.array_equal(fs.values[0], fs.values[1])
        assert fs.trace_ids == ("bug:TI-1", "bug:TI-999")
        lowered = " ".join(fs.feature_names).lower()
        for banned in ("case", "trace_id", "terminal", "status", "time", "split", "mutation",
                       "label"):
            assert banned not in lowered


def test_features_are_finite_and_deterministic(trace_of, cfg):
    rng = np.random.default_rng(0)
    alphabet = list("ABCDEF")
    def random_trace(name, symbols):
        size = int(rng.integers(1, 12))
        return trace_of(name, [str(x) for x in rng.choice(symbols, size=size)])

    train = [random_trace(f"t{i}", alphabet) for i in range(30)]
    probe = [random_trace(f"p{i}", alphabet + ["Z"]) for i in range(10)]
    for method in ("A_stats", "B_ngrams"):
        first = fit(method, train, cfg).transform(probe)
        second = fit(method, train, cfg).transform(probe)

        assert np.isfinite(first.values).all()
        assert np.array_equal(first.values, second.values)
        assert first.values.shape == (10, len(first.feature_names))


def test_transform_before_fit_and_unknown_method_are_errors(trace_of, cfg):
    with pytest.raises(RuntimeError, match="fit"):
        FeatureEncoder("A_stats", cfg, 42).transform([trace_of("t1", ["A"])])
    with pytest.raises(ValueError, match="Z_unknown"):
        FeatureEncoder("Z_unknown", cfg, 42)
    with pytest.raises(ValueError, match="rỗng|empty"):
        FeatureEncoder("A_stats", cfg, 42).fit([])


def test_schema_records_names_train_hash_and_dimensionality(trace_of, cfg):
    train = [trace_of("t1", ["A", "B"]), trace_of("t2", ["A", "C"])]
    encoder = fit("B_ngrams", train, cfg)
    reordered = fit("B_ngrams", list(reversed(train)), cfg)

    schema = encoder.schema()

    assert schema["method"] == "B_ngrams"
    assert schema["feature_names"] == list(encoder.transform(train).feature_names)
    assert schema["n_features"] == len(schema["feature_names"])
    assert schema["n_train_traces"] == 2
    assert len(schema["train_ids_sha256"]) == 64
    assert schema["train_ids_sha256"] == reordered.schema()["train_ids_sha256"]
    assert schema["include_time"] is False
    json.dumps(schema, allow_nan=False)  # ghi được ra JSON


def test_example_table_has_one_row_per_trace_and_named_columns(trace_of, cfg):
    train = [trace_of("t1", ["A", "B"]), trace_of("t2", ["A", "C"])]
    encoder = fit("A_stats", train, cfg)

    table = feature_example_table(encoder.transform(train), n=1)

    assert list(table.index) == ["t1"]
    assert tuple(table.columns) == H_FEATURE_NAMES


# --------------------------------------------------------------- C_embedding và D_hybrid


@pytest.fixture(scope="module")
def smoke_cfg():
    return load_config(REPO_ROOT / "configs" / "smoke.yaml")  # run nhỏ để test nhanh


@pytest.fixture
def flow_traces(trace_of):
    return [trace_of(f"t{i}", ["A", "B", "C", "D"]) for i in range(5)]


def test_embedding_methods_have_the_documented_dimensions_and_column_names(
    flow_traces, smoke_cfg
):
    d = smoke_cfg.embedding.dimensions
    c = fit("C_embedding", flow_traces, smoke_cfg).transform(flow_traces)
    h = fit("D_hybrid", flow_traces, smoke_cfg).transform(flow_traces)
    pooled = tuple(f"emb_mean_{i:02d}" for i in range(d))
    pooled += tuple(f"emb_max_{i:02d}" for i in range(d))

    assert c.feature_names == (*pooled, "unseen_node_ratio")
    assert h.feature_names == (*pooled, *H_FEATURE_NAMES)
    assert c.values.shape == (5, 2 * d + 1) and h.values.shape == (5, 2 * d + 10)
    assert np.isfinite(c.values).all() and np.isfinite(h.values).all()


def test_hybrid_uses_exactly_the_same_h_columns_as_a_stats(flow_traces, trace_of, smoke_cfg):
    probe = [trace_of("p1", ["A", "C", "B", "D"]), trace_of("p2", ["A", "NEW", "D"])]
    a = fit("A_stats", flow_traces, smoke_cfg).transform(probe)
    d = fit("D_hybrid", flow_traces, smoke_cfg).transform(probe)

    assert np.array_equal(d.values[:, -len(H_FEATURE_NAMES):], a.values)


def test_c_embedding_reports_unseen_nodes_and_pooling_alone_cannot_see_order(
    flow_traces, trace_of, smoke_cfg
):
    c = fit("C_embedding", flow_traces, smoke_cfg)
    d = fit("D_hybrid", flow_traces, smoke_cfg)
    ordered, shuffled = trace_of("o", ["A", "B", "C", "D"]), trace_of("s", ["A", "C", "B", "D"])
    novel = trace_of("n", ["A", "NEW", "D"])
    width = smoke_cfg.embedding.dimensions * 2

    c_fs = c.transform([ordered, shuffled, novel])
    d_fs = d.transform([ordered, shuffled])

    # cùng multiset ⇒ cùng pooling
    assert np.allclose(c_fs.values[0, :width], c_fs.values[1, :width])
    assert c_fs.values[2, -1] == pytest.approx(1 / 3)
    assert c_fs.values[0, -1] == 0.0
    # D_hybrid thấy khác biệt thứ tự nhờ H (chuyển tiếp chưa thấy), dù pooling giống hệt
    assert np.allclose(d_fs.values[0, :width], d_fs.values[1, :width])
    assert not np.allclose(d_fs.values[0, width:], d_fs.values[1, width:])


def test_embedding_methods_learn_only_from_train_and_transform_keeps_the_state(
    flow_traces, trace_of, smoke_cfg
):
    for method in ("C_embedding", "D_hybrid"):
        encoder = fit(method, flow_traces, smoke_cfg)
        before = encoder.state_fingerprint()
        matrix = encoder.embedding.matrix.copy()

        encoder.transform([trace_of("x", ["A", "ONLY_TEST", "D"])])

        assert "ONLY_TEST" not in encoder.embedding
        assert "ONLY_TEST" not in encoder.graph
        assert np.array_equal(encoder.embedding.matrix, matrix)
        assert encoder.state_fingerprint() == before


def test_embedding_methods_are_deterministic_and_the_seed_matters(flow_traces, smoke_cfg):
    one = fit("D_hybrid", flow_traces, smoke_cfg, seed=1)
    again = fit("D_hybrid", flow_traces, smoke_cfg, seed=1)
    other = fit("D_hybrid", flow_traces, smoke_cfg, seed=2)

    assert np.array_equal(one.transform(flow_traces).values, again.transform(flow_traces).values)
    assert one.state_fingerprint() == again.state_fingerprint()
    assert one.state_fingerprint() != other.state_fingerprint()


def test_embedding_schema_records_walk_and_embedding_diagnostics(flow_traces, smoke_cfg):
    schema = fit("D_hybrid", flow_traces, smoke_cfg).schema()

    assert schema["n_embedding_features"] == 2 * smoke_cfg.embedding.dimensions
    assert schema["embedding"]["vocabulary_size"] == schema["graph"]["n_nodes"]
    assert schema["walks"]["n_walks"] == schema["graph"]["n_nodes"] * smoke_cfg.walk.walks_per_node
    assert schema["walks"]["p"] == smoke_cfg.walk.p and schema["walks"]["q"] == smoke_cfg.walk.q
    json.dumps(schema, allow_nan=False)


# ====================================== cross-fit đặc trưng train (Task 12, giả thuyết 1 của RESEARCH_NOTES)

import dataclasses  # noqa: E402

from jira_ad.graph import build_dfg, trace_tokens, trace_transitions  # noqa: E402


def with_folds(cfg, folds):
    return dataclasses.replace(cfg, features=dataclasses.replace(cfg.features, cross_fit_folds=folds))


@pytest.fixture
def mixed_train(trace_of):
    """8 trace chung activity A,B,C,D, trong đó một trace có activity RARE không nơi nào khác có."""
    common = [trace_of(f"c{i}", ["A", "B", "C", "D"]) for i in range(6)]
    varied = [trace_of("v0", ["A", "C", "B", "D"]), trace_of("rare", ["A", "RARE", "D"])]
    return common + varied


def col(feature_set, name):
    return feature_set.values[:, feature_set.feature_names.index(name)]


def test_without_cross_fit_the_train_features_are_the_ordinary_in_sample_ones(mixed_train, cfg):
    for method in ("A_stats", "B_ngrams"):
        encoder = fit(method, mixed_train, cfg)

        assert np.array_equal(encoder.transform_train(mixed_train).values,
                              encoder.transform(mixed_train).values)


def test_cross_fit_lets_a_train_trace_be_novel_to_the_graph_built_from_the_other_folds(
    mixed_train, cfg
):
    plain = fit("A_stats", mixed_train, cfg)
    crossed = fit("A_stats", mixed_train, with_folds(cfg, 4))

    in_sample = col(plain.transform_train(mixed_train), "unseen_node_ratio")
    out_of_fold = col(crossed.transform_train(mixed_train), "unseen_node_ratio")

    assert in_sample.std() == 0.0  # V1: toàn 0, Isolation Forest không dùng được cột này
    rare = [t.trace_id for t in mixed_train].index("rare")
    assert out_of_fold[rare] == pytest.approx(1 / 3)  # RARE chưa từng thấy ở các fold khác
    assert out_of_fold.std() > 0.0
    assert out_of_fold[[i for i in range(len(mixed_train)) if i != rare]].max() == 0.0


def test_each_train_trace_is_described_by_a_graph_that_excludes_its_own_fold(mixed_train, cfg):
    cross_cfg = with_folds(cfg, 3)
    encoder = fit("A_stats", mixed_train, cross_cfg)
    got = encoder.transform_train(mixed_train)

    for index, trace in enumerate(mixed_train):
        fold = encoder.cross_fit_assignment[trace.trace_id]
        others = [t for t in mixed_train if encoder.cross_fit_assignment[t.trace_id] != fold]
        graph = build_dfg(others, cross_cfg.graph)
        tokens = trace_tokens(trace, cross_cfg.graph.encoding)
        expected = np.mean([transition_surprisal(graph, s, t, cross_cfg.graph.transition_alpha)
                            for s, t in trace_transitions(tokens, cross_cfg.graph.add_boundaries)])
        assert col(got, "mean_transition_surprisal")[index] == pytest.approx(expected)


def test_folds_are_balanced_deterministic_and_independent_of_order_and_model_seed(
    mixed_train, cfg
):
    cross_cfg = with_folds(cfg, 3)

    one = fit("A_stats", mixed_train, cross_cfg, seed=1).cross_fit_assignment
    other_seed = fit("A_stats", mixed_train[::-1], cross_cfg, seed=2).cross_fit_assignment

    assert one == other_seed
    sizes = sorted(list(one.values()).count(f) for f in range(3))
    assert sizes[-1] - sizes[0] <= 1 and sum(sizes) == len(mixed_train)


def test_held_out_features_do_not_depend_on_cross_fit(mixed_train, trace_of, cfg):
    probe = [trace_of("p1", ["A", "C", "B", "D"]), trace_of("p2", ["A", "NEW", "D"])]
    plain = fit("A_stats", mixed_train, cfg).transform(probe)
    crossed = fit("A_stats", mixed_train, with_folds(cfg, 4)).transform(probe)

    assert np.array_equal(plain.values, crossed.values)  # cùng đồ thị train đầy đủ


def test_cross_fit_changes_only_the_graph_dependent_h_columns_of_the_hybrid(
    mixed_train, smoke_cfg
):
    plain = fit("D_hybrid", mixed_train, smoke_cfg)
    crossed = fit("D_hybrid", mixed_train, with_folds(smoke_cfg, 4))

    a, b = plain.transform_train(mixed_train), crossed.transform_train(mixed_train)

    changed = {name for i, name in enumerate(a.feature_names)
               if not np.allclose(a.values[:, i], b.values[:, i])}
    assert changed <= {"mean_transition_surprisal", "max_transition_surprisal",
                       "unseen_node_ratio", "unseen_transition_ratio"}
    assert changed  # có thay đổi thật
    pooled = [n for n in a.feature_names if n.startswith("emb_")]
    assert all(np.array_equal(col(a, n), col(b, n)) for n in pooled)  # embedding vẫn in-sample


def test_cross_fit_leaves_the_fitted_state_untouched_by_scoring_but_records_itself(
    mixed_train, cfg
):
    plain = fit("A_stats", mixed_train, cfg)
    crossed = fit("A_stats", mixed_train, with_folds(cfg, 4))
    before = crossed.state_fingerprint()

    crossed.transform_train(mixed_train)

    assert crossed.state_fingerprint() == before
    assert crossed.state_fingerprint() != plain.state_fingerprint()
    assert crossed.schema()["cross_fit_folds"] == 4 and plain.schema()["cross_fit_folds"] == 0


def test_cross_fit_rejects_more_folds_than_train_traces(trace_of, cfg):
    tiny = [trace_of("a", ["A", "B"]), trace_of("b", ["A", "C"])]

    with pytest.raises(ValueError, match="fold"):
        fit("A_stats", tiny, with_folds(cfg, 3))


def test_transform_train_refuses_traces_that_were_not_in_train(mixed_train, trace_of, cfg):
    encoder = fit("A_stats", mixed_train, with_folds(cfg, 3))

    with pytest.raises(ValueError, match="train"):
        encoder.transform_train([trace_of("stranger", ["A", "B", "D"])])


# ======================================================= phương pháp cải tiến E/F/M (2026-10-22)


def test_new_methods_have_the_documented_column_names(flow_traces, smoke_cfg):
    d = smoke_cfg.embedding.dimensions
    e = fit("E_score_fusion", flow_traces, smoke_cfg).transform(flow_traces)
    f = fit("F_edge_hybrid", flow_traces, smoke_cfg).transform(flow_traces)
    m = fit("M_markov", flow_traces, smoke_cfg).transform(flow_traces)
    hybrid = fit("D_hybrid", flow_traces, smoke_cfg).transform(flow_traces)
    edges = tuple(f"edge_mean_{i:02d}" for i in range(d)) + tuple(f"edge_max_{i:02d}" for i in range(d))

    assert e.feature_names == hybrid.feature_names and np.array_equal(e.values, hybrid.values)
    assert f.feature_names == (*edges, *H_FEATURE_NAMES)
    assert m.feature_names == H_FEATURE_NAMES
    assert np.isfinite(f.values).all()


def test_edge_pooling_sees_an_order_that_node_pooling_cannot(flow_traces, trace_of, smoke_cfg):
    f = fit("F_edge_hybrid", flow_traces, smoke_cfg)
    width = 2 * smoke_cfg.embedding.dimensions
    ordered, swapped = trace_of("o", ["A", "B", "C", "D"]), trace_of("s", ["A", "C", "B", "D"])

    values = f.transform([ordered, swapped]).values

    assert not np.allclose(values[0, :width], values[1, :width])


def test_edge_features_are_hadamard_products_of_the_fitted_node_vectors(flow_traces, trace_of, smoke_cfg):
    f = fit("F_edge_hybrid", flow_traces, smoke_cfg)
    d = smoke_cfg.embedding.dimensions
    path = [START, "A", "B", "C", "D", END]
    edges = np.array([f.embedding.vector(a) * f.embedding.vector(b)
                      for a, b in zip(path, path[1:], strict=False)])

    values = f.transform([trace_of("o", ["A", "B", "C", "D"])]).values[0]

    assert np.allclose(values[:d], edges.mean(axis=0))
    assert np.allclose(values[d:2 * d], edges.max(axis=0))


def test_edge_pooling_of_a_single_event_and_of_unseen_tokens_is_finite(flow_traces, trace_of, smoke_cfg):
    f = fit("F_edge_hybrid", flow_traces, smoke_cfg)
    width = 2 * smoke_cfg.embedding.dimensions

    values = f.transform([trace_of("one", ["A"]), trace_of("new", ["NEW"])]).values

    assert np.isfinite(values).all()
    assert np.allclose(values[1, :width], 0.0)  # mọi cạnh chạm token chưa thấy là vector 0


def test_new_embedding_methods_learn_only_from_train(flow_traces, trace_of, smoke_cfg):
    for method in ("E_score_fusion", "F_edge_hybrid"):
        encoder = fit(method, flow_traces, smoke_cfg)
        before = encoder.state_fingerprint()

        encoder.transform([trace_of("x", ["A", "ONLY_TEST", "D"])])

        assert "ONLY_TEST" not in encoder.embedding and encoder.state_fingerprint() == before


def test_edge_hybrid_without_boundaries_handles_a_single_event_trace(flow_traces, trace_of, smoke_cfg):
    import dataclasses

    cfg = dataclasses.replace(smoke_cfg, graph=dataclasses.replace(smoke_cfg.graph, add_boundaries=False))
    f = fit("F_edge_hybrid", flow_traces, cfg)

    values = f.transform([trace_of("one", ["A"])]).values

    assert np.isfinite(values).all()
    assert np.allclose(values[0, :2 * cfg.embedding.dimensions], 0.0)  # không có cạnh nào
