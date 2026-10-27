"""Phân tích dùng lại cho notebook: nạp run đã kiểm fingerprint, bảng mô tả, bằng chứng theo ca.

Bằng chứng ở đây (chuyển tiếp có surprisal cao, đoạn lặp, độ phủ OOV) mô tả hành vi của trace so
với đồ thị train. Nó KHÔNG phải giải thích nhân quả của Isolation Forest: không được nói "mô hình
cảnh báo vì X" chỉ vì một bảng thống kê X.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib.figure
import networkx as nx
import numpy as np
import pandas as pd
import yaml
from sklearn.decomposition import PCA

from jira_ad.config import (
    ConfigError,
    MutationConfig,
    RunConfig,
    config_from_dict,
    config_hash,
    load_config,
)
from jira_ad.config import resolve_project_root as _find_project_root
from jira_ad.detector import DetectorBundle, load_bundle, score_traces
from jira_ad.evaluation import (
    bootstrap_by_parent,
    bootstrap_differences_frame,
    bootstrap_intervals_frame,
)
from jira_ad.graph import trace_tokens, trace_transitions, transition_info
from jira_ad.mutations import generate_mutations
from jira_ad.types import MISSING_ROLE, UNDETERMINED_ROLES, UNKNOWN_ROLE, Trace

BOT_ROLE = "bot"
NOTE = (
    "Bằng chứng mô tả hành vi so với đồ thị train; không phải giải thích nhân quả của "
    "Isolation Forest."
)
REVIEW_COLUMNS = [
    "review_id", "case_id", "n_events", "n_roles_undetermined", "trace_text",
    "explainable", "transitions_to_clarify", "valid_loops", "business_data_needed",
    "review_label", "review_reason", "reviewer",
]
REVIEW_LABELS = ("needs_review", "plausibly_valid", "insufficient_evidence")


def _repeats(tokens: list[str]) -> list[dict[str, Any]]:
    """Đoạn lặp kề nhau: cùng một activity xuất hiện liên tiếp từ `start`, dài `length` >= 2."""
    out, i = [], 0
    while i < len(tokens):
        j = i
        while j + 1 < len(tokens) and tokens[j + 1] == tokens[i]:
            j += 1
        if j > i:
            out.append({"activity": tokens[i], "start": i, "length": j - i + 1})
        i = j + 1
    return out


def describe_case(trace: Trace, bundle: DetectorBundle, top_k: int = 5) -> dict[str, Any]:
    """Bằng chứng hành vi của một trace so với state đã fit trong `bundle` (không sửa state)."""
    encoder = bundle.encoder
    graph, gcfg = encoder.graph, encoder.cfg.graph
    tokens = trace_tokens(trace, gcfg.encoding)
    rows = []
    for position, (source, target) in enumerate(trace_transitions(tokens, gcfg.add_boundaries)):
        info = transition_info(graph, source, target, gcfg.transition_alpha)
        count = graph[source][target]["weight"] if graph.has_edge(source, target) else 0
        rows.append({
            "position": position, "source": source, "target": target,
            "surprisal": float(info.surprisal), "count": int(count),
            "unseen_source": bool(info.unseen_source),
            "unseen_transition": bool(info.unseen_transition),
        })
    ranked = sorted(rows, key=lambda r: (-r["surprisal"], r["position"]))
    surprisals = [r["surprisal"] for r in rows]
    coverage = encoder.coverage([trace]).iloc[0]
    roles = list(trace.roles)
    return {
        "trace_id": trace.trace_id,
        "n_events": len(trace),
        "terminal_status": trace.terminal_status,
        "method": bundle.method,
        "transitions": ranked[:top_k],
        "mean_transition_surprisal": float(np.mean(surprisals)) if surprisals else 0.0,
        "max_transition_surprisal": max(surprisals) if surprisals else 0.0,
        "repeats": _repeats(tokens),
        "coverage": {
            "unseen_tokens": sorted({t for t in tokens if t not in encoder.vocabulary}),
            "unseen_node_ratio": float(coverage["unseen_node_ratio"]),
            "unseen_transition_ratio": float(coverage["unseen_transition_ratio"]),
        },
        "roles": {
            "n_missing": roles.count(MISSING_ROLE),
            "n_unknown": roles.count(UNKNOWN_ROLE),
            "n_bot": roles.count(BOT_ROLE),
        },
        "note": NOTE,
    }


def trace_text(trace: Trace) -> str:
    """Chuỗi dễ đọc cho người rà soát: `activity [role] → activity [role] …`."""
    return " → ".join(f"{a} [{r}]" for a, r in zip(trace.activities, trace.roles, strict=True))


def build_case_review(
    scores: pd.DataFrame,
    traces: list[Trace],
    seed: int,
    method: str = "",
    n_top: int = 10,
    n_random: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Top `n_top` theo điểm + `n_random` ngẫu nhiên (không hoàn lại) từ các ca còn lại.

    Trả `(blinded, key)` cùng thứ tự dòng đã xáo theo `seed`. Bảng `blinded` chỉ có nội dung ca
    và các cột rà soát để trống (không điểm, hạng, mô hình hay nhóm); `key` giữ ánh xạ để mở
    sau. Không đủ ca thì lấy tối đa có thể. Cột rà soát ban đầu trống: không tạo 'nhãn chuyên gia'.
    """
    by_id = {t.trace_id: t for t in traces}
    ranked = scores.sort_values(["anomaly_score", "trace_id"], ascending=[False, True],
                                kind="stable").reset_index(drop=True)
    ranked["rank"] = np.arange(1, len(ranked) + 1)
    top = ranked.head(n_top).assign(group="top")
    rest = ranked.iloc[len(top):]
    rng = np.random.default_rng(seed)
    picks = np.sort(rng.choice(len(rest), size=min(n_random, len(rest)), replace=False))
    chosen = pd.concat([top, rest.iloc[picks].assign(group="random")], ignore_index=True)
    chosen = chosen.iloc[rng.permutation(len(chosen))].reset_index(drop=True)
    chosen["review_id"] = [f"R{i + 1:02d}" for i in range(len(chosen))]

    key = pd.DataFrame({
        "review_id": chosen["review_id"], "case_id": chosen["trace_id"], "group": chosen["group"],
        "rank": chosen["rank"], "anomaly_score": chosen["anomaly_score"], "method": method,
    })
    rows = []
    for review_id, case_id in zip(chosen["review_id"], chosen["trace_id"], strict=True):
        trace = by_id[case_id]
        rows.append({
            "review_id": review_id, "case_id": case_id, "n_events": len(trace),
            "n_roles_undetermined": sum(r in UNDETERMINED_ROLES for r in trace.roles),
            "trace_text": trace_text(trace),
        })
    blinded = pd.DataFrame(rows)
    for column in REVIEW_COLUMNS[len(blinded.columns):]:
        blinded[column] = ""
    return blinded[REVIEW_COLUMNS], key


