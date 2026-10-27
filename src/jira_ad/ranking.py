"""Học biểu diễn và xếp hạng ca nên xem trước (B6), tái sử dụng giai đoạn 1, không fit lại mô hình.

- **Biểu diễn**: vector Node2Vec của run V1 (`node_vectors.parquet`) so với đặc trưng cấu trúc (bậc, trung
  tâm) trên cùng bài toán: tìm lại nhóm nghiệp vụ của activity (K-means + ARI/NMI; 1-NN leave-one-out),
  có baseline lớp phổ biến.
- **Xếp hạng**: hồ sơ nhiều chiều mỗi ca; mỗi chiều đổi thành phân vị trong nhóm cùng nhánh × độ dài; xếp
  theo số chiều vượt ngưỡng (p90). "Điểm cao" = "nên xem trước", không phải "vi phạm"; Rejected không phải
  bất thường.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, f1_score, normalized_mutual_info_score, silhouette_score
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.neighbors import KNeighborsClassifier

from jira_ad.analysis import NotebookInputError, open_run

LENGTH_LABELS = {2: ("ngắn", "dài"), 3: ("ngắn", "vừa", "dài")}


# ------------------------------------------------------------------------------------ biểu diễn


def load_v1_vectors(run_dir: Path) -> pd.DataFrame:
    """Vector nút của run V1 đã qua kiểm fingerprint (`analysis.open_run`), bỏ nút biên."""
    vectors = open_run(run_dir).read_parquet("node_vectors.parquet").set_index("node")
    return vectors.drop(index=[n for n in ("__START__", "__END__") if n in vectors.index])


def group_labels(nodes, groups: dict[str, tuple[str, ...]]) -> pd.Series:
    lookup = {a: g for g, acts in groups.items() for a in acts}
    return pd.Series([lookup.get(n, "other") for n in nodes], index=list(nodes), name="group")


def cluster_scan(x: pd.DataFrame, labels: pd.Series, *, k_min: int, k_max: int, seed: int) -> pd.DataFrame:
    rows = []
    for k in range(k_min, k_max + 1):
        found = KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(x.to_numpy())
        rows.append({"k": k, "silhouette": float(silhouette_score(x.to_numpy(), found)),
                     "ari": float(adjusted_rand_score(labels.loc[x.index], found)),
                     "nmi": float(normalized_mutual_info_score(labels.loc[x.index], found))})
    return pd.DataFrame(rows)


def loo_knn(x: pd.DataFrame, labels: pd.Series, *, metric: str) -> dict:
    """1-NN leave-one-out: biểu diễn có đặt activity cùng nhóm nghiệp vụ cạnh nhau không."""
    y = labels.loc[x.index].to_numpy()
    model = KNeighborsClassifier(n_neighbors=1, metric=metric)
    pred = cross_val_predict(model, x.to_numpy(), y, cv=LeaveOneOut())
    return {"accuracy": float((pred == y).mean()), "macro_f1": float(f1_score(y, pred, average="macro"))}


def majority_baseline(labels: pd.Series) -> dict:
    y = labels.to_numpy()
    pred = np.full(len(y), labels.value_counts().index[0])
    return {"accuracy": float((pred == y).mean()),
            "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0))}


def standardize(frame: pd.DataFrame) -> pd.DataFrame:
    std = frame.std(ddof=0).replace(0, 1.0)
    return (frame - frame.mean()) / std


# ------------------------------------------------------------------------------- hồ sơ, xếp hạng


def load_oof_scores(improvement_dir: Path, method: str) -> pd.DataFrame:
    """Điểm out-of-fold (cross-validation giai đoạn 1) của một phương pháp, trung bình các model seed."""
    improvement_dir = Path(improvement_dir)
    manifest = json.loads((improvement_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "completed":
        raise NotebookInputError(f"Run cải tiến {improvement_dir.name} có status {manifest.get('status')!r}, "
                                 "cần 'completed'")
    scores = pd.read_csv(improvement_dir / "cv_original_scores.csv")
    part = scores[scores["method"] == method]
    out = part.groupby("trace_id").agg(oof_score=("anomaly_score", "mean"), n_seeds=("model_seed", "nunique"),
                                       n_events=("n_events", "first")).reset_index()
    return out.rename(columns={"trace_id": "case_id"})


def length_adjusted(scores: pd.Series, n_events: pd.Series) -> pd.Series:
    """Phần dư của điểm sau hồi quy OLS theo log(số event): bỏ xu hướng 'ca dài điểm cao'."""
    x = np.log(n_events.loc[scores.index].to_numpy(dtype=float))
    design = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(design, scores.to_numpy(dtype=float), rcond=None)
    return pd.Series(scores.to_numpy() - design @ coef, index=scores.index, name="length_adjusted")


def peer_groups(cases: pd.DataFrame, *, bins: int) -> pd.Series:
    """Nhóm so sánh = nhánh kết thúc × khoảng độ dài (phân vị số event của toàn bộ ca)."""
    order = cases["n_events"].rank(method="first")
    length = pd.qcut(order, bins, labels=list(LENGTH_LABELS.get(bins, range(bins))))
    return pd.Series([f"{t}·{lab}" for t, lab in zip(cases["terminal_status"], length, strict=True)],
                     index=cases["case_id"], name="peer_group")


def _percentiles(profile: pd.DataFrame, dims, groups: pd.Series) -> pd.DataFrame:
    g = profile["case_id"].map(groups)
    return profile[dims].groupby(g.to_numpy()).rank(pct=True, method="average")


def _order(n_exceed: pd.Series, mean_pct: pd.Series, case_id: pd.Series) -> np.ndarray:
    keys = pd.DataFrame({"n": -n_exceed.to_numpy(), "m": -mean_pct.to_numpy(), "c": case_id.to_numpy()})
    return keys.sort_values(["n", "m", "c"]).index.to_numpy()


def rank_cases(profile: pd.DataFrame, dims, groups: pd.Series, *, p: float,
               labels: dict[str, str] | None = None) -> pd.DataFrame:
    """Xếp theo số chiều có phân vị trong nhóm > p, rồi theo phân vị trung bình; lý do bằng chữ."""
    labels = labels or {}
    pct = _percentiles(profile, dims, groups)
    out = profile.copy()
    out["peer_group"] = out["case_id"].map(groups)
    for d in dims:
        out[f"pct_{d}"] = pct[d].to_numpy()
    exceed = pct[dims] > p
    out["n_exceed"] = exceed.sum(axis=1).to_numpy()
    out["mean_pct"] = pct[dims].mean(axis=1).to_numpy()
    reasons = []
    for i in range(len(out)):
        parts = [f"{labels.get(d, d)} = {out[d].iloc[i]:.3g} (phân vị {pct[d].iloc[i] * 100:.0f} trong nhóm "
                 f"{out['peer_group'].iloc[i]})" for d in dims if exceed[d].iloc[i]]
        reasons.append("; ".join(parts).replace(".", ",") if parts else "")
    out["reasons"] = reasons
    out = out.loc[_order(out["n_exceed"], out["mean_pct"], out["case_id"])].reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out


def _bootstrap_tops(profile: pd.DataFrame, dims, groups: pd.Series, *, p: float, k: int, n_boot: int,
                    seed: int, top_share: float | None = None):
    """Mỗi lần bootstrap (lấy lại ca có hoàn lại): (tập ca được rút, tập top). Top = k ca cố định, hoặc
    `top_share` × số ca khác nhau được rút (dùng cho danh sách đồng thuận, tránh thổi phồng)."""
    rng = np.random.default_rng(seed)
    for _ in range(n_boot):
        sample = profile.iloc[rng.integers(0, len(profile), len(profile))].reset_index(drop=True)
        pct = _percentiles(sample, dims, groups)
        sample = sample.assign(n=(pct[dims] > p).sum(axis=1).to_numpy(), m=pct[dims].mean(axis=1).to_numpy())
        unique = sample.drop_duplicates("case_id").reset_index(drop=True)
        size = k if top_share is None else max(1, math.ceil(top_share * len(unique)))
        top = set(unique.loc[_order(unique["n"], unique["m"], unique["case_id"]), "case_id"].head(size))
        yield set(unique["case_id"]), top


def topk_stability(profile: pd.DataFrame, dims, groups: pd.Series, *, p: float, top_share: float,
                   n_boot: int, seed: int) -> dict:
    """Jaccard giữa top-k của dữ liệu gốc và top-k khi lấy mẫu lại ca (bootstrap)."""
    k = max(1, math.ceil(top_share * len(profile)))
    full = set(rank_cases(profile, dims, groups, p=p)["case_id"].head(k))
    scores = [len(top & full) / len(top | full)
              for _, top in _bootstrap_tops(profile, dims, groups, p=p, k=k, n_boot=n_boot, seed=seed)]
    lo, hi = np.percentile(scores, [2.5, 97.5])
    return {"k": k, "jaccard_mean": float(np.mean(scores)), "jaccard_low": float(lo),
            "jaccard_high": float(hi), "n_boot": n_boot}


def topk_consensus(profile: pd.DataFrame, dims, groups: pd.Series, *, p: float, top_share: float,
                   n_boot: int, seed: int, threshold: float) -> pd.DataFrame:
    """Danh sách đồng thuận: ca nằm trong top (`top_share` × số ca được rút) ở >= `threshold` số lần bootstrap
    mà ca đó được rút."""
    k = max(1, math.ceil(top_share * len(profile)))
    drawn = dict.fromkeys(profile["case_id"], 0)
    in_top = dict.fromkeys(profile["case_id"], 0)
    for sample, top in _bootstrap_tops(profile, dims, groups, p=p, k=k, n_boot=n_boot, seed=seed,
                                       top_share=top_share):
        for c in sample:
            drawn[c] += 1
        for c in top:
            in_top[c] += 1
    out = pd.DataFrame({"case_id": list(drawn), "n_drawn": list(drawn.values()),
                        "n_top": [in_top[c] for c in drawn]})
    out["share_top"] = out["n_top"] / out["n_drawn"].where(out["n_drawn"] > 0)
    out["consensus"] = out["share_top"] >= threshold
    return out.sort_values(["share_top", "case_id"], ascending=[False, True]).reset_index(drop=True)


def blind_review(ranked: pd.DataFrame, sequences: dict[str, str], *, n_top: int, n_random: int,
                 seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bảng mù cho người dùng tự rà soát: top + ngẫu nhiên, xáo trộn; khóa (nhóm, hạng) để riêng."""
    rng = np.random.default_rng(seed)
    top = ranked.head(n_top).assign(group="top")
    rest = ranked.iloc[n_top:]
    pick = rest.iloc[sorted(rng.choice(len(rest), size=min(n_random, len(rest)), replace=False))]
    both = pd.concat([top, pick.assign(group="random")]).iloc[rng.permutation(n_top + len(pick))]
    both = both.reset_index(drop=True)
    both.insert(0, "review_id", [f"R{i + 1:02d}" for i in range(len(both))])
    blinded = pd.DataFrame({"review_id": both["review_id"], "case_id": both["case_id"],
                            "sequence": both["case_id"].map(sequences), "label": "", "note": ""})
    key = both[["review_id", "case_id", "group", "rank"]]
    return blinded, key


