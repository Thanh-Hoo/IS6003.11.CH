from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime

import pandas as pd
import pytest
from helpers import Project, varied_rows

from jira_ad.analysis import (
    FingerprintMismatchError,
    MissingArtifactError,
    NotebookInputError,
    open_run,
)
from jira_ad.config import load_config
from jira_ad.pipeline import config_hash, run_experiment

FAST = {
    "embedding.dimensions": 4, "embedding.epochs": 1, "walk.walks_per_node": 3,
    "walk.length": 8, "detector.n_estimators": 12,
}


@pytest.fixture(scope="module")
def finished(tmp_path_factory):
    project = Project(tmp_path_factory.mktemp("nb"))
    project.write_bug(varied_rows(30))
    cfg = load_config(project.write_config(project.config(FAST)))
    run_dir = run_experiment(cfg, now=datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC))
    return project, cfg, run_dir


@pytest.fixture
def copy_of_run(finished, tmp_path):
    """Bản sao độc lập của repo + run để phá hoại mà không ảnh hưởng test khác."""
    project, _, run_dir = finished
    root = tmp_path / "repo"
    shutil.copytree(project.root, root)
    return root, root / run_dir.relative_to(project.root)


def test_a_valid_run_opens_and_exposes_its_provenance(finished, capsys):
    project, cfg, run_dir = finished

    run = open_run(run_dir)

    assert run.run_id == run_dir.name and run.manifest["status"] == "completed"
    assert run.project_root == project.root
    assert run.cfg == cfg  # dựng lại đúng cấu hình đã resolve của run
    assert config_hash(run.cfg) == run.manifest["config_hash"]
    header = run.header()
    for expected in (run.run_id, run.manifest["config_hash"][:12],
                     run.manifest["input_files"][0]["sha256"][:12]):
        assert expected in header
    assert not capsys.readouterr().out  # open_run không in; notebook tự in header()


def test_the_run_is_found_through_the_environment_when_no_path_is_given(finished, monkeypatch):
    _, _, run_dir = finished
    monkeypatch.setenv("JIRA_AD_RUN_DIR", str(run_dir))

    assert open_run().run_id == run_dir.name


def test_without_a_run_the_error_names_the_command_to_create_one(monkeypatch, tmp_path):
    monkeypatch.delenv("JIRA_AD_RUN_DIR", raising=False)
    monkeypatch.chdir(tmp_path)  # không có pyproject.toml ở đây: không có run nào để chọn tự động

    with pytest.raises(NotebookInputError, match=r"jira-ad notebooks --run-dir"):
        open_run()


