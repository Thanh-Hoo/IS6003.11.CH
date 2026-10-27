from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import nbformat
import pytest
from helpers import Project, varied_rows

from jira_ad import cli
from jira_ad.analysis import MissingArtifactError, open_run
from jira_ad.config import load_config
from jira_ad.notebook_runner import (
    NotebookExecutionError,
    execute_notebook,
    execute_notebooks,
)
from jira_ad.pipeline import run_experiment

FAST = {
    "embedding.dimensions": 4, "embedding.epochs": 1, "walk.walks_per_node": 3,
    "walk.length": 8, "detector.n_estimators": 12,
}


@pytest.fixture(scope="module")
def finished(tmp_path_factory):
    project = Project(tmp_path_factory.mktemp("runner"))
    project.write_bug(varied_rows(30))
    cfg = load_config(project.write_config(project.config(FAST)))
    return project, cfg, run_experiment(cfg, now=datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC))


@pytest.fixture
def workspace(finished, tmp_path):
    """Bản sao repo + run, kèm thư mục notebooks rỗng, để thử mà không ảnh hưởng test khác."""
    project, _, run_dir = finished
    root = tmp_path / "repo"
    shutil.copytree(project.root, root)
    (root / "notebooks").mkdir()
    return root, root / run_dir.relative_to(project.root)


def write_notebook(path: Path, cells: list[str]) -> Path:
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    nb.cells = [nbformat.v4.new_code_cell(c) for c in cells]
    nbformat.write(nb, path)
    return path


def output_text(notebook, cell=0) -> str:
    return "".join(o.get("text", "") for o in notebook.cells[cell].outputs)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_notebook_runs_in_a_clean_kernel_from_the_project_root_with_the_run_selected(workspace):
    root, run_dir = workspace
    source = write_notebook(root / "notebooks" / "demo.ipynb", [
        "import os, sys\n"
        "from jira_ad.analysis import open_run\n"
        "run = open_run()\n"
        "print(run.header())\n"
        "print('CWD=' + os.getcwd())\n"
        "print('PY=' + sys.executable)\n"
        "print('HASHSEED=' + os.environ.get('PYTHONHASHSEED', ''))\n"
    ])
    before = sha(source)

    result = execute_notebook(source, open_run(run_dir), timeout=60)

    executed = nbformat.read(run_dir / "notebooks_executed" / "demo.ipynb", as_version=4)
    text = output_text(executed)
    assert run_dir.name in text and "config_hash" in text  # header nguồn gốc hiện trong notebook
    assert f"CWD={root.resolve()}" in text  # cwd = project root
    assert f"PY={sys.executable}" in text  # kernel dùng đúng Python của môi trường đang chạy
    assert "HASHSEED=0" in text
    assert sha(source) == before  # notebook nguồn không bị ghi đè bằng output
    assert result["status"] == "ok" and result["seconds"] > 0 and result["python"] == sys.executable


def test_an_error_in_any_cell_fails_the_run_and_never_produces_a_passing_copy(workspace):
    root, run_dir = workspace
    source = write_notebook(root / "notebooks" / "broken.ipynb", [
        "print('before')", "raise ValueError('boom từ cell')", "print('after')"])

    with pytest.raises(NotebookExecutionError, match="boom từ cell"):
        execute_notebook(source, open_run(run_dir), timeout=60)

    assert not (run_dir / "notebooks_executed" / "broken.ipynb").exists()
    failed = nbformat.read(run_dir / "notebooks_executed" / "broken.FAILED.ipynb", as_version=4)
    assert "before" in output_text(failed, 0)
    assert not failed.cells[2].outputs  # cell sau lỗi không được chạy: allow_errors=False


def test_a_stale_passing_copy_never_survives_a_later_failure(workspace):
    root, run_dir = workspace
    source = write_notebook(root / "notebooks" / "flaky.ipynb", ["print('ok')"])
    run = open_run(run_dir)
    execute_notebook(source, run, timeout=60)
    assert (run_dir / "notebooks_executed" / "flaky.ipynb").exists()

    write_notebook(source, ["raise RuntimeError('lần này lỗi')"])
    with pytest.raises(NotebookExecutionError):
        execute_notebook(source, run, timeout=60)

    assert not (run_dir / "notebooks_executed" / "flaky.ipynb").exists()  # không để bản pass cũ che lỗi
    assert (run_dir / "notebooks_executed" / "flaky.FAILED.ipynb").exists()

    write_notebook(source, ["print('đã sửa')"])
    execute_notebook(source, run, timeout=60)
    assert not (run_dir / "notebooks_executed" / "flaky.FAILED.ipynb").exists()


def test_a_cell_that_exceeds_the_timeout_is_an_error(workspace):
    root, run_dir = workspace
    source = write_notebook(root / "notebooks" / "slow.ipynb", ["import time\ntime.sleep(30)"])

    with pytest.raises(NotebookExecutionError, match="timeout|quá"):
        execute_notebook(source, open_run(run_dir), timeout=2)


