"""Helper dùng chung cho test: dự án tạm có pyproject.toml, dataset giả lập, config hợp lệ.

Dữ liệu ở đây là fixture nhỏ do test tự dựng; không đọc `dataset/` thật. Nằm ngoài conftest để
fixture phạm vi module có thể dùng (conftest không import được một cách chắc chắn).
"""

from __future__ import annotations

import copy
import csv
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
HEADER = ("issueKey", "timestamp", "role", "action")
DELETE = object()  # sentinel: xóa khóa khỏi config

BASE_CONFIG: dict = {
    "project": {"output_root": "outputs"},
    "data": {
        "root": "dataset",
        "files": {"bug": "TIeventlogBug.csv", "story": "TIeventlogStory.csv"},
        "recursive_discovery": True,
        "cohort": "bug",
    },
    "preprocess": {
        "actions_file": "configs/actions.yaml",
        "view": "core",
        "terminal_statuses": ["DONE", "Rejected"],
        "noise_policy": "drop_generic_external_link_updates",
    },
    "split": {
        "seed": 42,
        "train_fraction": 0.60,
        "validation_fraction": 0.20,
        "test_fraction": 0.20,
        "stratify": "terminal_status",
    },
    "graph": {
        "directed": True,
        "encoding": "activity",
        "add_boundaries": True,
        "transition_alpha": 1.0,
    },
    "walk": {"p": 1.0, "q": 1.0, "length": 20, "walks_per_node": 50},
    "embedding": {
        "dimensions": 16,
        "window": 3,
        "epochs": 20,
        "negative": 5,
        "min_count": 1,
        "sample": 0.0,
        "workers": 1,
    },
    "features": {
        "methods": ["A_stats", "B_ngrams", "C_embedding", "D_hybrid"],
        "include_time": False,
    },
    "detector": {
        "n_estimators": 200,
        "max_samples": "auto",
        "contamination": "auto",
        "n_jobs": 1,
    },
    "mutation": {
        "types": ["swap_adjacent", "delete_internal", "duplicate_block"],
        "max_per_type_per_parent": 1,
        "validation_seed": 1042,
        "test_seed": 2042,
        "duplicate_block_max_length": 2,
    },
    "run": {"seed": 42, "fail_on_existing_output": True},
    "notebooks": {"timeout_seconds": 180},
}


def write_raw_csv(path: Path, rows, header=HEADER) -> Path:
    """Ghi CSV giống định dạng dataset gốc (mọi trường được quote)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)
        writer.writerow(header)
        writer.writerows(rows)
    return path


class Project:
    """Một repo tạm: pyproject.toml ở gốc, dataset/ và configs/."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "pyproject.toml").write_text('[project]\nname = "fixture"\n', encoding="utf-8")
        # Dùng đúng file quy tắc của repo để test kiểm chứng ánh xạ thật, không bản sao riêng.
        (root / "configs").mkdir(exist_ok=True)
        shutil.copy(REPO_ROOT / "configs" / "actions.yaml", root / "configs" / "actions.yaml")

    def write_bug(self, rows, rel: str = "dataset/TIeventlogBug.csv", header=HEADER) -> Path:
        return write_raw_csv(self.root / rel, rows, header)

    def write_story(self, rows, rel: str = "dataset/TIeventlogStory.csv", header=HEADER) -> Path:
        return write_raw_csv(self.root / rel, rows, header)

    def config(self, overrides: dict | None = None) -> dict:
        """Bản sao của BASE_CONFIG; khóa chấm như 'split.seed' ghi đè giá trị lồng nhau."""
        cfg = copy.deepcopy(BASE_CONFIG)
        for dotted, value in (overrides or {}).items():
            *parents, leaf = dotted.split(".")
            node = cfg
            for part in parents:
                node = node[part]
            if value is DELETE:
                del node[leaf]
            else:
                node[leaf] = value
        return cfg

    def write_config(self, cfg: dict | None = None, rel: str = "configs/test.yaml") -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(cfg if cfg is not None else self.config()), encoding="utf-8")
        return path



DONE_ROW = "update resolution to Done, update status to DONE"
REJECT_ROW = "update resolution to Canceled, update status to Rejected"
EDIT_POOL = [
    "edit description", "edit summary", "add Fix Version", "add Story Points", "add assignee",
    "update Rank to Ranked higher", "add link to relates to", "remove assignee",
    "update Backlog Classification to Technical Debt",
]


def timed_rows(issue, steps, start="2022-03-01T08:00:00", offset="-0700", step_seconds=60):
    """Dòng CSV của một issue: timestamp tăng đều, mỗi bước cách nhau `step_seconds`."""
    t0 = datetime.fromisoformat(start)
    rows = []
    for i, (role, action) in enumerate(steps):
        stamp = t0 + timedelta(seconds=i * step_seconds)
        rows.append((issue, f"{stamp:%Y-%m-%dT%H:%M:%S}.000{offset}", role, action))
    return rows


def varied_rows(n=30, seed=0, prefix="TI"):
    """n issue kết thúc xen kẽ DONE/Rejected, độ dài và nội dung khác nhau (có event nhiễu bot)."""
    import random

    rng = random.Random(seed)
    rows = []
    for i in range(n):
        steps = [("SQA", "Issue created")]
        steps += [(rng.choice(["PO", "Eng", "unknown"]), rng.choice(EDIT_POOL))
                  for _ in range(rng.randint(2, 7))]
        if rng.random() < 0.4:
            steps.insert(rng.randint(1, len(steps)), ("bot", "update RemoteIssueLink"))
        steps.append(("PO", REJECT_ROW if i % 2 else DONE_ROW))
        rows += timed_rows(f"{prefix}-{i + 1}", steps)
    return rows


