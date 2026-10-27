from __future__ import annotations

import random
from collections import Counter

import pandas as pd
import pytest

from jira_ad.config import SplitConfig, load_config
from jira_ad.data import load_raw_events
from jira_ad.preprocess import build_core_view, normalize_events
from jira_ad.splits import (
    SplitError,
    SplitManifestError,
    make_case_splits,
    read_split_manifest,
    split_hash,
    write_split_manifest,
)
from jira_ad.types import CaseSplits

CFG = SplitConfig(
    seed=42, train_fraction=0.6, validation_fraction=0.2, test_fraction=0.2,
    stratify="terminal_status",
)
DONE_ROW = "update resolution to Done, update status to DONE"
REJECT_ROW = "update resolution to Canceled, update status to Rejected"


@pytest.fixture
def traces(trace_factory):
    return (
        [trace_factory(f"bug:D{i:02d}", "DONE") for i in range(30)]
        + [trace_factory(f"bug:R{i:02d}", "Rejected") for i in range(20)]
    )


def split_of(splits: CaseSplits) -> dict[str, str]:
    out = {}
    for name, ids in (("train", splits.train_ids), ("validation", splits.validation_ids),
                      ("test", splits.test_ids)):
        out.update({case_id: name for case_id in ids})
    return out


def test_splits_partition_the_cases_in_the_configured_proportions(traces):
    splits = make_case_splits(traces, CFG)

    assert sorted(splits.all_ids) == sorted(t.trace_id for t in traces)  # không mất, không giao
    assert (len(splits.train_ids), len(splits.validation_ids), len(splits.test_ids)) == (30, 10, 10)


def test_each_terminal_status_is_split_in_the_same_proportions(traces):
    assignment = split_of(make_case_splits(traces, CFG))

    by_status = Counter((case_id[4], assignment[case_id]) for case_id in assignment)
    assert by_status == {
        ("D", "train"): 18, ("D", "validation"): 6, ("D", "test"): 6,
        ("R", "train"): 12, ("R", "validation"): 4, ("R", "test"): 4,
    }


def test_same_seed_gives_the_same_split_and_another_seed_a_different_one(traces):
    first = make_case_splits(traces, CFG)
    again = make_case_splits(traces, CFG)
    other = make_case_splits(traces, SplitConfig(43, 0.6, 0.2, 0.2, "terminal_status"))

    assert first == again
    assert first != other


def test_split_does_not_depend_on_the_order_of_the_input_cases(traces):
    baseline = make_case_splits(traces, CFG)
    shuffled = list(traces)
    random.Random(3).shuffle(shuffled)

    assert make_case_splits(shuffled, CFG) == baseline
    assert make_case_splits(list(reversed(traces)), CFG) == baseline


def test_split_depends_only_on_case_id_and_terminal_status_not_on_trace_content(
    traces, trace_factory
):
    changed = [trace_factory(t.trace_id, t.terminal_status, n=7) for t in traces]

    assert make_case_splits(changed, CFG) == make_case_splits(traces, CFG)


def test_too_small_stratum_fails_with_a_message_naming_it(trace_factory):
    traces = [trace_factory(f"bug:D{i}", "DONE") for i in range(10)]
    traces += [trace_factory("bug:R0", "Rejected"), trace_factory("bug:R1", "Rejected")]

    with pytest.raises(ValueError, match=r"Rejected.*stratify|stratify.*Rejected"):
        make_case_splits(traces, CFG)


def test_without_stratification_small_sets_still_get_all_three_splits(trace_factory):
    flat = SplitConfig(42, 0.6, 0.2, 0.2, "none")
    traces = [trace_factory(f"bug:C{i}", "DONE" if i % 2 else "Rejected") for i in range(5)]

    splits = make_case_splits(traces, flat)

    assert (len(splits.train_ids), len(splits.validation_ids), len(splits.test_ids)) == (3, 1, 1)


@pytest.mark.parametrize("n", [3, 4, 7, 11, 13, 101])
def test_every_split_is_non_empty_and_sizes_add_up(trace_factory, n):
    flat = SplitConfig(42, 0.6, 0.2, 0.2, "none")
    splits = make_case_splits([trace_factory(f"bug:C{i}") for i in range(n)], flat)

    sizes = (len(splits.train_ids), len(splits.validation_ids), len(splits.test_ids))
    assert min(sizes) >= 1 and sum(sizes) == n
    assert sizes[0] >= sizes[1] and sizes[0] >= sizes[2]