def test_the_batch_runner_writes_an_execution_log_and_leaves_the_manifest_alone(workspace):
    root, run_dir = workspace
    write_notebook(root / "notebooks" / "02_second.ipynb", ["print('two')"])
    write_notebook(root / "notebooks" / "01_first.ipynb", ["print('one')"])
    manifest_before = sha(run_dir / "manifest.json")
    log_before = sha(run_dir / "run.log")

    results = execute_notebooks(run_dir)

    assert [r["name"] for r in results] == ["01_first.ipynb", "02_second.ipynb"]
    log = json.loads((run_dir / "notebooks_executed" / "execution_log.json").read_text("utf-8"))
    assert log["run_id"] == run_dir.name and log["python"] == sys.executable
    assert [n["status"] for n in log["notebooks"]] == ["ok", "ok"]
    assert all(n["seconds"] > 0 for n in log["notebooks"])
    assert sha(run_dir / "manifest.json") == manifest_before
    assert sha(run_dir / "run.log") == log_before  # run.log đã băm trong manifest: không được sửa
    open_run(run_dir)  # run vẫn qua kiểm fingerprint sau khi chạy notebook


def test_the_runner_refuses_a_broken_run_before_starting_any_kernel(workspace):
    root, run_dir = workspace
    write_notebook(root / "notebooks" / "demo.ipynb", ["print('x')"])
    (run_dir / "metrics.json").unlink()

    with pytest.raises(MissingArtifactError, match="metrics.json"):
        execute_notebooks(run_dir)

    assert not (run_dir / "notebooks_executed" / "execution_log.json").exists()


def test_cli_notebooks_runs_every_notebook_and_reports_a_failure(workspace, capsys):
    root, run_dir = workspace
    write_notebook(root / "notebooks" / "a.ipynb", ["print('fine')"])

    assert cli.main(["notebooks", "--run-dir", str(run_dir)]) == 0
    assert "a.ipynb" in capsys.readouterr().out

    write_notebook(root / "notebooks" / "b.ipynb", ["assert 1 == 2, 'sai giả định'"])
    assert cli.main(["notebooks", "--run-dir", str(run_dir)]) != 0
    assert "sai giả định" in capsys.readouterr().err


REPO_ROOT = Path(__file__).resolve().parents[1]
# Giai đoạn 1 (run V1 trong outputs/runs/): 01–06. Giai đoạn 2 (run trong outputs/process/): 07 trở đi.
PROJECT_NOTEBOOKS = [
    "01_data_audit.ipynb", "02_process_exploration.ipynb", "03_embedding_diagnostics.ipynb",
    "04_model_comparison.ipynb", "05_case_studies.ipynb", "06_ablations_and_limits.ipynb",
]
PROCESS_NOTEBOOKS = ["07_quantitative.ipynb", "08_norms_centrality.ipynb", "09_conformance.ipynb",
                     "10_bpr.ipynb", "11_ranking.ipynb", "12_summary_report.ipynb"]


def test_the_six_project_notebooks_run_end_to_end_on_a_small_run(workspace):
    root, run_dir = workspace
    sources = [REPO_ROOT / "notebooks" / name for name in PROJECT_NOTEBOOKS]
    assert all(s.is_file() for s in sources), "thiếu notebook trong notebooks/"
    before = {s: sha(s) for s in sources}

    results = execute_notebooks(run_dir, notebooks_dir=REPO_ROOT / "notebooks")

    # notebook giai đoạn 2 (07+) không được chạy trên run V1
    assert [r["name"] for r in results] == PROJECT_NOTEBOOKS
    for name in PROJECT_NOTEBOOKS:
        executed = nbformat.read(run_dir / "notebooks_executed" / name, as_version=4)
        errors = [o for c in executed.cells if c.cell_type == "code" for o in c.outputs
                  if o.output_type == "error"]
        assert not errors, (name, errors)
        text = "".join(o.get("text", "") for c in executed.cells if c.cell_type == "code"
                       for o in c.outputs if o.output_type == "stream")
        assert run_dir.name in text and "config_hash" in text, name  # mỗi notebook hiện nguồn gốc
        assert any(o.output_type in ("display_data", "execute_result") for c in executed.cells
                   if c.cell_type == "code" for o in c.outputs), name
    assert {s: sha(s) for s in sources} == before  # notebook nguồn không bị ghi đè bằng output
    assert any((run_dir / "figures").glob("nb0*.png"))
    open_run(run_dir)  # chạy notebook không làm hỏng fingerprint của run