DIMENSION_LABELS = {"nonconformance": "lệch mô hình chuẩn (1 − fitness)", "n_flags": "số cờ quy tắc",
                    "n_late": "số lượt trễ định mức", "n_back_reopen": "lùi trạng thái/mở lại",
                    "n_assignee": "đổi người phụ trách", "n_backfill": "lần đổi trạng thái bù",
                    "markov_adj": "độ bất ngờ M_markov (khử độ dài)"}


def build_profile(cases: pd.DataFrame, replay: pd.DataFrame | None, flags: pd.DataFrame, late: pd.DataFrame,
                  events: pd.DataFrame, oof: pd.DataFrame | None, *, assignee_activities
                  ) -> tuple[pd.DataFrame, list[str]]:
    """Hồ sơ nhiều chiều mỗi ca từ artifact các bước trước; chiều thiếu nguồn (replay, điểm OOF) bị bỏ."""
    out = cases[["case_id", "terminal_status", "n_events"]].copy()
    dims = []
    if replay is not None:
        out["nonconformance"] = 1 - out["case_id"].map(replay.set_index("case_id")["trace_fitness"])
        dims.append("nonconformance")
    real = flags[(flags["flag"] != "backfill") & (flags["n"] > 0)]
    out["n_flags"] = out["case_id"].map(real.groupby("case_id").size()).fillna(0).astype(int)
    out["n_late"] = out["case_id"].map(late.set_index("case_id")["n_late"]).fillna(0).astype(int)
    out["n_back_reopen"] = (cases["n_back"] + cases["n_reopen"]).to_numpy()
    assign = events[events["activity"].isin(set(assignee_activities))].groupby("case_id").size()
    out["n_assignee"] = out["case_id"].map(assign).fillna(0).astype(int)
    out["n_backfill"] = cases["n_backfill"].to_numpy()
    dims += ["n_flags", "n_late", "n_back_reopen", "n_assignee", "n_backfill"]
    if oof is not None:
        scores = out["case_id"].map(oof.set_index("case_id")["oof_score"])
        if scores.notna().all():
            idx = out.set_index("case_id")
            out["markov_raw"] = scores.to_numpy()
            out["markov_adj"] = length_adjusted(pd.Series(scores.to_numpy(), index=idx.index),
                                                idx["n_events"]).to_numpy()
            dims.append("markov_adj")
    return out, dims


