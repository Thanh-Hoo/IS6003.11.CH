"""Mô hình chuẩn → Petri net, khai phá, token replay, cờ quy tắc, bảng cung, Work System, BPMN (B1, B5)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pandas as pd
import pytest

pytest.importorskip("pm4py")

from jira_ad.conformance import (  # noqa: E402
    FlagRule,
    ReferenceModel,
    arc_table,
    discover,
    flag_cases,
    quality,
    reference_bpmn_xml,
    reference_net,
    replay_cases,
    state_lanes,
    status_event_log,
)

ARCS = ("CREATE -> To Do", "CREATE -> Rejected", "To Do -> In Progress", "To Do -> Rejected",
        "In Progress -> In Test", "In Test -> In Progress", "In Test -> DONE")
MODEL = ReferenceModel.from_strings(ARCS, start="CREATE", ends=("DONE", "Rejected"))
T0 = pd.Timestamp("2022-06-13T08:00:00", tz="UTC")


def log_of(cases: dict[str, list[str]], roles: dict[str, list[str]] | None = None,
           gaps: dict[str, list[float]] | None = None) -> pd.DataFrame:
    """Status log tối giản: lượt đầu là __CREATED__, mỗi lượt cách nhau 1 giờ (hoặc `gaps` giây)."""
    rows = []
    for case, states in cases.items():
        seq = ["__CREATED__", *states]
        t = T0
        for i, s in enumerate(seq):
            gap = (gaps or {}).get(case, [3600.0] * len(seq))[i] if i < len(seq) - 1 else None
            rows.append({
                "case_id": case, "visit_index": i, "state": s, "t_enter": t,
                "terminal_status": states[-1],
                "exit_role": None if i == len(seq) - 1 else (roles or {}).get(case, ["PO"] * len(seq))[i],
                "dwell_work_s": gap, "is_backfill_entry": False,
            })
            if gap is not None:
                t = t + pd.Timedelta(seconds=gap)
        for j in range(2, len(rows[-len(seq):])):
            prev = rows[-len(seq) + j - 1]
            rows[-len(seq) + j]["is_backfill_entry"] = prev["dwell_work_s"] < 60
        for j in range(1, len(seq)):
            cur, prev = rows[-len(seq) + j], rows[-len(seq) + j - 1]["state"]
            cur["is_back"] = prev in ORDER and cur["state"] in ORDER and ORDER[cur["state"]] < ORDER[prev]
            cur["is_reopen"] = prev in ("DONE", "Rejected")
        rows[-len(seq)]["is_back"] = rows[-len(seq)]["is_reopen"] = False
        block = rows[-len(seq):]
        for j, cur in enumerate(block):  # thuộc đợt bù: tự là lần đổi bù, hoặc mở đầu một chuỗi đổi bù
            nxt = block[j + 1]["is_backfill_entry"] if j + 1 < len(block) else False
            cur["burst_id"] = 0 if j > 0 and (cur["is_backfill_entry"] or nxt) else -1
    return pd.DataFrame(rows)


ORDER = {s: i for i, s in enumerate(["Inbox", "To Investigate", "INVESTIGATED", "To Do", "In Progress",
                                     "In Test"])}


CONFORMING = {"a": ["To Do", "In Progress", "In Test", "DONE"],
              "b": ["To Do", "In Progress", "In Test", "In Progress", "In Test", "DONE"],
              "c": ["Rejected"]}


def test_reference_model_parses_arcs_and_rejects_bad_ones():
    assert ("In Test", "In Progress") in MODEL.arcs and MODEL.activities >= {"CREATE", "DONE"}
    with pytest.raises(ValueError, match="->"):
        ReferenceModel.from_strings(("CREATE To Do",), start="CREATE", ends=("DONE",))
    with pytest.raises(ValueError, match="không có cung vào"):
        ReferenceModel.from_strings(("CREATE -> A", "B -> DONE"), start="CREATE", ends=("DONE",))


def test_status_event_log_keeps_visit_order_even_with_equal_timestamps():
    log = log_of({"x": ["To Do", "In Progress", "In Test", "DONE"]}, gaps={"x": [3600, 0, 0, 3600]})
    ev = status_event_log(log)
    assert list(ev["concept:name"]) == ["CREATE", "To Do", "In Progress", "In Test", "DONE"]
    assert ev["time:timestamp"].is_monotonic_increasing and ev["time:timestamp"].is_unique


def test_conforming_cases_replay_with_fitness_one():
    net, im, fm = reference_net(MODEL)
    out = replay_cases(status_event_log(log_of(CONFORMING)), net, im, fm).set_index("case_id")
    assert out["is_fit"].all() and (out["trace_fitness"] == 1.0).all()


def test_skipped_state_is_not_fit():
    net, im, fm = reference_net(MODEL)
    out = replay_cases(status_event_log(log_of({"s": ["To Do", "In Test", "DONE"]})), net, im, fm)
    assert not out.iloc[0]["is_fit"] and out.iloc[0]["trace_fitness"] < 1


def test_unknown_activity_is_flagged_without_raising():
    net, im, fm = reference_net(MODEL)
    out = replay_cases(status_event_log(log_of({"u": ["Triage", "Rejected"]})), net, im, fm)
    row = out.iloc[0]
    assert not row["is_fit"] and row["unknown_activities"] == "Triage"


def test_replay_of_empty_log_raises():
    net, im, fm = reference_net(MODEL)
    empty = status_event_log(log_of({}))
    with pytest.raises(ValueError, match="rỗng"):
        replay_cases(empty, net, im, fm)


def test_inductive_on_sequential_log_has_fitness_and_precision_one():
    log = status_event_log(log_of({f"c{i}": ["To Do", "In Progress", "In Test", "DONE"] for i in range(5)}))
    net, im, fm = discover(log, "inductive", {"noise_threshold": 0.0})
    q = quality(log, net, im, fm)
    assert q["fitness"] == pytest.approx(1.0) and q["precision"] == pytest.approx(1.0)
    assert q["perc_fit_traces"] == pytest.approx(100.0)
    assert 0 <= q["generalization"] <= 1 and 0 <= q["simplicity"] <= 1


def test_arc_table_marks_arcs_outside_model_with_example_cases():
    log = log_of({**CONFORMING, "s": ["To Do", "In Test", "DONE"], "t": ["To Do", "In Test", "DONE"]})
    arcs = arc_table(log, MODEL).set_index(["source", "target"])
    assert arcs.loc[("To Do", "In Test"), "in_model"] == False  # noqa: E712
    assert arcs.loc[("To Do", "In Test"), "count"] == 2
    assert arcs.loc[("To Do", "In Test"), "example_cases"] == "s, t"
    assert arcs.loc[("In Test", "DONE"), "in_model"] == True  # noqa: E712
    # cung trong mô hình nhưng không quan sát được vẫn được liệt kê với count 0
    assert arcs.loc[("To Do", "Rejected"), "count"] == 0


RULES = (
    FlagRule("skip_investigation", "Bỏ pha điều tra", "missing_before",
             ("To Do", "In Progress", "In Test", "DONE"), ("To Investigate", "INVESTIGATED")),
    FlagRule("direct_reject", "CREATE → Rejected trực tiếp", "first_status_is", ("Rejected",), ()),
    FlagRule("reject_after_work", "Rejected sau khi đã In Progress", "after",
             ("Rejected",), ("In Progress",)),
    FlagRule("reopen_done", "Mở lại sau DONE", "leaves", ("DONE",), ()),
    FlagRule("back_to_inbox", "Lùi về Inbox", "enters_from_status", ("Inbox",), ()),
    FlagRule("progress_not_from_todo", "Vào In Progress không qua To Do", "enters_not_from",
             ("In Progress",), ("To Do", "In Test")),
    FlagRule("backfill", "Đổi trạng thái trong đợt cập nhật bù", "backfill", (), ()),
)


def test_each_flag_rule_on_its_own_case():
    log = log_of({
        "skip": ["To Do", "In Progress", "In Test", "DONE"],
        "inv": ["To Investigate", "INVESTIGATED", "To Do", "In Progress", "In Test", "DONE"],
        "direct": ["Rejected"],
        "late_rej": ["To Investigate", "INVESTIGATED", "To Do", "In Progress", "Rejected"],
        "reopen": ["To Investigate", "INVESTIGATED", "To Do", "In Progress", "In Test", "DONE",
                   "To Do", "In Progress", "In Test", "DONE"],
        "inbox": ["To Investigate", "INVESTIGATED", "To Do", "Inbox", "Rejected"],
        "jump": ["To Investigate", "INVESTIGATED", "In Progress", "In Test", "DONE"],
        "fast": ["To Investigate", "INVESTIGATED", "To Do", "In Progress", "In Test", "DONE"],
    }, gaps={"fast": [3600, 3600, 3600, 3600, 10, 10, 0]})
    flags = flag_cases(log, RULES)
    hit = {(r.case_id, r.flag) for r in flags[flags.n > 0].itertuples()}
    assert ("skip", "skip_investigation") in hit and ("inv", "skip_investigation") not in hit
    assert ("direct", "direct_reject") in hit and ("late_rej", "direct_reject") not in hit
    assert ("late_rej", "reject_after_work") in hit and ("direct", "reject_after_work") not in hit
    assert ("reopen", "reopen_done") in hit and ("inv", "reopen_done") not in hit
    assert ("inbox", "back_to_inbox") in hit
    assert ("jump", "progress_not_from_todo") in hit and ("reopen", "progress_not_from_todo") not in hit
    assert ("fast", "backfill") in hit and ("inv", "backfill") not in hit


def test_flag_with_no_violation_is_still_reported_as_zero():
    flags = flag_cases(log_of({"inv": ["To Investigate", "INVESTIGATED", "Rejected"]}), RULES)
    assert set(flags.flag) == {r.id for r in RULES} and (flags.n == 0).all()


def test_state_lanes_use_most_frequent_human_exit_role():
    log = log_of({"a": ["To Do", "In Progress", "In Test", "DONE"],
                  "b": ["To Do", "In Progress", "In Test", "DONE"]},
                 roles={"a": ["SQA", "PO", "Eng", "SQA", None], "b": ["SQA", "PO", "bot", "SQA", None]})
    lanes = state_lanes(log, MODEL)
    assert lanes["To Do"] == "PO" and lanes["In Progress"] == "Eng" and lanes["In Test"] == "SQA"


def test_bpmn_xml_has_lanes_xor_gateways_and_connected_flows():
    lanes = {"To Do": "PO", "In Progress": "Eng", "In Test": "SQA"}
    root = ET.fromstring(reference_bpmn_xml(MODEL, lanes, names={"CREATE": "Bug được tạo"}))
    ns = {"b": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
    process = root.find("b:process", ns)
    lane_refs = {lane.get("name"): {r.text for r in lane.findall("b:flowNodeRef", ns)}
                 for lane in process.findall("b:laneSet/b:lane", ns)}
    tasks = {t.get("id"): t.get("name") for t in process.findall("b:task", ns)}
    assert set(tasks.values()) == {"To Do", "In Progress", "In Test"}
    assert all(any(tid in refs for refs in lane_refs.values()) for tid in tasks)
    gateways = process.findall("b:exclusiveGateway", ns)
    assert len(gateways) == 3  # CREATE, To Do, In Test có hơn một cung ra
    ids = {e.get("id") for e in process}
    flows = process.findall("b:sequenceFlow", ns)
    assert all(f.get("sourceRef") in ids and f.get("targetRef") in ids for f in flows)
    assert len(process.findall("b:endEvent", ns)) == 2 and len(process.findall("b:startEvent", ns)) == 1
    assert root.find("{http://www.omg.org/spec/BPMN/20100524/DI}BPMNDiagram") is not None


def test_work_system_has_eight_components_each_with_evidence(project):
    from helpers import write_process_project
    from test_status_log import ALL_ROWS

    from jira_ad.conformance import WORK_SYSTEM_COMPONENTS, work_system_table
    from jira_ad.process_config import load_process_config
    from jira_ad.status_log import build_status_log, case_table, load_cohort

    rows = ALL_ROWS + [("TI-1", "2022-06-16T09:00:00.000-0700", "bot", "update RemoteIssueLink")]
    cfg = load_process_config(write_process_project(project, rows))
    cohort = load_cohort(cfg, "bug")
    assert len(cohort.events_full) == len(cohort.events) + 1  # event sau DONE chỉ có ở full view
    log = build_status_log(cohort.events, cohort.traces, cfg)
    table = work_system_table(cohort, log, case_table(log, cohort.traces))
    assert list(table.component) == list(WORK_SYSTEM_COMPONENTS) and len(table) == 8
    assert table.evidence.str.len().gt(0).all() and table.content.str.len().gt(0).all()
    participants = table.set_index("component").loc["Người tham gia", "evidence"]
    assert "PO" in participants and "bot" not in participants.split(";")[0]


def test_flags_respect_order_of_states():
    log = log_of({
        # điều tra diễn ra SAU khi đã vào To Do (có 3 ca như vậy trong dữ liệu thật) ⇒ vẫn là bỏ pha điều tra
        "late_inv": ["To Do", "Inbox", "To Investigate", "INVESTIGATED", "To Do", "In Progress", "In Test",
                     "DONE"],
        # Rejected rồi mới In Progress ⇒ không phải "Rejected sau khi đã In Progress"
        "rej_first": ["Rejected", "Inbox", "To Investigate", "INVESTIGATED", "To Do", "In Progress",
                      "In Test", "DONE"],
        # Inbox ngay sau CREATE ⇒ không phải lùi về Inbox
        "inbox_first": ["Inbox", "To Investigate", "INVESTIGATED", "Rejected"],
    })
    flags = flag_cases(log, RULES)
    hit = {(r.case_id, r.flag) for r in flags[flags.n > 0].itertuples()}
    assert ("late_inv", "skip_investigation") in hit
    assert ("rej_first", "reject_after_work") not in hit
    assert ("inbox_first", "back_to_inbox") not in hit
    assert ("rej_first", "back_to_inbox") in hit


def test_state_lanes_ignore_bot_even_when_bot_is_most_frequent():
    states = ["To Do", "In Progress", "In Test", "DONE"]
    log = log_of({"a": states, "b": states, "c": states},
                 roles={"a": ["SQA", "PO", "Eng", "SQA", None], "b": ["SQA", "PO", "bot", "SQA", None],
                        "c": ["SQA", "PO", "bot", "SQA", None]})
    assert state_lanes(log, MODEL)["In Progress"] == "Eng"


# ------------------------------------------------- bổ sung sau khi duyệt mô hình chuẩn (Ruling 88)

def test_with_extra_arcs_builds_a_new_model_and_keeps_the_original():
    fast = MODEL.with_extra_arcs(("CREATE -> In Progress",))
    assert ("CREATE", "In Progress") in fast.arcs and ("CREATE", "In Progress") not in MODEL.arcs
    with pytest.raises(ValueError, match="đã có"):
        MODEL.with_extra_arcs(("CREATE -> To Do",))


def test_compare_replays_reports_fit_side_by_side_and_cases_explained_by_extra_arc():
    from jira_ad.conformance import compare_replays

    log = status_event_log(log_of({**CONFORMING, "jump": ["In Progress", "In Test", "DONE"],
                                   "odd": ["In Test", "DONE"]}))
    base = replay_cases(log, *reference_net(MODEL))
    fast = replay_cases(log, *reference_net(MODEL.with_extra_arcs(("CREATE -> In Progress",))))
    table, gained = compare_replays({"chuan": base, "nhanh": fast}, reference="chuan")
    t = table.set_index("model")
    assert (t.loc["chuan", "n_fit"], t.loc["nhanh", "n_fit"]) == (3, 4)
    assert t.loc["nhanh", "n_newly_fit_vs_reference"] == 1 and t.loc["chuan", "n_newly_fit_vs_reference"] == 0
    assert t.loc["nhanh", "share_fit"] == pytest.approx(4 / 5)
    assert t.loc["nhanh", "mean_fitness"] > t.loc["chuan", "mean_fitness"]
    assert list(gained.case_id) == ["jump"] and gained.iloc[0]["model"] == "nhanh"


def test_unobserved_arc_precision_effect_lists_only_zero_count_arcs():
    from jira_ad.conformance import unobserved_arc_precision

    log = log_of(CONFORMING)
    out = unobserved_arc_precision(log, MODEL)
    assert list(zip(out.source, out.target, strict=True)) == [("To Do", "Rejected")]
    row = out.iloc[0]
    assert row.precision_without >= row.precision_with
    assert row.fitness_without == pytest.approx(row.fitness_with)  # cung không ai đi ⇒ bỏ không đổi fitness


def test_deviation_breakdown_by_branch_and_backfill():
    from jira_ad.conformance import deviation_breakdown

    log = log_of({
        "d1": ["To Do", "In Progress", "In Test", "DONE"],                    # CREATE → To Do, DONE
        "r1": ["To Do", "Rejected"],                                          # CREATE → To Do, Rejected
        "d2": ["To Investigate", "INVESTIGATED", "To Do", "In Progress", "To Do", "In Progress",
               "In Test", "DONE"],                                            # lùi In Progress → To Do
        "d3": ["To Do", "In Progress", "In Test", "DONE", "In Progress", "In Test", "DONE"],  # mở lại
    }, gaps={"d1": [3600, 3600, 10, 10, 0]})
    out = deviation_breakdown(log, arcs=(("CREATE", "To Do"),))
    key = out.set_index(["category", "branch"])
    row = key.loc[("CREATE → To Do", "DONE")]
    # chỉ tính lần sai lệch THUỘC đợt bù (rà soát I1), không tính "ca có bù ở chỗ khác"
    assert (row.n_cases, row.n_occ_in_burst) == (2, 0)
    assert (row.n_cases_only_in_burst, row.n_cases_outside_burst) == (0, 2)
    assert row.examples_outside_burst == "d1, d3"
    assert key.loc[("CREATE → To Do", "Rejected"), "n_cases"] == 1
    assert key.loc[("CREATE → To Do", "all"), "n_cases"] == 3
    assert key.loc[("Lùi trạng thái", "DONE"), "n_cases"] == 1
    assert key.loc[("Mở lại", "DONE"), "n_occurrences"] == 1
    # nhánh không có ca nào vẫn có dòng với 0
    assert key.loc[("Mở lại", "Rejected"), "n_cases"] == 0


def test_unobserved_arc_whose_removal_breaks_the_model_is_reported_not_raised():
    from jira_ad.conformance import unobserved_arc_precision

    model = ReferenceModel.from_strings(("CREATE -> Inbox", "CREATE -> To Do", "Inbox -> To Do",
                                         "To Do -> DONE"), start="CREATE", ends=("DONE",))
    out = unobserved_arc_precision(log_of({"a": ["To Do", "DONE"]}), model).set_index(["source", "target"])
    row = out.loc[("CREATE", "Inbox")]
    assert pd.isna(row.precision_without) and "không hợp lệ" in row.note


def test_bpmn_marks_automated_flows():
    from jira_ad.process_figures import bpmn_dot

    lanes = {"To Do": "PO", "In Progress": "Eng", "In Test": "SQA"}
    xml = reference_bpmn_xml(MODEL, lanes, names={}, flow_labels={("To Do", "In Progress"): "tự động"})
    ns = {"b": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
    flows = ET.fromstring(xml).find("b:process", ns).findall("b:sequenceFlow", ns)
    assert [f.get("name") for f in flows if f.get("name")] == ["tự động"]
    src = bpmn_dot(MODEL, lanes, title="T", automated={("To Do", "In Progress")})
    assert "style=dashed" in src and 'label="tự động"' in src


def test_deviation_breakdown_counts_back_transition_inside_a_burst():
    from jira_ad.conformance import deviation_breakdown

    log = log_of({"q": ["To Investigate", "INVESTIGATED", "To Do", "In Progress", "To Do", "In Progress",
                        "In Test", "DONE"]}, gaps={"q": [3600, 3600, 3600, 3600, 20, 20, 3600, 0]})
    row = deviation_breakdown(log, arcs=()).set_index(["category", "branch"]).loc[("Lùi trạng thái", "all")]
    assert (row.n_occurrences, row.n_occ_in_burst, row.n_cases_only_in_burst) == (1, 1, 1)
    assert row.examples_only_in_burst == "q"
