"""Đặc trưng cấp trace: thống kê quy trình H và n-gram, với trạng thái fit/transform (spec §5.4).

Mọi thứ học được (DFG, từ vựng, từ vựng bigram, walk, embedding) chỉ đến từ `fit(train)`.
`transform` không sửa state: nút hay chuyển tiếp chưa thấy chỉ làm tăng tỷ lệ `unseen_*`.
Định danh, split, trạng thái terminal, nhãn và thời gian KHÔNG bao giờ trở thành feature.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

from jira_ad.config import FEATURE_METHODS, RunConfig
from jira_ad.embedding import (
    Node2VecEmbedding,
    embedding_diagnostics,
    fit_embedding,
    pool_edges,
    pool_tokens,
)
from jira_ad.graph import (
    build_dfg,
    graph_diagnostics,
    trace_tokens,
    trace_transitions,
    transition_info,
)
from jira_ad.types import UNDETERMINED_ROLES, FeatureSet, Trace
from jira_ad.walks import generate_walks, walk_diagnostics, walk_graph

H_FEATURE_NAMES = (
    "log1p_length",
    "distinct_activity_ratio",
    "adjacent_repeat_ratio",
    "revisit_ratio",
    "known_role_switch_ratio",
    "known_role_coverage",
    "mean_transition_surprisal",
    "max_transition_surprisal",
    "unseen_node_ratio",
    "unseen_transition_ratio",
)
UNIGRAM_PREFIX = "unigram::"
BIGRAM_PREFIX = "bigram::"
EMBEDDING_METHODS = ("C_embedding", "D_hybrid", "E_score_fusion", "F_edge_hybrid")
# E_score_fusion dùng đúng cột của D_hybrid (khác ở bộ chấm điểm); M_markov chỉ dùng H.
H_ONLY_METHODS = ("A_stats", "M_markov")
UNSEEN_NODE_INDEX = H_FEATURE_NAMES.index("unseen_node_ratio")
UNSEEN_TRANSITION_INDEX = H_FEATURE_NAMES.index("unseen_transition_ratio")
WALK_SAMPLE_SIZE = 20


def bigram_name(first: str, second: str) -> str:
    """Tên feature bigram có thứ tự, mã hóa JSON nên không nhập nhằng khi tên chứa dấu phẩy."""
    return BIGRAM_PREFIX + json.dumps([first, second], ensure_ascii=False)


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator > 0 else 0.0


class FeatureEncoder:
    """`FeatureEncoder(method, cfg, seed).fit(train).transform(traces)`; A_stats và B_ngrams."""

    def __init__(self, method: str, cfg: RunConfig, seed: int) -> None:
        if method not in FEATURE_METHODS:
            raise ValueError(f"method {method!r} không thuộc {FEATURE_METHODS}")
        self.method = method
        self.cfg = cfg
        self.seed = seed
        self._fitted = False

    # ------------------------------------------------------------------------------ fit

    def fit(self, traces: list[Trace]) -> FeatureEncoder:
        if not traces:
            raise ValueError("Tập train rỗng (empty): không thể fit encoder")
        gcfg = self.cfg.graph
        self.graph = build_dfg(traces, gcfg)
        self.vocabulary: tuple[str, ...] = self.graph.graph["vocabulary"]
        self._vocabulary_set = frozenset(self.vocabulary)
        self.bigrams: tuple[tuple[str, str], ...] = ()
        self.embedding: Node2VecEmbedding | None = None
        self.walk_summary: dict[str, Any] | None = None
        self.walk_sample: list[list[str]] = []
        self.embedding_summary: dict[str, Any] | None = None
        names = list(H_FEATURE_NAMES)
        if self.method == "B_ngrams":
            pairs: set[tuple[str, str]] = set()
            for trace in traces:
                tokens = trace_tokens(trace, gcfg.encoding)
                pairs.update(zip(tokens, tokens[1:], strict=False))
            self.bigrams = tuple(sorted(pairs))
            names += [UNIGRAM_PREFIX + token for token in self.vocabulary]
            names += [bigram_name(a, b) for a, b in self.bigrams]
        elif self.method in EMBEDDING_METHODS:
            self._fit_embedding()
            width = self.cfg.embedding.dimensions
            prefix = "edge" if self.method == "F_edge_hybrid" else "emb"
            pooled = [f"{prefix}_mean_{i:02d}" for i in range(width)]
            pooled += [f"{prefix}_max_{i:02d}" for i in range(width)]
            names = pooled + (["unseen_node_ratio"] if self.method == "C_embedding"
                              else list(H_FEATURE_NAMES))
        self.feature_names: tuple[str, ...] = tuple(names)
        self.train_ids: tuple[str, ...] = tuple(sorted(t.trace_id for t in traces))
        self.cross_fit_folds: int = self.cfg.features.cross_fit_folds
        self.cross_fit_assignment: dict[str, int] = {}
        self._train_h: dict[str, list[float]] = {}
        if self.cross_fit_folds:
            self._fit_cross_fit(traces)
        self._fitted = True
        return self

    def _fit_cross_fit(self, traces: list[Trace]) -> None:
        """H của từng trace train tính bằng DFG dựng từ các fold KHÁC (chỉ dữ liệu train).

        Chia fold theo băm SHA-256 của `split.seed:cross_fit:trace_id` rồi chia vòng tròn nên cân bằng
        (chênh tối đa 1), không phụ thuộc thứ tự đầu vào hay model seed. Chỉ các cột H phụ thuộc đồ
        thị (surprisal, unseen_*) thay đổi; embedding vẫn học trên toàn bộ train (không cross-fit).
        """
        folds = self.cross_fit_folds
        if len(traces) < folds:
            raise ValueError(
                f"cross_fit_folds={folds} lớn hơn số trace train ({len(traces)}): không chia được fold")
        ranked = sorted(traces, key=lambda t: hashlib.sha256(
            f"{self.cfg.split.seed}:cross_fit:{t.trace_id}".encode()).hexdigest())
        self.cross_fit_assignment = {t.trace_id: i % folds for i, t in enumerate(ranked)}
        gcfg = self.cfg.graph
        for fold in range(folds):
            graph = build_dfg(
                [t for t in traces if self.cross_fit_assignment[t.trace_id] != fold], gcfg)
            vocabulary = frozenset(graph.graph["vocabulary"])
            for trace in traces:
                if self.cross_fit_assignment[trace.trace_id] == fold:
                    self._train_h[trace.trace_id] = self._h_features(
                        trace_tokens(trace, gcfg.encoding), trace.roles, graph, vocabulary)

    def _fit_embedding(self) -> None:
        """Walk + Skip-gram trên DFG train; chỉ vector của nút đã thấy ở train được học."""
        view = walk_graph(self.graph, self.cfg.graph.directed)
        walks = generate_walks(view, self.cfg.walk, self.seed)
        self.embedding = fit_embedding(view, walks, self.cfg.embedding, self.seed)
        self.walk_sample = walks[:WALK_SAMPLE_SIZE]
        self.walk_summary = {
            **walk_diagnostics(walks, view),
            "p": self.cfg.walk.p,
            "q": self.cfg.walk.q,
            "length": self.cfg.walk.length,
            "walks_per_node": self.cfg.walk.walks_per_node,
            "directed": self.cfg.graph.directed,
        }
        self.embedding_summary = embedding_diagnostics(self.embedding, view, walks)

    # ------------------------------------------------------------------------- transform

    def transform(self, traces: list[Trace]) -> FeatureSet:
        """Đặc trưng của trace bất kỳ bằng state đã fit (đồ thị train đầy đủ); không sửa state."""
        return self._build(traces, None)

    def transform_train(self, traces: list[Trace]) -> FeatureSet:
        """Đặc trưng của chính các trace train để fit detector.

        Không cross-fit (`features.cross_fit_folds = 0`): giống hệt `transform` (in-sample, V1). Có
        cross-fit: cột H phụ thuộc đồ thị lấy từ đồ thị của các fold khác. Chỉ nhận trace thuộc train.
        """
        if not self._fitted:
            raise RuntimeError("Encoder chưa fit: gọi fit(train) trước transform_train")
        if not self.cross_fit_folds:
            return self.transform(traces)
        strangers = sorted({t.trace_id for t in traces} - set(self.train_ids))
        if strangers:
            raise ValueError(f"transform_train chỉ nhận trace thuộc train, lạ: {strangers[:5]}")
        return self._build(traces, self._train_h)

    def _build(self, traces: list[Trace], cached_h: dict[str, list[float]] | None) -> FeatureSet:
        if not self._fitted:
            raise RuntimeError("Encoder chưa fit: gọi fit(train) trước transform")
        rows = []
        for trace in traces:
            tokens = trace_tokens(trace, self.cfg.graph.encoding)
            h = (cached_h[trace.trace_id] if cached_h is not None
                 else self._h_features(tokens, trace.roles))
            if self.method in H_ONLY_METHODS:
                row = h
            elif self.method == "B_ngrams":
                row = h + self._ngram_features(tokens)
            else:
                if self.method == "F_edge_hybrid":
                    mean, maximum = pool_edges(
                        trace_transitions(tokens, self.cfg.graph.add_boundaries), self.embedding)
                else:
                    mean, maximum = pool_tokens(tokens, self.embedding)
                tail = [h[UNSEEN_NODE_INDEX]] if self.method == "C_embedding" else h
                row = [*mean, *maximum, *tail]
            rows.append(row)
        values = np.asarray(rows, dtype=np.float64).reshape(len(traces), len(self.feature_names))
        return FeatureSet(
            values=values,
            trace_ids=tuple(t.trace_id for t in traces),
            feature_names=self.feature_names,
        )

    def coverage(self, traces: list[Trace]) -> pd.DataFrame:
        """Độ phủ theo trace, độc lập phương pháp: nút và chuyển tiếp chưa thấy ở train."""
        records = []
        for trace in traces:
            h = self._h_features(trace_tokens(trace, self.cfg.graph.encoding), trace.roles)
            records.append({
                "trace_id": trace.trace_id,
                "n_events": len(trace),
                "unseen_node_ratio": h[UNSEEN_NODE_INDEX],
                "unseen_transition_ratio": h[UNSEEN_TRANSITION_INDEX],
            })
        return pd.DataFrame(
            records,
            columns=["trace_id", "n_events", "unseen_node_ratio", "unseen_transition_ratio"],
        )

    def _h_features(
        self, tokens: list[str], roles: tuple[str, ...],
        graph: nx.DiGraph | None = None, vocabulary: frozenset[str] | None = None,
    ) -> list[float]:
        """Thống kê quy trình H; mẫu số 0 trả 0 (spec §5.4). `bot` là một role xác định.

        `graph`/`vocabulary` mặc định là đồ thị train đầy đủ của encoder; cross-fit truyền đồ thị
        của các fold khác để trace train được mô tả bởi đồ thị không chứa chính nó.
        """
        graph = self.graph if graph is None else graph
        vocabulary = self._vocabulary_set if vocabulary is None else vocabulary
        length = len(tokens)
        pairs = max(length - 1, 1)
        repeats = sum(a == b for a, b in zip(tokens, tokens[1:], strict=False))
        seen: set[str] = set()
        revisits = 0
        for i, token in enumerate(tokens):
            if i > 0 and token in seen and token != tokens[i - 1]:
                revisits += 1  # quay lại activity đã thấy sau khi rời nó (không phải lặp kề nhau)
            seen.add(token)
        known = [r for r in roles if r not in UNDETERMINED_ROLES]
        switches = sum(a != b for a, b in zip(known, known[1:], strict=False))
        infos = [
            transition_info(graph, s, t, self.cfg.graph.transition_alpha)
            for s, t in trace_transitions(tokens, self.cfg.graph.add_boundaries)
        ]
        surprisals = [info.surprisal for info in infos]
        return [
            math.log1p(length),
            len(set(tokens)) / length,
            repeats / pairs,
            revisits / pairs,
            _ratio(switches, len(known) - 1),
            len(known) / length,
            float(np.mean(surprisals)) if surprisals else 0.0,
            max(surprisals) if surprisals else 0.0,
            sum(t not in vocabulary for t in tokens) / length,
            _ratio(sum(info.unseen_transition for info in infos), len(infos)),
        ]

    def _ngram_features(self, tokens: list[str]) -> list[float]:
        """Tần suất tương đối: unigram count/L; bigram có thứ tự count/max(L-1, 1)."""
        length = len(tokens)
        unigrams = Counter(tokens)
        bigrams = Counter(zip(tokens, tokens[1:], strict=False))
        pairs = max(length - 1, 1)
        return [unigrams[t] / length for t in self.vocabulary] + [
            bigrams[b] / pairs for b in self.bigrams
        ]

    # ------------------------------------------------------------------------- provenance

    def state_fingerprint(self) -> str:
        """SHA-256 của toàn bộ state đã fit; không đổi sau `transform`."""
        graph = self.graph
        payload = {
            "method": self.method,
            "nodes": [[n, d["count"], d["out_count"]] for n, d in graph.nodes(data=True)],
            "edges": [[u, v, w] for u, v, w in graph.edges(data="weight")],
            "bigrams": [list(b) for b in self.bigrams],
            "feature_names": list(self.feature_names),
            "train_ids": list(self.train_ids),
            "embedding_sha256": None if self.embedding is None else hashlib.sha256(
                self.embedding.matrix.tobytes()).hexdigest(),
            "embedding_vocabulary": None if self.embedding is None else list(
                self.embedding.vocabulary),
        }
        if self.cross_fit_folds:  # chỉ thêm khi bật, để fingerprint của baseline không đổi
            payload["cross_fit"] = {
                "folds": self.cross_fit_folds,
                "assignment": sorted(self.cross_fit_assignment.items()),
                "train_h": sorted(self._train_h.items()),
            }
        text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def schema(self) -> dict[str, Any]:
        """Mô tả encoder đã fit (JSON được): tên feature, chiều, hash id train, DFG diagnostics."""
        if not self._fitted:
            raise RuntimeError("Encoder chưa fit")
        gcfg = self.cfg.graph
        return {
            "method": self.method,
            "feature_names": list(self.feature_names),
            "n_features": len(self.feature_names),
            "n_h_features": len(H_FEATURE_NAMES),
            "n_train_traces": len(self.train_ids),
            "cross_fit_folds": self.cross_fit_folds,
            "train_ids_sha256": hashlib.sha256("\n".join(self.train_ids).encode()).hexdigest(),
            "vocabulary_size": len(self.vocabulary),
            "n_bigram_features": len(self.bigrams),
            "n_embedding_features": (
                2 * self.cfg.embedding.dimensions if self.embedding is not None else 0),
            "include_time": self.cfg.features.include_time,
            "encoding": gcfg.encoding,
            "add_boundaries": gcfg.add_boundaries,
            "transition_alpha": gcfg.transition_alpha,
            "seed": self.seed,
            "state_sha256": self.state_fingerprint(),
            "graph": graph_diagnostics(self.graph),
            "walks": self.walk_summary,
            "embedding": self.embedding_summary,
        }


def feature_example_table(features: FeatureSet, n: int = 5) -> pd.DataFrame:
    """Bảng ví dụ n trace đầu (chỉ số = trace_id) cho notebook đọc."""
    return pd.DataFrame(
        features.values[:n],
        index=list(features.trace_ids[:n]),
        columns=list(features.feature_names),
    )
