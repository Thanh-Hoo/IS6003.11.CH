"""Cấu hình chạy: dataclass có kiểm tra khóa thừa/thiếu, kiểu và miền giá trị (spec §4.4, §8).

YAML giữ tham số nghiên cứu, đường dẫn và seed; quy tắc thuật toán nằm trong code. Mọi đường dẫn
trong YAML là tương đối so với repo root (thư mục chứa pyproject.toml gần nhất đi lên từ file
config), không chấp nhận đường dẫn tuyệt đối.
"""

from __future__ import annotations

import dataclasses
import hashlib
import types as pytypes
import typing
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml

COHORTS = ("bug", "story")
# A–D là V1. E/F/M là phương pháp cải tiến (2026-10-22), chỉ dùng khi YAML liệt kê.
FEATURE_METHODS = ("A_stats", "B_ngrams", "C_embedding", "D_hybrid",
                   "E_score_fusion", "F_edge_hybrid", "M_markov")
# Ba loại đầu là V1. `skip_status`, `multi_edit` chỉ dùng trong giao thức cross-validation cải tiến.
MUTATION_TYPES = ("swap_adjacent", "delete_internal", "duplicate_block", "skip_status", "multi_edit")
SPLIT_STRATEGIES = ("random", "temporal")
FRACTION_TOLERANCE = 1e-6


class ConfigError(ValueError):
    """Config sai khóa, kiểu hoặc giá trị; thông báo luôn nêu khóa lỗi."""


def _check_relative_path(name: str, value: str) -> None:
    if (
        not value
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or value.startswith("~")
    ):
        raise ConfigError(f"{name}={value!r}: không chấp nhận đường dẫn tuyệt đối (absolute)")
    if ".." in PurePosixPath(value.replace("\\", "/")).parts:
        raise ConfigError(f"{name}={value!r}: không được thoát khỏi repo root bằng '..'")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


@dataclass(frozen=True)
class ProjectConfig:
    output_root: str

    def __post_init__(self) -> None:
        _check_relative_path("project.output_root", self.output_root)


@dataclass(frozen=True)
class DataConfig:
    root: str
    files: dict[str, str]
    recursive_discovery: bool
    cohort: str
    # Số liệu tham chiếu trong spec §2, chỉ để audit báo sai khác; không phải kết quả pipeline.
    reference_counts: dict[str, dict[str, int]] | None = None

    def __post_init__(self) -> None:
        _check_relative_path("data.root", self.root)
        _require(bool(self.files), "data.files: cần ít nhất một file")
        for cohort, name in self.files.items():
            _require(cohort in COHORTS, f"data.files: cohort {cohort!r} không hỗ trợ {COHORTS}")
            _check_relative_path(f"data.files.{cohort}", name)
        _require(
            self.cohort in self.files,
            f"data.cohort={self.cohort!r} phải là một khóa của data.files {sorted(self.files)}",
        )
        for cohort, counts in (self.reference_counts or {}).items():
            _require(
                cohort in self.files,
                f"data.reference_counts: cohort {cohort!r} không có trong data.files",
            )
            _require(
                set(counts) == {"events", "issues"} and all(v >= 0 for v in counts.values()),
                f"data.reference_counts.{cohort}: cần đúng hai khóa events, issues (số >= 0)",
            )


@dataclass(frozen=True)
class PreprocessConfig:
    actions_file: str
    view: str
    terminal_statuses: tuple[str, ...]
    noise_policy: str
    # Đường dẫn tuyệt đối của actions_file, do load_config gán; không đọc từ YAML.
    actions_path: Path | None = field(default=None, metadata={"yaml": False})

    def __post_init__(self) -> None:
        _check_relative_path("preprocess.actions_file", self.actions_file)
        _require(self.view in ("core", "full"), f"preprocess.view={self.view!r}: core|full")
        _require(bool(self.terminal_statuses), "preprocess.terminal_statuses: không được rỗng")
        _require(
            self.noise_policy in ("drop_generic_external_link_updates", "keep_all"),
            f"preprocess.noise_policy={self.noise_policy!r}: "
            "drop_generic_external_link_updates|keep_all",
        )


