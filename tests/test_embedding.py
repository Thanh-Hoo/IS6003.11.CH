from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import numpy as np
import pytest

from jira_ad.config import EmbeddingConfig, GraphConfig, WalkConfig
from jira_ad.embedding import (
    Node2VecEmbedding,
    embedding_diagnostics,
    fit_embedding,
    pool_tokens,
)
from jira_ad.graph import END, START, build_dfg
from jira_ad.walks import generate_walks

GRAPH_CFG = GraphConfig(directed=True, encoding="activity", add_boundaries=True,
                        transition_alpha=1.0)
WALK_CFG = WalkConfig(p=1.0, q=1.0, length=10, walks_per_node=10)
EMB_CFG = EmbeddingConfig(dimensions=8, window=2, epochs=3, negative=5, min_count=1, sample=0.0,
                          workers=1)


@pytest.fixture
def fitted(trace_of):
    traces = [trace_of("t1", ["A", "B", "C", "D"]), trace_of("t2", ["A", "C", "B", "D"]),
              trace_of("t3", ["A", "B", "D"])]
    graph = build_dfg(traces, GRAPH_CFG)
    walks = generate_walks(graph, WALK_CFG, seed=1)
    return graph, walks, fit_embedding(graph, walks, EMB_CFG, seed=1)


def test_embedding_covers_every_graph_node_with_finite_vectors_of_the_configured_size(fitted):
    graph, _, emb = fitted

    assert isinstance(emb, Node2VecEmbedding)
    assert emb.vocabulary == tuple(sorted(graph.nodes))
    assert emb.matrix.shape == (len(graph), 8) and emb.dim == 8
    assert np.isfinite(emb.matrix).all()
    assert START in emb and END in emb and "A" in emb and "NEVER" not in emb
    assert np.array_equal(emb.vector("A"), emb.matrix[emb.vocabulary.index("A")])
    assert emb.vector("NEVER") is None


def test_same_seed_gives_identical_vectors_and_another_seed_differs(fitted):
    graph, walks, emb = fitted

    again = fit_embedding(graph, walks, EMB_CFG, seed=1)
    other = fit_embedding(graph, walks, EMB_CFG, seed=2)

    assert np.array_equal(emb.matrix, again.matrix)
    assert not np.array_equal(emb.matrix, other.matrix)


def test_embedding_vectors_do_not_depend_on_pythonhashseed(tmp_path):
    script = textwrap.dedent(
        """
        import hashlib
        from jira_ad.config import EmbeddingConfig
        from jira_ad.embedding import fit_embedding
        import networkx as nx
        g = nx.DiGraph()
        walks = [["A", "B", "C"], ["A", "C", "B"], ["B", "C", "A"]] * 20
        for w in walks:
            g.add_nodes_from(w)
        cfg = EmbeddingConfig(dimensions=8, window=2, epochs=3, negative=5, min_count=1,
                              sample=0.0, workers=1)
        emb = fit_embedding(g, walks, cfg, seed=3)
        print(hashlib.sha256(emb.matrix.tobytes()).hexdigest())
        """
    )
    digests = set()
    for hash_seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        out = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True,
                             text=True, check=True, cwd=tmp_path)
        digests.add(out.stdout.strip())

    assert len(digests) == 1


def test_unseen_token_gets_a_zero_vector_and_the_model_is_not_retrained(fitted):
    _, _, emb = fitted
    before = emb.matrix.copy()

    vectors, known = emb.lookup(["A", "ONLY_TEST", "B"])

    assert known.tolist() == [True, False, True]
    assert np.array_equal(vectors[1], np.zeros(8))
    assert np.array_equal(vectors[0], emb.vector("A"))
    assert np.array_equal(emb.matrix, before)
    assert "ONLY_TEST" not in emb and len(emb.vocabulary) == before.shape[0]


def test_pooling_is_per_dimension_mean_and_max_with_unseen_tokens_kept_in_the_denominator(fitted):
    _, _, emb = fitted

    mean, maximum = pool_tokens(["A", "ONLY_TEST"], emb)

    va = emb.vector("A")
    assert np.allclose(mean, va / 2)  # vector zero vẫn nằm trong mẫu số
    assert np.allclose(maximum, np.maximum(va, 0.0))  # và tham gia max như một vector zero


def test_single_token_pooling_returns_its_vector(fitted):
    _, _, emb = fitted

    mean, maximum = pool_tokens(["C"], emb)

    assert np.allclose(mean, emb.vector("C")) and np.allclose(maximum, emb.vector("C"))


def test_pooling_cannot_see_order_which_is_why_transition_features_exist(fitted):
    _, _, emb = fitted

    first = pool_tokens(["A", "B", "C", "D"], emb)
    second = pool_tokens(["A", "C", "B", "D"], emb)

    assert np.allclose(first[0], second[0]) and np.allclose(first[1], second[1])


def test_pooling_an_empty_token_list_is_rejected(fitted):
    _, _, emb = fitted

    with pytest.raises(ValueError, match="rỗng|empty"):
        pool_tokens([], emb)


def test_diagnostics_report_coverage_walks_and_norms(fitted):
    graph, walks, emb = fitted

    d = embedding_diagnostics(emb, graph, walks)

    assert d["vocabulary_size"] == len(graph) and d["dimensions"] == 8
    assert d["node_coverage"] == 1.0
    assert d["n_walks"] == len(walks)
    assert d["n_single_token_walks"] == 10  # walk bắt đầu từ sink __END__
    assert d["norm_min"] > 0 and d["norm_max"] >= d["norm_mean"] >= d["norm_min"]
    assert d["gensim_version"]


def test_fit_requires_walks(fitted):
    graph, _, _ = fitted

    with pytest.raises(ValueError, match="rỗng|empty"):
        fit_embedding(graph, [], EMB_CFG, seed=1)


def test_whole_encoder_state_and_features_do_not_depend_on_pythonhashseed(tmp_path):
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = textwrap.dedent(
        f"""
        import hashlib
        from pathlib import Path
        from jira_ad.config import load_config
        from jira_ad.features import FeatureEncoder
        from jira_ad.types import Trace

        def trace(i, acts):
            return Trace(trace_id=f"t{{i}}", parent_case_id=f"t{{i}}", issue_type="bug",
                         activities=tuple(acts), roles=tuple("PO" for _ in acts),
                         event_ids=tuple(f"e{{i}}-{{j}}" for j in range(len(acts))),
                         timestamps=None, terminal_status="DONE")

        cfg = load_config(Path({repo_root!r}) / "configs" / "smoke.yaml")
        train = [trace(i, ["CREATE", "S_A", "S_B", "S_DONE"] + (["EDIT"] if i % 2 else []))
                 for i in range(12)]
        probe = [trace(99, ["CREATE", "EDIT", "S_B", "S_DONE", "NEW"])]
        digest = hashlib.sha256()
        for method in ("B_ngrams", "C_embedding", "D_hybrid"):
            enc = FeatureEncoder(method, cfg, 5).fit(train)
            digest.update(enc.state_fingerprint().encode())
            digest.update(enc.transform(probe).values.tobytes())
        print(digest.hexdigest())
        """
    )
    digests = set()
    for hash_seed in ("0", "7", "99999"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        out = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True,
                             text=True, check=True, cwd=tmp_path)
        digests.add(out.stdout.strip())

    assert len(digests) == 1
