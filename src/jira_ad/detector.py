"""Isolation Forest làm bộ xếp hạng khác thường, kèm bundle lưu/nạp (spec §5.4, §9).

Điểm xuất thống nhất `anomaly_score = -model.score_samples(X)`: lớn hơn nghĩa là khác thường hơn.
Đây là điểm xếp hạng liên tục, không phải xác suất vi phạm và không có ngưỡng cờ mặc định.
"""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from jira_ad.config import RunConfig
from jira_ad.features import H_FEATURE_NAMES, FeatureEncoder
from jira_ad.preprocess import load_action_rules
from jira_ad.types import Trace

BUNDLE_VERSION = 1
SCORE_COLUMNS = [
    "trace_id", "parent_case_id", "method", "anomaly_score", "n_events", "unseen_node_ratio",
    "unseen_transition_ratio",
]
TRACKED_PACKAGES = ("numpy", "pandas", "scikit-learn", "gensim", "networkx", "pyarrow", "joblib")
MAX_LISTED_CONSTANT_FEATURES = 50


@dataclass
class DetectorBundle:
    """Encoder đã fit + bộ chấm điểm (`score_samples`) + metadata tự chứa (gồm nội dung action rules).

    A–D, F: một IsolationForest. E_score_fusion: `ZScoreFusion`. M_markov: `ColumnScore`.
    """

    method: str
    encoder: FeatureEncoder
    model: Any
    metadata: dict[str, Any]


class ZScoreFusion:
    """Một Isolation Forest cho mỗi nhóm cột; điểm của mỗi rừng chuẩn hóa z theo phân bố điểm TRAIN của
    chính nó, rồi lấy trung bình (E_score_fusion). Nhóm cột không làm loãng nhau như khi ghép chung.

    `score_samples` theo quy ước sklearn (lớn hơn = bình thường hơn) nên `anomaly_score = -score_samples`.
    Std điểm train bằng 0 thì dùng 1,0 để không chia cho 0.
    """

    def __init__(self, groups: list[list[int]], make_forest) -> None:
        self.groups = [list(g) for g in groups]
        self._make_forest = make_forest
        self.forests: list[IsolationForest] = []
        self.train_mean: list[float] = []
        self.train_std: list[float] = []

    def fit(self, values: np.ndarray) -> ZScoreFusion:
        for cols in self.groups:
            forest = self._make_forest().fit(values[:, cols])
            scores = -forest.score_samples(values[:, cols])
            self.forests.append(forest)
            self.train_mean.append(float(scores.mean()))
            self.train_std.append(float(scores.std()) or 1.0)
        self._make_forest = None  # không lưu closure vào bundle
        return self

    def score_samples(self, values: np.ndarray) -> np.ndarray:
        z = [(-forest.score_samples(values[:, cols]) - mean) / std for forest, cols, mean, std
             in zip(self.forests, self.groups, self.train_mean, self.train_std, strict=True)]
        return -np.mean(z, axis=0)


class ColumnScore:
    """Điểm = một cột đặc trưng (M_markov: `mean_transition_surprisal`); không học gì thêm."""

    def __init__(self, index: int) -> None:
        self.index = index

    def score_samples(self, values: np.ndarray) -> np.ndarray:
        return -values[:, self.index]


def package_versions() -> dict[str, str]:
    versions = {"python": platform.python_version(), "platform": platform.platform()}
    for name in TRACKED_PACKAGES:
        versions[name] = importlib_metadata.version(name)
    return versions


