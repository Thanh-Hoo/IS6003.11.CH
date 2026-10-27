from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from jira_ad.config import load_config
from jira_ad.data import (
    AmbiguousInputError,
    DataError,
    InputNotFoundError,
    RowDataError,
    SchemaError,
    audit_events,
    discover_input_files,
    find_input_file,
    fingerprint_file,
    load_raw_events,
)

# Thứ tự dòng trong file cố ý KHÔNG theo thời gian, có role trống và hai offset -0700/-0800.
UNORDERED_ROWS = [
    ("TI-1", "2022-06-21T22:40:38.856-0700", "SQA", "Issue created"),
    ("TI-1", "2022-06-22T06:01:47.958-0700", "PO",
     "update resolution to Done, update status to DONE"),
    ("TI-1", "2022-06-22T01:14:11.285-0700", "", "edit description"),
    ("TI-2", "2022-01-10T09:00:00.000-0800", "Eng", "Issue created"),
]


def load(project, rows=None, **overrides):
    project.write_bug(UNORDERED_ROWS if rows is None else rows)
    cfg = load_config(project.write_config(project.config(overrides)))
    return load_raw_events(cfg.data, cfg.project_root)


def test_timestamps_are_converted_to_utc_from_their_own_offset(project):
    events = load(project)

    created = events.loc[events.raw_action == "Issue created"].set_index("case_id")
    ti1_utc = pd.Timestamp("2022-06-22T05:40:38.856", tz="UTC")
    ti2_utc = pd.Timestamp("2022-01-10T17:00:00", tz="UTC")
    assert created.loc["bug:TI-1", "timestamp_utc"] == ti1_utc
    assert created.loc["bug:TI-2", "timestamp_utc"] == ti2_utc
    assert str(events["timestamp_utc"].dt.tz) == "UTC"
    assert created.loc["bug:TI-1", "timestamp_raw"] == "2022-06-21T22:40:38.856-0700"


def test_rows_are_sorted_by_case_then_time_and_keep_their_file_position(project):
    events = load(project)

    ti1 = events[events.case_id == "bug:TI-1"]
    assert list(ti1.raw_action) == [
        "Issue created",
        "edit description",
        "update resolution to Done, update status to DONE",
    ]
    # source_row = vị trí 1-based của dòng dữ liệu trong CSV (không tính header)
    assert list(ti1.source_row) == [1, 3, 2]
    assert list(events.case_id.drop_duplicates()) == ["bug:TI-1", "bug:TI-2"]


def test_order_follows_the_utc_instant_not_the_local_clock_text(project):
    # 09:00 (-0800) = 17:00Z đứng SAU 09:30 (-0700) = 16:30Z, dù chuỗi văn bản của nó nhỏ hơn.
    rows = [
        ("TI-5", "2022-01-11T09:00:00.000-0800", "PO", "later_in_utc"),
        ("TI-5", "2022-01-11T09:30:00.000-0700", "PO", "earlier_in_utc"),
    ]
    events = load(project, rows)

    assert list(events.raw_action) == ["earlier_in_utc", "later_in_utc"]
    assert list(events.source_row) == [2, 1]
    assert audit_events(events)["n_cases_needing_reorder"] == 1


def test_equal_instants_with_different_offsets_are_ordered_by_source_row(project):
    rows = [
        ("TI-9", "2022-01-10T09:00:00.000-0800", "PO", "second_in_text_but_first_in_file"),
        ("TI-9", "2022-01-10T10:00:00.000-0700", "PO", "same_instant_later_row"),
        ("TI-9", "2022-01-09T10:00:00.000-0700", "PO", "earlier"),
    ]
    events = load(project, rows)

    assert list(events.raw_action) == [
        "earlier",
        "second_in_text_but_first_in_file",
        "same_instant_later_row",
    ]
    audit = audit_events(events)
    assert audit["n_tie_groups"] == 1
    assert audit["n_events_in_ties"] == 2


def test_blank_role_is_preserved_and_distinct_from_unknown(project):
    rows = [
        ("TI-1", "2022-01-01T00:00:00.000-0700", "", "Issue created"),
        ("TI-1", "2022-01-01T00:00:01.000-0700", "unknown", "edit description"),
        ("TI-1", "2022-01-01T00:00:02.000-0700", "bot", "update RemoteIssueLink"),
    ]
    events = load(project, rows)

    assert list(events.role) == ["", "unknown", "bot"]
    audit = audit_events(events)
    assert audit["n_blank_role"] == 1
    assert audit["role_counts"] == {"": 1, "unknown": 1, "bot": 1}


