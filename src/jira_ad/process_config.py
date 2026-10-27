"""Cấu hình giai đoạn 2 (`configs/process.yaml`): phân tích, kiểm định và tái thiết kế quy trình.

Cùng phong cách với `config.py`: dataclass có kiểm khóa thừa/thiếu, kiểu và miền giá trị; đường dẫn
tương đối repo root. Cấu hình giai đoạn 1 (`paths.base_config`) chỉ được đọc, không bị sửa.
"""

from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from jira_ad.config import (
    COHORTS,
    ConfigError,
    _build,
    _check_relative_path,
    _plain,
    _require,
    resolve_project_root,
)

CALENDARS = ("local", "utc")
FLAG_KINDS = ("missing_before", "first_status_is", "after", "leaves", "enters_from_status",
              "enters_not_from", "backfill")
MINERS = ("alpha", "heuristics", "inductive")
BPR_CANDIDATES = ("early_triage", "auto_transition", "merge_investigated", "reduce_po_dependency",
                  "early_duplicate_detection", "add_investigating_state", "fast_track")
KPI_NAMES = ("ct_work_median_days", "ct_work_p90_days", "rejected_issue_days_work", "pt_share_main",
             "status_changes_per_case", "conformance_share_fit", "ct_work_median_days_upper",
             "rejected_issue_days_work_upper")


@dataclass(frozen=True)
class PathsConfig:
    base_config: str
    output_root: str
    v1_run: str
    improvement_dir: str

    def __post_init__(self) -> None:
        for f in dataclasses.fields(self):
            _check_relative_path(f"paths.{f.name}", getattr(self, f.name))


@dataclass(frozen=True)
class CalendarConfig:
    workdays: tuple[int, ...]
    primary: str

    def __post_init__(self) -> None:
        _require(
            bool(self.workdays) and all(0 <= d <= 6 for d in self.workdays)
            and len(set(self.workdays)) == len(self.workdays),
            f"calendar.workdays={list(self.workdays)}: các số 0..6 (Thứ Hai = 0), không trùng",
        )
        _require(self.primary in CALENDARS, f"calendar.primary={self.primary!r}: {CALENDARS}")


@dataclass(frozen=True)
class BackfillConfig:
    threshold_seconds: float

    def __post_init__(self) -> None:
        _require(self.threshold_seconds > 0, "backfill.threshold_seconds phải > 0")


@dataclass(frozen=True)
class StatesConfig:
    order: tuple[str, ...]
    work: tuple[str, ...]
    wait: tuple[str, ...]
    terminal: tuple[str, ...]
    sensitivity_work: tuple[str, ...]

    def __post_init__(self) -> None:
        _require(len(set(self.order)) == len(self.order), "states.order có trạng thái trùng")
        overlap = sorted(set(self.work) & set(self.wait))
        _require(not overlap, f"states: trạng thái vừa là work vừa là wait: {overlap}")
        _require(bool(self.terminal), "states.terminal: cần ít nhất một trạng thái kết thúc")
        for name in ("work", "wait", "sensitivity_work"):
            stray = sorted(set(getattr(self, name)) & set(self.terminal))
            _require(not stray, f"states.{name} chứa trạng thái kết thúc {stray}")
        missing = sorted((set(self.work) | set(self.wait)) - set(self.order))
        _require(not missing, f"states.order thiếu trạng thái {missing}")


@dataclass(frozen=True)
class NormsConfig:
    percentile: float
    min_visits: int
    explicit_days: dict[str, float]

    def __post_init__(self) -> None:
        _require(0 < self.percentile < 1, f"norms.percentile={self.percentile}: trong (0, 1)")
        _require(self.min_visits >= 1, "norms.min_visits phải >= 1")
        bad = sorted(k for k, v in self.explicit_days.items() if v <= 0)
        _require(not bad, f"norms.explicit_days: định mức phải > 0 ở {bad}")


@dataclass(frozen=True)
class CentralityConfig:
    pagerank_alpha: float
    top_late: int
    example_cases: int

    def __post_init__(self) -> None:
        _require(0 < self.pagerank_alpha < 1, f"centrality.pagerank_alpha={self.pagerank_alpha}: (0, 1)")
        _require(self.top_late >= 1 and self.example_cases >= 1,
                 "centrality.top_late và centrality.example_cases phải >= 1")


@dataclass(frozen=True)
class ReferenceModelConfig:
    """Mô hình chuẩn (giả định của tác giả); `approved` chỉ bật sau khi người dùng duyệt (điểm dừng 2)."""

    approved: bool
    start: str
    ends: tuple[str, ...]
    arcs: tuple[str, ...]


@dataclass(frozen=True)
class FlagRule:
    """Cờ quy tắc: chỉ đếm số lần xảy ra, không kết luận lỗi (Quyết định 4)."""

    id: str
    label: str
    kind: str
    states: tuple[str, ...]
    other_states: tuple[str, ...]

    def __post_init__(self) -> None:
        _require(self.kind in FLAG_KINDS, f"Cờ {self.id!r}: kind {self.kind!r} không hỗ trợ {FLAG_KINDS}")