@dataclass(frozen=True)
class SplitConfig:
    seed: int
    train_fraction: float
    validation_fraction: float
    test_fraction: float
    stratify: str
    # `random`: holdout ngẫu nhiên theo ca (V1). `temporal`: train = các ca kết thúc sớm nhất (mở rộng, §5.1).
    strategy: str = field(default="random", metadata={"omit_default": True})

    def __post_init__(self) -> None:
        fractions = (self.train_fraction, self.validation_fraction, self.test_fraction)
        _require(all(f > 0 for f in fractions), f"split: mỗi fraction phải > 0, nhận {fractions}")
        total = sum(fractions)
        _require(
            abs(total - 1.0) <= FRACTION_TOLERANCE,
            f"split: tổng train+validation+test phải bằng 1, nhận {total}",
        )
        _require(
            self.stratify in ("terminal_status", "none"),
            f"split.stratify={self.stratify!r}: terminal_status|none",
        )
        _require(
            self.strategy in SPLIT_STRATEGIES,
            f"split.strategy={self.strategy!r}: {'|'.join(SPLIT_STRATEGIES)}",
        )


@dataclass(frozen=True)
class GraphConfig:
    directed: bool
    encoding: str
    add_boundaries: bool
    transition_alpha: float

    def __post_init__(self) -> None:
        _require(
            self.encoding in ("activity", "activity_role"),
            f"graph.encoding={self.encoding!r}: activity|activity_role",
        )
        _require(self.transition_alpha > 0, "graph.transition_alpha phải > 0")


@dataclass(frozen=True)
class WalkConfig:
    p: float
    q: float
    length: int
    walks_per_node: int

    def __post_init__(self) -> None:
        _require(self.p > 0, "walk.p phải > 0")
        _require(self.q > 0, "walk.q phải > 0")
        _require(self.length >= 2, "walk.length phải >= 2")
        _require(self.walks_per_node >= 1, "walk.walks_per_node phải >= 1")


@dataclass(frozen=True)
class EmbeddingConfig:
    dimensions: int
    window: int
    epochs: int
    negative: int
    min_count: int
    sample: float
    workers: int

    def __post_init__(self) -> None:
        _require(self.dimensions >= 1, "embedding.dimensions phải >= 1")
        _require(self.window >= 1, "embedding.window phải >= 1")
        _require(self.epochs >= 1, "embedding.epochs phải >= 1")
        _require(self.negative >= 0, "embedding.negative phải >= 0")
        _require(self.min_count >= 1, "embedding.min_count phải >= 1")
        _require(self.sample >= 0, "embedding.sample phải >= 0")
        _require(self.workers >= 1, "embedding.workers phải >= 1")


@dataclass(frozen=True)
class FeatureConfig:
    methods: tuple[str, ...]
    include_time: bool
    # 0 = đặc trưng phụ thuộc đồ thị của train tính in-sample (V1). k >= 2: tính chéo k phần trên train.
    cross_fit_folds: int = field(default=0, metadata={"omit_default": True})

    def __post_init__(self) -> None:
        _require(
            self.cross_fit_folds == 0 or self.cross_fit_folds >= 2,
            f"features.cross_fit_folds={self.cross_fit_folds}: 0 (tắt) hoặc >= 2",
        )
        _require(bool(self.methods), "features.methods: không được rỗng")
        _require(len(set(self.methods)) == len(self.methods), "features.methods: có phần tử lặp")
        unknown = [m for m in self.methods if m not in FEATURE_METHODS]
        _require(not unknown, f"features.methods: {unknown} không thuộc {FEATURE_METHODS}")


@dataclass(frozen=True)
class DetectorConfig:
    n_estimators: int
    max_samples: str | int | float
    contamination: str | float
    n_jobs: int

    def __post_init__(self) -> None:
        _require(self.n_estimators >= 1, "detector.n_estimators phải >= 1")
        ms = self.max_samples
        _require(
            ms == "auto"
            or (isinstance(ms, int) and ms >= 1)
            or (isinstance(ms, float) and 0 < ms <= 1),
            f"detector.max_samples={ms!r}: 'auto', số nguyên >= 1 hoặc số thực trong (0, 1]",
        )
        c = self.contamination
        _require(
            c == "auto" or (isinstance(c, float) and 0 < c <= 0.5),
            f"detector.contamination={c!r}: 'auto' hoặc số thực trong (0, 0.5]",
        )
        _require(self.n_jobs >= 1, "detector.n_jobs phải >= 1")


@dataclass(frozen=True)
class MutationConfig:
    types: tuple[str, ...]
    max_per_type_per_parent: int
    validation_seed: int
    test_seed: int
    duplicate_block_max_length: int

    def __post_init__(self) -> None:
        unknown = [t for t in self.types if t not in MUTATION_TYPES]
        _require(not unknown, f"mutation.types: {unknown} không thuộc {MUTATION_TYPES}")
        _require(
            self.max_per_type_per_parent == 1,
            "mutation.max_per_type_per_parent: V1 chỉ hỗ trợ đúng 1 mutant mỗi loại cho mỗi parent",
        )
        _require(
            self.duplicate_block_max_length >= 1, "mutation.duplicate_block_max_length phải >= 1"
        )


