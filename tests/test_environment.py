"""Hợp đồng môi trường (spec §9): chọn dependency xong phải fit/save/load được thật.

Không kiểm tra logic dự án; chỉ chặn việc lock ra bộ phiên bản import được nhưng không chạy được
các đường mà Task 4+ cần (Word2Vec Skip-gram một worker, joblib bundle, parquet).
"""

from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from gensim.models import Word2Vec
from sklearn.ensemble import IsolationForest


def test_skipgram_single_worker_fit_save_load_roundtrip(tmp_path):
    walks = [["A", "B", "C"], ["A", "C", "B"], ["B", "C", "A"]] * 20
    model = Word2Vec(
        walks, vector_size=8, window=2, min_count=1, sg=1, negative=5, sample=0,
        epochs=3, workers=1, seed=1,
    )
    model.save(str(tmp_path / "w2v.model"))

    loaded = Word2Vec.load(str(tmp_path / "w2v.model"))

    assert loaded.wv.vector_size == 8
    assert sorted(loaded.wv.index_to_key) == ["A", "B", "C"]
    assert np.allclose(model.wv["A"], loaded.wv["A"])


def test_isolation_forest_joblib_and_parquet_roundtrip(tmp_path):
    x = np.random.default_rng(0).normal(size=(60, 4))
    forest = IsolationForest(n_estimators=20, random_state=0, n_jobs=1).fit(x)
    joblib.dump(forest, tmp_path / "forest.joblib")
    reloaded = joblib.load(tmp_path / "forest.joblib")

    frame = pd.DataFrame({"trace_id": ["a", "b"], "anomaly_score": [0.1, 0.2]})
    frame.to_parquet(tmp_path / "scores.parquet")

    assert np.allclose(forest.score_samples(x), reloaded.score_samples(x), atol=1e-8)
    assert pd.read_parquet(tmp_path / "scores.parquet").equals(frame)
