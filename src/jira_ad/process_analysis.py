"""Nạp run giai đoạn 2 (`outputs/process/<run>`) cho notebook, kèm nhận xét sinh từ số liệu.

Giống `analysis.open_run` (Ruling 44, 63): kiểm manifest `completed`, sha256 từng artifact và
`config_hash` dựng lại từ cấu hình lưu trong manifest. Thứ tự chọn run: đối số; biến môi trường
`JIRA_AD_PROCESS_RUN_DIR` (do bộ chạy notebook đặt); nếu không có, run hoàn tất mới nhất có
`config_hash` bằng `configs/process.yaml` hiện tại (mở tay trong VSCode/Jupyter không cần biến).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from jira_ad.analysis import NotebookInputError
from jira_ad.config import ConfigError
from jira_ad.process_config import hash_config_dict, load_process_config, process_config_hash

PROCESS_RUN_ENV = "JIRA_AD_PROCESS_RUN_DIR"
DEFAULT_PROCESS_CONFIG = Path("configs") / "process.yaml"
RUN_COMMAND = "uv run jira-ad process --config configs/process.yaml"
DAY = 86_400.0


def fmt(x: float, digits: int = 1, *, percent: bool = False) -> str:
    """Số kiểu Việt Nam: dấu chấm phân nghìn, dấu phẩy thập phân (vd 1.234,6; 16,7%)."""
    value = float(x) * (100 if percent else 1)
    text = f"{value:,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return text + ("%" if percent else "")


@dataclass(frozen=True)
class ProcessRun:
    run_dir: Path
    project_root: Path
    manifest: dict[str, Any]
    selection: str

    @property
    def run_id(self) -> str:
        return self.run_dir.name

    @property
    def config_hash(self) -> str:
        return self.manifest["config_hash"]

    def path(self, rel: str) -> Path:
        return self.run_dir / rel

    def csv(self, rel: str, **kwargs) -> pd.DataFrame:
        return pd.read_csv(self.path(rel), **kwargs)

    def json(self, rel: str) -> Any:
        return json.loads(self.path(rel).read_text(encoding="utf-8"))

    def show(self, fig) -> bytes:
        """Hiển thị Figure (không pyplot) dưới dạng PNG trong notebook; trả bytes PNG."""
        from io import BytesIO

        from IPython.display import Image, display

        buffer = BytesIO()
        fig.savefig(buffer, format="png", dpi=110)
        png = buffer.getvalue()
        display(Image(data=png))
        return png

    def header(self) -> str:
        return "\n".join([
            f"run: {self.run_dir.relative_to(self.project_root).as_posix()}",
            f"chọn run: {self.selection}",
            f"config: {self.manifest['config_path']}",
            f"config_hash: {self.config_hash}",
            f"code.sha256: {self.manifest.get('code', {}).get('sha256', '(không có)')}",
            f"tạo lúc (UTC): {self.manifest['created_utc']}",
            f"số artifact đã kiểm sha256: {len(self.manifest['files'])}",
        ])


def _project_root(start: Path) -> Path:
    for directory in (start, *start.parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    raise NotebookInputError(f"Không tìm thấy pyproject.toml đi lên từ {start}")


def _verify(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise NotebookInputError(f"{run_dir} không có manifest.json; chạy lại: {RUN_COMMAND}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "completed":
        raise NotebookInputError(
            f"Run {run_dir.name} có status {manifest.get('status')!r}, cần 'completed'; "
            f"chạy lại: {RUN_COMMAND}")
    for rel, digest in manifest["files"].items():
        path = run_dir / rel
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise NotebookInputError(f"Artifact {rel} của run {run_dir.name} thiếu hoặc đã bị sửa (sha256 "
                                     f"không khớp manifest); chạy lại: {RUN_COMMAND}")
    if hash_config_dict(manifest["config"]) != manifest["config_hash"]:
        raise NotebookInputError(f"config_hash của run {run_dir.name} không khớp cấu hình lưu trong manifest")
    return manifest


def _default_run(root: Path) -> Path:
    config = root / DEFAULT_PROCESS_CONFIG
    try:
        wanted = process_config_hash(load_process_config(config))
    except ConfigError as exc:
        raise NotebookInputError(
            f"Không nạp được {DEFAULT_PROCESS_CONFIG} để chọn run tự động: {exc}") from exc
    base = root / load_process_config(config).paths.output_root
    candidates = []
    for manifest_path in sorted(base.glob("*/manifest.json")) if base.is_dir() else []:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") == "completed" and manifest.get("config_hash") == wanted:
            candidates.append(manifest_path.parent)
    if not candidates:
        raise NotebookInputError(
            f"Chưa có run hoàn tất nào khớp {DEFAULT_PROCESS_CONFIG} hiện tại (config_hash {wanted[:8]}); "
            f"chạy: {RUN_COMMAND} (hoặc đặt {PROCESS_RUN_ENV}=<thư mục run>)")
    return candidates[-1]


def open_process_run(run_dir: Path | str | None = None) -> ProcessRun:
    if run_dir is not None:
        selection = "chỉ định trực tiếp"
    elif os.environ.get(PROCESS_RUN_ENV):
        run_dir, selection = os.environ[PROCESS_RUN_ENV], f"biến môi trường {PROCESS_RUN_ENV}"
    else:
        selection = f"tự động (run hoàn tất mới nhất khớp {DEFAULT_PROCESS_CONFIG.as_posix()})"
    root = _project_root(Path(run_dir).resolve() if run_dir is not None else Path.cwd().resolve())
    if run_dir is None:
        run_dir = _default_run(root)
    run_dir = Path(run_dir).resolve()
    return ProcessRun(run_dir, root, _verify(run_dir), selection)


# --------------------------------------------------------------------- nhận xét sinh từ số liệu


WIDE_RANGE_PP = 10.0  # khoảng PT rộng hơn 10 điểm phần trăm ⇒ kết luận phụ thuộc cách phân loại


def pt_range_verdict(lo: float, hi: float, *, main: float, sensitivity: float) -> str:
    """Câu kết luận về khoảng PT, suy ra từ độ rộng khoảng và chênh lệch giữa hai cách phân loại."""
    width = (hi - lo) * 100
    if width > WIDE_RANGE_PP:
        driver = ("cách xếp To Investigate" if abs(sensitivity - main) * 100 > WIDE_RANGE_PP / 2
                  else "cận trên do cập nhật bù")
        return f"khoảng rộng {fmt(width, 1)} điểm % ⇒ kết luận PT/WT phụ thuộc {driver}"
    return f"khoảng hẹp {fmt(width, 1)} điểm % ⇒ PT/WT ổn định trước các giả định phân loại"


def remarks_quant(run: ProcessRun, cohort: str = "bug") -> list[str]:
    """Nhận xét Chương 2 (B2) sinh hoàn toàn từ artifact của bước A."""
    d = f"a_quant/{cohort}"
    cases = run.csv(f"{d}/cases.csv")
    ranges = run.csv(f"{d}/pt_wt_ranges.csv")
    work = ranges[(ranges["clock"] == "work") & (ranges["branch"] == "all")].set_index("variant")
    q = run.json(f"{d}/fpy.json")
    little = run.json(f"{d}/little.json")
    rej = run.csv(f"{d}/rejected_cost.csv").set_index("group")
    gates = run.csv(f"{d}/gate_roles.csv")
    top = gates[gates["is_top_human"]].sort_values("n", ascending=False)
    by_branch = cases.groupby("terminal_status")["ct_work_s"].median() / DAY
    out = [
        f"{len(cases)} ca; CT trung vị {fmt(cases['ct_work_s'].median() / DAY, 1)} ngày làm việc "
        f"({fmt(cases['ct_cal_s'].median() / DAY, 1)} ngày lịch), "
        f"P90 {fmt(cases['ct_work_s'].quantile(0.9) / DAY, 1)} "
        "ngày làm việc; theo nhánh: "
        + ", ".join(f"{b} {fmt(v, 1)}" for b, v in by_branch.items()) + ".",
        f"Tỉ trọng PT (ngày làm việc) dao động {fmt(work['pt_share'].min(), 1, percent=True)}–"
        f"{fmt(work['pt_share'].max(), 1, percent=True)} giữa bốn biến thể; phương án chính "
        f"{fmt(work.loc['main', 'pt_share'], 1, percent=True)}, độ nhạy (To Investigate là làm) "
        f"{fmt(work.loc['sensitivity', 'pt_share'], 1, percent=True)}; "
        + pt_range_verdict(work["pt_share"].min(), work["pt_share"].max(), main=work.loc["main", "pt_share"],
                           sensitivity=work.loc["sensitivity", "pt_share"]) + ".",
        f"FPY strict {fmt(q['fpy_strict'], 3)}, adjusted {fmt(q['fpy_adjusted'], 3)} "
        f"({q['n_cases_rework']} ca có lùi/mở lại, {q['n_cases_rework_outside_backfill']} ca nếu bỏ lần lùi "
        "trong đợt bù).",
    ]
    if "all" in rej.index and rej.loc["all", "n_cases"] > 0:
        out.append(
            f"{int(rej.loc['all', 'n_cases'])} ca Rejected tiêu tốn "
            f"{fmt(rej.loc['all', 'issue_days_work'], 1)} ngày-issue làm việc; "
            f"{int(rej.loc['after_in_progress', 'n_cases'])} ca bị loại sau khi đã In Progress.")
    out.append(f"Little: λ = {fmt(little['lambda_per_day'], 3)} ca/ngày, "
               f"W = {fmt(little['W_days'], 1)} ngày, "
               f"L = {fmt(little['L_measured'], 1)} ca (đồng nhất thức); ca đến nửa đầu/nửa sau kỳ: "
               f"{little['arrivals_first_half']}/{little['arrivals_second_half']}.")
    if len(top):
        out.append("Vai trò cổng: " + "; ".join(
            f"{r.role} cho {r.target_state} ({fmt(r.share_of_target, 0, percent=True)})"
            for r in top.head(4).itertuples()) + ".")
    return out


def remarks_norms(run: ProcessRun) -> list[str]:
    """Nhận xét Chương 3 (B3) từ artifact của bước B."""
    pri = run.csv("b_norms/priorities.csv")
    roles = run.csv("b_norms/late_by_role.csv")
    cent = run.csv("b_norms/centrality_status.csv").sort_values("betweenness", ascending=False)
    human = roles[roles["is_human"]].sort_values("excess_days", ascending=False)
    out = []
    if len(pri):
        top = pri.iloc[0]
        out.append(f"Ưu tiên 1: {top.state} với {fmt(top.excess_days, 1)} ngày làm việc vượt định mức "
                   f"({fmt(top.share_of_excess, 0, percent=True)} tổng), "
                   f"định mức P75 {fmt(top.norm_days, 1)} "
                   f"ngày, vai trò cổng {top.gate_role}.")
        out.append("Thứ tự ưu tiên: " + " > ".join(pri["state"]) + ".")
    if len(human):
        r = human.iloc[0]
        out.append(f"Theo vai trò chuyển ra: {r.role} gắn với {fmt(r.excess_days, 1)} ngày vượt định mức "
                   f"qua {int(r.n_exits)} lần chuyển (mức vai trò, không đánh giá cá nhân).")
    non_human = roles[~roles["is_human"]]["excess_days"].sum()
    out.append("Phần không gán được vai trò người (bot/unknown/thiếu): "
               f"{fmt(non_human, 1)} ngày vượt định mức.")
    if len(cent):
        c = cent.iloc[0]
        out.append(f"Trạng thái trung gian nhất trên DFG: {c.node} (betweenness {fmt(c.betweenness, 3)}, "
                   f"PageRank {fmt(c.pagerank, 3)}).")
    return out


def remarks_conformance(run: ProcessRun) -> list[str]:
    """Nhận xét Chương 1 + 5 (B1, B5) từ artifact của bước C."""
    d = "c_conformance"
    quality = run.csv(f"{d}/discovery_quality.csv")
    best_fit = quality.sort_values(["fitness", "precision"], ascending=False).iloc[0]
    best_prec = quality.sort_values(["precision", "fitness"], ascending=False).iloc[0]
    out = [f"Khai phá: {best_fit.id} có fitness cao nhất ({fmt(best_fit.fitness, 3)}, precision "
           f"{fmt(best_fit.precision, 3)}); {best_prec.id} có precision cao nhất "
           f"({fmt(best_prec.precision, 3)}, "
           f"fitness {fmt(best_prec.fitness, 3)}) ⇒ không mô hình khai phá nào vừa khớp hết vừa chặt."]
    flags = run.csv(f"{d}/flag_summary.csv").sort_values("n_cases", ascending=False)
    top = flags.iloc[0]
    zero = list(flags.loc[flags["n_cases"] == 0, "label"])
    tail = f"; cờ 0 ca (tuân thủ ở điểm đó): {', '.join(zero)}." if zero else "; không cờ nào bằng 0."
    out.append(f"Cờ phổ biến nhất: {top.label} ({int(top.n_cases)} ca, "
               f"{fmt(top.share_cases, 1, percent=True)})" + tail)
    status = run.json(f"{d}/status.json")["reference_replay"]
    if not run.path(f"{d}/replay_summary.json").is_file():
        out.append(f"Replay mô hình chuẩn: {status}.")
        return out
    summary = run.json(f"{d}/replay_summary.json")
    allb = summary["by_branch"]["all"]
    out.append(f"Mô hình chuẩn: {allb['n_fit']}/{allb['n_cases']} ca khớp hoàn toàn "
               f"({fmt(allb['share_fit'], 1, percent=True)}), fitness trung bình theo ca "
               f"{fmt(allb['mean_trace_fitness'], 3)}; fitness token cao vì một token thiếu chỉ trừ ít "
               "điểm, nên "
               "chỉ số chính là tỉ lệ ca khớp hoàn toàn.")
    if "unfit" in summary and summary["unfit"]["n_cases"]:
        u = summary["unfit"]
        token = fmt(summary["model_quality"]["fitness"], 3)
        out.append(f"Vì sao fitness token ({token}) cao hơn tỉ lệ ca khớp: {u['n_cases']} ca không khớp "
                   f"vẫn có fitness trung bình {fmt(u['mean_trace_fitness'], 3)} "
                   f"(thấp nhất {fmt(u['min_trace_fitness'], 3)}), vì mỗi ca chỉ sai một vài bước nên chỉ "
                   "thiếu/thừa vài token trên tổng số token của cả chuỗi.")
    for branch in ("DONE", "Rejected"):
        if branch in summary["by_branch"]:
            b = summary["by_branch"][branch]
            out.append(f"Nhánh {branch}: {b['n_fit']}/{b['n_cases']} ca khớp "
                       f"({fmt(b['share_fit'], 1, percent=True)}).")
    comparison = run.csv(f"{d}/replay_comparison.csv").set_index("model")
    for model in comparison.index.drop("reference"):
        r = comparison.loc[model]
        out.append(f"Mô hình phụ {model} (KHÔNG phải mô hình chuẩn, ứng viên TO-BE): {int(r.n_fit)} ca khớp "
                   f"({fmt(r.share_fit, 1, percent=True)}), "
                   f"giải thích thêm {int(r.n_newly_fit_vs_reference)} ca.")
    unseen = run.csv(f"{d}/unobserved_arc_precision.csv")
    for r in unseen.itertuples():
        if pd.notna(r.precision_without):
            out.append(f"Cung {r.source} → {r.target} chưa từng xảy ra nhưng được giữ (Quyết định 8): "
                       f"precision {fmt(r.precision_with, 3)} (bỏ cung: {fmt(r.precision_without, 3)}), "
                       "fitness không đổi.")
    dev = run.csv(f"{d}/deviation_breakdown.csv")
    for r in dev[dev["branch"] == "all"].itertuples():
        out.append(f"{r.category}: {r.n_cases} ca, {r.n_occurrences} lần; "
                   f"{r.n_occ_in_burst} lần nằm trong đợt "
                   f"cập nhật bù; {r.n_cases_only_in_burst} ca chỉ lệch trong đợt bù.")
    return out


KPI_UNITS_PERCENT = {"pt_share_main", "conformance_share_fit"}


def remarks_bpr(run: ProcessRun) -> list[str]:
    """Nhận xét Chương 4 (B2 heuristics, B4) từ artifact của bước D; mọi số TO-BE gắn nhãn mục tiêu."""
    d = "d_bpr"
    checks = run.csv(f"{d}/checks.csv")
    out = [f"{r.candidate}: {r.verdict} — {r.evidence}." for r in checks.itertuples()]
    kpi = run.csv(f"{d}/kpi_asis_tobe.csv")
    for r in kpi.itertuples():
        pct = r.kpi in KPI_UNITS_PERCENT
        asis = fmt(r.asis, 1, percent=True) if pct else fmt(r.asis, 1)
        tobe = fmt(r.tobe, 1, percent=True) if pct else fmt(r.tobe, 1)
        out.append(f"{r.kpi}: AS-IS (đo) {asis} → TO-BE {tobe} ({r.tobe_label}; kịch bản {r.scenario}).")
    roles = run.csv(f"{d}/todo_excess_by_role.csv")
    human = roles[roles["is_human"]]
    if len(human) and roles["excess_days"].sum() > 0:
        top = human.iloc[0]
        verdict = checks.set_index("candidate")["verdict"].get("reduce_po_dependency")
        tail = (" dù phép kiểm theo trung vị không ủng hộ ⇒ dồn đọng nằm ở đuôi phân bố"
                if verdict == "không ủng hộ" else "")
        out.append("Mô tả bổ sung (không phải phán quyết): "
                   f"{fmt(top.share_of_state_excess, 1, percent=True)} số ngày vượt định mức ở To Do "
                   f"rơi vào lượt do {top.role} chuyển ra{tail}.")
    return out


def remarks_ranking(run: ProcessRun) -> list[str]:
    """Nhận xét Chương 6 (B6) từ artifact của bước E."""
    d = "e_ranking"
    status = run.json(f"{d}/status.json")
    out = [f"Biểu diễn: {status['representation']}."]
    if run.path(f"{d}/classify.csv").is_file():
        c = run.csv(f"{d}/classify.csv").set_index("representation")
        n2v, st, base = (c.loc[k, "accuracy"] for k in ("node2vec_v1", "structural", "majority_baseline"))
        better = "tốt hơn" if n2v > st else "không tốt hơn"
        out.append(f"Tìm lại nhóm nghiệp vụ của activity (1-NN): Node2Vec {fmt(n2v, 3)}, bậc + trung tâm "
                   f"{fmt(st, 3)}, baseline lớp phổ biến {fmt(base, 3)} ⇒ Node2Vec {better} "
                   "đặc trưng cấu trúc.")
        cl = run.csv(f"{d}/clusters.csv")
        best = cl.sort_values("nmi", ascending=False).iloc[0]
        sil = cl[cl.representation == "node2vec_v1"].silhouette.max()
        out.append(f"K-means: NMI cao nhất {fmt(best.nmi, 3)} ({best.representation}, K = {int(best.k)}); "
                   f"silhouette của Node2Vec tối đa {fmt(sil, 3)}"
                   + (" ⇒ cấu trúc cụm yếu." if sil < 0.25 else "."))
    out.append(f"Chiều M_markov: {status['markov']}.")
    corr = run.json(f"{d}/correlations.json")
    stab = run.json(f"{d}/stability.json")
    out.append(f"Top {corr['k']} ca (nên xem trước, không phải vi phạm): tỉ lệ Rejected "
               f"{fmt(corr['share_rejected_top'], 1, percent=True)} so với "
               f"{fmt(corr['share_rejected_all'], 1, percent=True)} toàn bộ; Spearman điểm–độ dài "
               f"{fmt(corr['spearman_score_vs_n_events'], 3)}.")
    if "spearman_markov_raw_vs_n_events" in corr:
        out.append("Khử độ dài: Spearman M_markov–độ dài từ "
                   f"{fmt(corr['spearman_markov_raw_vs_n_events'], 3)} "
                   f"xuống {fmt(corr['spearman_markov_adj_vs_n_events'], 3)}.")
    if stab["jaccard_low"] >= 0.5:
        level = "ổn định"
    elif stab["jaccard_mean"] >= 0.3:
        level = "chỉ ổn định vừa phải"
    else:
        level = "kém ổn định"
    out.append(f"Ổn định top-{stab['k']} qua bootstrap: Jaccard trung bình {fmt(stab['jaccard_mean'], 2)} "
               f"[{fmt(stab['jaccard_low'], 2)}; {fmt(stab['jaccard_high'], 2)}] ⇒ danh sách {level}.")
    if run.path(f"{d}/consensus.csv").is_file():
        cons = run.csv(f"{d}/consensus.csv")
        threshold = run.manifest["config"]["ranking"]["consensus_share"]
        chosen = list(cons.loc[cons["consensus"], "case_id"])
        out.append(f"Danh sách đồng thuận (nằm trong top ở >= {fmt(threshold, 0, percent=True)} số lần "
                   f"bootstrap): {len(chosen)} ca đồng thuận"
                   + (": " + ", ".join(chosen) if chosen else "") + ".")
    if "spearman_n_exceed_vs_n_events" in corr:
        near_zero = abs(corr["spearman_score_vs_n_events"]) < 0.1
        rho = fmt(corr["spearman_n_exceed_vs_n_events"], 3)
        tail = ("; điểm tổng gần như không tương quan vì phân vị trung bình được tính trong nhóm cùng độ dài."
                if near_zero else ".")
        out.append(f"Riêng số chiều vượt có Spearman {rho} với độ dài{tail}")
    return out