@dataclass(frozen=True)
class MinerConfig:
    id: str
    miner: str
    params: dict[str, float]

    def __post_init__(self) -> None:
        _require(self.miner in MINERS, f"discovery {self.id!r}: miner {self.miner!r} không hỗ trợ {MINERS}")


@dataclass(frozen=True)
class AlternativeModel:
    """Mô hình phụ = mô hình chuẩn + cung thêm; KHÔNG phải mô hình chuẩn (vd ứng viên TO-BE, Quyết định 8)."""

    id: str
    label: str
    extra_arcs: tuple[str, ...]


@dataclass(frozen=True)
class DeviationReportConfig:
    arcs: tuple[str, ...]  # các cung sai lệch báo chi tiết theo nhánh và cập nhật bù


@dataclass(frozen=True)
class BprConfig:
    """Ngưỡng kiểm chứng ứng viên BPR, khóa trước khi tính phán quyết (Task 22)."""

    early_triage_min_share: float
    early_triage_min_median_days: float
    auto_transition_min_share: float
    merge_max_days: float
    merge_min_share: float
    po_state: str
    duplicate_pattern: str
    duplicate_min_cases: int
    duplicate_min_median_days: float
    investigating_min_width_pp: float
    fast_track_max_fpy_drop: float
    bootstrap_n: int
    seed: int

    def __post_init__(self) -> None:
        for name in ("early_triage_min_share", "auto_transition_min_share", "merge_min_share"):
            _require(0 < getattr(self, name) <= 1, f"bpr.{name} phải trong (0, 1]")
        _require(self.bootstrap_n >= 100, "bpr.bootstrap_n phải >= 100")


@dataclass(frozen=True)
class CandidateConfig:
    id: str
    problem: str
    heuristic: str

    def __post_init__(self) -> None:
        _require(self.id in BPR_CANDIDATES,
                 f"bpr_candidates: {self.id!r} không có phép kiểm chứng {BPR_CANDIDATES}")


@dataclass(frozen=True)
class TobeModelConfig:
    """Mô hình TO-BE (thiết kế, không phải kết quả đo); lane là đề xuất, cung tự động được đánh dấu."""

    start: str
    ends: tuple[str, ...]
    arcs: tuple[str, ...]
    automated_arcs: tuple[str, ...]
    lanes: dict[str, str]

    def __post_init__(self) -> None:
        stray = sorted(set(self.automated_arcs) - set(self.arcs))
        _require(not stray, f"tobe_model.automated_arcs không thuộc arcs: {stray}")


@dataclass(frozen=True)
class PilotPhase:
    id: str
    weeks: str
    action: str
    kpis: tuple[str, ...]

    def __post_init__(self) -> None:
        bad = sorted(set(self.kpis) - set(KPI_NAMES))
        _require(not bad, f"pilot {self.id!r}: KPI không định nghĩa {bad}; hợp lệ {KPI_NAMES}")


