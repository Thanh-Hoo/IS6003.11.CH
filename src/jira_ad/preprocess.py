"""Chuẩn hóa event Jira, quy tắc action, core view và dựng trace (spec §4.1–4.3).

Quy tắc ánh xạ nằm trong `configs/actions.yaml`; module này chỉ diễn giải chúng. Mọi bước chỉ
dựa trên dữ liệu của chính từng issue (không có thống kê học từ nhiều issue), nên không có rủi ro
rò rỉ train/test ở đây; việc chia train/validation/test nằm ở `splits.py`.
"""

from __future__ import annotations

import hashlib
import re
import string
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from jira_ad.config import PreprocessConfig
from jira_ad.types import MISSING_ROLE, UNKNOWN_ROLE, Trace

SORT_KEYS = ["case_id", "timestamp_utc", "source_row"]
RULE_KEYS = {"name", "match", "activity"}
TOP_KEYS = {
    "version", "missing_role", "bot_roles", "fallback_activity", "clause_separator",
    "noise_policies", "rules",
}
TEMPLATE_FIELDS = {"verb", "field", "status"}
FALLBACK_RULE = "fallback"


class ActionRulesError(ValueError):
    """Quy tắc action sai cấu trúc, sai regex hoặc không đủ cho cấu hình đang chạy."""


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    activity: str  # mẫu, có thể chứa {verb} {field} {status}


@dataclass(frozen=True)
class ActionRules:
    """Quy tắc đã nạp. `text` giữ nguyên nội dung YAML để bundle lưu nội dung, không chỉ path."""

    version: int
    missing_role: str
    bot_roles: frozenset[str]
    fallback_activity: str
    separator: re.Pattern[str]
    noise_policies: dict[str, frozenset[str]]
    rules: tuple[Rule, ...]
    sha256: str
    text: str


@dataclass(frozen=True)
class ActionInfo:
    """Kết quả phân loại một chuỗi action thô."""

    activity: str
    rule: str
    secondary: tuple[str, ...]
    status_value: str | None
    is_fallback: bool


@dataclass
class CoreView:
    traces: list[Trace]
    case_exclusions: pd.DataFrame
    event_exclusions: pd.DataFrame
    audit: dict[str, Any]


# ------------------------------------------------------------------------------- nạp quy tắc


def _fail(message: str) -> ActionRulesError:
    return ActionRulesError(message)


def _expect(value: Any, kind: type, where: str) -> Any:
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise _fail(f"{where}: cần {kind.__name__}, nhận {type(value).__name__}")
    return value