def test_the_first_code_cell_of_every_project_notebook_runs_when_opened_by_hand(
    workspace, monkeypatch, tmp_path
):
    """Tái hiện VSCode/Jupyter mở tay: kernel không có JIRA_AD_RUN_DIR, cwd = notebooks/ (lỗi đã gặp)."""
    from nbclient import NotebookClient

    root, run_dir = workspace
    shutil.copy(root / "configs" / "test.yaml", root / "configs" / "baseline.yaml")
    monkeypatch.delenv("JIRA_AD_RUN_DIR", raising=False)
    spec_dir = tmp_path / "jupyter" / "kernels" / "by-hand"
    spec_dir.mkdir(parents=True)
    (spec_dir / "kernel.json").write_text(json.dumps({
        "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": "by-hand", "language": "python"}), encoding="utf-8")  # cố ý không có env nào
    monkeypatch.setenv("JUPYTER_PATH", str(tmp_path / "jupyter"))
    notebooks = root / "notebooks"

    for name in PROJECT_NOTEBOOKS:
        notebook = nbformat.read(REPO_ROOT / "notebooks" / name, as_version=4)
        first = next(i for i, c in enumerate(notebook.cells) if c.cell_type == "code")
        notebook.cells = notebook.cells[: first + 1]
        NotebookClient(notebook, kernel_name="by-hand", timeout=120, allow_errors=False,
                       resources={"metadata": {"path": str(notebooks)}}).execute()
        text = "".join(o.get("text", "") for o in notebook.cells[first].outputs
                       if o.output_type == "stream")
        assert run_dir.name in text and "tự động" in text, name  # header nêu run đã được chọn tự động


# ----------------------------------------------------------------- notebook giai đoạn 2 (07+)


@pytest.fixture(scope="module")
def process_workspace(tmp_path_factory):
    from helpers import write_process_project
    from test_status_log import ALL_ROWS

    from jira_ad.process_run import run_process

    project = Project(tmp_path_factory.mktemp("proc_nb") / "repo")
    config = write_process_project(project, ALL_ROWS, overrides={"reference_model.approved": True})
    out = run_process(config, now=datetime(2026, 10, 26, 8, 0, 0, tzinfo=UTC))
    return project.root, out


def test_process_notebooks_run_end_to_end_on_a_small_process_run(process_workspace):
    from jira_ad.notebook_runner import execute_process_notebooks

    root, out = process_workspace
    sources = [REPO_ROOT / "notebooks" / name for name in PROCESS_NOTEBOOKS]
    assert all(s.is_file() for s in sources), "thiếu notebook giai đoạn 2 trong notebooks/"
    before = {s: sha(s) for s in sources}
    results = execute_process_notebooks(out, notebooks_dir=REPO_ROOT / "notebooks")
    assert [r["name"] for r in results][: len(PROCESS_NOTEBOOKS)] == PROCESS_NOTEBOOKS
    assert not any(r["name"] in PROJECT_NOTEBOOKS for r in results)
    for name in PROCESS_NOTEBOOKS:
        executed = nbformat.read(out / "notebooks_executed" / name, as_version=4)
        headings = [c.source.splitlines()[0] for c in executed.cells if c.cell_type == "markdown"]
        for part in ("1.", "2.", "3.", "4.", "5.", "6.", "7."):
            assert any(h.startswith(f"## {part}") for h in headings), (name, part)
        text = "".join(o.get("text", "") for c in executed.cells if c.cell_type == "code"
                       for o in c.outputs if o.output_type == "stream")
        assert out.name in text and "config_hash" in text, name
        assert any(o.output_type == "display_data" and "image/png" in o.get("data", {})
                   for c in executed.cells if c.cell_type == "code" for o in c.outputs), name
    assert {s: sha(s) for s in sources} == before
    log = json.loads((out / "notebooks_executed" / "execution_log.json").read_text(encoding="utf-8"))
    assert log["run_id"] == out.name


def test_cli_notebooks_dispatches_process_runs(process_workspace, capsys, monkeypatch):
    root, out = process_workspace
    monkeypatch.chdir(root)
    shutil.copytree(REPO_ROOT / "notebooks", root / "notebooks", dirs_exist_ok=True)
    assert cli.main(["notebooks", "--run-dir", str(out), "--only", "07_quantitative"]) == 0
    assert "07_quantitative.ipynb" in capsys.readouterr().out


def test_first_code_cell_of_process_notebooks_runs_when_opened_by_hand(process_workspace, monkeypatch,
                                                                       tmp_path):
    from nbclient import NotebookClient

    root, out = process_workspace
    monkeypatch.delenv("JIRA_AD_PROCESS_RUN_DIR", raising=False)
    spec_dir = tmp_path / "jupyter" / "kernels" / "by-hand"
    spec_dir.mkdir(parents=True)
    (spec_dir / "kernel.json").write_text(json.dumps({
        "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": "by-hand", "language": "python"}), encoding="utf-8")
    monkeypatch.setenv("JUPYTER_PATH", str(tmp_path / "jupyter"))
    (root / "notebooks").mkdir(exist_ok=True)
    for name in PROCESS_NOTEBOOKS:
        notebook = nbformat.read(REPO_ROOT / "notebooks" / name, as_version=4)
        first = next(i for i, c in enumerate(notebook.cells) if c.cell_type == "code")
        notebook.cells = notebook.cells[: first + 1]
        NotebookClient(notebook, kernel_name="by-hand", timeout=120, allow_errors=False,
                       resources={"metadata": {"path": str(root / "notebooks")}}).execute()
        text = "".join(o.get("text", "") for o in notebook.cells[first].outputs if o.output_type == "stream")
        assert out.name in text and "tự động" in text, name
