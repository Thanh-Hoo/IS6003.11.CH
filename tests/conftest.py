"""Fixture dùng chung cho test; helper dựng repo/dữ liệu giả nằm ở `helpers.py`."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import DELETE, Project, timed_rows


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return Project(tmp_path / "repo")


@pytest.fixture
def case_rows():
    """Dựng các dòng CSV của một issue với timestamp tăng đều (mỗi bước cách nhau 1 phút)."""
    return timed_rows


@pytest.fixture
def terminal_cases(case_rows):
    """n issue kết thúc ở DONE/Rejected (xen kẽ), mỗi issue có một event nhiễu và một edit."""
    done = "update resolution to Done, update status to DONE"
    rejected = "update resolution to Canceled, update status to Rejected"

    def build(n=12, n_rejected=None):
        rows = []
        for i in range(n):
            is_rejected = (i % 2 == 1) if n_rejected is None else (i < n_rejected)
            rows += case_rows(
                f"TI-{i + 1}",
                [("SQA", "Issue created"), ("bot", "update RemoteIssueLink"),
                 ("PO", "edit summary"), ("PO", rejected if is_rejected else done)],
            )
        return rows

    return build


@pytest.fixture
def trace_of():
    """Dựng Trace từ danh sách activity (và role) cụ thể; id/status không ảnh hưởng đặc trưng."""
    from jira_ad.types import Trace

    def make(trace_id, activities, roles=None, terminal_status="DONE"):
        roles = roles if roles is not None else ["PO"] * len(activities)
        return Trace(
            trace_id=trace_id,
            parent_case_id=trace_id,
            issue_type="bug",
            activities=tuple(activities),
            roles=tuple(roles),
            event_ids=tuple(f"{trace_id}-e{i}" for i in range(len(activities))),
            timestamps=None,
            terminal_status=terminal_status,
        )

    return make


@pytest.fixture
def trace_factory():
    from jira_ad.types import Trace

    def make(case_id, terminal_status="DONE", n=3):
        return Trace(
            trace_id=case_id,
            parent_case_id=case_id,
            issue_type="bug",
            activities=tuple(f"A{i}" for i in range(n)),
            roles=tuple("PO" for _ in range(n)),
            event_ids=tuple(f"{case_id}-e{i}" for i in range(n)),
            timestamps=None,
            terminal_status=terminal_status,
        )

    return make


@pytest.fixture
def delete():
    return DELETE