def _compile(pattern: str, where: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise _fail(f"{where}: regex không hợp lệ ({exc}): {pattern!r}") from exc


def load_action_rules(path: Path) -> ActionRules:
    """Nạp và kiểm tra `actions.yaml` từ file; băm SHA-256 theo byte file (action_rules_hash)."""
    path = Path(path)
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise _fail(f"Không đọc được file quy tắc {path}: {exc}") from exc
    return parse_action_rules(raw_bytes, str(path))


def parse_action_rules(content: bytes | str, source: str) -> ActionRules:
    """Phân tích quy tắc từ nội dung (file hoặc chuỗi lưu trong bundle); băm theo byte nội dung."""
    raw_bytes = content.encode("utf-8") if isinstance(content, str) else content
    path = source
    try:
        data = yaml.safe_load(raw_bytes)
    except yaml.YAMLError as exc:
        raise _fail(f"{path}: không phải YAML hợp lệ: {exc}") from exc
    if not isinstance(data, dict):
        raise _fail(f"{path}: gốc phải là ánh xạ (mapping)")
    unknown = sorted(set(data) - TOP_KEYS)
    if unknown:
        raise _fail(f"{path}: khóa không hợp lệ {unknown}; hợp lệ: {sorted(TOP_KEYS)}")
    missing = sorted(TOP_KEYS - set(data))
    if missing:
        raise _fail(f"{path}: thiếu khóa {missing}")

    version = _expect(data["version"], int, "version")
    missing_role = _expect(data["missing_role"], str, "missing_role")
    if missing_role != MISSING_ROLE:
        raise _fail(
            f"missing_role={missing_role!r}: phải là {MISSING_ROLE!r} "
            "(hằng số của giao thức mà features.py dựa vào)"
        )
    fallback = _expect(data["fallback_activity"], str, "fallback_activity")
    bot_roles = frozenset(_expect(r, str, "bot_roles[]") for r in _expect(
        data["bot_roles"], list, "bot_roles"))
    separator = _compile(_expect(data["clause_separator"], str, "clause_separator"),
                         "clause_separator")
    noise_policies = {
        _expect(name, str, "noise_policies"): frozenset(
            _expect(a, str, f"noise_policies.{name}[]") for a in _expect(
                activities, list, f"noise_policies.{name}")
        )
        for name, activities in _expect(data["noise_policies"], dict, "noise_policies").items()
    }

    rules, seen = [], set()
    raw_rules = _expect(data["rules"], list, "rules")
    if not raw_rules:
        raise _fail("rules: không được rỗng")
    for index, entry in enumerate(raw_rules):
        _expect(entry, dict, f"rules[{index}]")
        if set(entry) != RULE_KEYS:
            raise _fail(
                f"rules[{index}]: cần đúng các khóa {sorted(RULE_KEYS)}, nhận {sorted(entry)}"
            )
        name = _expect(entry["name"], str, f"rules[{index}].name")
        if name in seen:
            raise _fail(f"rules: tên quy tắc lặp lại: {name!r}")
        seen.add(name)
        pattern = _compile(_expect(entry["match"], str, f"rule {name!r}.match"), f"rule {name!r}")
        template = _expect(entry["activity"], str, f"rule {name!r}.activity")
        for _, placeholder, _, _ in string.Formatter().parse(template):
            if placeholder is None:
                continue
            if placeholder not in TEMPLATE_FIELDS or placeholder not in pattern.groupindex:
                raise _fail(
                    f"rule {name!r}: placeholder {{{placeholder}}} phải thuộc "
                    f"{sorted(TEMPLATE_FIELDS)} và là một nhóm có tên trong match"
                )
        rules.append(Rule(name=name, pattern=pattern, activity=template))

    return ActionRules(
        version=version,
        missing_role=missing_role,
        bot_roles=bot_roles,
        fallback_activity=fallback,
        separator=separator,
        noise_policies=noise_policies,
        rules=tuple(rules),
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
        text=raw_bytes.decode("utf-8"),
    )


def _rules_for(cfg: PreprocessConfig, rules: ActionRules | None) -> ActionRules:
    if rules is not None:
        return rules
    if cfg.actions_path is None:
        raise _fail("preprocess.actions_path chưa resolve: dùng load_config hoặc truyền rules=")
    return load_action_rules(cfg.actions_path)


# ----------------------------------------------------------------------------- phân loại action


def _canonical(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").upper()


def _render(rule: Rule, match: re.Match[str]) -> tuple[str, str | None]:
    values = {}
    status = None
    for key, raw in match.groupdict().items():
        if raw is None:
            continue
        if key == "status":
            status = values[key] = raw.strip()  # giữ nguyên chữ hoa/thường và khoảng trắng
        else:
            values[key] = _canonical(raw)
    return rule.activity.format(**values), status


def classify_action(raw_action: str, rules: ActionRules) -> ActionInfo:
    """Phân loại một dòng Jira thành MỘT activity chính (+ các thay đổi phụ), không tách event.

    Dòng được cắt thành mệnh đề; mỗi mệnh đề khớp quy tắc đầu tiên trong danh sách (thứ tự =
    ưu tiên). Activity chính là mệnh đề có quy tắc ưu tiên cao nhất, hòa thì mệnh đề xuất hiện
    trước. Mệnh đề không khớp quy tắc nào trở thành `fallback_activity`.
    """
    clauses = [c.strip() for c in rules.separator.split(raw_action) if c.strip()]
    found: list[tuple[int, str, str]] = []  # (ưu tiên, tên quy tắc, activity)
    status_value = None
    for clause in clauses:
        for priority, rule in enumerate(rules.rules):
            match = rule.pattern.fullmatch(clause)
            if match:
                activity, status = _render(rule, match)
                status_value = status if status is not None else status_value
                found.append((priority, rule.name, activity))
                break
        else:
            found.append((len(rules.rules), FALLBACK_RULE, rules.fallback_activity))
    if not found:
        found.append((len(rules.rules), FALLBACK_RULE, rules.fallback_activity))
    primary_index = min(range(len(found)), key=lambda i: (found[i][0], i))
    _, rule_name, activity = found[primary_index]
    secondary = tuple(a for i, (_, _, a) in enumerate(found) if i != primary_index)
    return ActionInfo(
        activity=activity,
        rule=rule_name,
        secondary=secondary,
        status_value=status_value,
        is_fallback=rule_name == FALLBACK_RULE,
    )


def normalize_events(
    events: pd.DataFrame, cfg: PreprocessConfig, rules: ActionRules | None = None
) -> pd.DataFrame:
    """Thêm activity/status vào bảng event thô; mỗi dòng CSV vẫn là đúng một event.

    Role trống thành `missing_role`; `unknown` vẫn là giá trị riêng. Đầu vào không bị sửa.
    """
    rules = _rules_for(cfg, rules)
    ordered = events.sort_values(SORT_KEYS, kind="stable").reset_index(drop=True)
    info = {a: classify_action(a, rules) for a in ordered["raw_action"].unique()}
    out = ordered.copy()
    out["activity"] = ordered["raw_action"].map(lambda a: info[a].activity)
    out["activity_rule"] = ordered["raw_action"].map(lambda a: info[a].rule)
    out["secondary_changes"] = ordered["raw_action"].map(lambda a: "|".join(info[a].secondary))
    out["status_value"] = ordered["raw_action"].map(lambda a: info[a].status_value)
    out["has_status_update"] = out["status_value"].notna()
    out["is_bot"] = ordered["role"].isin(rules.bot_roles)
    out["role"] = ordered["role"].where(ordered["role"] != "", rules.missing_role)
    columns = [
        "event_id", "case_id", "issue_key", "issue_type", "timestamp_utc", "timestamp_raw",
        "source_file", "source_row", "raw_action", "activity", "activity_rule",
        "secondary_changes", "role", "is_bot", "has_status_update", "status_value",
    ]
    return out[columns]


def mapping_coverage(events: pd.DataFrame) -> pd.DataFrame:
    """Mỗi chuỗi action thô -> activity, quy tắc quyết định, số event/issue (để kiểm tra phủ)."""
    grouped = events.groupby(
        ["raw_action", "activity", "activity_rule", "secondary_changes"], sort=False, dropna=False
    ).agg(n_events=("event_id", "size"), n_cases=("case_id", "nunique")).reset_index()
    grouped = grouped.rename(columns={"activity_rule": "rule"})
    grouped["is_fallback"] = grouped["rule"] == FALLBACK_RULE
    grouped = grouped.sort_values(
        ["n_events", "raw_action"], ascending=[False, True], kind="stable"
    )
    columns = ["raw_action", "activity", "secondary_changes", "rule", "is_fallback",
               "n_events", "n_cases"]
    return grouped.reset_index(drop=True)[columns]


# ---------------------------------------------------------------------------------- trace/core


def _make_trace(group: pd.DataFrame, terminal_status: str | None) -> Trace:
    case_id = group["case_id"].iloc[0]
    return Trace(
        trace_id=case_id,
        parent_case_id=case_id,
        issue_type=group["issue_type"].iloc[0],
        activities=tuple(group["activity"]),
        roles=tuple(group["role"]),
        event_ids=tuple(group["event_id"]),
        timestamps=tuple(ts.to_pydatetime() for ts in group["timestamp_utc"]),
        terminal_status=terminal_status,
    )


def _has_reopen(statuses: list[str], terminal: set[str]) -> bool:
    """Đã có trạng thái terminal rồi sau đó lại có trạng thái không-terminal trước mốc cuối."""
    closed = False
    for status in statuses[:-1]:
        if status in terminal:
            closed = True
        elif closed:
            return True
    return False


def _events_per_case(sizes: list[int]) -> dict[str, float] | None:
    if not sizes:
        return None
    arr = np.asarray(sizes)
    return {"min": int(arr.min()), "median": float(np.median(arr)), "max": int(arr.max()),
            "mean": float(arr.mean())}


def build_core_view(
    events: pd.DataFrame, cfg: PreprocessConfig, rules: ActionRules | None = None
) -> CoreView:
    """Dựng core view hồi cứu (spec §4.2) từ bảng event đã chuẩn hóa.

    - Case có status cuối là terminal: giữ đến event của status đó (mọi vòng reopen trước nó được
      giữ; không cắt ở DONE đầu tiên). Event sau mốc này là post-terminal và bị bỏ khỏi core.
    - Case không có status hoặc status cuối không terminal: loại, ghi lý do (không kết luận issue
      thực sự chưa xong).
    - Noise policy chỉ bỏ event có activity thuộc policy; event terminal cuối luôn được giữ nên
      việc chọn case chỉ phụ thuộc full view, không đổi theo noise policy.
    Cắt theo vị trí trong thứ tự ổn định (case, thời điểm, source_row); khi trùng thời điểm, vị trí
    là quy tắc kỹ thuật chứ không phải thứ tự nghiệp vụ.
    """
    rules = _rules_for(cfg, rules)
    if cfg.noise_policy not in rules.noise_policies:
        raise _fail(
            f"noise_policy {cfg.noise_policy!r} không được định nghĩa trong quy tắc "
            f"(có: {sorted(rules.noise_policies)})"
        )
    noise = rules.noise_policies[cfg.noise_policy]
    terminal = set(cfg.terminal_statuses)
    ordered = events.sort_values(SORT_KEYS, kind="stable").reset_index(drop=True)

    traces: list[Trace] = []
    excluded: list[dict[str, Any]] = []
    post_events = post_cases = reopen_cases = 0
    noise_events: Counter[str] = Counter()
    noise_cases: Counter[str] = Counter()
    for case_id, group in ordered.groupby("case_id", sort=True):
        positions = np.flatnonzero(group["has_status_update"].to_numpy())
        if positions.size == 0:
            excluded.append({"case_id": case_id, "reason": "no_status_update",
                             "last_status_value": None, "n_events": len(group)})
            continue
        last = int(positions[-1])
        statuses = list(group["status_value"].iloc[positions])
        if statuses[-1] not in terminal:
            excluded.append({"case_id": case_id, "reason": "last_status_not_terminal",
                             "last_status_value": statuses[-1], "n_events": len(group)})
            continue
        kept = group.iloc[: last + 1]
        if len(group) > last + 1:
            post_events += len(group) - (last + 1)
            post_cases += 1
        reopen_cases += _has_reopen(statuses, terminal)
        drop = kept["activity"].isin(noise).to_numpy().copy()
        drop[-1] = False  # event terminal cuối luôn được giữ
        for activity, count in Counter(kept["activity"][drop]).items():
            noise_events[activity] += count
            noise_cases[activity] += 1
        traces.append(_make_trace(kept[~drop], statuses[-1]))

    case_exclusions = pd.DataFrame(
        excluded, columns=["case_id", "reason", "last_status_value", "n_events"]
    )
    event_rows = []
    for reason, part in case_exclusions.groupby("reason", sort=True):
        event_rows.append(("case_excluded", reason, int(part["n_events"].sum()), len(part)))
    if post_events:
        event_rows.append(("post_terminal", "after_final_terminal_status", post_events, post_cases))
    for activity in sorted(noise_events):
        event_rows.append(
            ("noise_policy", f"{cfg.noise_policy}:{activity}", noise_events[activity],
             noise_cases[activity])
        )
    event_exclusions = pd.DataFrame(event_rows, columns=["stage", "rule", "n_events", "n_cases"])

    return CoreView(
        traces=traces,
        case_exclusions=case_exclusions,
        event_exclusions=event_exclusions,
        audit=_core_audit(ordered, traces, case_exclusions, cfg, rules, post_events, post_cases,
                          reopen_cases, noise_events),
    )


def _full_stats(events: pd.DataFrame, rules: ActionRules) -> dict[str, Any]:
    return {
        "n_events": len(events),
        "n_cases": int(events["case_id"].nunique()),
        "n_missing_role_events": int((events["role"] == rules.missing_role).sum()),
        "n_unknown_role_events": int((events["role"] == UNKNOWN_ROLE).sum()),
        "n_bot_events": int(events["is_bot"].sum()),
        "n_fallback_activity_events": int((events["activity_rule"] == FALLBACK_RULE).sum()),
        "n_distinct_activities": int(events["activity"].nunique()),
    }


def _core_stats(traces: list[Trace], rules: ActionRules) -> dict[str, Any]:
    roles = Counter(role for t in traces for role in t.roles)
    activities = Counter(a for t in traces for a in t.activities)
    return {
        "n_events": sum(len(t) for t in traces),
        "n_cases": len(traces),
        "n_missing_role_events": roles[rules.missing_role],
        "n_unknown_role_events": roles[UNKNOWN_ROLE],
        "n_bot_events": sum(roles[r] for r in rules.bot_roles),
        "n_fallback_activity_events": activities[rules.fallback_activity],
        "n_distinct_activities": len(activities),
        "events_per_case": _events_per_case([len(t) for t in traces]),
        "terminal_status_counts": dict(sorted(Counter(t.terminal_status for t in traces).items())),
        "activity_counts": dict(sorted(activities.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def _core_audit(
    ordered: pd.DataFrame,
    traces: list[Trace],
    case_exclusions: pd.DataFrame,
    cfg: PreprocessConfig,
    rules: ActionRules,
    post_events: int,
    post_cases: int,
    reopen_cases: int,
    noise_events: Counter[str],
) -> dict[str, Any]:
    core_stats = _core_stats(traces, rules)
    return {
        "view": "core",
        "terminal_statuses": list(cfg.terminal_statuses),
        "noise_policy": cfg.noise_policy,
        "action_rules_sha256": rules.sha256,
        "full_view": _full_stats(ordered, rules),
        "core_view": core_stats,
        "funnel": {
            "n_events_full": len(ordered),
            "n_events_in_excluded_cases": int(case_exclusions["n_events"].sum()),
            "n_events_post_terminal": post_events,
            "n_events_dropped_noise": sum(noise_events.values()),
            "n_events_core": core_stats["n_events"],
        },
        "case_exclusions": {
            str(k): int(v) for k, v in case_exclusions["reason"].value_counts().sort_index().items()
        },
        "post_terminal": {"n_events": post_events, "n_cases": post_cases},
        "reopen": {"n_cases_with_reopen": reopen_cases},
        "noise": {"events_dropped_by_activity": dict(sorted(noise_events.items()))},
    }


def build_traces(
    events: pd.DataFrame, cfg: PreprocessConfig, rules: ActionRules | None = None
) -> list[Trace]:
    """Trace theo `cfg.view`: `core` = core view hồi cứu; `full` = mọi event của mọi case."""
    if cfg.view == "core":
        return build_core_view(events, cfg, rules).traces
    terminal = set(cfg.terminal_statuses)
    ordered = events.sort_values(SORT_KEYS, kind="stable").reset_index(drop=True)
    traces = []
    for _, group in ordered.groupby("case_id", sort=True):
        statuses = group["status_value"].dropna()
        last = statuses.iloc[-1] if len(statuses) else None
        traces.append(_make_trace(group, last if last in terminal else None))
    return traces
