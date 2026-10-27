from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROWS_BUG = [
    ("TI-1", "2022-06-21T22:40:38.856-0700", "SQA", "Issue created"),
    ("TI-1", "2022-06-22T06:01:47.958-0700", "PO",
     "update resolution to Done, update status to DONE"),
    ("TI-1", "2022-06-22T01:14:11.285-0700", "", "edit description"),
]
ROWS_STORY = [
    ("TI-7", "2022-06-21T05:57:10.673-0700", "Eng", "Issue created"),
    ("TI-7", "2022-07-08T02:49:14.335-0700", "bot", "update RemoteIssueLink"),
]


def run_cli(args, cwd: Path):
    return subprocess.run(
        [sys.executable, "-m", "jira_ad.cli", *args],
        cwd=cwd, capture_output=True, text=True, check=False,
    )


def test_audit_writes_fingerprinted_json_and_leaves_raw_files_untouched(project, tmp_path):
    bug = project.write_bug(ROWS_BUG)
    story = project.write_story(ROWS_STORY)
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (bug, story)}
    config = project.write_config()

    result = run_cli(["audit", "--config", str(config)], cwd=tmp_path)  # cwd khác repo

    assert result.returncode == 0, result.stderr
    out = project.root / "outputs" / "analysis" / "audit_raw.json"
    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["scope"] == "analysis_only"
    assert data["view"] == "raw"
    by_path = {i["relative_path"]: i for i in data["inputs"]}
    assert by_path["dataset/TIeventlogBug.csv"]["sha256"] == before[bug]
    assert by_path["dataset/TIeventlogStory.csv"]["n_rows"] == len(ROWS_STORY)
    assert data["cohorts"]["bug"]["n_events"] == len(ROWS_BUG)
    assert data["cohorts"]["bug"]["n_cases"] == 1
    assert data["cohorts"]["story"]["n_events"] == len(ROWS_STORY)
    assert "bug" in result.stdout and "story" in result.stdout
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (bug, story)} == before


def test_audit_reports_differences_from_reference_counts_without_blocking(project, tmp_path):
    project.write_bug(ROWS_BUG)
    project.write_story(ROWS_STORY)
    cfg = project.config({
        "data.reference_counts": {
            "bug": {"events": 99, "issues": 1},
            "story": {"events": 2, "issues": 1},
        }
    })
    config = project.write_config(cfg)

    result = run_cli(["audit", "--config", str(config)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    data = json.loads(
        (project.root / "outputs" / "analysis" / "audit_raw.json").read_text(encoding="utf-8")
    )
    bug_diff = data["cohorts"]["bug"]["reference_diff"]
    assert bug_diff["events"] == {"expected": 99, "actual": 3, "delta": -96}
    assert bug_diff["issues"] == {"expected": 1, "actual": 1, "delta": 0}
    assert data["cohorts"]["story"]["reference_diff"]["events"]["delta"] == 0
    assert "sai khác" in result.stdout


def test_audit_fails_loudly_on_bad_data_and_writes_no_report(project, tmp_path):
    project.write_bug([("TI-1", "garbage", "PO", "Issue created")])
    project.write_story(ROWS_STORY)
    config = project.write_config()

    result = run_cli(["audit", "--config", str(config)], cwd=tmp_path)

    assert result.returncode != 0
    assert "source_row=1" in result.stderr
    assert not (project.root / "outputs" / "analysis" / "audit_raw.json").exists()


def prepared_dirs(project):
    root = project.root / "outputs" / "prepared"
    return sorted(p for p in root.iterdir()) if root.exists() else []


def test_prepare_writes_split_exclusions_and_mapping_before_any_model(
    project, tmp_path, case_rows, terminal_cases
):
    rows = terminal_cases()
    rows += case_rows("TI-99", [("SQA", "Issue created"), ("PO", "update status to In Test")])
    bug = project.write_bug(rows)
    before = hashlib.sha256(bug.read_bytes()).hexdigest()
    config = project.write_config()

    result = run_cli(["prepare", "--config", str(config)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    (directory,) = prepared_dirs(project)
    assert directory.name.startswith("bug-")
    expected = {"split_manifest.csv", "exclusions.csv", "event_exclusions.csv",
                "mapping_coverage.csv", "preprocess_audit.json"}
    assert {p.name for p in directory.iterdir()} == expected

    manifest = pd.read_csv(directory / "split_manifest.csv", dtype=str)
    # TI-99 bị loại nên không nằm trong split
    assert len(manifest) == 12 and manifest.case_id.is_unique
    assert "bug:TI-99" not in set(manifest.case_id)
    exclusions = pd.read_csv(directory / "exclusions.csv", dtype=str)
    assert list(exclusions.case_id) == ["bug:TI-99"]
    assert list(exclusions.reason) == ["last_status_not_terminal"]

    audit = json.loads((directory / "preprocess_audit.json").read_text(encoding="utf-8"))
    assert audit["funnel"]["n_events_full"] == 12 * 4 + 2
    assert audit["input"]["sha256"] == before
    assert len(audit["split"]["split_hash"]) == 64
    assert hashlib.sha256(bug.read_bytes()).hexdigest() == before  # dữ liệu gốc không đổi


def test_prepare_is_safe_to_rerun_and_a_changed_input_gets_its_own_directory(
    project, tmp_path, terminal_cases
):
    project.write_bug(terminal_cases())
    config = project.write_config()
    run_cli(["prepare", "--config", str(config)], cwd=tmp_path)
    (first,) = prepared_dirs(project)
    snapshot = {p.name: p.read_bytes() for p in first.iterdir()}

    again = run_cli(["prepare", "--config", str(config)], cwd=tmp_path)

    assert again.returncode == 0, again.stderr
    assert prepared_dirs(project) == [first]
    assert {p.name: p.read_bytes() for p in first.iterdir()} == snapshot
    assert "đã có" in again.stdout

    project.write_bug(terminal_cases(n=14))  # input khác -> fingerprint khác
    changed = run_cli(["prepare", "--config", str(config)], cwd=tmp_path)

    assert changed.returncode == 0, changed.stderr
    assert len(prepared_dirs(project)) == 2 and first in prepared_dirs(project)
    assert {p.name: p.read_bytes() for p in first.iterdir()} == snapshot  # bản cũ không bị ghi đè


def test_prepare_fails_when_a_stratum_is_too_small_and_leaves_no_partial_output(
    project, tmp_path, terminal_cases
):
    project.write_bug(terminal_cases(n=12, n_rejected=2))
    config = project.write_config()

    result = run_cli(["prepare", "--config", str(config)], cwd=tmp_path)

    assert result.returncode != 0
    assert "Rejected" in result.stderr
    assert prepared_dirs(project) == []


def test_audit_fails_clearly_on_invalid_config(project, tmp_path):
    project.write_bug(ROWS_BUG)
    project.write_story(ROWS_STORY)
    config = project.write_config(project.config({"split.test_fraction": 0.5}))

    result = run_cli(["audit", "--config", str(config)], cwd=tmp_path)

    assert result.returncode != 0
    assert "split" in result.stderr