REVIEW_LABELS = ("needs_review", "plausibly_valid", "insufficient_evidence")


def _wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (centre - half, centre + half)


def compare_blind_review(filled: pd.DataFrame, key: pd.DataFrame) -> dict:
    """Mở khóa bảng mù và so tỉ lệ `needs_review` giữa nhóm top và nhóm ngẫu nhiên.

    Fisher exact (hai phía) trên bảng 2×2 (needs_review / nhãn khác × top / ngẫu nhiên); odds ratio kèm khoảng
    tin cậy 95% (scipy); tỉ lệ mỗi nhóm kèm khoảng Wilson; hiệu hai tỉ lệ kèm khoảng Newcombe (Wilson lai).
    """
    from scipy.stats import fisher_exact
    from scipy.stats.contingency import odds_ratio

    labels = filled.set_index("review_id")["label"].fillna("").astype(str).str.strip()
    missing = sorted(labels[labels == ""].index)
    if missing:
        raise ValueError(f"Chưa gán nhãn cho: {missing}")
    unknown = sorted(set(labels) - set(REVIEW_LABELS))
    if unknown:
        raise ValueError(f"Nhãn không hợp lệ {unknown}; hợp lệ: {REVIEW_LABELS}")
    merged = key.set_index("review_id").join(labels.rename("label"), how="inner")
    out: dict = {}
    for group in ("top", "random"):
        part = merged[merged["group"] == group]
        n, k = len(part), int((part["label"] == "needs_review").sum())
        out[group] = {"n": n, **{lab: int((part["label"] == lab).sum()) for lab in REVIEW_LABELS},
                      "share": k / n if n else float("nan"), "share_ci": _wilson(k, n)}
    table = [[out["top"]["needs_review"], out["top"]["n"] - out["top"]["needs_review"]],
             [out["random"]["needs_review"], out["random"]["n"] - out["random"]["needs_review"]]]
    out["fisher_p_two_sided"] = float(fisher_exact(table, alternative="two-sided").pvalue)
    result = odds_ratio(table)
    ci = result.confidence_interval(confidence_level=0.95)
    out["odds_ratio"] = float(result.statistic)
    out["odds_ratio_ci"] = (float(ci.low), float(ci.high))
    (l1, u1), (l2, u2) = out["top"]["share_ci"], out["random"]["share_ci"]
    p1, p2 = out["top"]["share"], out["random"]["share"]
    diff = p1 - p2
    out["difference"] = diff
    out["difference_ci"] = (diff - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2),
                            diff + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2))
    return out
