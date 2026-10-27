"""Cấu hình giai đoạn 2 (`configs/process.yaml`): kiểm khóa, miền giá trị, hash tất định."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from jira_ad.config import ConfigError
from jira_ad.process_config import load_process_config, process_config_hash

REPO_ROOT = Path(__file__).resolve().parents[1]

BASE_PROCESS: dict = {
    "paths": {
        "base_config": "configs/test.yaml",
        "output_root": "outputs/process",
        "v1_run": "outputs/runs/v1",
        "improvement_dir": "outputs/improvement/imp",
    },
    "cohorts": ["bug", "story"],
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


def write(root: Path, data: dict, name: str = "process.yaml") -> Path:
    (root / "configs").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    path = root / "configs" / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_loads_valid_config_and_resolves_paths(tmp_path):
    cfg = load_process_config(write(tmp_path, BASE_PROCESS))
    assert cfg.project_root == tmp_path
    assert cfg.resolve(cfg.paths.output_root) == tmp_path / "outputs" / "process"
    assert cfg.states.work == ("In Progress", "In Test")
    assert cfg.primary_cohort == "bug"


def test_rejects_unknown_key(tmp_path):
    data = copy.deepcopy(BASE_PROCESS)
    data["states"]["extra"] = 1
    with pytest.raises(ConfigError, match="extra"):
        load_process_config(write(tmp_path, data))


def test_rejects_state_in_both_work_and_wait(tmp_path):
    data = copy.deepcopy(BASE_PROCESS)
    data["states"]["wait"] = ["Inbox", "In Test"]
    with pytest.raises(ConfigError, match="In Test"):
        load_process_config(write(tmp_path, data))


def test_rejects_bad_calendar(tmp_path):
    data = copy.deepcopy(BASE_PROCESS)
    data["calendar"]["workdays"] = [0, 7]
    with pytest.raises(ConfigError, match="workdays"):
        load_process_config(write(tmp_path, data))
    data["calendar"] = {"workdays": [0], "primary": "moon"}
    with pytest.raises(ConfigError, match="primary"):
        load_process_config(write(tmp_path, data))


def test_rejects_absolute_path_and_unknown_cohort(tmp_path):
    data = copy.deepcopy(BASE_PROCESS)
    data["paths"]["output_root"] = "/tmp/x"
    with pytest.raises(ConfigError, match="tuyệt đối"):
        load_process_config(write(tmp_path, data))
    data = copy.deepcopy(BASE_PROCESS)
    data["cohorts"] = ["epic"]
    with pytest.raises(ConfigError, match="epic"):
        load_process_config(write(tmp_path, data))


def test_hash_depends_on_values_not_on_comments_or_file_location(tmp_path):
    a = load_process_config(write(tmp_path, BASE_PROCESS, "a.yaml"))
    path_b = write(tmp_path, BASE_PROCESS, "b.yaml")
    path_b.write_text("# chú thích\n" + path_b.read_text(encoding="utf-8"), encoding="utf-8")
    b = load_process_config(path_b)
    changed = copy.deepcopy(BASE_PROCESS)
    changed["backfill"]["threshold_seconds"] = 30
    c = load_process_config(write(tmp_path, changed, "c.yaml"))
    assert process_config_hash(a) == process_config_hash(b) != process_config_hash(c)


def test_repo_process_yaml_is_valid():
    cfg = load_process_config(REPO_ROOT / "configs" / "process.yaml")
    assert cfg.paths.base_config == "configs/baseline.yaml"
    assert cfg.states.work == ("In Progress", "In Test")
    assert cfg.calendar.primary == "local"


def test_norms_and_centrality_sections_are_checked(tmp_path):
    data = copy.deepcopy(BASE_PROCESS)
    data["norms"]["percentile"] = 1.5
    with pytest.raises(ConfigError, match="percentile"):
        load_process_config(write(tmp_path, data))
    data = copy.deepcopy(BASE_PROCESS)
    data["centrality"]["pagerank_alpha"] = 1.0
    with pytest.raises(ConfigError, match="pagerank_alpha"):
        load_process_config(write(tmp_path, data))
    data = copy.deepcopy(BASE_PROCESS)
    data["norms"]["explicit_days"] = {"To Do": 3}
    assert load_process_config(write(tmp_path, data)).norms.explicit_days == {"To Do": 3.0}


def test_reference_model_flags_and_discovery_are_checked(tmp_path):
    cfg = load_process_config(write(tmp_path, BASE_PROCESS))
    assert ("In Test", "In Progress") in cfg.reference.arcs and not cfg.reference_model.approved
    assert cfg.flags[0].id == "skip_investigation" and cfg.discovery[1].params == {"noise_threshold": 0.0}
    data = copy.deepcopy(BASE_PROCESS)
    data["reference_model"]["arcs"].append("To Do In Test")
    with pytest.raises(ConfigError, match="->"):
        load_process_config(write(tmp_path, data))
    data = copy.deepcopy(BASE_PROCESS)
    data["flags"][0]["kind"] = "magic"
    with pytest.raises(ConfigError, match="magic"):
        load_process_config(write(tmp_path, data))
    data = copy.deepcopy(BASE_PROCESS)
    data["discovery"][0]["miner"] = "genetic"
    with pytest.raises(ConfigError, match="genetic"):
        load_process_config(write(tmp_path, data))
    data = copy.deepcopy(BASE_PROCESS)
    data["flags"].append(dict(data["flags"][0]))
    with pytest.raises(ConfigError, match="trùng"):
        load_process_config(write(tmp_path, data))


def test_alternative_models_and_deviation_report_are_checked(tmp_path):
    cfg = load_process_config(write(tmp_path, BASE_PROCESS))
    fast = cfg.alternative_models[0]
    assert fast.id == "fast_track" and ("CREATE", "To Do") in cfg.alternative(fast.id).arcs
    assert cfg.deviation_report.arcs == ("CREATE -> To Do", "To Do -> Inbox")
    data = copy.deepcopy(BASE_PROCESS)
    data["alternative_models"][0]["extra_arcs"] = ["CREATE -> To Investigate"]  # đã có trong mô hình chuẩn
    with pytest.raises(ConfigError, match="đã có"):
        load_process_config(write(tmp_path, data))


def test_bpr_design_sections_are_checked(tmp_path):
    cfg = load_process_config(write(tmp_path, BASE_PROCESS))
    assert ("Inbox", "To Do") in cfg.tobe.arcs and cfg.pilot[0].kpis == ("ct_work_median_days",)
    for key, value, match in [
        (("bpr_candidates", 0, "id"), "magic_wand", "magic_wand"),
        (("pilot", 0, "kpis"), ["happiness"], "happiness"),
        (("tobe_model", "automated_arcs"), ["Inbox -> In Test"], "automated_arcs"),
    ]:
        data = copy.deepcopy(BASE_PROCESS)
        node = data
        for k in key[:-1]:
            node = node[k]
        node[key[-1]] = value
        with pytest.raises(ConfigError, match=match):
            load_process_config(write(tmp_path, data))