# ============================================================================ nạp run cho notebook

RUN_ENV = "JIRA_AD_RUN_DIR"
DEFAULT_CONFIG_HINT = "configs/baseline.yaml"


class NotebookInputError(RuntimeError):
    """Notebook không có đủ đầu vào hợp lệ; thông điệp luôn nêu lệnh để tạo lại."""


class MissingArtifactError(NotebookInputError):
    """Thiếu run hoặc một artifact mà manifest đã khai báo."""


class FingerprintMismatchError(NotebookInputError):
    """Artifact, dữ liệu đầu vào hoặc cấu hình không còn khớp fingerprint trong manifest."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class RunArtifacts:
    """Một run đã hoàn tất và đã kiểm fingerprint; notebook chỉ đọc từ đây, không tự fit lại."""

    run_dir: Path
    project_root: Path
    manifest: dict[str, Any]
    cfg: RunConfig
    selection: str = "chỉ định (đối số hoặc biến môi trường)"  # cách run này được chọn; header in ra
    _bundles: dict[str, DetectorBundle] = field(default_factory=dict, repr=False)

    @property
    def run_id(self) -> str:
        return str(self.manifest["run_id"])

    @property
    def methods(self) -> list[str]:
        return list(self.manifest["methods"])

    def header(self) -> str:
        """Khối thông tin nguồn gốc mọi notebook phải hiển thị: run, cấu hình, fingerprint đầu vào."""
        m = self.manifest
        inputs = "; ".join(
            f"{i['relative_path']} sha256={i['sha256'][:12]}…" for i in m["input_files"])
        return (
            f"run_id      : {self.run_id}  (status: {m['status']})\n"
            f"chọn run    : {self.selection}\n"
            f"config_hash : {m['config_hash'][:12]}…  config: {m.get('config_path', '?')}\n"
            f"split_hash  : {m['split_hash'][:12]}…  action_rules: {m['action_rules_hash'][:12]}…\n"
            f"đầu vào     : {inputs}\n"
            f"seeds       : {m['seeds']}  | cohort: {m['cohort']}  | methods: {self.methods}"
        )

    def read_csv(self, relative: str) -> pd.DataFrame:
        return pd.read_csv(self.run_dir / relative)

    def read_parquet(self, relative: str) -> pd.DataFrame:
        return pd.read_parquet(self.run_dir / relative)

    def read_json(self, relative: str) -> Any:
        return json.loads((self.run_dir / relative).read_text(encoding="utf-8"))

    def bundle(self, method: str) -> DetectorBundle:
        """Bundle đã lưu của một phương pháp (nạp một lần). Chỉ nạp file do chính run này tạo."""
        if method not in self.methods:
            raise NotebookInputError(f"Phương pháp {method!r} không có trong run: {self.methods}")
        if method not in self._bundles:
            self._bundles[method] = load_bundle(self.run_dir / "models" / method / "bundle.joblib")
        return self._bundles[method]

    def save_table(self, frame: pd.DataFrame, name: str) -> Path:
        path = self.run_dir / "tables" / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, lineterminator="\n")
        return path

    def save_figure(
        self, fig: matplotlib.figure.Figure, name: str, data: pd.DataFrame | None = None
    ) -> Path:
        """Lưu hình PNG và (nếu có) bảng dữ liệu vẽ hình `tables/<name>_data.csv`."""
        path = self.run_dir / "figures" / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=130, bbox_inches="tight")
        if data is not None:
            self.save_table(data, f"{name}_data")
        return path

    def show(
        self, fig: matplotlib.figure.Figure, name: str, data: pd.DataFrame | None = None
    ) -> Path:
        """Lưu hình + bảng dữ liệu vẽ hình rồi hiển thị PNG trong notebook (không phụ thuộc backend)."""
        from IPython.display import Image, display

        path = self.save_figure(fig, name, data)
        display(Image(filename=str(path)))
        return path


def _rerun_hint(manifest: dict[str, Any]) -> str:
    """Lệnh tái tạo run: ưu tiên lệnh đã ghi trong manifest (vd thí nghiệm), nếu không thì `run`."""
    return manifest.get("rerun_command") or (
        f"uv run jira-ad run --config {manifest.get('config_path', DEFAULT_CONFIG_HINT)}")


def _root_from_cwd() -> Path | None:
    """Repo root tìm từ thư mục làm việc (notebook mở bằng tay thường có cwd = `notebooks/`)."""
    try:
        return _find_project_root(Path.cwd() / "_")
    except ConfigError:
        return None


def _default_run() -> tuple[Path, str]:
    """Run hoàn tất MỚI NHẤT có `config_hash` bằng đúng cấu hình `configs/baseline.yaml` hiện tại.

    Chỉ dùng khi không chỉ định run (mở notebook bằng tay trong VSCode/Jupyter, nơi không có bước nào
    đặt biến môi trường trước khi kernel khởi động). Không phải cache âm thầm: run phải khớp cấu hình
    hiện tại, mọi fingerprint vẫn được kiểm, và lựa chọn được in trong header của notebook. Cấu hình
    đã đổi hoặc chưa có run khớp thì dừng với lỗi nêu đúng lệnh tạo lại.
    """
    base_hint = (
        "Chưa chỉ định run. Chạy: uv run jira-ad notebooks --run-dir outputs/runs/<run_id> "
        f"(hoặc đặt biến môi trường {RUN_ENV}); "
        f"tạo run bằng: uv run jira-ad run --config {DEFAULT_CONFIG_HINT}"
    )
    root = _root_from_cwd()
    if root is None:
        raise NotebookInputError(base_hint)
    baseline = root / DEFAULT_CONFIG_HINT
    if not baseline.is_file():
        raise NotebookInputError(
            f"{base_hint}. Không có {DEFAULT_CONFIG_HINT} để chọn run tự động; đặt {RUN_ENV}=<thư mục run>.")
    try:
        cfg = load_config(baseline)
    except ConfigError as exc:
        raise NotebookInputError(
            f"{DEFAULT_CONFIG_HINT} không hợp lệ nên không chọn được run tự động: {exc}") from exc
    wanted = config_hash(cfg)
    candidates = []
    for manifest_path in (cfg.output_dir / "runs").glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if manifest.get("status") == "completed" and manifest.get("config_hash") == wanted:
            candidates.append((str(manifest.get("started_at_utc", "")), manifest_path.parent.name,
                               manifest_path.parent))
    if not candidates:
        raise NotebookInputError(
            f"Chưa có run hoàn tất nào khớp {DEFAULT_CONFIG_HINT} hiện tại (config_hash {wanted[:12]}…); "
            f"tạo bằng: uv run jira-ad run --config {DEFAULT_CONFIG_HINT} "
            f"(hoặc chỉ định run bằng {RUN_ENV}=<thư mục run>)")
    chosen = max(candidates)[2]
    return chosen, (f"tự động: run hoàn tất mới nhất khớp {DEFAULT_CONFIG_HINT} hiện tại "
                    f"(đặt {RUN_ENV} để chọn run khác)")


def open_run(run_dir: Path | str | None = None, *, verify_inputs: bool = True) -> RunArtifacts:
    """Mở một run đã hoàn tất sau khi kiểm manifest, fingerprint từng artifact và dữ liệu đầu vào.

    Không bao giờ im lặng dùng kết quả cũ hay thiếu: mọi vấn đề dừng với lỗi nêu đúng lệnh tạo
    lại. Thứ tự chọn run: đối số `run_dir`; biến môi trường `JIRA_AD_RUN_DIR` (do `jira-ad notebooks`
    đặt; đường dẫn tương đối được tìm từ thư mục làm việc rồi từ repo root); cuối cùng, run mới nhất
    khớp `configs/baseline.yaml` hiện tại (xem `_default_run`).
    """
    selection = "chỉ định (đối số hoặc biến môi trường)"
    if run_dir is None:
        run_dir = os.environ.get(RUN_ENV)
    if run_dir:
        path = Path(run_dir)
        if not path.is_absolute() and not path.exists():
            root = _root_from_cwd()
            if root is not None and (root / path).exists():
                path = root / path  # notebook mở từ notebooks/: đường dẫn tương đối tính từ repo root
        run_dir = path
    else:
        run_dir, selection = _default_run()
    run_dir = Path(run_dir).resolve()
    project_root = _find_project_root(run_dir / "manifest.json")
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise MissingArtifactError(
            f"Không có manifest.json trong {run_dir}; tạo run bằng: "
            f"uv run jira-ad run --config {DEFAULT_CONFIG_HINT}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hint = _rerun_hint(manifest)
    if manifest.get("status") != "completed":
        raise NotebookInputError(
            f"Run {run_dir.name} chưa hoàn tất (status={manifest.get('status')}); chạy lại: {hint}"
        )
    for relative, expected in manifest["artifacts"].items():
        path = run_dir / relative
        if not path.is_file():
            raise MissingArtifactError(f"Thiếu artifact {relative} của run {run_dir.name}; chạy lại: {hint}")
        if _sha256_file(path) != expected["sha256"]:
            raise FingerprintMismatchError(
                f"Artifact {relative} không còn khớp fingerprint trong manifest "
                f"(file đã bị sửa); chạy lại: {hint}"
            )
    if verify_inputs:
        for item in manifest["input_files"]:
            path = project_root / item["relative_path"]
            if not path.is_file():
                raise MissingArtifactError(f"Thiếu file đầu vào {item['relative_path']}; {hint}")
            if _sha256_file(path) != item["sha256"]:
                raise FingerprintMismatchError(
                    f"Đầu vào {item['relative_path']} đã đổi sau khi chạy run {run_dir.name}; "
                    f"chạy lại: {hint}"
                )
    raw = yaml.safe_load((run_dir / "config.resolved.yaml").read_text(encoding="utf-8"))
    cfg = config_from_dict(raw, project_root, project_root / manifest.get("config_path", "run.yaml"))
    if config_hash(cfg) != manifest["config_hash"]:
        raise FingerprintMismatchError(
            "config.resolved.yaml không khớp config_hash của manifest; chạy lại: " + hint
        )
    return RunArtifacts(run_dir=run_dir, project_root=project_root, manifest=manifest, cfg=cfg,
                        selection=selection)


# ============================================================================== bảng mô tả dữ liệu


def trace_variants(traces: list[Trace], top: int | None = None) -> pd.DataFrame:
    """Biến thể trace (chuỗi activity giống hệt): tần suất, độ dài và số ca theo trạng thái cuối."""
    groups: dict[tuple[str, ...], list[Trace]] = {}
    for trace in traces:
        groups.setdefault(tuple(trace.activities), []).append(trace)
    statuses = sorted({t.terminal_status for t in traces if t.terminal_status})
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), " → ".join(kv[0])))
    rows = []
    for index, (variant, members) in enumerate(ordered, start=1):
        row: dict[str, Any] = {
            "variant_id": f"V{index:02d}", "variant": " → ".join(variant), "length": len(variant),
            "n_cases": len(members), "share": len(members) / len(traces),
        }
        for status in statuses:
            row[status] = sum(t.terminal_status == status for t in members)
        rows.append(row)
    frame = pd.DataFrame(rows)
    return frame.head(top) if top else frame


def status_durations(events: pd.DataFrame) -> pd.DataFrame:
    """Thời gian lưu mỗi trạng thái = từ cập nhật status này đến cập nhật status KẾ TIẾP trong ca.

    Đoạn trước status đầu tiên chưa biết trạng thái nên không được tính; status cuối không bị gán
    thời lượng đến 'hiện tại'. Đây là thời gian lịch, không phải công sức xử lý.
    """
    status = events.loc[events["has_status_update"],
                        ["case_id", "status_value", "timestamp_utc"]].copy()
    status = status.sort_values(["case_id", "timestamp_utc"], kind="stable")
    grouped = status.groupby("case_id")
    status["next_status"] = grouped["status_value"].shift(-1)
    status["next_utc"] = grouped["timestamp_utc"].shift(-1)
    status = status.dropna(subset=["next_status"])
    return pd.DataFrame({
        "case_id": status["case_id"], "status": status["status_value"],
        "next_status": status["next_status"], "started_utc": status["timestamp_utc"],
        "seconds": (status["next_utc"] - status["timestamp_utc"]).dt.total_seconds(),
    }).reset_index(drop=True)


def create_to_terminal(events: pd.DataFrame, terminal_statuses: tuple[str, ...]) -> pd.DataFrame:
    """Thời gian từ event CREATE đến cập nhật status terminal CUỐI, riêng với thời gian lưu trạng thái.

    Ca không có CREATE hoặc không có status terminal bị bỏ qua (không suy diễn).
    """
    created = events.loc[events["activity"] == "CREATE"].groupby("case_id")["timestamp_utc"].min()
    terminal = events[events["has_status_update"] & events["status_value"].isin(terminal_statuses)]
    rows = []
    for case_id, part in terminal.groupby("case_id"):
        if case_id not in created.index:
            continue
        last = part.iloc[-1]
        rows.append({
            "case_id": case_id, "terminal_status": last["status_value"],
            "created_utc": created[case_id], "terminal_utc": last["timestamp_utc"],
            "seconds": (last["timestamp_utc"] - created[case_id]).total_seconds(),
            "n_terminal_updates": len(part),
        })
    return pd.DataFrame(rows, columns=["case_id", "terminal_status", "created_utc", "terminal_utc",
                                       "seconds", "n_terminal_updates"])


def dfg_edge_table(graph: nx.DiGraph, top: int = 20) -> pd.DataFrame:
    """Cạnh nặng nhất của DFG với xác suất thực nghiệm count/out (chưa làm mượt) và cờ self-loop."""
    rows = [{"source": u, "target": v, "weight": int(w),
             "probability": w / graph.nodes[u]["out_count"], "self_loop": u == v}
            for u, v, w in graph.edges(data="weight")]
    frame = pd.DataFrame(rows).sort_values(["weight", "source", "target"],
                                           ascending=[False, True, True], kind="stable")
    return frame.head(top).reset_index(drop=True)


def embedding_pca(
    matrix: np.ndarray, vocabulary: tuple[str, ...]
) -> tuple[pd.DataFrame, list[float]]:
    """Chiếu vector nút xuống 2D bằng PCA để minh họa; KHÔNG dùng để khẳng định hiệu quả detector."""
    if matrix.shape[0] < 2 or matrix.shape[1] < 2:
        raise ValueError(f"Cần ít nhất 2 nút và 2 chiều để PCA, nhận {matrix.shape}")
    pca = PCA(n_components=2, svd_solver="full").fit(matrix)
    coords = pca.transform(matrix)
    frame = pd.DataFrame({"node": list(vocabulary), "pc1": coords[:, 0], "pc2": coords[:, 1]})
    return frame, [float(x) for x in pca.explained_variance_ratio_]


def order_blindness_demo(bundle: DetectorBundle, trace: Trace, seed: int = 0) -> dict[str, Any]:
    """Hai chuỗi cùng histogram khác thứ tự: pooling giống hệt, đặc trưng chuyển tiếp thì khác.

    Hoán đổi một cặp activity kề nhau (mutation `swap_adjacent`) rồi so cột pooling và cột H bằng
    chính encoder đã fit trong bundle. Chỉ minh họa tính mù thứ tự của pooling.
    """
    encoder = bundle.encoder
    if encoder.embedding is None:
        raise ValueError(f"{bundle.method} không dùng embedding nên không có cột pooling để so")
    cfg = MutationConfig(types=("swap_adjacent",), max_per_type_per_parent=1,
                         validation_seed=seed, test_seed=seed, duplicate_block_max_length=1)
    swapped = generate_mutations([trace], cfg, seed).traces
    if not swapped:
        raise ValueError("Không hoán đổi được hai activity kề nhau khác nhau trong trace này")
    names = encoder.feature_names
    a, b = (encoder.transform([t]).values[0] for t in (trace, swapped[0]))
    pooled = [i for i, n in enumerate(names) if n.startswith(("emb_mean_", "emb_max_"))]
    h_rows = [{"feature": n, "original": float(a[i]), "swapped": float(b[i])}
              for i, n in enumerate(names) if not n.startswith(("emb_mean_", "emb_max_"))]
    scores = score_traces(bundle, [trace, swapped[0]])["anomaly_score"].tolist()
    return {
        "original": list(trace.activities), "swapped": list(swapped[0].activities),
        "pooled_max_abs_diff": float(np.max(np.abs(a[pooled] - b[pooled]))),
        "h_features": h_rows, "score_original": float(scores[0]), "score_swapped": float(scores[1]),
    }


def case_event_table(events: pd.DataFrame, trace: Trace) -> pd.DataFrame:
    """Mọi event (full view) của ca đánh dấu event nào còn trong core view và lý do bị bỏ."""
    part = events[events["case_id"] == trace.parent_case_id].reset_index(drop=True)
    in_core = part["event_id"].isin(set(trace.event_ids)).to_numpy()
    last_core = int(np.flatnonzero(in_core)[-1]) if in_core.any() else -1
    reasons = ["" if keep else ("post_terminal" if i > last_core else "noise_policy")
               for i, keep in enumerate(in_core)]
    table = part[["event_id", "source_row", "timestamp_utc", "role", "raw_action", "activity"]].copy()
    table["in_core"] = in_core
    table["dropped_reason"] = reasons
    return table


def run_macro_metrics(runs_dir: Path | str, run_ids: list[str], split: str = "test") -> pd.DataFrame:
    """Macro (trung bình theo loại mutation) AUROC/AP/paired win của MỖI run và phương pháp.

    Dùng để tính trung bình và độ lệch chuẩn của macro qua các model seed (std của macro, không phải
    trung bình các std theo loại). Loại có metric null bị bỏ khỏi trung bình; `n_types` ghi số loại dùng.
    """
    records = []
    for run_id in run_ids:
        table = pd.read_csv(Path(runs_dir) / run_id / "metrics_by_type.csv")
        table = table[table["split"] == split]
        for method, part in table.groupby("method", sort=True):
            scored = part.dropna(subset=["auroc"])
            records.append({
                "run_id": run_id, "method": method,
                "macro_auroc": float(scored["auroc"].mean()),
                "macro_average_precision": float(scored["average_precision"].mean()),
                "macro_paired_win_rate": float(scored["paired_win_rate"].mean()),
                "n_types": int(len(scored)),
            })
    return pd.DataFrame(records, columns=["run_id", "method", "macro_auroc",
                                          "macro_average_precision", "macro_paired_win_rate", "n_types"])



ABLATION_COLUMNS = [
    "experiment", "method", "split", "scope", "metric", "baseline_estimate", "experiment_estimate",
    "estimate", "ci_low", "ci_high", "prob_positive", "n_parents", "n_seeds", "confidence",
    "null_reason",
]


def ablation_vs_baseline(
    runs_dir: Path | str, groups: dict[str, list[str]], *, baseline: str, split: str,
    n_resamples: int, seed: int, confidence: float,
) -> pd.DataFrame:
    """Chênh lệch ghép cặp (thí nghiệm − baseline) của TỪNG phương pháp, kèm khoảng bootstrap theo parent.

    `groups` ánh xạ tên thí nghiệm sang các run (mỗi model seed một run) cùng protocol. Mọi run phải
    có đúng cùng tập (phương pháp, loại mutation, parent) với baseline, nếu không không ghép cặp được.
    Trong mỗi lần resample, số liệu của một thí nghiệm là trung bình qua các model seed của nó; bootstrap
    đo độ bất định do chọn ca, không coi model seed là mẫu độc lập. Dùng `split="validation"` để chọn và
    `split="test"` chỉ để mô tả độ nhạy khám phá.
    """
    runs_dir = Path(runs_dir)
    if baseline not in groups:
        raise ValueError(f"không có nhóm baseline {baseline!r} trong {sorted(groups)}")

    def load(run_id: str) -> pd.DataFrame:
        table = pd.read_csv(runs_dir / run_id / "paired_scores.csv")
        table = table[table["split"] == split]
        if table.empty:
            raise ValueError(f"run {run_id}: không có paired_scores cho split {split!r}")
        return table

    def signature(table: pd.DataFrame) -> frozenset:
        return frozenset(zip(table["method"], table["mutation_type"], table["parent_case_id"],
                             strict=True))

    base_tables = {rid: load(rid) for rid in groups[baseline]}
    reference = signature(next(iter(base_tables.values())))
    if any(signature(t) != reference for t in base_tables.values()):
        raise ValueError(f"baseline {baseline!r}: các run không cùng tập parent/phương pháp/loại")
    methods = sorted({m for m, _, _ in reference})

    records = []
    for name, run_ids in groups.items():
        if name == baseline:
            continue
        tables = {rid: load(rid) for rid in run_ids}
        if any(signature(t) != reference for t in tables.values()):
            raise ValueError(
                f"experiment {name!r}: không cùng tập parent/phương pháp/loại mutation với baseline "
                f"{baseline!r}; chỉ so được các run cùng protocol")
        frames, aggregate = [], {}
        for label, members in ((baseline, base_tables), (name, tables)):
            for method in methods:
                aggregate[f"{label}|{method}"] = [f"{label}|{method}|{rid}" for rid in members]
            frames += [t.assign(method=t["method"].map(lambda m, rid=rid, label=label:
                                                       f"{label}|{m}|{rid}"))
                       for rid, t in members.items()]
        result = bootstrap_by_parent(
            pd.concat(frames, ignore_index=True),
            methods=[member for members in aggregate.values() for member in members],
            n_resamples=n_resamples, seed=seed, confidence=confidence, aggregate=aggregate)
        intervals = bootstrap_intervals_frame(result).set_index(["method", "scope", "metric"])
        for row in bootstrap_differences_frame(result).itertuples():
            method = row.method_a.split("|", 1)[1]
            if row.method_a != f"{name}|{method}" or row.method_b != f"{baseline}|{method}":
                continue  # chỉ so mỗi phương pháp với chính nó
            records.append({
                "experiment": name, "method": method, "split": split, "scope": row.scope,
                "metric": row.metric,
                "baseline_estimate": float(intervals.loc[(row.method_b, row.scope, row.metric),
                                                         "estimate"]),
                "experiment_estimate": float(intervals.loc[(row.method_a, row.scope, row.metric),
                                                           "estimate"]),
                "estimate": row.estimate, "ci_low": row.ci_low, "ci_high": row.ci_high,
                "prob_positive": row.prob_positive, "n_parents": row.n_parents,
                "n_seeds": len(run_ids), "confidence": confidence, "null_reason": row.null_reason,
            })
    return pd.DataFrame(records, columns=ABLATION_COLUMNS)
