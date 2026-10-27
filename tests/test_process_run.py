"""Lệnh `jira-ad process`: thư mục run bất biến, manifest + fingerprint, tất định, bảo vệ input khóa."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd
import pytest
from helpers import write_process_project
from test_status_log import ALL_ROWS

from jira_ad import process_run
from jira_ad.cli import main
from jira_ad.process_run import FrozenInputChanged, RunExistsError, frozen_fingerprint, run_process

T0 = datetime(2026, 10, 26, 8, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 26, 9, 0, 0, tzinfo=UTC)


@pytest.fixture
def config_path(project):
    return write_process_project(project, ALL_ROWS, overrides={"cohorts": ["bug", "story"]})


def test_run_writes_step_a_tables_for_each_cohort_and_a_completed_manifest(config_path, project):
    out = run_process(config_path, now=T0)
    assert out.parent == project.root / "outputs" / "process"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["frozen_before"] == manifest["frozen_after"]
    for cohort in ("bug", "story"):
        for name in ("status_log.csv", "cases.csv", "pt_wt_ranges.csv", "dwell_by_state.csv",
                     "weekly_little.csv", "little.json", "fpy.json", "rejected_cost.csv",
                     "gate_roles.csv", "kpi_asis.csv"):
            rel = f"a_quant/{cohort}/{name}"
            assert (out / rel).is_file() and rel in manifest["files"]
    assert manifest["inputs"]["bug"]["sha256"] and manifest["config_hash"]


def test_rerun_gives_identical_tables(config_path):
    a = run_process(config_path, now=T0)
    b = run_process(config_path, now=T1)
    files_a = json.loads((a / "manifest.json").read_text(encoding="utf-8"))["files"]
    files_b = json.loads((b / "manifest.json").read_text(encoding="utf-8"))["files"]
    assert files_a == files_b


def test_refuses_to_overwrite_existing_run(config_path):
    run_process(config_path, now=T0)
    with pytest.raises(RunExistsError):
        run_process(config_path, now=T0)


def test_frozen_fingerprint_detects_change_in_old_runs(project):
    runs = project.root / "outputs" / "runs" / "r1"
    runs.mkdir(parents=True)
    (runs / "manifest.json").write_text("{}", encoding="utf-8")
    before = frozen_fingerprint(project.root)
    (runs / "manifest.json").write_text('{"x": 1}', encoding="utf-8")
    assert frozen_fingerprint(project.root) != before


def test_run_fails_and_records_it_when_a_frozen_input_changes(config_path, project, monkeypatch):
    original = process_run._run_steps

    def tamper(cfg, out):
        original(cfg, out)
        (project.root / "configs" / "actions.yaml").write_text("# sửa\n", encoding="utf-8")

    monkeypatch.setattr(process_run, "_run_steps", tamper)
    with pytest.raises(FrozenInputChanged, match="actions.yaml"):
        run_process(config_path, now=T0)
    manifest = next((project.root / "outputs" / "process").glob("*/manifest.json"))
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "failed"


def test_cli_process_command(config_path, capsys):
    assert main(["process", "--config", str(config_path)]) == 0
    assert "Run dir: outputs/process/" in capsys.readouterr().out


def test_run_writes_step_b_norms_and_centrality_for_primary_cohort(config_path):
    out = run_process(config_path, now=T0)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for name in ("norms.csv", "late_visits.csv", "late_by_state.csv", "late_by_role.csv",
                 "late_by_case.csv", "top_late.csv", "centrality_status.csv", "centrality_activity.csv",
                 "centrality_vs_delay.csv", "priorities.csv", "status_dfg.dot", "train_ids.csv"):
        assert f"b_norms/{name}" in manifest["files"], name
    assert not (out / "b_norms" / "story").exists()  # bước B chỉ cho cohort chính


def test_manifest_records_source_code_fingerprint(config_path, project, monkeypatch):
    out = run_process(config_path, now=T0)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    code = manifest["code"]
    assert len(code["sha256"]) == 64 and "jira_ad/process_run.py" in code["files"]


C_FILES = ("work_system.csv", "lanes.json", "reference_model.bpmn", "reference_model.dot",
           "reference_net.dot", "arc_table.csv", "flags.csv", "flag_summary.csv",
           "discovery_quality.csv", "models/alpha.dot", "models/inductive.dot")


def test_run_writes_step_c_without_reference_replay_until_approved(config_path):
    out = run_process(config_path, now=T0)
    files = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["files"]
    for name in C_FILES:
        assert f"c_conformance/{name}" in files, name
    assert "c_conformance/replay_cases.csv" not in files
    assert json.loads((out / "c_conformance" / "status.json").read_text(encoding="utf-8")) == {
        "reference_replay": "chờ duyệt mô hình chuẩn (reference_model.approved: false)"}


def test_run_replays_reference_model_once_approved(project):
    path = write_process_project(project, ALL_ROWS, overrides={"reference_model.approved": True})
    out = run_process(path, now=T0)
    replay = out / "c_conformance" / "replay_cases.csv"
    assert replay.is_file() and (out / "c_conformance" / "replay_summary.json").is_file()
    assert (out / "c_conformance" / "deviations_top.csv").is_file()
    for name in ("replay_cases_fast_track.csv", "replay_comparison.csv", "replay_gained_cases.csv",
                 "unobserved_arc_precision.csv", "deviation_breakdown.csv", "models/fast_track.dot"):
        assert (out / "c_conformance" / name).is_file(), name
    comparison = pd.read_csv(out / "c_conformance" / "replay_comparison.csv")
    assert list(comparison.model) == ["reference", "fast_track"]


def test_run_writes_step_d_bpr(config_path):
    out = run_process(config_path, now=T0)
    files = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["files"]
    for name in ("checks.csv", "problems.csv", "kpi_asis_tobe.csv", "todo_excess_by_role.csv",
                 "tobe_model.bpmn", "tobe_model.dot", "pilot.csv"):
        assert f"d_bpr/{name}" in files, name
    kpi = pd.read_csv(out / "d_bpr" / "kpi_asis_tobe.csv")
    assert (kpi["tobe_label"] == "mục tiêu / kịch bản ước tính").all()
    assert kpi["assumption"].str.len().gt(0).all()
    pilot = pd.read_csv(out / "d_bpr" / "pilot.csv")
    assert pilot["baseline_asis"].notna().all()


def test_step_d_runs_every_check_path_when_both_fast_track_groups_exist(project):
    # hồi quy: fixture cũ chỉ có ca DONE bỏ điều tra nên nhánh so sánh của check_fast_track không được chạy
    from helpers import stamped_rows, status

    investigated = stamped_rows("TI-9", [
        ("2022-06-13T08:00:00", "SQA", "Issue created"),
        ("2022-06-13T09:00:00", "PO", status("To Investigate")),
        ("2022-06-14T09:00:00", "PO", status("INVESTIGATED")),
        ("2022-06-14T10:00:00", "PO", status("To Do")),
        ("2022-06-15T10:00:00", "Eng", status("In Progress")),
        ("2022-06-16T10:00:00", "SQA", status("In Test")),
        ("2022-06-17T10:00:00", "SQA", status("DONE")),
    ])
    out = run_process(write_process_project(project, ALL_ROWS + investigated), now=T0)
    checks = pd.read_csv(out / "d_bpr" / "checks.csv").set_index("candidate")
    assert checks.loc["fast_track", "verdict"] in ("ủng hộ", "không ủng hộ")


def test_run_writes_step_e_ranking_even_without_v1_run_or_oof_scores(config_path):
    out = run_process(config_path, now=T0)
    files = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["files"]
    for name in ("groups.csv", "profile.csv", "ranking.csv", "top.csv", "stability.json", "correlations.json",
                 "blind_review.csv", "blind_review_key.csv", "status.json"):
        assert f"e_ranking/{name}" in files, name
    status = json.loads((out / "e_ranking" / "status.json").read_text(encoding="utf-8"))
    assert "không có" in status["representation"] and "không có" in status["markov"]
    blinded = pd.read_csv(out / "e_ranking" / "blind_review.csv")
    assert "rank" not in blinded.columns


def test_step_d_reports_feasible_and_upper_bound_scenarios_after_review(config_path):
    # rà soát độc lập I2, I4, I5
    out = run_process(config_path, now=T0)
    kpi = pd.read_csv(out / "d_bpr" / "kpi_asis_tobe.csv").set_index("kpi")
    assert {"rejected_issue_days_work", "rejected_issue_days_work_upper", "ct_work_median_days_upper"} <= set(
        kpi.index)
    assert kpi.loc["rejected_issue_days_work_upper", "tobe"] <= kpi.loc["rejected_issue_days_work", "tobe"]
    assert "đường TO-BE" in kpi.loc["status_changes_per_case", "assumption"]
    assert (out / "d_bpr" / "todo_excess_by_role_target.csv").is_file()


def test_replay_summary_reports_fitness_of_unfit_cases():
    from jira_ad.process_run import replay_summary

    replay = pd.DataFrame({"case_id": list("abcd"), "trace_fitness": [1.0, 1.0, 0.9, 0.8],
                           "is_fit": [True, True, False, False], "terminal_status": ["DONE"] * 4})
    out = replay_summary(replay, {})
    assert out["unfit"]["n_cases"] == 2 and out["unfit"]["mean_trace_fitness"] == pytest.approx(0.85)


def test_correlations_report_spearman_of_exceed_count_with_length(config_path):
    out = run_process(config_path, now=T0)
    corr = json.loads((out / "e_ranking" / "correlations.json").read_text(encoding="utf-8"))
    assert "spearman_n_exceed_vs_n_events" in corr
    assert (out / "e_ranking" / "consensus.csv").is_file()


def test_cli_blind_review_compare_unlocks_key_and_prints_fisher(project, capsys):
    path = write_process_project(project, ALL_ROWS)
    out = run_process(path, now=T0)
    blinded = pd.read_csv(out / "e_ranking" / "blind_review.csv")
    labels = ["needs_review", "plausibly_valid", "insufficient_evidence", "plausibly_valid"]
    blinded["label"] = labels[: len(blinded)]
    filled = project.root / "blind_review_filled.csv"
    blinded.to_csv(filled, index=False)
    assert main(["blind-review-compare", "--run-dir", str(out), "--labels", str(filled)]) == 0
    text = capsys.readouterr().out
    assert "Fisher" in text and "top" in text and "ngẫu nhiên" in text


def test_cli_blind_review_compare_reports_unlabelled_rows(project, capsys):
    out = run_process(write_process_project(project, ALL_ROWS), now=T0)
    filled = project.root / "empty.csv"
    pd.read_csv(out / "e_ranking" / "blind_review.csv").to_csv(filled, index=False)
    assert main(["blind-review-compare", "--run-dir", str(out), "--labels", str(filled)]) == 2
    assert "Chưa gán nhãn" in capsys.readouterr().err