def test_a_directory_without_a_manifest_is_not_silently_replaced_by_a_cache(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    empty = tmp_path / "outputs" / "runs" / "R"
    empty.mkdir(parents=True)

    with pytest.raises(MissingArtifactError, match=r"uv run jira-ad run --config"):
        open_run(empty)


def test_a_missing_artifact_names_the_file_and_the_exact_command(copy_of_run):
    root, run_dir = copy_of_run
    (run_dir / "scores" / "originals.parquet").unlink()

    with pytest.raises(MissingArtifactError) as excinfo:
        open_run(run_dir)

    message = str(excinfo.value)
    assert "scores/originals.parquet" in message
    assert "uv run jira-ad run --config configs/test.yaml" in message


def test_a_modified_artifact_fails_on_its_fingerprint(copy_of_run):
    _, run_dir = copy_of_run
    target = run_dir / "metrics_by_type.csv"
    target.write_text(target.read_text(encoding="utf-8").replace("0.5", "0.6", 1),
                      encoding="utf-8")

    with pytest.raises(FingerprintMismatchError, match="metrics_by_type.csv"):
        open_run(run_dir)


def test_input_data_changed_after_the_run_is_rejected(copy_of_run):
    root, run_dir = copy_of_run
    csv = root / "dataset" / "TIeventlogBug.csv"
    csv.write_text(csv.read_text(encoding="utf-8") + '"TI-999","2022-01-01T00:00:00.000-0700",'
                   '"PO","edit summary"\n', encoding="utf-8")

    with pytest.raises(FingerprintMismatchError, match="TIeventlogBug.csv"):
        open_run(run_dir)
    assert open_run(run_dir, verify_inputs=False).run_id == run_dir.name  # tắt kiểm tra rõ ràng


def test_a_run_that_did_not_complete_is_refused(copy_of_run):
    _, run_dir = copy_of_run
    path = run_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["status"] = "failed"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(NotebookInputError, match="failed"):
        open_run(run_dir)


def test_tampered_resolved_config_no_longer_matches_the_config_hash(copy_of_run):
    _, run_dir = copy_of_run
    path = run_dir / "config.resolved.yaml"
    text = path.read_text(encoding="utf-8").replace("n_estimators: 12", "n_estimators: 13")
    path.write_text(text, encoding="utf-8")
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["config.resolved.yaml"]["sha256"] = hashlib.sha256(
        path.read_bytes()).hexdigest()  # qua được kiểm tra artifact, nhưng hash cấu hình thì không
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(FingerprintMismatchError, match="config_hash"):
        open_run(run_dir)


def test_artifact_readers_and_savers_write_outside_the_verified_set(finished, tmp_path):
    project, _, run_dir = finished
    run = open_run(run_dir)

    table = run.save_table(pd.DataFrame({"a": [1, 2]}), "demo_table")
    assert table == run_dir / "tables" / "demo_table.csv" and table.is_file()
    assert run.read_csv("metrics_by_type.csv").shape[0] > 0
    assert run.read_parquet("scores/originals.parquet").shape[0] > 0
    assert run.read_json("metrics.json")["primary_split"] == "test"
    assert open_run(run_dir).run_id == run.run_id  # file mới không làm hỏng việc kiểm tra


def test_bundles_are_loaded_once_and_come_from_the_verified_run(finished):
    _, _, run_dir = finished
    run = open_run(run_dir)

    first, second = run.bundle("D_hybrid"), run.bundle("D_hybrid")

    assert first is second and first.method == "D_hybrid"
    with pytest.raises(NotebookInputError, match="Z_unknown"):
        run.bundle("Z_unknown")


def test_show_saves_the_figure_and_its_data_and_displays_a_png(finished, monkeypatch):
    from matplotlib.figure import Figure

    _, _, run_dir = finished
    run = open_run(run_dir)
    shown = []
    monkeypatch.setattr("IPython.display.display", lambda obj: shown.append(obj))
    fig = Figure()
    fig.subplots().plot([0, 1], [0, 1])

    path = run.show(fig, "demo_figure", pd.DataFrame({"x": [0, 1], "y": [0, 1]}))

    assert path == run_dir / "figures" / "demo_figure.png" and path.stat().st_size > 0
    assert (run_dir / "tables" / "demo_figure_data.csv").is_file()
    assert len(shown) == 1 and type(shown[0]).__name__ == "Image"
    open_run(run_dir)  # hình/bảng mới nằm ngoài tập artifact đã băm nên run vẫn hợp lệ


# ======================== mở notebook bằng tay (VSCode/Jupyter): không biến môi trường, cwd = notebooks/


def _baseline_workspace(copy_of_run, monkeypatch):
    """Repo tạm có `configs/baseline.yaml` đúng bằng cấu hình đã chạy; cwd = notebooks/, không đặt biến."""
    root, run_dir = copy_of_run
    shutil.copy(root / "configs" / "test.yaml", root / "configs" / "baseline.yaml")
    (root / "notebooks").mkdir(exist_ok=True)
    monkeypatch.delenv("JIRA_AD_RUN_DIR", raising=False)
    monkeypatch.chdir(root / "notebooks")
    return root, run_dir


def _clone_run(run_dir, name, *, started=None, status=None):
    """Bản sao của run (cùng artifact, cùng fingerprint) với thời điểm bắt đầu/trạng thái khác."""
    clone = run_dir.parent / name
    shutil.copytree(run_dir, clone)
    manifest = json.loads((clone / "manifest.json").read_text(encoding="utf-8"))
    manifest["run_id"] = name
    if started:
        manifest["started_at_utc"] = started
    if status:
        manifest["status"] = status
    (clone / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return clone


def test_opened_by_hand_the_newest_run_matching_the_current_baseline_config_is_used(
    copy_of_run, monkeypatch
):
    root, run_dir = _baseline_workspace(copy_of_run, monkeypatch)
    newer = _clone_run(run_dir, "20261016T130000Z-newer", started="2026-10-16T13:00:00+00:00")

    run = open_run()

    assert run.run_dir == newer.resolve()
    assert run.project_root == root
    assert "tự động" in run.selection and "configs/baseline.yaml" in run.selection
    assert "tự động" in run.header()  # không âm thầm: notebook luôn in run nào đã được chọn


def test_an_explicit_run_always_beats_the_automatic_choice(copy_of_run, monkeypatch):
    _, run_dir = _baseline_workspace(copy_of_run, monkeypatch)
    _clone_run(run_dir, "20261016T130000Z-newer", started="2026-10-16T13:00:00+00:00")
    monkeypatch.setenv("JIRA_AD_RUN_DIR", str(run_dir))

    run = open_run()

    assert run.run_dir == run_dir.resolve() and "tự động" not in run.selection
    assert run_dir.name in run.header()


def test_a_relative_run_path_is_resolved_from_the_project_root_not_the_notebook_folder(
    copy_of_run, monkeypatch
):
    root, run_dir = _baseline_workspace(copy_of_run, monkeypatch)
    monkeypatch.setenv("JIRA_AD_RUN_DIR", run_dir.relative_to(root).as_posix())

    assert open_run().run_dir == run_dir.resolve()


def test_a_run_made_with_an_older_baseline_config_is_never_used_silently(copy_of_run, monkeypatch):
    root, _ = _baseline_workspace(copy_of_run, monkeypatch)
    text = (root / "configs" / "baseline.yaml").read_text(encoding="utf-8")
    (root / "configs" / "baseline.yaml").write_text(text.replace("q: 1.0", "q: 2.0"), encoding="utf-8")

    with pytest.raises(NotebookInputError, match=r"uv run jira-ad run --config configs/baseline.yaml"):
        open_run()


def test_runs_that_did_not_complete_are_not_candidates(copy_of_run, monkeypatch):
    _, run_dir = _baseline_workspace(copy_of_run, monkeypatch)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["status"] = "failed"
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(NotebookInputError, match=r"jira-ad run --config configs/baseline.yaml"):
        open_run()


def test_without_a_baseline_config_the_error_says_so_and_how_to_pick_a_run(copy_of_run, monkeypatch):
    root, _ = _baseline_workspace(copy_of_run, monkeypatch)
    (root / "configs" / "baseline.yaml").unlink()

    with pytest.raises(NotebookInputError) as excinfo:
        open_run()
    assert "Không có configs/baseline.yaml" in str(excinfo.value)
    assert "JIRA_AD_RUN_DIR" in str(excinfo.value)


def test_the_automatically_chosen_run_still_passes_every_fingerprint_check(copy_of_run, monkeypatch):
    root, run_dir = _baseline_workspace(copy_of_run, monkeypatch)
    victim = run_dir / "metrics.json"
    victim.write_text(victim.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(FingerprintMismatchError, match="metrics.json"):
        open_run()