# ------------------------------------------------------------------ giai đoạn 2 (process.yaml)

PROCESS_CONFIG: dict = {
    "paths": {
        "base_config": "configs/test.yaml",
        "output_root": "outputs/process",
        "v1_run": "outputs/runs/v1",
        "improvement_dir": "outputs/improvement/imp",
    },
    "cohorts": ["bug"],
    "calendar": {"workdays": [0, 1, 2, 3, 4], "primary": "local"},
    "backfill": {"threshold_seconds": 60},
    "states": {
        "order": ["Inbox", "To Investigate", "INVESTIGATED", "To Do", "In Progress", "In Test"],
        "work": ["In Progress", "In Test"],
        "wait": ["Inbox", "To Investigate", "INVESTIGATED", "To Do"],
        "terminal": ["DONE", "Rejected"],
        "sensitivity_work": ["To Investigate", "In Progress", "In Test"],
    },
    "norms": {"percentile": 0.75, "min_visits": 2, "explicit_days": {}},
    "centrality": {"pagerank_alpha": 0.85, "top_late": 20, "example_cases": 3},
    "reference_model": {
        "approved": False,
        "start": "CREATE",
        "ends": ["DONE", "Rejected"],
        "arcs": ["CREATE -> Inbox", "CREATE -> To Investigate", "CREATE -> Rejected",
                 "Inbox -> To Investigate", "Inbox -> Rejected",
                 "To Investigate -> INVESTIGATED", "To Investigate -> Rejected",
                 "INVESTIGATED -> To Do", "INVESTIGATED -> Rejected",
                 "To Do -> In Progress", "To Do -> Rejected",
                 "In Progress -> In Test", "In Test -> In Progress", "In Test -> DONE"],
    },
    "flags": [
        {"id": "skip_investigation", "label": "Bỏ pha điều tra", "kind": "missing_before",
         "states": ["To Do", "In Progress", "In Test", "DONE"],
         "other_states": ["To Investigate", "INVESTIGATED"]},
        {"id": "backfill", "label": "Đổi trạng thái trong đợt cập nhật bù", "kind": "backfill",
         "states": [], "other_states": []},
    ],
    "discovery": [
        {"id": "alpha", "miner": "alpha", "params": {}},
        {"id": "inductive", "miner": "inductive", "params": {"noise_threshold": 0.0}},
    ],
    "alternative_models": [
        {"id": "fast_track", "label": "Luồng nhanh (ứng viên TO-BE)", "extra_arcs": ["CREATE -> To Do"]},
    ],
    "deviation_report": {"arcs": ["CREATE -> To Do", "To Do -> Inbox"]},
    "bpr": {"early_triage_min_share": 0.2, "early_triage_min_median_days": 5.0,
            "auto_transition_min_share": 0.3, "merge_max_days": 1.0, "merge_min_share": 0.5,
            "po_state": "To Do", "duplicate_pattern": "link to duplicates", "duplicate_min_cases": 5,
            "duplicate_min_median_days": 5.0, "investigating_min_width_pp": 10.0,
            "fast_track_max_fpy_drop": 0.1, "bootstrap_n": 200, "seed": 1},
    "bpr_candidates": [
        {"id": "early_triage", "problem": "p", "heuristic": "h"},
        {"id": "fast_track", "problem": "p2", "heuristic": "h2"},
    ],
    "tobe_model": {
        "start": "CREATE", "ends": ["DONE", "Rejected"],
        "arcs": ["CREATE -> Inbox", "Inbox -> Rejected", "Inbox -> To Do", "To Do -> In Progress",
                 "To Do -> Rejected", "In Progress -> In Test", "In Test -> DONE"],
        "automated_arcs": ["To Do -> In Progress"],
        "lanes": {"Inbox": "PO", "To Do": "PO", "In Progress": "Eng", "In Test": "SQA"},
    },
    "pilot": [{"id": "p1", "weeks": "1–2", "action": "a", "kpis": ["ct_work_median_days"]}],
    "ranking": {"oof_method": "M_markov", "k_min": 2, "k_max": 3, "seed": 1, "top_share": 0.25,
                "peer_percentile": 0.9, "length_bins": 2, "n_boot": 20, "consensus_share": 0.7,
                "blind_top": 2, "blind_random": 2,
                "assignee_activities": ["ADD_ASSIGNEE", "UPDATE_ASSIGNEE", "REMOVE_ASSIGNEE"],
                "activity_groups": {"status": ["STATUS_DONE", "STATUS_Rejected"],
                                    "documentation": ["CREATE"]}},
}


def status(name: str) -> str:
    """Action Jira đổi sang trạng thái `name` (DONE/Rejected kèm resolution như dữ liệu thật)."""
    if name == "DONE":
        return DONE_ROW
    if name == "Rejected":
        return REJECT_ROW
    return f"update status to {name}"


def stamped_rows(issue, steps, offset="-0700"):
    """Dòng CSV với thời điểm cụ thể: steps = [(giờ địa phương 'YYYY-MM-DDTHH:MM:SS', role, action)]."""
    return [(issue, f"{local}.000{offset}", role, action) for local, role, action in steps]


def write_process_project(project: Project, bug_rows, story_rows=None, overrides=None) -> Path:
    """Ghi dataset giả + configs/test.yaml (giai đoạn 1) + configs/process.yaml; trả đường dẫn sau."""
    project.write_bug(bug_rows)
    project.write_story(story_rows if story_rows is not None else bug_rows)
    project.write_config()
    cfg = copy.deepcopy(PROCESS_CONFIG)
    for dotted, value in (overrides or {}).items():
        *parents, leaf = dotted.split(".")
        node = cfg
        for part in parents:
            node = node[part]
        node[leaf] = value
    path = project.root / "configs" / "process.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path
