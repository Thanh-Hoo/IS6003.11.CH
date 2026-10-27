"""Ma trận thực nghiệm thành phần (spec §11, Task 8): mỗi thí nghiệm đổi một yếu tố so với baseline.

`configs/experiments.yaml` khai báo cấu hình gốc, các model seed và danh sách thí nghiệm. Mỗi cặp
(thí nghiệm, seed) là một run đầy đủ (`run_experiment`) có manifest ghi rõ thí nghiệm, thay đổi và
lệnh tái tạo. Không chạy tích Descartes; nhiều thay đổi một lúc phải có lý do ghi tường minh.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from jira_ad.config import (
    ConfigError,
    RunConfig,
    config_from_dict,
    load_config,
    resolve_project_root,
)
from jira_ad.pipeline import run_experiment

PLAN_REQUIRED = {"base", "model_seeds", "experiments"}
PLAN_KEYS = PLAN_REQUIRED | {"decision"}
DECISION_KEYS = {"primary_method", "selection_split", "family_alpha", "comparisons"}
SELECTION_SPLITS = ("validation",)  # chọn cấu hình chỉ trên validation (spec §5, §7)
BASELINE_NAME = "baseline"
EXPERIMENT_KEYS = {"name", "changes", "seeds", "note", "allow_multiple_changes"}


@dataclass(frozen=True)
class Experiment:
    name: str
    changes: dict[str, Any]
    seeds: tuple[int, ...]
    note: str = ""
    allow_multiple_changes: str | bool = False


@dataclass(frozen=True)
class DecisionRule:
    """Quy tắc quyết định KHÓA TRƯỚC khi chạy các so sánh chính (ghi trong `experiments.yaml`).

    Một thí nghiệm chỉ là "ứng viên cải thiện" nếu khoảng bootstrap theo parent của (thí nghiệm −
    baseline) về macro AUROC của `primary_method` trên `selection_split`, trung bình qua các model
    seed, nằm hoàn toàn trên 0. Mức tin cậy chia theo số so sánh (Bonferroni) để không tăng cơ hội
    dương tính giả. Dù kết quả thế nào, baseline vẫn là cấu hình ghi nhận.
    """

    primary_method: str
    selection_split: str
    family_alpha: float
    comparisons: tuple[str, ...]

    @property
    def confidence(self) -> float:
        return 1 - self.family_alpha / len(self.comparisons)


@dataclass(frozen=True)
class ExperimentPlan:
    path: Path
    base: RunConfig
    model_seeds: tuple[int, ...]
    experiments: tuple[Experiment, ...]
    decision: DecisionRule | None = None


@dataclass(frozen=True)
class PlanRun:
    experiment: str
    seed: int
    run_dir: Path


def _seeds(value: Any, where: str) -> tuple[int, ...]:
    if (not isinstance(value, list) or not value
            or not all(isinstance(s, int) and not isinstance(s, bool) for s in value)
            or len(set(value)) != len(value)):
        raise ConfigError(f"{where}: cần danh sách số nguyên không rỗng, không lặp, nhận {value!r}")
    return tuple(value)


def _apply(raw: dict[str, Any], changes: dict[str, Any], name: str) -> None:
    for dotted, value in changes.items():
        *parents, leaf = dotted.split(".")
        node = raw
        for part in parents:
            if not isinstance(node, dict) or part not in node:
                raise ConfigError(f"experiment {name!r}: khóa {dotted!r} không tồn tại trong cấu hình")
            node = node[part]
        if not isinstance(node, dict) or leaf not in node:
            raise ConfigError(f"experiment {name!r}: khóa {dotted!r} không tồn tại trong cấu hình")
        node[leaf] = value


def build_config(plan: ExperimentPlan, experiment: Experiment, seed: int) -> RunConfig:
    """Cấu hình của một run: baseline + đúng các thay đổi của thí nghiệm + model seed; baseline giữ nguyên."""
    raw = copy.deepcopy(plan.base.as_dict(include_defaults=True))  # đủ khóa tùy chọn để đổi được
    _apply(raw, experiment.changes, experiment.name)
    raw["run"]["seed"] = seed
    try:
        return config_from_dict(raw, plan.base.project_root, plan.path)
    except ConfigError as exc:
        raise ConfigError(f"experiment {experiment.name!r}: {exc}") from exc


def _decision(raw: Any, base: RunConfig, names: set[str]) -> DecisionRule:
    if not isinstance(raw, dict):
        raise ConfigError("decision: cần một ánh xạ (mapping)")
    extra = sorted(set(raw) - DECISION_KEYS)
    if extra:
        raise ConfigError(f"decision: khóa không hợp lệ {extra}; hợp lệ: {sorted(DECISION_KEYS)}")
    missing = sorted(DECISION_KEYS - set(raw))
    if missing:
        raise ConfigError(f"decision: thiếu khóa {missing}")
    method, split, alpha, comparisons = (raw[k] for k in (
        "primary_method", "selection_split", "family_alpha", "comparisons"))
    if method not in base.features.methods:
        raise ConfigError(
            f"decision.primary_method={method!r}: phải là một phương pháp của base "
            f"{list(base.features.methods)}")
    if split not in SELECTION_SPLITS:
        raise ConfigError(f"decision.selection_split={split!r}: chỉ chọn trên {SELECTION_SPLITS}")
    if isinstance(alpha, bool) or not isinstance(alpha, int | float) or not 0 < alpha < 1:
        raise ConfigError(f"decision.family_alpha={alpha!r}: cần số trong (0, 1)")
    if not isinstance(comparisons, list) or not comparisons:
        raise ConfigError("decision.comparisons: cần danh sách tên thí nghiệm không rỗng")
    if len(set(comparisons)) != len(comparisons):
        dup = sorted({c for c in comparisons if comparisons.count(c) > 1})
        raise ConfigError(f"decision.comparisons: tên bị lặp {dup}")
    for name in comparisons:
        if name == BASELINE_NAME:
            raise ConfigError("decision.comparisons: không so baseline với chính nó (baseline)")
        if name not in names:
            raise ConfigError(f"decision.comparisons: thí nghiệm {name!r} không có trong kế hoạch")
    return DecisionRule(method, split, float(alpha), tuple(comparisons))


def load_plan(path: Path) -> ExperimentPlan:
    """Đọc và kiểm tra nghiêm ngặt `experiments.yaml`; mọi thí nghiệm phải dựng được cấu hình hợp lệ."""
    path = Path(path).resolve()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Không đọc được {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: gốc phải là ánh xạ (mapping)")
    unknown = sorted(set(raw) - PLAN_KEYS)
    if unknown:
        raise ConfigError(f"{path}: khóa không hợp lệ {unknown}; hợp lệ: {sorted(PLAN_KEYS)}")
    missing = sorted(PLAN_REQUIRED - set(raw))
    if missing:
        raise ConfigError(f"{path}: thiếu khóa {missing}")
    base_name = raw["base"]
    if not isinstance(base_name, str) or Path(base_name).is_absolute():
        raise ConfigError(f"base {base_name!r}: cần đường dẫn tương đối repo root")
    base_path = (resolve_project_root(path) / base_name).resolve()
    if not base_path.is_file():
        raise ConfigError(f"base {base_name!r}: không tìm thấy file ({base_path})")
    base = load_config(base_path)
    model_seeds = _seeds(raw["model_seeds"], "model_seeds")
    if not isinstance(raw["experiments"], list) or not raw["experiments"]:
        raise ConfigError("experiments: cần danh sách không rỗng")
    experiments, names = [], set()
    for index, entry in enumerate(raw["experiments"]):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"]:
            raise ConfigError(f"experiments[{index}]: cần một ánh xạ có 'name'")
        name = entry["name"]
        extra = sorted(set(entry) - EXPERIMENT_KEYS)
        if extra:
            raise ConfigError(f"experiment {name!r}: khóa không hợp lệ {extra}")
        if name in names:
            raise ConfigError(f"experiment {name!r}: tên bị lặp lại")
        names.add(name)
        if not isinstance(entry.get("changes"), dict):
            raise ConfigError(f"experiment {name!r}: thiếu 'changes' (dùng {{}} cho baseline)")
        changes = entry["changes"]
        if "run.seed" in changes:
            raise ConfigError(
                f"experiment {name!r}: đặt model seed bằng model_seeds/seeds, không bằng changes"
            )
        allow = entry.get("allow_multiple_changes", False)
        if len(changes) > 1 and not allow:
            raise ConfigError(
                f"experiment {name!r}: đổi nhiều yếu tố một lúc ({sorted(changes)}); thêm "
                "allow_multiple_changes với lý do nếu thật sự cần (kế hoạch: từng yếu tố một)"
            )
        seeds = _seeds(entry["seeds"], f"experiment {name!r}.seeds") if "seeds" in entry else model_seeds
        experiment = Experiment(name, dict(changes), seeds, str(entry.get("note", "")), allow)
        experiments.append(experiment)
    decision = _decision(raw["decision"], base, names) if "decision" in raw else None
    plan = ExperimentPlan(path, base, model_seeds, tuple(experiments), decision)
    for experiment in plan.experiments:  # dựng thử: mọi thay đổi phải cho cấu hình hợp lệ
        build_config(plan, experiment, experiment.seeds[0])
    return plan


def run_plan(
    path: Path, only: list[str] | None = None, now: datetime | None = None
) -> list[PlanRun]:
    """Chạy lần lượt mọi (thí nghiệm, seed); `only` giới hạn theo tên (tên lạ là lỗi)."""
    plan = load_plan(path)
    known = {e.name for e in plan.experiments}
    unknown = sorted(set(only or []) - known)
    if unknown:
        raise ConfigError(f"Thí nghiệm không có trong kế hoạch: {unknown}; có: {sorted(known)}")
    plan_rel = plan.path.relative_to(plan.base.project_root).as_posix()
    results = []
    for experiment in plan.experiments:
        if only and experiment.name not in only:
            continue
        for seed in experiment.seeds:
            cfg = build_config(plan, experiment, seed)
            run_dir = run_experiment(
                cfg, now=now,
                experiment={"name": experiment.name, "plan": plan_rel, "changes": experiment.changes,
                            "note": experiment.note},
                rerun_command=f"uv run jira-ad experiments --config {plan_rel} --only {experiment.name}",
            )
            results.append(PlanRun(experiment.name, seed, run_dir))
    return results