def test_fewer_than_three_cases_cannot_be_split(trace_factory):
    flat = SplitConfig(42, 0.6, 0.2, 0.2, "none")

    with pytest.raises(ValueError, match="3"):
        make_case_splits([trace_factory("bug:A"), trace_factory("bug:B")], flat)


def test_duplicate_trace_ids_are_rejected(trace_factory):
    flat = SplitConfig(42, 0.6, 0.2, 0.2, "none")
    traces = [trace_factory("bug:A"), trace_factory("bug:A"), trace_factory("bug:B"),
              trace_factory("bug:C")]

    with pytest.raises(ValueError, match="bug:A"):
        make_case_splits(traces, flat)


def test_changing_the_noise_policy_does_not_create_a_new_split(project, case_rows):
    rows = []
    for i in range(12):
        closing = DONE_ROW if i % 2 == 0 else REJECT_ROW
        rows += case_rows(
            f"TI-{i + 1}",
            [("SQA", "Issue created"), ("bot", "update RemoteIssueLink"), ("PO", "edit summary"),
             ("PO", closing)],
        )
    project.write_bug(rows)

    def core_traces(noise_policy):
        cfg = load_config(project.write_config(
            project.config({"preprocess.noise_policy": noise_policy})))
        events = normalize_events(load_raw_events(cfg.data, cfg.project_root), cfg.preprocess)
        return build_core_view(events, cfg.preprocess).traces, cfg

    default_traces, cfg = core_traces("drop_generic_external_link_updates")
    keep_traces, _ = core_traces("keep_all")

    assert [len(t) for t in default_traces] != [len(t) for t in keep_traces]  # nội dung có đổi
    assert make_case_splits(default_traces, cfg.split) == make_case_splits(keep_traces, cfg.split)


def test_manifest_round_trips_and_has_a_stable_hash(tmp_path, traces):
    splits = make_case_splits(traces, CFG)
    path = tmp_path / "split_manifest.csv"

    write_split_manifest(splits, traces, CFG, path)
    loaded = read_split_manifest(path)

    assert loaded == splits
    manifest = pd.read_csv(path, dtype=str, keep_default_na=False)
    assert list(manifest.columns) == [
        "case_id", "split", "terminal_status", "stratum", "split_seed"
    ]
    assert len(manifest) == 50
    assert set(manifest.split) == {"train", "validation", "test"}
    assert split_hash(loaded) == split_hash(splits)
    swapped = CaseSplits(
        train_ids=splits.train_ids[1:] + splits.validation_ids[:1],
        validation_ids=splits.validation_ids[1:] + splits.train_ids[:1],
        test_ids=splits.test_ids,
    )
    assert split_hash(swapped) != split_hash(splits)


def test_split_hash_ignores_row_order_but_not_assignment(traces):
    splits = make_case_splits(traces, CFG)
    reordered = CaseSplits(
        train_ids=tuple(reversed(splits.train_ids)),
        validation_ids=tuple(reversed(splits.validation_ids)),
        test_ids=tuple(reversed(splits.test_ids)),
    )

    assert split_hash(reordered) == split_hash(splits)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("case_id,split\nbug:A,train\n", "cột"),
        ("case_id,split,terminal_status,stratum,split_seed\n"
         "bug:A,holdout,DONE,DONE,42\n", "holdout"),
        ("case_id,split,terminal_status,stratum,split_seed\n"
         "bug:A,train,DONE,DONE,42\nbug:A,test,DONE,DONE,42\n", "bug:A"),
    ],
)
def test_malformed_manifests_are_rejected(tmp_path, text, expected):
    path = tmp_path / "split_manifest.csv"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(SplitManifestError, match=expected):
        read_split_manifest(path)


# ============================================ holdout theo thời gian (Task 14, spec §5.1 mở rộng)

import dataclasses  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

from jira_ad.splits import temporal_report  # noqa: E402
from jira_ad.types import Trace  # noqa: E402

TEMPORAL = dataclasses.replace(CFG, strategy="temporal")
T0 = datetime(2022, 1, 1, tzinfo=UTC)


def timed_trace(case_id, start_day, duration_days, status="DONE", events=3):
    """Trace có timestamp: bắt đầu `start_day`, event cuối (terminal) sau `duration_days` ngày."""
    stamps = tuple(T0 + timedelta(days=start_day + duration_days * i / (events - 1))
                   for i in range(events))
    return Trace(
        trace_id=case_id, parent_case_id=case_id, issue_type="bug",
        activities=tuple(f"A{i}" for i in range(events)), roles=("PO",) * events,
        event_ids=tuple(f"{case_id}-e{i}" for i in range(events)), timestamps=stamps,
        terminal_status=status,
    )