def test_event_table_has_the_contracted_raw_columns(project):
    events = load(project)

    assert list(events.columns) == [
        "event_id", "case_id", "issue_key", "issue_type", "timestamp_utc", "timestamp_raw",
        "source_file", "source_row", "raw_action", "role",
    ]
    assert set(events.issue_type) == {"bug"}
    assert events.case_id.str.startswith("bug:").all()
    assert set(events.source_file) == {"dataset/TIeventlogBug.csv"}


def test_bad_timestamps_report_source_row_and_cause_and_fail(project):
    rows = [
        ("TI-1", "2022-06-21T22:40:38.856-0700", "PO", "Issue created"),
        ("TI-1", "not-a-time", "PO", "edit description"),
        ("TI-1", "2022-06-21T22:40:38.856", "PO", "edit summary"),  # thiếu timezone
    ]

    with pytest.raises(RowDataError) as excinfo:
        load(project, rows)

    problems = excinfo.value.problems
    assert [p["source_row"] for p in problems] == [2, 3]
    assert "source_row=2" in str(excinfo.value)
    assert "source_row=3" in str(excinfo.value)
    assert problems[0]["cause"] != problems[1]["cause"]  # sai định dạng khác với thiếu timezone
    assert "timezone" in problems[1]["cause"]


def test_blank_issue_key_is_rejected_with_its_row(project):
    rows = [
        ("TI-1", "2022-06-21T22:40:38.856-0700", "PO", "Issue created"),
        ("", "2022-06-21T22:40:39.000-0700", "PO", "edit description"),
    ]

    with pytest.raises(RowDataError) as excinfo:
        load(project, rows)

    assert [p["source_row"] for p in excinfo.value.problems] == [2]


@pytest.mark.parametrize(
    "header, expected_word",
    [
        (("issueKey", "timestamp", "action"), "role"),  # thiếu cột
        (("issueKey", "timestamp", "role", "action", "extra"), "extra"),  # thừa cột
    ],
)
def test_schema_mismatch_is_blocked_and_names_the_column(project, header, expected_word):
    project.write_bug([], header=header)
    cfg = load_config(project.write_config())

    with pytest.raises(SchemaError, match=expected_word):
        load_raw_events(cfg.data, cfg.project_root)


def test_same_named_files_in_different_folders_are_ambiguous_unless_configured(project):
    row = [("TI-1", "2022-06-21T22:40:38.856-0700", "PO", "Issue created")]
    project.write_bug(row, rel="dataset/a/TIeventlogBug.csv")
    project.write_bug(row, rel="dataset/b/TIeventlogBug.csv")
    cfg = load_config(project.write_config())

    with pytest.raises(AmbiguousInputError) as excinfo:
        load_raw_events(cfg.data, cfg.project_root)
    assert "dataset/a/TIeventlogBug.csv" in str(excinfo.value)
    assert "dataset/b/TIeventlogBug.csv" in str(excinfo.value)

    explicit = load_config(
        project.write_config(
            project.config({"data.files.bug": "a/TIeventlogBug.csv"}), rel="configs/explicit.yaml"
        )
    )
    events = load_raw_events(explicit.data, explicit.project_root)
    assert set(events.source_file) == {"dataset/a/TIeventlogBug.csv"}


def test_top_level_file_plus_nested_duplicate_is_ambiguous(project):
    row = [("TI-1", "2022-06-21T22:40:38.856-0700", "PO", "Issue created")]
    project.write_bug(row)
    project.write_bug(row, rel="dataset/old/TIeventlogBug.csv")
    cfg = load_config(project.write_config())

    with pytest.raises(AmbiguousInputError):
        find_input_file(cfg.data, cfg.project_root, "bug")


def test_missing_file_is_reported_and_discovery_respects_recursive_flag(project):
    row = [("TI-1", "2022-06-21T22:40:38.856-0700", "PO", "Issue created")]
    project.write_bug(row, rel="dataset/sub/TIeventlogBug.csv")

    recursive = load_config(project.write_config())
    found = find_input_file(recursive.data, recursive.project_root, "bug")
    assert found.name == "TIeventlogBug.csv"

    flat_cfg = project.config({"data.recursive_discovery": False})
    flat = load_config(project.write_config(flat_cfg, rel="configs/flat.yaml"))
    with pytest.raises(InputNotFoundError, match="TIeventlogBug.csv"):
        find_input_file(flat.data, flat.project_root, "bug")


