"""Đối chiếu tự động mọi con số trong báo cáo với artifact của run giai đoạn 2."""

from __future__ import annotations

import json

import pandas as pd

from jira_ad.process_report import artifact_values, check_report, extract_numbers


def tokens(text):
    return [n.token for n in extract_numbers(text)]


def test_extract_vietnamese_numbers_and_ignore_labels_codes_and_dates():
    text = ("CT trung vị 17,0 ngày; ngày-issue 1.928,6; PT 16,7%; 105/161 ca. "
            "Xem Ruling 80, Task 19, Quyết định 8, Chương 3, Buổi 2, B5, Ch6, notebook 07, "
            "ngày 2026-10-26, file `outputs/process/20261026T011903Z-5d4973b3`, giai đoạn 2021-06 → 2022-08.")
    assert tokens(text) == ["17,0", "1.928,6", "16,7%", "105", "161"]
    parsed = {n.token: n.value for n in extract_numbers(text)}
    assert parsed["1.928,6"] == 1928.6 and parsed["16,7%"] == 16.7


def test_check_report_flags_numbers_absent_from_artifacts(tmp_path):
    run = tmp_path / "run"
    (run / "a").mkdir(parents=True)
    frame = pd.DataFrame({"x": [17.0316, 0.1674], "note": ["39/58 ca", "khác"]})
    frame.to_csv(run / "a" / "t.csv", index=False)
    (run / "a" / "s.json").write_text(json.dumps({"share": 0.6522, "nested": {"n": 105}}), encoding="utf-8")
    (run / "manifest.json").write_text(json.dumps({"config": {"p": 0.75}, "files": {}}), encoding="utf-8")
    report = "CT 17,0 ngày; PT 16,7%; khớp 65,2%; 105 ca; 39 trên 58; P75 = 0,75; sai 99,9 và 12,34%."
    missing = check_report(report, artifact_values(run))
    assert [m.token for m in missing] == ["99,9", "12,34%"]
    assert "sai 99,9" in missing[0].context


def test_artifact_values_skip_executed_notebooks(tmp_path):
    run = tmp_path / "run"
    (run / "notebooks_executed").mkdir(parents=True)
    (run / "notebooks_executed" / "x.json").write_text(json.dumps({"v": 123.456}), encoding="utf-8")
    (run / "manifest.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
    assert check_report("giá trị 123,456", artifact_values(run))


def test_numbers_inside_code_spans_are_ignored():
    assert tokens("lệnh `uv run jira-ad process --top 60` cho 17,0 ngày") == ["17,0"]


def test_cli_check_report_returns_nonzero_when_numbers_are_missing(tmp_path, capsys):
    from jira_ad.cli import main

    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"config": {"x": 17.03}, "files": {}}), encoding="utf-8")
    good, bad = tmp_path / "good.md", tmp_path / "bad.md"
    good.write_text("CT 17,0 ngày", encoding="utf-8")
    bad.write_text("CT 18,0 ngày", encoding="utf-8")
    assert main(["check-report", "--report", str(good), "--run-dir", str(run)]) == 0
    assert main(["check-report", "--report", str(bad), "--run-dir", str(run)]) == 1
    assert "18,0" in capsys.readouterr().out