@dataclass(frozen=True)
class RankingConfig:
    """Tham số học biểu diễn + xếp hạng (Task 23), khóa trước khi tính."""

    oof_method: str
    k_min: int
    k_max: int
    seed: int
    top_share: float
    peer_percentile: float
    length_bins: int
    n_boot: int
    consensus_share: float
    blind_top: int
    blind_random: int
    assignee_activities: tuple[str, ...]
    activity_groups: dict[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        _require(2 <= self.k_min <= self.k_max, "ranking: cần 2 <= k_min <= k_max")
        _require(0 < self.top_share < 1 and 0 < self.peer_percentile < 1,
                 "ranking.top_share và ranking.peer_percentile phải trong (0, 1)")
        _require(self.length_bins in (2, 3), "ranking.length_bins phải là 2 hoặc 3")
        seen: dict[str, str] = {}
        for group, acts in self.activity_groups.items():
            for act in acts:
                _require(act not in seen,
                         f"ranking.activity_groups: {act!r} thuộc cả {seen.get(act)} và {group}")
                seen[act] = group


LIST_SECTIONS: dict[str, type] = {"flags": FlagRule, "discovery": MinerConfig,
                                  "alternative_models": AlternativeModel, "bpr_candidates": CandidateConfig,
                                  "pilot": PilotPhase}

SECTIONS: dict[str, type] = {
    "paths": PathsConfig,
    "calendar": CalendarConfig,
    "backfill": BackfillConfig,
    "states": StatesConfig,
    "norms": NormsConfig,
    "centrality": CentralityConfig,
    "reference_model": ReferenceModelConfig,
    "deviation_report": DeviationReportConfig,
    "bpr": BprConfig,
    "tobe_model": TobeModelConfig,
    "ranking": RankingConfig,
}


@dataclass(frozen=True)
class ProcessConfig:
    paths: PathsConfig
    cohorts: tuple[str, ...]
    calendar: CalendarConfig
    backfill: BackfillConfig
    states: StatesConfig
    norms: NormsConfig
    centrality: CentralityConfig
    reference_model: ReferenceModelConfig
    deviation_report: DeviationReportConfig
    bpr: BprConfig
    tobe_model: TobeModelConfig
    ranking: RankingConfig
    flags: tuple[FlagRule, ...]
    discovery: tuple[MinerConfig, ...]
    alternative_models: tuple[AlternativeModel, ...]
    bpr_candidates: tuple[CandidateConfig, ...]
    pilot: tuple[PilotPhase, ...]
    project_root: Path
    config_path: Path

    def __post_init__(self) -> None:
        _require(bool(self.cohorts), "cohorts: cần ít nhất một cohort")
        for cohort in self.cohorts:
            _require(cohort in COHORTS, f"cohorts: {cohort!r} không hỗ trợ {COHORTS}")

    @property
    def primary_cohort(self) -> str:
        """Cohort chính của đồ án (phần tử đầu); các cohort sau chỉ đặt cạnh, không trộn."""
        return self.cohorts[0]

    def resolve(self, relative: str | Path) -> Path:
        return self.project_root / relative

    @property
    def reference(self):
        """Mô hình chuẩn đã kiểm (`conformance.ReferenceModel`)."""
        from jira_ad.conformance import ReferenceModel

        rm = self.reference_model
        return ReferenceModel.from_strings(rm.arcs, start=rm.start, ends=rm.ends)

    @property
    def tobe(self):
        """Mô hình TO-BE đã kiểm (`conformance.ReferenceModel`)."""
        from jira_ad.conformance import ReferenceModel

        tm = self.tobe_model
        return ReferenceModel.from_strings(tm.arcs, start=tm.start, ends=tm.ends)

    def alternative(self, model_id: str):
        """Mô hình phụ theo id: mô hình chuẩn + `extra_arcs`."""
        spec = next(m for m in self.alternative_models if m.id == model_id)
        return self.reference.with_extra_arcs(spec.extra_arcs)

    def as_dict(self) -> dict[str, Any]:
        out = {name: _plain(getattr(self, name)) for name in SECTIONS}
        out.update({name: [_plain(x) for x in getattr(self, name)] for name in LIST_SECTIONS})
        out["cohorts"] = list(self.cohorts)
        return out


def _build_list(cls: type, raw: Any, name: str) -> tuple:
    _require(isinstance(raw, list), f"{name}: cần một danh sách")
    items = tuple(_build(cls, item, f"{name}[{i}]") for i, item in enumerate(raw))
    ids = [x.id for x in items]
    dup = sorted({x for x in ids if ids.count(x) > 1})
    _require(not dup, f"{name}: id trùng {dup}")
    return items


def hash_config_dict(payload: dict[str, Any]) -> str:
    """sha256 của cấu hình dạng dict (cùng phép băm dùng khi chạy, để kiểm lại từ manifest)."""
    text = yaml.safe_dump(payload, sort_keys=True, allow_unicode=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def process_config_hash(cfg: ProcessConfig) -> str:
    return hash_config_dict(cfg.as_dict())


def load_process_config(path: Path) -> ProcessConfig:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Không đọc được config {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config {path} không phải YAML hợp lệ: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Config {path}: gốc phải là một ánh xạ (mapping)")
    allowed = {*SECTIONS, *LIST_SECTIONS, "cohorts"}
    unknown = sorted(str(k) for k in set(raw) - allowed)
    _require(not unknown, f"Config {path}: section không hợp lệ {unknown}; hợp lệ: {sorted(allowed)}")
    missing = sorted(allowed - set(raw))
    _require(not missing, f"Config {path}: thiếu section {missing}")
    cohorts = raw["cohorts"]
    _require(isinstance(cohorts, list) and all(isinstance(c, str) for c in cohorts),
             "cohorts: cần danh sách tên cohort")
    sections = {name: _build(cls, raw[name], name) for name, cls in SECTIONS.items()}
    sections.update({name: _build_list(cls, raw[name], name) for name, cls in LIST_SECTIONS.items()})
    cfg = ProcessConfig(**sections, cohorts=tuple(cohorts),
                        project_root=resolve_project_root(path), config_path=path.resolve())
    try:
        cfg.reference  # noqa: B018 - kiểm mô hình chuẩn ngay khi nạp
        for model in cfg.alternative_models:
            cfg.alternative(model.id)
        type(cfg.reference).parse_arcs(cfg.deviation_report.arcs)
        cfg.tobe  # noqa: B018
    except ValueError as exc:
        raise ConfigError(f"reference_model/alternative_models/deviation_report/tobe_model: {exc}") from exc
    return cfg
