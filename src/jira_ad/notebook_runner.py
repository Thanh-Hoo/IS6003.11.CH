"""Chạy notebook bằng nbclient trên một run đã hoàn tất (spec §7).

Quy tắc: kernel là chính Python đang chạy lệnh (cùng môi trường dự án), cwd = project root,
`allow_errors=False`, timeout hữu hạn theo cấu hình, bản đã thực thi lưu vào
`<run>/notebooks_executed/` và notebook nguồn không bị ghi đè. Run phải qua kiểm fingerprint
trước khi mở bất kỳ kernel nào.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError, CellTimeoutError

from jira_ad.analysis import RUN_ENV, NotebookInputError, RunArtifacts, open_run
from jira_ad.process_analysis import PROCESS_RUN_ENV, open_process_run

STARTUP_TIMEOUT = 60
HASH_SEED = "0"  # PYTHONHASHSEED đặt từ lúc kernel khởi động (spec §5.3)
KERNEL_NAME = "jira-ad"
FIRST_PROCESS_NOTEBOOK = 7  # 01–06: run V1 (outputs/runs/); 07 trở đi: run giai đoạn 2 (outputs/process/)
PROCESS_TIMEOUT = 300


def notebook_number(path: Path) -> int | None:
    """Số thứ tự ở đầu tên notebook (`07_quantitative.ipynb` → 7); không có số ⇒ None."""
    head = Path(path).name.split("_", 1)[0]
    return int(head) if head.isdigit() else None


def is_process_notebook(path: Path) -> bool:
    number = notebook_number(path)
    return number is not None and number >= FIRST_PROCESS_NOTEBOOK


class NotebookExecutionError(RuntimeError):
    """Một notebook báo lỗi hoặc quá thời hạn; không có bản 'đã thực thi thành công' nào được ghi."""


@contextlib.contextmanager
def _project_kernel(run, env_var: str = RUN_ENV) -> Iterator[str]:
    """Đăng ký tạm một kernelspec chạy ĐÚNG `sys.executable` (môi trường dự án) và trả tên của nó.

    Dùng kernelspec thay vì truyền `km=` tự dựng cho nbclient: thực nghiệm cho thấy khi truyền
    `km`, nbclient bỏ qua `timeout` (cell ngủ 8 giây không bị cắt dù `timeout=2`).
    """
    with tempfile.TemporaryDirectory(prefix="jira-ad-kernel-") as tmp:
        spec_dir = Path(tmp) / "kernels" / KERNEL_NAME
        spec_dir.mkdir(parents=True)
        (spec_dir / "kernel.json").write_text(json.dumps({
            "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "display_name": "jira-ad", "language": "python",
            "env": {env_var: str(run.run_dir), "PYTHONHASHSEED": HASH_SEED},
        }), encoding="utf-8")
        previous = os.environ.get("JUPYTER_PATH")
        os.environ["JUPYTER_PATH"] = tmp + (os.pathsep + previous if previous else "")
        try:
            yield KERNEL_NAME
        finally:
            if previous is None:
                os.environ.pop("JUPYTER_PATH", None)
            else:
                os.environ["JUPYTER_PATH"] = previous


def execute_notebook(source: Path, run: RunArtifacts, *, timeout: int,
                     env_var: str = RUN_ENV) -> dict[str, Any]:
    """Thực thi một notebook từ kernel sạch; lỗi bất kỳ cell nào là lỗi thật (không nuốt)."""
    source = Path(source)
    out_dir = run.run_dir / "notebooks_executed"
    out_dir.mkdir(exist_ok=True)
    passed, failed = out_dir / f"{source.stem}.ipynb", out_dir / f"{source.stem}.FAILED.ipynb"
    passed.unlink(missing_ok=True)  # bản cũ không được che lỗi của lần chạy này
    failed.unlink(missing_ok=True)
    notebook = nbformat.read(source, as_version=4)
    started = time.perf_counter()
    with _project_kernel(run, env_var) as kernel_name:
        client = NotebookClient(
            notebook, kernel_name=kernel_name, timeout=timeout, startup_timeout=STARTUP_TIMEOUT,
            allow_errors=False, record_timing=True,
            resources={"metadata": {"path": str(run.project_root)}},
        )
        try:
            client.execute()
        except (CellExecutionError, CellTimeoutError, TimeoutError) as exc:
            nbformat.write(client.nb, failed)
            if isinstance(exc, CellExecutionError):
                detail = f"{exc.ename}: {exc.evalue}"
            else:
                detail = f"quá thời hạn (timeout) {timeout}s cho một cell"
            raise NotebookExecutionError(
                f"{source.name} thất bại — {detail}; bản chạy dở: {failed.name}"
            ) from exc
    seconds = time.perf_counter() - started
    notebook.metadata["jira_ad"] = {
        "run_id": run.run_id, "config_hash": run.manifest["config_hash"],
        "executed_with": sys.executable,
    }
    nbformat.write(notebook, passed)
    return {"name": source.name, "status": "ok", "seconds": round(seconds, 3),
            "python": sys.executable, "executed_path": str(passed)}


def execute_notebooks(
    run_dir: Path, notebooks_dir: Path | None = None, timeout: int | None = None,
    only: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Mở run (kiểm fingerprint), chạy lần lượt các notebook, ghi `execution_log.json`.

    Nhật ký chạy nằm ở `notebooks_executed/execution_log.json`; không ghi vào `run.log` hay manifest
    vì chúng đã được băm và phải giữ nguyên để run còn qua kiểm fingerprint.
    """
    run = open_run(run_dir)
    directory = Path(notebooks_dir) if notebooks_dir else run.project_root / "notebooks"
    sources = [s for s in sorted(directory.glob("*.ipynb")) if not is_process_notebook(s)]
    if only:
        sources = [s for s in sources if s.name in set(only) or s.stem in set(only)]
    if not sources:
        raise NotebookInputError(f"Không có notebook nào để chạy trong {directory}")
    limit = timeout if timeout is not None else run.cfg.notebooks.timeout_seconds
    started = datetime.now(UTC).isoformat(timespec="seconds")
    results = [execute_notebook(source, run, timeout=limit) for source in sources]
    log = {"run_id": run.run_id, "started_at_utc": started, "python": sys.executable,
           "timeout_seconds": limit, "notebooks": results}
    (run.run_dir / "notebooks_executed" / "execution_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return results


def execute_process_notebooks(
    run_dir: Path, notebooks_dir: Path | None = None, timeout: int | None = None,
    only: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Notebook giai đoạn 2 (07+) trên một run `outputs/process/<run>` đã qua kiểm fingerprint."""
    run = open_process_run(run_dir)
    directory = Path(notebooks_dir) if notebooks_dir else run.project_root / "notebooks"
    sources = [s for s in sorted(directory.glob("*.ipynb")) if is_process_notebook(s)]
    if only:
        sources = [s for s in sources if s.name in set(only) or s.stem in set(only)]
    if not sources:
        raise NotebookInputError(f"Không có notebook giai đoạn 2 (07+) nào để chạy trong {directory}")
    limit = timeout if timeout is not None else PROCESS_TIMEOUT
    started = datetime.now(UTC).isoformat(timespec="seconds")
    results = [execute_notebook(s, run, timeout=limit, env_var=PROCESS_RUN_ENV) for s in sources]
    log = {"run_id": run.run_id, "started_at_utc": started, "python": sys.executable,
           "timeout_seconds": limit, "notebooks": results}
    (run.run_dir / "notebooks_executed" / "execution_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return results


def is_process_run(run_dir: Path) -> bool:
    """Run giai đoạn 2 nhận ra qua manifest: cấu hình có section `states` (run V1 không có)."""
    manifest = Path(run_dir) / "manifest.json"
    if not manifest.is_file():
        return False
    config = json.loads(manifest.read_text(encoding="utf-8")).get("config")
    return isinstance(config, dict) and "states" in config