def test_cohorts_are_never_mixed(project):
    project.write_bug([("TI-1", "not-a-time", "PO", "Issue created")])  # bug hỏng
    project.write_story([("TI-7", "2022-06-21T22:40:38.856-0700", "Eng", "Issue created")])
    cfg = load_config(project.write_config(project.config({"data.cohort": "story"})))

    events = load_raw_events(cfg.data, cfg.project_root)

    assert set(events.issue_type) == {"story"}
    assert list(events.case_id) == ["story:TI-7"]
    assert set(discover_input_files(cfg.data, cfg.project_root)) == {"bug", "story"}


def test_event_ids_are_deterministic_unique_and_tied_to_file_content(project):
    rows = [
        ("TI-1", "2022-06-21T22:40:38.856-0700", "PO", "Issue created"),
        ("TI-1", "2022-06-21T22:40:39.856-0700", "PO", "edit description"),
        ("TI-1", "2022-06-21T22:40:39.856-0700", "PO", "edit description"),  # trùng hệt, giữ cả hai
    ]
    first = load(project, rows)
    again = load(project, rows)

    assert list(first.event_id) == list(again.event_id)
    assert first.event_id.is_unique
    assert len(first) == 3  # không tự xóa dòng trùng

    changed = load(project, [rows[0], rows[1], ("TI-1", "2022-06-21T22:40:39.856-0700", "PO", "X")])
    assert set(first.event_id).isdisjoint(changed.event_id)


def test_exact_duplicates_are_reported_not_removed(project):
    rows = [
        ("TI-1", "2022-06-21T22:40:38.856-0700", "PO", "Issue created"),
        ("TI-1", "2022-06-21T22:40:39.856-0700", "PO", "edit description"),
        ("TI-1", "2022-06-21T22:40:39.856-0700", "PO", "edit description"),
    ]
    audit = audit_events(load(project, rows))

    assert audit["n_events"] == 3
    assert audit["n_exact_duplicate_rows"] == 1


def test_fingerprint_matches_an_independent_hash(project):
    path = project.write_bug(UNORDERED_ROWS)

    fp = fingerprint_file(path, project.root)

    assert fp["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert fp["size_bytes"] == path.stat().st_size
    assert fp["relative_path"] == "dataset/TIeventlogBug.csv"
    assert fp["n_rows"] == len(UNORDERED_ROWS)


def test_loading_and_auditing_never_modify_the_raw_file(project):
    path = project.write_bug(UNORDERED_ROWS)
    before = (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode)

    cfg = load_config(project.write_config())
    events = load_raw_events(cfg.data, cfg.project_root)
    audit_events(events)
    fingerprint_file(path, project.root)

    assert (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode) == before


def test_audit_counts_match_the_fixture(project):
    audit = audit_events(load(project))

    assert audit["n_events"] == 4
    assert audit["n_cases"] == 2
    assert audit["events_per_case"] == {"min": 1, "median": 2.0, "max": 3, "mean": 2.0}
    assert audit["n_single_event_cases"] == 1
    assert audit["n_blank_role"] == 1
    assert audit["n_role_bot"] == 0
    assert audit["bot_share"] == 0.0
    assert audit["utc_offsets"] == {"-0700": 3, "-0800": 1}
    # TI-1 chỉ đúng thứ tự khi sắp lại (dòng 2 và 3 bị đảo); TI-2 chỉ có một event
    assert audit["n_cases_needing_reorder"] == 1
    assert audit["n_tie_groups"] == 0
    assert audit["timestamp_min_utc"] == "2022-01-10T17:00:00.000+00:00"
    assert audit["timestamp_max_utc"] == "2022-06-22T13:01:47.958+00:00"


def test_audit_of_an_empty_log_is_zero_not_a_crash(project):
    audit = audit_events(load(project, []))

    assert audit["n_events"] == 0
    assert audit["n_cases"] == 0
    assert audit["bot_share"] is None
    assert audit["timestamp_min_utc"] is None


def test_all_data_errors_share_a_base_class():
    for exc in (AmbiguousInputError, InputNotFoundError, RowDataError, SchemaError):
        assert issubclass(exc, DataError)