@dataclass(frozen=True)
class EvaluationConfig:
    """Tham số báo cáo/kiểm tra bộ máy (không đổi mô hình); mọi khóa tùy chọn, vắng = mặc định."""

    bootstrap_resamples: int = field(default=2000, metadata={"omit_default": True})
    bootstrap_seed: int = field(default=20260, metadata={"omit_default": True})
    permutations: int = field(default=2000, metadata={"omit_default": True})
    confidence: float = field(default=0.95, metadata={"omit_default": True})
    # Seed của đối chứng dương (chỉ validation), nối tiếp 1042 (validation) và 2042 (test).
    positive_control_seed: int = field(default=3042, metadata={"omit_default": True})

    def __post_init__(self) -> None:
        _require(self.bootstrap_resamples >= 1, "evaluation.bootstrap_resamples phải >= 1")
        _require(self.permutations >= 1, "evaluation.permutations phải >= 1")
        _require(0 < self.confidence < 1, "evaluation.confidence phải nằm trong (0, 1)")


@dataclass(frozen=True)
class RunSettings:
    seed: int
    fail_on_existing_output: bool


@dataclass(frozen=True)
class NotebookConfig:
    timeout_seconds: int

    def __post_init__(self) -> None:
        _require(self.timeout_seconds >= 1, "notebooks.timeout_seconds phải >= 1")


SECTIONS: dict[str, type] = {
    "project": ProjectConfig,
    "data": DataConfig,
    "preprocess": PreprocessConfig,
    "split": SplitConfig,
    "graph": GraphConfig,
    "walk": WalkConfig,
    "embedding": EmbeddingConfig,
    "features": FeatureConfig,
    "detector": DetectorConfig,
    "mutation": MutationConfig,
    "evaluation": EvaluationConfig,
    "run": RunSettings,
    "notebooks": NotebookConfig,
}
# Section có thể vắng trong YAML (khi đó dùng mặc định) và không xuất hiện trong dạng đã resolve nếu
# mọi khóa còn mặc định: nhờ vậy cấu hình/run cũ giữ nguyên `config_hash`.
OPTIONAL_SECTIONS = frozenset({"evaluation"})


@dataclass(frozen=True)
class RunConfig:
    project: ProjectConfig
    data: DataConfig
    preprocess: PreprocessConfig
    split: SplitConfig
    graph: GraphConfig
    walk: WalkConfig
    embedding: EmbeddingConfig
    features: FeatureConfig
    detector: DetectorConfig
    mutation: MutationConfig
    evaluation: EvaluationConfig
    run: RunSettings
    notebooks: NotebookConfig
    project_root: Path
    config_path: Path

    def __post_init__(self) -> None:
        _require(
            not (self.features.include_time and self.mutation.types),
            "features.include_time=true bị từ chối: mutant cấu trúc V1 không có timestamp "
            "(thời gian chỉ dùng cho EDA)",
        )

    def resolve(self, relative: str | Path) -> Path:
        """Ghép đường dẫn tương đối trong YAML với repo root."""
        return self.project_root / relative

    @property
    def output_dir(self) -> Path:
        return self.resolve(self.project.output_root)

    def as_dict(self, include_defaults: bool = False) -> dict[str, Any]:
        """Các section YAML thành dict thuần (để ghi config.resolved.yaml, băm...).

        Mặc định bỏ khóa tùy chọn còn giá trị mặc định (và section tùy chọn rỗng) để cấu hình cũ giữ
        nguyên hash; `include_defaults=True` liệt kê đủ mọi khóa (để áp thay đổi thí nghiệm).
        """
        out = {}
        for name in SECTIONS:
            plain = _plain(getattr(self, name), include_defaults)
            if name in OPTIONAL_SECTIONS and not plain:
                continue
            out[name] = plain
        return out


def config_hash(cfg: RunConfig) -> str:
    """SHA-256 của cấu hình đã resolve; bỏ cờ vận hành `fail_on_existing_output`."""
    payload = cfg.as_dict()
    payload["run"] = {k: v for k, v in payload["run"].items() if k != "fail_on_existing_output"}
    text = yaml.safe_dump(payload, sort_keys=True, allow_unicode=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _yaml_fields(cls: type) -> list[dataclasses.Field]:
    """Các field đến từ YAML (bỏ field do loader gán như actions_path)."""
    return [f for f in dataclasses.fields(cls) if f.metadata.get("yaml", True)]


def _plain(value: Any, include_defaults: bool = True) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _plain(getattr(value, f.name), include_defaults)
            for f in _yaml_fields(type(value))
            if include_defaults
            or not (f.metadata.get("omit_default") and getattr(value, f.name) == f.default)
        }
    if isinstance(value, tuple):
        return [_plain(v, include_defaults) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v, include_defaults) for k, v in value.items()}
    return value


