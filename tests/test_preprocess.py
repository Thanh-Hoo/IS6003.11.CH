from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest
import yaml

from jira_ad.config import load_config
from jira_ad.data import load_raw_events
from jira_ad.preprocess import (
    ActionRulesError,
    build_core_view,
    build_traces,
    classify_action,
    load_action_rules,
    mapping_coverage,
    normalize_events,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIONS_FILE = REPO_ROOT / "configs" / "actions.yaml"
MOVE_ROW = (
    "update project to TI-TI, update status to To Do, "
    "update Workflow to SW Development Story Workflow, edit Key"
)
DONE_ROW = "update resolution to Done, update status to DONE"
REOPEN_ROW = "remove resolution, update status to In Progress"
REJECT_ROW = "update resolution to Canceled, update status to Rejected"


@pytest.fixture
def rules():
    return load_action_rules(ACTIONS_FILE)


def prepare(project, rows, **overrides):
    """CSV -> raw events -> normalized events, đi qua đúng đường config như CLI."""
    project.write_bug(rows)
    cfg = load_config(project.write_config(project.config(overrides)))
    raw = load_raw_events(cfg.data, cfg.project_root)
    return cfg, raw, normalize_events(raw, cfg.preprocess)


# ----------------------------------------------------------------------------- ánh xạ action

CLASSIFY_CASES = [
    ("Issue created", "CREATE", ()),
    ("update status to In Progress", "STATUS_In Progress", ()),
    ("update status to To Investigate", "STATUS_To Investigate", ()),
    (DONE_ROW, "STATUS_DONE", ("UPDATE_RESOLUTION",)),
    (REOPEN_ROW, "STATUS_In Progress", ("REMOVE_RESOLUTION",)),
    (REJECT_ROW, "STATUS_Rejected", ("UPDATE_RESOLUTION",)),
    ("add RemoteIssueLink to Commit", "LINK_COMMIT", ()),
    ("remove RemoteIssueLink to Commit", "LINK_COMMIT", ()),
    ("add RemoteIssueLink to Merge request", "LINK_MERGE_REQUEST", ()),
    ("update RemoteIssueLink", "UPDATE_EXTERNAL_LINK", ()),
    ("remove assignee", "REMOVE_ASSIGNEE", ()),
    ("update assignee", "UPDATE_ASSIGNEE", ()),
    ("add Sprint", "ADD_SPRINT", ()),
    # dấu phẩy nằm TRONG giá trị không được cắt mệnh đề
    ("update Fix Version to removed, added", "UPDATE_FIX_VERSION", ()),
    ("update Fix Version to added, removed", "UPDATE_FIX_VERSION", ()),
    (
        "add assignee, update Backlog Classification to Business Value, add Fix Version",
        "ADD_ASSIGNEE",  # assignee đứng trước fix version trong thứ tự ưu tiên
        ("UPDATE_BACKLOG_CLASSIFICATION", "ADD_FIX_VERSION"),
    ),
    (
        "update Backlog Classification to Business Value, add Fix Version",
        "ADD_FIX_VERSION",  # fix version đứng trước field khác
        ("UPDATE_BACKLOG_CLASSIFICATION",),
    ),
    (
        "update Fix Version to removed, added, update project to TI-TI, edit Key",
        "UPDATE_FIX_VERSION",
        ("UPDATE_PROJECT", "EDIT_KEY"),
    ),
    ("edit description", "EDIT_DESCRIPTION", ()),
    ("edit IssueParentAssociation", "EDIT_ISSUEPARENTASSOCIATION", ()),
    ("update Rank to Ranked higher", "UPDATE_RANK", ()),
    ("update Rank to Ranked lower", "UPDATE_RANK", ()),  # hướng không phải một activity khác
    ("update Backlog Classification to Technical Debt", "UPDATE_BACKLOG_CLASSIFICATION", ()),
    ("update Backlog Classification to Support", "UPDATE_BACKLOG_CLASSIFICATION", ()),
    ("add link to relates to", "ADD_ISSUE_LINK", ()),
    ("remove link to is cloned by", "REMOVE_ISSUE_LINK", ()),
    ("update project to TI-TI, edit Key", "UPDATE_PROJECT", ("EDIT_KEY",)),
    (MOVE_ROW, "STATUS_To Do", ("UPDATE_PROJECT", "UPDATE_WORKFLOW", "EDIT_KEY")),
    (
        "update TEST FIELD OBJECT to , " + MOVE_ROW,  # mệnh đề có giá trị rỗng
        "STATUS_To Do",
        ("UPDATE_TEST_FIELD_OBJECT", "UPDATE_PROJECT", "UPDATE_WORKFLOW", "EDIT_KEY"),
    ),
    ("update labels to ", "UPDATE_LABELS", ()),
    ("update Blocking for Release to Yes", "UPDATE_BLOCKING_FOR_RELEASE", ()),
    (
        "remove Sprint, add Story Points, update issuetype to Bug, remove Parent, "
        "update Workflow to Copy of SW Development Bug Workflow",
        "REMOVE_SPRINT",
        ("ADD_STORY_POINTS", "UPDATE_ISSUETYPE", "REMOVE_PARENT", "UPDATE_WORKFLOW"),
    ),
    ("update project to Automation - AutoStar Platform, edit Key", "UPDATE_PROJECT", ("EDIT_KEY",)),
    ("Something no rule was written for", "OTHER_ACTION", ()),
]


@pytest.mark.parametrize("raw_action, activity, secondary", CLASSIFY_CASES)
def test_classify_action_follows_the_documented_priority(rules, raw_action, activity, secondary):
    info = classify_action(raw_action, rules)

    assert info.activity == activity
    assert info.secondary == secondary


def test_only_unmatched_text_falls_back_and_is_flagged(rules):
    assert classify_action("Something no rule was written for", rules).is_fallback is True
    assert classify_action("edit description", rules).is_fallback is False


def test_status_value_is_kept_verbatim_only_for_status_rows(rules):
    assert classify_action(DONE_ROW, rules).status_value == "DONE"
    investigate = classify_action("update status to To Investigate", rules)
    assert investigate.status_value == "To Investigate"
    assert classify_action("edit description", rules).status_value is None
    assert classify_action("update resolution to Done", rules).status_value is None


def test_rules_hash_is_the_sha256_of_the_file_bytes(rules):
    assert rules.sha256 == hashlib.sha256(ACTIONS_FILE.read_bytes()).hexdigest()


def _write_rules(tmp_path, mutate):
    data = yaml.safe_load(ACTIONS_FILE.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "bad_actions.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda d: d["rules"][1].update(match="update status to (?P<status>"), "status"),
        (lambda d: d["rules"][1].update(activity="STATUS_{state}"), "state"),
        (lambda d: d["rules"][2].update(name="create"), "create"),
        (lambda d: d.update(surprise=1), "surprise"),
        (lambda d: d.pop("fallback_activity"), "fallback_activity"),
        (lambda d: d.pop("noise_policies"), "noise_policies"),
        # features.py nhận token role thiếu như một hằng số của giao thức, nên YAML không được đổi
        (lambda d: d.update(missing_role="NO_ROLE"), "missing_role"),
    ],
)
def test_malformed_rules_are_rejected_with_the_culprit_named(tmp_path, mutate, expected):
    with pytest.raises(ActionRulesError, match=expected):
        load_action_rules(_write_rules(tmp_path, mutate))


# ------------------------------------------------------------------------------ normalize_events


def test_each_csv_row_stays_exactly_one_event(project, case_rows):
    rows = case_rows(
        "TI-1",
        [("SQA", "Issue created"), ("PO", DONE_ROW), ("PO", MOVE_ROW), ("Eng", "edit description")],
    )
    _, raw, events = prepare(project, rows)

    assert len(events) == len(raw) == 4
    assert list(events.event_id) == list(raw.event_id)


def test_status_row_uses_the_status_as_activity_and_keeps_other_fields(project, case_rows):
    rows = case_rows("TI-1", [("SQA", "Issue created"), ("PO", DONE_ROW), ("PO", MOVE_ROW)])
    _, _, events = prepare(project, rows)

    done = events.iloc[1]
    assert done.activity == "STATUS_DONE"
    assert bool(done.has_status_update) is True
    assert done.status_value == "DONE"
    assert done.secondary_changes == "UPDATE_RESOLUTION"
    assert events.iloc[2].secondary_changes == "UPDATE_PROJECT|UPDATE_WORKFLOW|EDIT_KEY"
    created = events.iloc[0]
    assert created.activity == "CREATE"
    assert bool(created.has_status_update) is False
    assert pd.isna(created.status_value)
    assert created.secondary_changes == ""


def test_blank_unknown_and_bot_roles_stay_distinct(project, case_rows):
    rows = case_rows(
        "TI-1",
        [("", "Issue created"), ("unknown", "edit description"), ("bot", "update RemoteIssueLink"),
         ("PO", "edit summary")],
    )
    _, raw, events = prepare(project, rows)

    assert list(raw.role) == ["", "unknown", "bot", "PO"]  # raw giữ nguyên
    assert list(events.role) == ["__MISSING_ROLE__", "unknown", "bot", "PO"]
    assert list(events.is_bot) == [False, False, True, False]


def test_normalization_is_independent_of_input_row_order_and_leaves_input_intact(
    project, case_rows
):
    rows = case_rows("TI-1", [("SQA", "Issue created"), ("PO", DONE_ROW), ("Eng", "edit summary")])
    rows += case_rows("TI-2", [("SQA", "Issue created"), ("PO", REJECT_ROW)])
    cfg, raw, events = prepare(project, rows)
    shuffled = raw.sample(frac=1.0, random_state=7)
    snapshot = shuffled.copy()

    again = normalize_events(shuffled, cfg.preprocess)

    pd.testing.assert_frame_equal(again.reset_index(drop=True), events.reset_index(drop=True))
    pd.testing.assert_frame_equal(shuffled, snapshot)


def test_mapping_coverage_accounts_for_every_event_and_flags_fallbacks(project, case_rows):
    rows = case_rows(
        "TI-1",
        [("SQA", "Issue created"), ("PO", "edit description"), ("PO", "edit description"),
         ("PO", "Something no rule was written for"), ("PO", DONE_ROW)],
    )
    _, _, events = prepare(project, rows)

    coverage = mapping_coverage(events)

    assert coverage["n_events"].sum() == len(events)
    by_action = coverage.set_index("raw_action")
    assert by_action.loc["edit description", "n_events"] == 2
    assert bool(by_action.loc["Something no rule was written for", "is_fallback"]) is True
    assert bool(by_action.loc["edit description", "is_fallback"]) is False
    assert set(coverage.columns) >= {"raw_action", "activity", "secondary_changes", "rule",
                                     "is_fallback", "n_events", "n_cases"}


# ----------------------------------------------------------------------------------- core view


def reopen_case(case_rows, issue="TI-1"):
    return case_rows(
        issue,
        [("SQA", "Issue created"), ("PO", DONE_ROW), ("PO", REOPEN_ROW), ("PO", DONE_ROW),
         ("Eng", "edit description")],
    )


def test_reopen_loop_is_kept_and_the_edit_after_the_last_terminal_is_dropped(project, case_rows):
    cfg, _, events = prepare(project, reopen_case(case_rows))

    (trace,) = build_traces(events, cfg.preprocess)

    assert trace.activities == ("CREATE", "STATUS_DONE", "STATUS_In Progress", "STATUS_DONE")
    assert trace.roles == ("SQA", "PO", "PO", "PO")
    assert trace.terminal_status == "DONE"
    assert trace.event_ids == tuple(events.event_id.iloc[:4])
    assert "EDIT_DESCRIPTION" not in trace.activities


def test_cut_is_at_the_last_terminal_status_so_the_final_terminal_status_wins(project, case_rows):
    rows = case_rows(
        "TI-1",
        [("SQA", "Issue created"), ("PO", DONE_ROW), ("Eng", "edit description"),
         ("PO", REOPEN_ROW), ("Eng", "edit summary"), ("PO", REJECT_ROW),
         ("Eng", "add Attachment")],
    )
    cfg, _, events = prepare(project, rows)

    (trace,) = build_traces(events, cfg.preprocess)

    assert trace.terminal_status == "Rejected"
    assert trace.activities == (
        "CREATE", "STATUS_DONE", "EDIT_DESCRIPTION", "STATUS_In Progress", "EDIT_SUMMARY",
        "STATUS_Rejected",
    )


def test_trace_identity_and_timestamps_come_from_the_events(project, case_rows):
    cfg, _, events = prepare(project, reopen_case(case_rows, "TI-9"))

    (trace,) = build_traces(events, cfg.preprocess)

    assert trace.trace_id == trace.parent_case_id == "bug:TI-9"
    assert trace.issue_type == "bug"
    assert trace.timestamps is not None and len(trace.timestamps) == len(trace)
    assert all(ts.utcoffset().total_seconds() == 0 for ts in trace.timestamps)
    assert list(trace.timestamps) == sorted(trace.timestamps)
    assert trace.timestamps[0] == events.timestamp_utc.iloc[0].to_pydatetime()


def test_cases_not_ending_on_a_terminal_status_are_excluded_with_a_reason(project, case_rows):
    rows = reopen_case(case_rows, "TI-1")
    rows += case_rows("TI-2", [("SQA", "Issue created"), ("PO", "update status to In Test")])
    rows += case_rows("TI-3", [("SQA", "Issue created"), ("PO", "edit description")])
    cfg, _, events = prepare(project, rows)

    core = build_core_view(events, cfg.preprocess)

    assert [t.trace_id for t in core.traces] == ["bug:TI-1"]
    excluded = core.case_exclusions.set_index("case_id")
    assert excluded.loc["bug:TI-2", "reason"] == "last_status_not_terminal"
    assert excluded.loc["bug:TI-2", "last_status_value"] == "In Test"
    assert excluded.loc["bug:TI-2", "n_events"] == 2
    assert excluded.loc["bug:TI-3", "reason"] == "no_status_update"
    assert core.audit["case_exclusions"] == {"last_status_not_terminal": 1, "no_status_update": 1}


def test_a_case_reopened_after_done_and_never_closed_again_is_not_cut_at_the_first_done(
    project, case_rows
):
    rows = case_rows(
        "TI-1",
        [("SQA", "Issue created"), ("PO", DONE_ROW), ("PO", REOPEN_ROW), ("Eng", "edit summary")],
    )
    cfg, _, events = prepare(project, rows)

    core = build_core_view(events, cfg.preprocess)

    assert core.traces == []  # trạng thái cuối là In Progress: loại, không cắt ở DONE đầu tiên
    assert core.case_exclusions.loc[0, "reason"] == "last_status_not_terminal"


def test_default_noise_policy_drops_only_generic_external_link_updates(project, case_rows):
    rows = case_rows(
        "TI-1",
        [("SQA", "Issue created"), ("bot", "update RemoteIssueLink"),
         ("bot", "update RemoteIssueLink"),
         ("bot", "add RemoteIssueLink to Commit"), ("bot", "add RemoteIssueLink to Merge request"),
         ("PO", "edit description"), ("PO", DONE_ROW)],
    )
    cfg, _, events = prepare(project, rows)

    core = build_core_view(events, cfg.preprocess)

    (trace,) = core.traces
    assert trace.activities == (
        "CREATE", "LINK_COMMIT", "LINK_MERGE_REQUEST", "EDIT_DESCRIPTION", "STATUS_DONE"
    )
    noise = core.event_exclusions[core.event_exclusions.stage == "noise_policy"]
    assert list(noise.rule) == ["drop_generic_external_link_updates:UPDATE_EXTERNAL_LINK"]
    assert list(noise.n_events) == [2]


def test_keep_all_keeps_noise_but_selects_exactly_the_same_cases(project, case_rows):
    rows = case_rows(
        "TI-1",
        [("SQA", "Issue created"), ("bot", "update RemoteIssueLink"), ("PO", DONE_ROW)],
    )
    rows += case_rows("TI-2", [("SQA", "Issue created"), ("PO", "update status to In Test")])
    cfg_default, _, events_default = prepare(project, rows)
    cfg_keep, _, events_keep = prepare(project, rows, **{"preprocess.noise_policy": "keep_all"})

    default = build_core_view(events_default, cfg_default.preprocess)
    keep = build_core_view(events_keep, cfg_keep.preprocess)

    assert [t.trace_id for t in default.traces] == [t.trace_id for t in keep.traces]
    assert list(default.case_exclusions.case_id) == list(keep.case_exclusions.case_id)
    assert "UPDATE_EXTERNAL_LINK" in keep.traces[0].activities
    assert "UPDATE_EXTERNAL_LINK" not in default.traces[0].activities


def test_single_event_case_does_not_crash_and_a_lone_create_is_excluded(project, case_rows):
    rows = case_rows("TI-1", [("PO", DONE_ROW)])
    rows += case_rows("TI-2", [("SQA", "Issue created")])
    cfg, _, events = prepare(project, rows)

    core = build_core_view(events, cfg.preprocess)

    (trace,) = core.traces
    assert trace.activities == ("STATUS_DONE",) and len(trace) == 1
    assert list(core.case_exclusions.case_id) == ["bug:TI-2"]


def test_full_view_keeps_every_case_and_event(project, case_rows):
    rows = reopen_case(case_rows, "TI-1")
    rows += case_rows("TI-2", [("SQA", "Issue created"), ("bot", "update RemoteIssueLink"),
                               ("PO", "update status to In Test")])
    cfg, _, events = prepare(project, rows, **{"preprocess.view": "full"})

    traces = {t.trace_id: t for t in build_traces(events, cfg.preprocess)}

    assert sum(len(t) for t in traces.values()) == len(events) == 8
    assert traces["bug:TI-1"].activities[-1] == "EDIT_DESCRIPTION"  # post-terminal còn trong full
    assert traces["bug:TI-1"].terminal_status == "DONE"
    assert traces["bug:TI-2"].terminal_status is None  # chưa kết thúc ở trạng thái terminal
    assert "UPDATE_EXTERNAL_LINK" in traces["bug:TI-2"].activities


def test_audit_reports_full_and_core_separately_and_the_funnel_adds_up(project, case_rows):
    rows = case_rows(  # A: reopen + 1 event sau terminal (role trống)
        "TI-1",
        [("SQA", "Issue created"), ("PO", DONE_ROW), ("PO", REOPEN_ROW), ("PO", DONE_ROW),
         ("", "edit description")],
    )
    rows += case_rows("TI-2", [("SQA", "Issue created"), ("PO", "update status to In Test")])
    rows += case_rows(  # C: 2 event nhiễu
        "TI-3",
        [("SQA", "Issue created"), ("bot", "update RemoteIssueLink"),
         ("bot", "update RemoteIssueLink"),
         ("bot", "add RemoteIssueLink to Commit"), ("PO", "update status to DONE")],
    )
    cfg, _, events = prepare(project, rows)

    audit = build_core_view(events, cfg.preprocess).audit

    assert audit["funnel"] == {
        "n_events_full": 12,
        "n_events_in_excluded_cases": 2,
        "n_events_post_terminal": 1,
        "n_events_dropped_noise": 2,
        "n_events_core": 7,
    }
    f = audit["funnel"]
    assert f["n_events_full"] == (
        f["n_events_in_excluded_cases"] + f["n_events_post_terminal"]
        + f["n_events_dropped_noise"] + f["n_events_core"]
    )
    assert audit["full_view"]["n_events"] == 12 and audit["full_view"]["n_cases"] == 3
    assert audit["core_view"]["n_events"] == 7 and audit["core_view"]["n_cases"] == 2
    assert audit["post_terminal"] == {"n_events": 1, "n_cases": 1}
    assert audit["reopen"] == {"n_cases_with_reopen": 1}
    assert audit["full_view"]["n_missing_role_events"] == 1  # nằm sau terminal nên không vào core
    assert audit["core_view"]["n_missing_role_events"] == 0
    assert audit["core_view"]["terminal_status_counts"] == {"DONE": 2}
    assert audit["noise_policy"] == "drop_generic_external_link_updates"


def test_unknown_noise_policy_in_rules_is_an_error(project, case_rows, tmp_path):
    rows = case_rows("TI-1", [("SQA", "Issue created"), ("PO", DONE_ROW)])
    cfg, _, events = prepare(project, rows)
    data = yaml.safe_load(ACTIONS_FILE.read_text(encoding="utf-8"))
    del data["noise_policies"]["drop_generic_external_link_updates"]
    data["noise_policies"]["only_this"] = []
    path = tmp_path / "other_actions.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    other_rules = load_action_rules(path)

    with pytest.raises(ActionRulesError, match="drop_generic_external_link_updates"):
        build_core_view(events, cfg.preprocess, rules=other_rules)
