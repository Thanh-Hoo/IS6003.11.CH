"""Word2Vec Skip-gram trên walk của DFG train và chính sách OOV (spec §5.3).

Vector chỉ được học từ đồ thị train. Nút chưa thấy ở validation/test nhận vector zero, vẫn nằm
trong mẫu số pooling, không bị thêm vào mô hình và không retrain. Không so cosine giữa hai
không gian được học độc lập.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import gensim
import networkx as nx
import numpy as np
from gensim.models import Word2Vec

from jira_ad.config import EmbeddingConfig
from jira_ad.walks import walk_diagnostics


@dataclass(eq=False)
class Node2VecEmbedding:
    """Bảng vector đã fit: thứ tự từ vựng, ma trận (n, d) và provenance của lần fit."""

    vocabulary: tuple[str, ...]
    matrix: np.ndarray
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.matrix.ndim != 2 or self.matrix.shape[0] != len(self.vocabulary):
            raise ValueError(
                f"Ma trận {self.matrix.shape} không khớp từ vựng ({len(self.vocabulary)} token)"
            )
        self._index = {token: i for i, token in enumerate(self.vocabulary)}

    @property
    def dim(self) -> int:
        return int(self.matrix.shape[1])

    def __contains__(self, token: object) -> bool:
        return token in self._index

    def vector(self, token: str) -> np.ndarray | None:
        index = self._index.get(token)
        return None if index is None else self.matrix[index]

    def lookup(self, tokens: list[str]) -> tuple[np.ndarray, np.ndarray]:
        """Ma trận (len(tokens), d), vector zero cho token chưa thấy, và cờ `known` từng token."""
        vectors = np.zeros((len(tokens), self.dim))
        known = np.zeros(len(tokens), dtype=bool)
        for i, token in enumerate(tokens):
            index = self._index.get(token)
            if index is not None:
                vectors[i] = self.matrix[index]
                known[i] = True
        return vectors, known


def fit_embedding(
    graph: nx.DiGraph, walks: list[list[str]], cfg: EmbeddingConfig, seed: int
) -> Node2VecEmbedding:
    """Skip-gram (sg=1, negative sampling) trên walk; `workers=1` để tái lập (spec §5.3).

    Gensim 4.4.0 khởi tạo vector bằng RNG theo `seed` nên kết quả không phụ thuộc
    PYTHONHASHSEED (đã kiểm bằng thực nghiệm); `tests/test_embedding.py` canh điều này khi nâng
    phiên bản thư viện.
    """
    if not walks:
        raise ValueError("Danh sách walk rỗng (empty): không có gì để học embedding")
    model = Word2Vec(
        sentences=walks,
        vector_size=cfg.dimensions,
        window=cfg.window,
        min_count=cfg.min_count,
        sg=1,
        hs=0,
        negative=cfg.negative,
        sample=cfg.sample,
        epochs=cfg.epochs,
        workers=cfg.workers,
        seed=seed,
    )
    vocabulary = tuple(sorted(model.wv.index_to_key))
    matrix = np.stack([model.wv[token] for token in vocabulary]).astype(np.float64)
    provenance = {
        "seed": seed,
        "dimensions": cfg.dimensions,
        "window": cfg.window,
        "epochs": cfg.epochs,
        "negative": cfg.negative,
        "min_count": cfg.min_count,
        "sample": cfg.sample,
        "workers": cfg.workers,
        "n_walks": len(walks),
        "n_tokens": int(sum(len(w) for w in walks)),
        "gensim_version": gensim.__version__,
        "graph_nodes": graph.number_of_nodes(),
    }
    return Node2VecEmbedding(vocabulary=vocabulary, matrix=matrix, provenance=provenance)


def pool_tokens(tokens: list[str], embedding: Node2VecEmbedding) -> tuple[np.ndarray, np.ndarray]:
    """Mean và max pooling theo từng chiều trên các token của MỘT trace (không có START/END).

    Token chưa thấy là vector zero, vẫn nằm trong mẫu số của mean và tham gia max. Pooling
    không giữ thứ tự: hai chuỗi cùng multiset cho cùng kết quả.
    """
    if not tokens:
        raise ValueError("Danh sách token rỗng (empty): không pooling được")
    vectors, _ = embedding.lookup(tokens)
    return vectors.mean(axis=0), vectors.max(axis=0)


def pool_edges(
    transitions: list[tuple[str, str]], embedding: Node2VecEmbedding
) -> tuple[np.ndarray, np.ndarray]:
    """Mean và max theo từng chiều của vector CẠNH `v_a ⊙ v_b` (Hadamard) trên các chuyển tiếp của một trace.

    Khác `pool_tokens`, kết quả phụ thuộc thứ tự vì mỗi cạnh ghép hai nút liền nhau. Token chưa thấy là
    vector zero nên mọi cạnh chạm nó cũng là zero (vẫn nằm trong mẫu số của mean). Trace một event khi
    tắt `add_boundaries` không có cạnh nào: trả vector zero (không chia cho 0).
    """
    if not transitions:
        zero = np.zeros(embedding.dim)
        return zero, zero.copy()
    sources, _ = embedding.lookup([a for a, _ in transitions])
    targets, _ = embedding.lookup([b for _, b in transitions])
    edges = sources * targets
    return edges.mean(axis=0), edges.max(axis=0)


def embedding_diagnostics(
    embedding: Node2VecEmbedding, graph: nx.DiGraph, walks: list[list[str]]
) -> dict[str, Any]:
    """Độ phủ nút, thống kê walk và chuẩn vector (JSON được) để kiểm tra trước khi diễn giải."""
    norms = np.linalg.norm(embedding.matrix, axis=1)
    covered = sum(node in embedding for node in graph.nodes)
    return {
        "vocabulary_size": len(embedding.vocabulary),
        "dimensions": embedding.dim,
        "node_coverage": covered / graph.number_of_nodes(),
        "norm_min": float(norms.min()),
        "norm_mean": float(norms.mean()),
        "norm_max": float(norms.max()),
        **walk_diagnostics(walks, graph),
        **{k: v for k, v in embedding.provenance.items() if k in ("seed", "gensim_version")},
    }