def _coerce(value: Any, tp: Any, path: str) -> Any:
    """Kiểm tra `value` theo annotation `tp`; int được nhận cho float, bool không phải int."""
    origin = typing.get_origin(tp)
    if origin in (typing.Union, pytypes.UnionType):
        for member in typing.get_args(tp):
            try:
                return _coerce(value, member, path)
            except ConfigError:
                continue
        raise ConfigError(f"{path}: giá trị {value!r} không khớp kiểu nào trong {tp}")
    if tp is type(None):
        if value is None:
            return None
        raise ConfigError(f"{path}: kỳ vọng null, nhận {value!r}")
    if tp is bool:
        if isinstance(value, bool):
            return value
    elif tp is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    elif tp is float:
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    elif tp is str:
        if isinstance(value, str):
            return value
    elif origin is tuple:
        if isinstance(value, list | tuple):
            item_type = typing.get_args(tp)[0]
            return tuple(_coerce(v, item_type, f"{path}[{i}]") for i, v in enumerate(value))
    elif origin is dict:
        if isinstance(value, dict):
            key_type, val_type = typing.get_args(tp)
            return {
                _coerce(k, key_type, f"{path}.<khóa>"): _coerce(v, val_type, f"{path}.{k}")
                for k, v in value.items()
            }
    else:  # pragma: no cover - lỗi lập trình, không phải lỗi của người dùng config
        raise TypeError(f"Annotation chưa được hỗ trợ ở {path}: {tp}")
    raise ConfigError(f"{path}: kiểu không hợp lệ, nhận {type(value).__name__} ({value!r})")


def _build(cls: type, data: Any, path: str) -> Any:
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: cần một ánh xạ (mapping), nhận {type(data).__name__}")
    fields = _yaml_fields(cls)
    names = {f.name for f in fields}
    unknown = sorted(str(k) for k in set(data) - names)
    if unknown:
        raise ConfigError(f"{path}: khóa không hợp lệ {unknown}; hợp lệ: {sorted(names)}")
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in fields:
        key_path = f"{path}.{f.name}"
        if f.name not in data:
            if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
                raise ConfigError(f"{key_path}: thiếu khóa bắt buộc")
            continue
        kwargs[f.name] = _coerce(data[f.name], hints[f.name], key_path)
    return cls(**kwargs)


def resolve_project_root(config_path: Path) -> Path:
    """Repo root = thư mục gần nhất chứa pyproject.toml, đi lên từ vị trí file config."""
    start = Path(config_path).resolve().parent
    for directory in (start, *start.parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    raise ConfigError(f"Không tìm thấy pyproject.toml đi lên từ {config_path}")


def config_from_dict(raw: Any, project_root: Path, config_path: Path) -> RunConfig:
    """Dựng RunConfig từ dict đã parse (nghiêm ngặt như đọc file); `project_root` do người gọi cấp.

    Dùng để dựng lại đúng cấu hình đã resolve của một run (`config.resolved.yaml`).
    """
    source = str(config_path)
    if not isinstance(raw, dict):
        raise ConfigError(f"Config {source}: gốc phải là một ánh xạ (mapping)")
    unknown = sorted(str(k) for k in set(raw) - set(SECTIONS))
    if unknown:
        raise ConfigError(
            f"Config {source}: section không hợp lệ {unknown}; hợp lệ: {list(SECTIONS)}"
        )
    missing = [name for name in SECTIONS if name not in raw and name not in OPTIONAL_SECTIONS]
    if missing:
        raise ConfigError(f"Config {source}: thiếu section {missing}")
    sections = {
        name: _build(cls, raw.get(name, {}) if name in OPTIONAL_SECTIONS else raw[name], name)
        for name, cls in SECTIONS.items()
    }
    preprocess = sections["preprocess"]
    sections["preprocess"] = dataclasses.replace(
        preprocess, actions_path=project_root / preprocess.actions_file
    )
    return RunConfig(**sections, project_root=project_root, config_path=Path(config_path))


def load_config(path: Path) -> RunConfig:
    """Đọc YAML, kiểm tra nghiêm ngặt và trả RunConfig đã gắn project_root."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Không đọc được config {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config {path} không phải YAML hợp lệ: {exc}") from exc
    return config_from_dict(raw, resolve_project_root(path), path.resolve())