def fit_detector(
    train: list[Trace], cfg: RunConfig, method: str, seed: int | None = None
) -> DetectorBundle:
    """Fit encoder rồi Isolation Forest, CHỈ trên `train`. `seed` mặc định là `cfg.run.seed`."""
    seed = cfg.run.seed if seed is None else seed
    started = time.perf_counter()
    encoder = FeatureEncoder(method, cfg, seed).fit(train)
    features = encoder.transform_train(train)  # in-sample (V1) hoặc cross-fit nếu được bật
    dcfg = cfg.detector

    def forest() -> IsolationForest:
        return IsolationForest(n_estimators=dcfg.n_estimators, max_samples=dcfg.max_samples,
                               contamination=dcfg.contamination, random_state=seed,
                               n_jobs=dcfg.n_jobs)

    names = features.feature_names
    if method == "M_markov":
        model = ColumnScore(names.index("mean_transition_surprisal"))
    elif method == "E_score_fusion":
        h_cols = [i for i, n in enumerate(names) if n in H_FEATURE_NAMES]
        pooled = [i for i, n in enumerate(names) if n not in H_FEATURE_NAMES]
        model = ZScoreFusion([h_cols, pooled], forest).fit(features.values)
    else:
        model = forest().fit(features.values)
    constant = [
        name for name, std in zip(features.feature_names, features.values.std(axis=0), strict=True)
        if std == 0
    ]
    rules_text = rules_sha256 = None
    actions_path = cfg.preprocess.actions_path
    if actions_path is not None and Path(actions_path).is_file():
        rules = load_action_rules(actions_path)
        rules_text, rules_sha256 = rules.text, rules.sha256
    meta = {
        "bundle_version": BUNDLE_VERSION,
        "method": method,
        "seed": seed,
        "n_train": len(train),
        "n_features": len(features.feature_names),
        "train_ids_sha256": encoder.schema()["train_ids_sha256"],
        "encoder_state_sha256": encoder.state_fingerprint(),
        # fit→transform in-sample: feature hằng trên train không được Isolation Forest sử dụng
        "n_constant_features": len(constant),
        "constant_feature_names": constant[:MAX_LISTED_CONSTANT_FEATURES],
        "fit_seconds": time.perf_counter() - started,
        "detector_params": {
            "n_estimators": dcfg.n_estimators, "max_samples": dcfg.max_samples,
            "contamination": dcfg.contamination, "n_jobs": dcfg.n_jobs,
        },
        "preprocess": {
            "view": cfg.preprocess.view,
            "terminal_statuses": list(cfg.preprocess.terminal_statuses),
            "noise_policy": cfg.preprocess.noise_policy,
            "actions_file": cfg.preprocess.actions_file,
        },
        "action_rules_sha256": rules_sha256,
        "action_rules_text": rules_text,  # nội dung đã resolve, không chỉ đường dẫn YAML
        "config": cfg.as_dict(),
        "packages": package_versions(),
    }
    return DetectorBundle(method=method, encoder=encoder, model=model, metadata=meta)


def score_traces(bundle: DetectorBundle, traces: list[Trace]) -> pd.DataFrame:
    """Điểm khác thường cho từng trace; không fit lại và không sửa state của bundle.

    Kèm độ phủ (`unseen_node_ratio`, `unseen_transition_ratio`) để đọc điểm đúng ngữ cảnh.
    """
    if not traces:
        return pd.DataFrame(columns=SCORE_COLUMNS)
    features = bundle.encoder.transform(traces)
    scores = -bundle.model.score_samples(features.values)
    if not np.isfinite(scores).all():
        raise ValueError("Điểm khác thường không hữu hạn (NaN/Inf); không ghi kết quả âm thầm")
    coverage = bundle.encoder.coverage(traces)
    frame = pd.DataFrame({
        "trace_id": [t.trace_id for t in traces],
        "parent_case_id": [t.parent_case_id for t in traces],
        "method": bundle.method,
        "anomaly_score": scores,
    })
    frame["n_events"] = coverage["n_events"].to_numpy()
    frame["unseen_node_ratio"] = coverage["unseen_node_ratio"].to_numpy()
    frame["unseen_transition_ratio"] = coverage["unseen_transition_ratio"].to_numpy()
    return frame[SCORE_COLUMNS]


def save_bundle(bundle: DetectorBundle, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)


def load_bundle(path: Path) -> DetectorBundle:
    """Nạp bundle đã lưu. CẢNH BÁO: joblib/pickle chạy mã khi nạp, chỉ nạp file do chính bạn tạo."""
    bundle = joblib.load(Path(path))
    if not isinstance(bundle, DetectorBundle):
        raise TypeError(f"{path} không phải DetectorBundle (nhận {type(bundle).__name__})")
    return bundle
