"""Nạp run `outputs/process/<run>` cho notebook: kiểm fingerprint, chọn run tự động, nhận xét từ số liệu."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from helpers import Project, write_process_project
from test_status_log import ALL_ROWS

from jira_ad.analysis import NotebookInputError
from jira_ad.process_analysis import (
    PROCESS_RUN_ENV,
    fmt,
    open_process_run,
    remarks_norms,
    remarks_quant,
)
from jira_ad.process_run import run_process

T0 = datetime(2026, 10, 26, 8, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 26, 9, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    project = Project(tmp_path_factory.mktemp("proc") / "repo")
    config = write_process_project(project, ALL_ROWS)
    old = run_process(config, now=T0)
    new = run_process(config, now=T1)
    return project.root, config, old, new


def test_open_explicit_run_checks_files_and_reads_artifacts(built):
    _, _, _, new = built
    run = open_process_run(new)
    assert run.run_id == new.name and len(run.config_hash) == 64
    assert len(run.csv("a_quant/bug/cases.csv")) == 8
    assert run.json("a_quant/bug/fpy.json")["n_cases"] == 8
    header = run.header()
    assert new.name in header and "config_hash" in header and "chỉ định" in header


def test_default_run_is_latest_completed_matching_current_config(built, monkeypatch):
    root, _, old, new = built
    monkeypatch.delenv(PROCESS_RUN_ENV, raising=False)
    monkeypatch.chdir(root / "configs")  # mở tay từ thư mục con (như notebooks/)
    run = open_process_run()
    assert run.run_dir == new and "tự động" in run.header()
    monkeypatch.setenv(PROCESS_RUN_ENV, str(old))
    assert open_process_run().run_dir == old


def test_tampered_artifact_is_rejected(tmp_path):
    project = Project(tmp_path / "repo")
    out = run_process(write_process_project(project, ALL_ROWS), now=T0)
    (out / "a_quant" / "bug" / "cases.csv").write_text("x\n1\n", encoding="utf-8")
    with pytest.raises(NotebookInputError, match="cases.csv"):
        open_process_run(out)


def test_incomplete_or_mismatched_runs_are_not_chosen(tmp_path, monkeypatch):
    project = Project(tmp_path / "repo")
    config = write_process_project(project, ALL_ROWS)
    out = run_process(config, now=T0)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    manifest["status"] = "failed"
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.delenv(PROCESS_RUN_ENV, raising=False)
    monkeypatch.chdir(project.root)
    with pytest.raises(NotebookInputError, match="jira-ad process --config"):
        open_process_run()
    with pytest.raises(NotebookInputError, match="completed"):
        open_process_run(out)


def test_fmt_uses_vietnamese_decimal_comma():
    assert fmt(1234.5678, 1) == "1.234,6" and fmt(0.25, 2) == "0,25" and fmt(17, 0) == "17"
    assert fmt(0.167, 1, percent=True) == "16,7%"


def test_remarks_are_generated_from_artifact_numbers(built):
    _, _, _, new = built
    run = open_process_run(new)
    quant = " ".join(remarks_quant(run, "bug"))
    cases = run.csv("a_quant/bug/cases.csv")
    assert fmt(cases.ct_work_s.median() / 86_400, 1) in quant
    fpy = run.json("a_quant/bug/fpy.json")
    assert fmt(fpy["fpy_strict"], 3) in quant
    norms = " ".join(remarks_norms(run))
    top = run.csv("b_norms/priorities.csv").iloc[0]
    assert top.state in norms and fmt(top.excess_days, 1) in norms


def test_open_does_not_need_environment_variables(built, monkeypatch):
    root, *_ = built
    for key in list(os.environ):
        if key.startswith("JIRA_AD"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(Path(root))
    assert open_process_run().run_id


def test_show_renders_figure_as_png(built):
    from matplotlib.figure import Figure

    _, _, _, new = built
    fig = Figure()
    fig.subplots().plot([0, 1], [0, 1])
    png = open_process_run(new).show(fig)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_pt_range_verdict_depends_on_the_width_of_the_range():
    from jira_ad.process_analysis import pt_range_verdict

    assert "phụ thuộc" in pt_range_verdict(0.167, 0.592, main=0.167, sensitivity=0.570)
    narrow = pt_range_verdict(0.280, 0.319, main=0.280, sensitivity=0.280)
    assert "phụ thuộc" not in narrow and "ổn định" in narrow


def test_remarks_conformance_come_from_replay_artifacts(tmp_path):
    from jira_ad.process_analysis import remarks_conformance

    project = Project(tmp_path / "repo")
    out = run_process(write_process_project(project, ALL_ROWS, overrides={"reference_model.approved": True}),
                      now=T0)
    run = open_process_run(out)
    text = " ".join(remarks_conformance(run))
    summary = run.json("c_conformance/replay_summary.json")["by_branch"]["all"]
    assert fmt(summary["share_fit"], 1, percent=True) in text
    comparison = run.csv("c_conformance/replay_comparison.csv").set_index("model")
    assert f"{int(comparison.loc['fast_track', 'n_newly_fit_vs_reference'])} ca" in text
    assert "KHÔNG phải mô hình chuẩn" in text


def test_remarks_conformance_before_approval_says_replay_is_pending(built):
    from jira_ad.process_analysis import remarks_conformance

    _, _, _, new = built
    assert "chờ duyệt" in " ".join(remarks_conformance(open_process_run(new)))


def test_remarks_bpr_label_every_tobe_number_as_target(tmp_path):
    from jira_ad.process_analysis import remarks_bpr

    project = Project(tmp_path / "repo")
    out = run_process(write_process_project(project, ALL_ROWS, overrides={"reference_model.approved": True}),
                      now=T0)
    run = open_process_run(out)
    lines = remarks_bpr(run)
    checks = run.csv("d_bpr/checks.csv")
    assert all(any(c in line for line in lines) for c in checks["candidate"])
    kpi_lines = [line for line in lines if "→" in line]
    assert kpi_lines and all("mục tiêu / kịch bản ước tính" in line for line in kpi_lines)


def test_remarks_ranking_mention_stability_and_reading_rule(tmp_path):
    from jira_ad.process_analysis import remarks_ranking

    project = Project(tmp_path / "repo")
    run = open_process_run(run_process(write_process_project(project, ALL_ROWS), now=T0))
    text = " ".join(remarks_ranking(run))
    stab = run.json("e_ranking/stability.json")
    assert fmt(stab["jaccard_mean"], 2) in text and "nên xem trước" in text and "không phải vi phạm" in text
    assert "không có run V1" in text  # dự án nhỏ không có run V1: nói rõ phần bị bỏ


def test_remarks_explain_token_fitness_and_consensus_list(tmp_path):
    from jira_ad.process_analysis import remarks_conformance, remarks_ranking

    project = Project(tmp_path / "repo")
    out = run_process(write_process_project(project, ALL_ROWS, overrides={"reference_model.approved": True}),
                      now=T0)
    run = open_process_run(out)
    conf = " ".join(remarks_conformance(run))
    unfit = run.json("c_conformance/replay_summary.json")["unfit"]
    assert f"fitness trung bình {fmt(unfit['mean_trace_fitness'], 3)}" in conf
    rank = " ".join(remarks_ranking(run))
    n = int(run.csv("e_ranking/consensus.csv")["consensus"].sum())
    assert f"{n} ca đồng thuận" in rank
    corr = run.json("e_ranking/correlations.json")
    assert fmt(corr["spearman_n_exceed_vs_n_events"], 3) in rank