@pytest.fixture
def timeline():
    """50 ca kết thúc lần lượt mỗi ngày một ca (ca k kết thúc ngày k), id xáo trộn so với thời gian."""
    rng = random.Random(7)
    order = list(range(50))
    rng.shuffle(order)
    return [timed_trace(f"bug:T{k:02d}", start_day=max(k - 5, 0), duration_days=min(k, 5),
                        status="DONE" if k % 2 else "Rejected") for k in order]


def end_of(trace):
    return trace.timestamps[-1]


def test_temporal_split_puts_the_earliest_finishing_cases_in_train_then_validation_then_test(
    timeline,
):
    splits = make_case_splits(timeline, TEMPORAL)
    by_id = {t.trace_id: t for t in timeline}

    assert (len(splits.train_ids), len(splits.validation_ids), len(splits.test_ids)) == (30, 10, 10)
    ends = {name: [end_of(by_id[i]) for i in ids] for name, ids in
            (("train", splits.train_ids), ("validation", splits.validation_ids),
             ("test", splits.test_ids))}
    assert max(ends["train"]) <= min(ends["validation"])
    assert max(ends["validation"]) <= min(ends["test"])
    assert sorted(splits.all_ids) == sorted(by_id)


def test_temporal_split_ignores_the_seed_stratification_and_input_order(timeline):
    base = make_case_splits(timeline, TEMPORAL)

    reseeded = make_case_splits(timeline, dataclasses.replace(TEMPORAL, seed=7, stratify="none"))
    reversed_ = make_case_splits(timeline[::-1], TEMPORAL)

    assert base == reseeded == reversed_


def test_temporal_ties_are_broken_by_case_id_not_by_input_order():
    # 12 ca: 5 ca kết thúc sớm, 7 ca kết thúc CÙNG một thời điểm nằm vắt qua ranh giới train/val/test.
    earlier = [timed_trace(f"bug:L{i}", i, 0.0, events=2) for i in range(5)]
    tied = [timed_trace(f"bug:{c}", 20, 0.0, events=2) for c in "GFEDCBA"]

    forward = make_case_splits(earlier + tied, TEMPORAL)
    backward = make_case_splits((earlier + tied)[::-1], TEMPORAL)

    assert forward == backward
    assert set(forward.train_ids) == {f"bug:L{i}" for i in range(5)} | {"bug:A", "bug:B"}
    assert set(forward.validation_ids) == {"bug:C", "bug:D", "bug:E"}
    assert set(forward.test_ids) == {"bug:F", "bug:G"}


def test_temporal_split_needs_timestamps_and_says_which_case_lacks_them(timeline, trace_factory):
    broken = [*timeline[:-1], trace_factory("bug:NOTIME")]

    with pytest.raises(SplitError, match="bug:NOTIME"):
        make_case_splits(broken, TEMPORAL)


def test_temporal_report_counts_held_out_cases_that_started_before_the_train_period_ended(
    timeline,
):
    splits = make_case_splits(timeline, TEMPORAL)

    report = temporal_report(splits, timeline)

    by_id = {t.trace_id: t for t in timeline}
    train_end = max(end_of(by_id[i]) for i in splits.train_ids)
    expected = sum(by_id[i].timestamps[0] < train_end
                   for i in (*splits.validation_ids, *splits.test_ids))
    assert report["train_end_utc"] == train_end.isoformat(timespec="seconds")
    assert report["n_heldout_started_before_train_end"] == expected > 0
    assert report["by_split"]["train"]["n"] == 30
    assert report["by_split"]["test"]["last_terminal_utc"] >= report["by_split"]["test"][
        "first_terminal_utc"]
    assert report["train_validation_boundary_tie"] is False


def test_temporal_manifest_labels_the_stratum_and_round_trips(tmp_path, timeline):
    splits = make_case_splits(timeline, TEMPORAL)

    write_split_manifest(splits, timeline, TEMPORAL, tmp_path / "m.csv")

    frame = pd.read_csv(tmp_path / "m.csv")
    assert set(frame.stratum) == {"temporal"}
    assert read_split_manifest(tmp_path / "m.csv") == splits


def test_the_default_strategy_is_the_unchanged_random_holdout(traces):
    assert CFG.strategy == "random"
    assert make_case_splits(traces, CFG) == make_case_splits(traces, dataclasses.replace(
        CFG, strategy="random"))
