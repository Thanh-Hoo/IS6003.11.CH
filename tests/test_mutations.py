from __future__ import annotations

import json
import random
from collections import Counter

from jira_ad.config import MutationConfig
from jira_ad.mutations import LEDGER_COLUMNS, generate_mutations
from jira_ad.types import MutationResult

CFG = MutationConfig(
    types=("swap_adjacent", "delete_internal", "duplicate_block"),
    max_per_type_per_parent=1, validation_seed=1042, test_seed=2042, duplicate_block_max_length=2,
)
LONG = ["CREATE", "S_A", "EDIT", "LINK", "S_B", "S_DONE"]


def only(types, **kw):
    return MutationConfig(types=tuple(types), max_per_type_per_parent=1, validation_seed=1,
                          test_seed=2, duplicate_block_max_length=kw.get("max_len", 2))


def make(trace_of, trace_id, activities, **kw):
    roles = [f"R{i}" for i in range(len(activities))]  # role khác nhau để theo dõi lineage
    return trace_of(trace_id, activities, roles=roles, **kw)


def created(result, mutation_type):
    ledger = result.ledger
    ids = set(ledger.loc[(ledger.mutation_type == mutation_type) & (ledger.status == "created"),
                         "mutation_id"])
    return [t for t in result.traces if t.trace_id in ids]


def triples(trace):
    return list(zip(trace.activities, trace.roles, trace.event_ids, strict=True))


def test_swap_changes_the_order_but_not_the_histogram_or_length(trace_of):
    parent = make(trace_of, "bug:P", LONG)

    (mutant,) = created(generate_mutations([parent], only(["swap_adjacent"]), seed=5),
                        "swap_adjacent")

    assert len(mutant) == len(parent)
    assert Counter(mutant.activities) == Counter(parent.activities)
    assert mutant.activities != parent.activities
    differing = [i for i, (a, b) in enumerate(zip(parent.activities, mutant.activities,
                                                  strict=True)) if a != b]
    assert len(differing) == 2 and differing[1] == differing[0] + 1  # đúng một cặp kề nhau


def test_delete_removes_exactly_one_internal_event_and_keeps_the_rest_in_order(trace_of):
    parent = make(trace_of, "bug:P", LONG)

    (mutant,) = created(generate_mutations([parent], only(["delete_internal"]), seed=5),
                        "delete_internal")

    assert len(mutant) == len(parent) - 1
    removed = [t for t in triples(parent) if t not in triples(mutant)]
    assert len(removed) == 1 and removed[0] not in (triples(parent)[0], triples(parent)[-1])
    assert [t for t in triples(parent) if t in triples(mutant)] == triples(mutant)


def valid_duplications(parent, max_len):
    """Mọi chuỗi activity có thể có khi lặp một khối 1..max_len event nội bộ ngay sau chính nó."""
    acts, results = list(parent.activities), set()
    for k in range(1, max_len + 1):
        for i in range(1, len(acts) - k):  # khối [i, i+k) không chạm event đầu/cuối
            results.add(tuple(acts[: i + k] + acts[i : i + k] + acts[i + k :]))
    return results


def test_duplicate_repeats_a_contiguous_internal_block_of_one_or_two_events(trace_of):
    parent = make(trace_of, "bug:P", LONG)
    extras = set()
    for seed in range(40):
        (mutant,) = created(generate_mutations([parent], only(["duplicate_block"]), seed=seed),
                            "duplicate_block")
        assert mutant.activities in valid_duplications(parent, 2)
        extras.add(len(mutant) - len(parent))
    assert extras == {1, 2}


def test_duplicate_block_length_respects_the_config(trace_of):
    parent = make(trace_of, "bug:P", LONG)
    for seed in range(30):
        (mutant,) = created(
            generate_mutations([parent], only(["duplicate_block"], max_len=1), seed=seed),
            "duplicate_block",
        )
        assert len(mutant) == len(parent) + 1


def test_first_and_last_events_are_protected_for_every_type(trace_of):
    parent = make(trace_of, "bug:P", LONG)
    for seed in range(25):
        result = generate_mutations([parent], CFG, seed=seed)
        for mutant in result.traces:
            assert triples(mutant)[0] == triples(parent)[0]
            assert triples(mutant)[-1] == triples(parent)[-1]


def test_role_and_event_lineage_travel_with_the_activity_and_no_new_tokens_appear(trace_of):
    parent = make(trace_of, "bug:P", LONG)
    parent_triples = set(triples(parent))
    for seed in range(15):
        for mutant in generate_mutations([parent], CFG, seed=seed).traces:
            assert set(triples(mutant)) <= parent_triples  # (activity, role, event_id) nguyên vẹn
            assert set(mutant.activities) <= set(parent.activities)  # không có OOV giả


def test_mutants_are_structural_new_traces_that_keep_the_parent_outcome(trace_of):
    parent = make(trace_of, "bug:P", LONG, terminal_status="Rejected")

    result = generate_mutations([parent], CFG, seed=3)

    assert isinstance(result, MutationResult) and len(result.traces) == 3
    for mutant in result.traces:
        assert mutant.timestamps is None  # không giả tạo thời gian
        assert mutant.trace_id != parent.trace_id
        assert mutant.parent_case_id == "bug:P"
        assert mutant.issue_type == parent.issue_type
        assert mutant.terminal_status == "Rejected"
    ids = [t.trace_id for t in result.traces]
    assert len(set(ids)) == len(ids)


def test_one_mutant_per_type_per_parent_and_one_ledger_row_per_attempt(trace_of):
    parents = [make(trace_of, f"bug:P{i}", LONG) for i in range(5)]

    result = generate_mutations(parents, CFG, seed=9)

    assert len(result.ledger) == 5 * 3
    counts = result.ledger.groupby(["parent_case_id", "mutation_type"]).size()
    assert (counts == 1).all()
    assert len(result.traces) == (result.ledger.status == "created").sum()


def test_only_configured_types_are_generated(trace_of):
    result = generate_mutations([make(trace_of, "bug:P", LONG)], only(["delete_internal"]), seed=1)

    assert set(result.ledger.mutation_type) == {"delete_internal"}


def test_too_short_or_degenerate_parents_are_skipped_with_a_reason(trace_of):
    parents = [
        make(trace_of, "bug:two", ["CREATE", "S_OTHER"]),  # không trùng kết quả xoá của bug:three
        make(trace_of, "bug:one", ["S_DONE"]),
        make(trace_of, "bug:three", ["CREATE", "EDIT", "S_DONE"]),
        make(trace_of, "bug:flat", ["CREATE", "EDIT", "EDIT", "EDIT", "S_DONE"]),
    ]

    ledger = generate_mutations(parents, CFG, seed=1).ledger.set_index(
        ["parent_case_id", "mutation_type"])

    for parent in ("bug:two", "bug:one"):
        for mtype in CFG.types:
            row = ledger.loc[(parent, mtype)]
            assert row.status == "skipped" and row.skip_reason == "no_internal_events"
    assert ledger.loc[("bug:three", "swap_adjacent")].skip_reason == "no_distinct_adjacent_pair"
    assert ledger.loc[("bug:three", "delete_internal")].status == "created"
    assert ledger.loc[("bug:three", "duplicate_block")].status == "created"
    assert ledger.loc[("bug:flat", "swap_adjacent")].skip_reason == "no_distinct_adjacent_pair"
    assert ledger.loc[("bug:flat", "delete_internal")].status == "created"


def test_a_mutant_equal_to_another_original_in_the_holdout_is_rejected(trace_of):
    only_swap = only(["swap_adjacent"])
    p = make(trace_of, "bug:P", ["CREATE", "A", "B", "S_DONE"])
    q = make(trace_of, "bug:Q", ["CREATE", "B", "A", "S_DONE"])  # = P sau khi hoán đổi (A, B)

    result = generate_mutations([p, q], only_swap, seed=1)

    assert result.traces == []
    assert set(result.ledger.skip_reason) == {"all_candidates_match_originals"}
    assert list(result.ledger.n_candidates) == [1, 1]
    assert list(result.ledger.n_rejected_candidates) == [1, 1]


def test_another_candidate_is_used_when_the_first_one_collides_with_an_original(trace_of):
    p = make(trace_of, "bug:P", ["CREATE", "A", "B", "E", "S_DONE"])
    q = make(trace_of, "bug:Q", ["CREATE", "B", "A", "E", "S_DONE"])

    result = generate_mutations([p, q], only(["swap_adjacent"]), seed=4)

    row = result.ledger.set_index("parent_case_id").loc["bug:P"]
    assert row.status == "created" and row.n_candidates == 2
    (mutant,) = [t for t in result.traces if t.parent_case_id == "bug:P"]
    assert mutant.activities != q.activities and mutant.activities != p.activities


def test_results_are_deterministic_and_independent_of_parent_order(trace_of):
    parents = [make(trace_of, f"bug:P{i}", LONG[:1] + ["X", "Y", "Z", f"W{i}"] + LONG[-1:])
               for i in range(8)]
    shuffled = list(parents)
    random.Random(1).shuffle(shuffled)

    one = generate_mutations(parents, CFG, seed=7)
    two = generate_mutations(shuffled, CFG, seed=7)
    other = generate_mutations(parents, CFG, seed=8)

    def signature(result):
        return sorted((t.trace_id, t.activities, t.event_ids) for t in result.traces)

    assert signature(one) == signature(two)
    assert one.ledger.sort_values("mutation_id").reset_index(drop=True).equals(
        two.ledger.sort_values("mutation_id").reset_index(drop=True))
    assert signature(one) != signature(other)


def test_ledger_has_the_documented_columns_and_consistent_values(trace_of):
    parents = [make(trace_of, "bug:P", LONG), make(trace_of, "bug:short", ["CREATE", "S_DONE"])]

    ledger = generate_mutations(parents, CFG, seed=11, split="test").ledger

    assert list(ledger.columns) == LEDGER_COLUMNS
    assert set(ledger.split) == {"test"} and set(ledger.seed) == {11}
    created_rows = ledger[ledger.status == "created"]
    assert created_rows.skip_reason.isna().all()
    assert (created_rows.original_sequence_hash != created_rows.mutated_sequence_hash).all()
    assert created_rows.mutated_length.notna().all()
    skipped = ledger[ledger.status == "skipped"]
    assert skipped.skip_reason.notna().all() and skipped.mutated_sequence_hash.isna().all()
    assert ledger.mutation_id.is_unique
    for positions in created_rows.edited_positions:
        assert all(isinstance(p, int) for p in json.loads(positions))
    swap = created_rows[created_rows.mutation_type == "swap_adjacent"].iloc[0]
    assert swap.original_length == swap.mutated_length == len(LONG)
    delete = created_rows[created_rows.mutation_type == "delete_internal"].iloc[0]
    assert delete.mutated_length == len(LONG) - 1


def test_trace_ids_of_mutants_match_ledger_mutation_ids(trace_of):
    result = generate_mutations([make(trace_of, "bug:P", LONG)], CFG, seed=2)

    created_ids = set(result.ledger.loc[result.ledger.status == "created", "mutation_id"])
    assert {t.trace_id for t in result.traces} == created_ids


# ============================================= đối chứng dương: xáo toàn bộ phần nội bộ (Ruling 31)

import pytest  # noqa: E402

from jira_ad.mutations import POSITIVE_CONTROL_TYPE, generate_positive_control  # noqa: E402

LONGER = ["CREATE", "A", "B", "C", "D", "E", "F", "S_DONE"]


def shuffled(result):
    return [t for t in result.traces]


def test_the_control_shuffles_only_the_internal_part_and_keeps_histogram_and_length(trace_of):
    parent = make(trace_of, "bug:P", LONGER)

    (mutant,) = shuffled(generate_positive_control([parent], seed=5, split="validation"))

    assert len(mutant) == len(parent)
    assert Counter(mutant.activities) == Counter(parent.activities)
    assert mutant.activities[0] == parent.activities[0] and mutant.activities[-1] == parent.activities[-1]
    assert mutant.activities[1:-1] != parent.activities[1:-1]
    assert mutant.timestamps is None and mutant.parent_case_id == parent.trace_id


def test_the_control_moves_role_and_event_lineage_with_the_activity(trace_of):
    parent = make(trace_of, "bug:P", LONGER)

    (mutant,) = shuffled(generate_positive_control([parent], seed=5, split="validation"))

    assert sorted(triples(mutant)) == sorted(triples(parent))  # cùng bộ ba, chỉ khác thứ tự


def test_the_control_never_reproduces_the_parent_or_any_other_original(trace_of):
    parents = [make(trace_of, f"bug:P{i}", LONGER) for i in range(4)]
    swapped = list(LONGER)
    swapped[2], swapped[3] = swapped[3], swapped[2]
    parents.append(make(trace_of, "bug:Q", swapped))
    originals = {t.activities for t in parents}

    result = generate_positive_control(parents, seed=1, split="validation")

    assert result.traces and all(t.activities not in originals for t in result.traces)


def test_the_control_ledger_records_the_type_and_why_a_case_was_skipped(trace_of):
    short = make(trace_of, "bug:S", ["CREATE", "A", "S_DONE"])  # chỉ 1 event nội bộ
    flat = make(trace_of, "bug:F", ["CREATE", "A", "A", "A", "S_DONE"])  # nội bộ toàn như nhau
    ok = make(trace_of, "bug:O", LONGER)

    result = generate_positive_control([short, flat, ok], seed=3, split="validation")

    ledger = result.ledger.set_index("parent_case_id")
    assert list(result.ledger.columns) == LEDGER_COLUMNS
    assert set(result.ledger.mutation_type) == {POSITIVE_CONTROL_TYPE}
    assert ledger.loc["bug:S", "status"] == "skipped" and ledger.loc["bug:S", "skip_reason"]
    assert ledger.loc["bug:F", "status"] == "skipped" and ledger.loc["bug:F", "skip_reason"]
    assert ledger.loc["bug:O", "status"] == "created"
    assert ledger.loc["bug:O", "split"] == "validation"
    assert [t.parent_case_id for t in result.traces] == ["bug:O"]


def test_the_control_is_reproducible_and_independent_of_parent_order(trace_of):
    parents = [make(trace_of, f"bug:P{i}", LONGER) for i in range(5)]

    first = generate_positive_control(parents, seed=9, split="validation")
    reversed_ = generate_positive_control(parents[::-1], seed=9, split="validation")
    other = generate_positive_control(parents, seed=10, split="validation")

    assert {t.trace_id: t.activities for t in first.traces} == {
        t.trace_id: t.activities for t in reversed_.traces}
    assert {t.trace_id: t.activities for t in first.traces} != {
        t.trace_id: t.activities for t in other.traces}


@pytest.mark.parametrize("split", ["test", "train", ""])
def test_the_control_refuses_to_run_outside_validation(trace_of, split):
    parent = make(trace_of, "bug:P", LONGER)

    with pytest.raises(ValueError, match="validation"):
        generate_positive_control([parent], seed=1, split=split)


def test_the_control_is_not_one_of_the_configurable_mutation_types():
    from jira_ad.config import MUTATION_TYPES

    assert POSITIVE_CONTROL_TYPE not in MUTATION_TYPES


def test_the_control_skips_a_parent_whose_only_other_ordering_is_another_original(trace_of):
    # Hai event nội bộ khác nhau: hoán vị duy nhất khác parent chính là chuỗi gốc của parent kia.
    p = make(trace_of, "bug:P", ["CREATE", "A", "B", "S_DONE"])
    q = make(trace_of, "bug:Q", ["CREATE", "B", "A", "S_DONE"])

    result = generate_positive_control([p, q], seed=2, split="validation")

    assert result.traces == []
    assert set(result.ledger.skip_reason) == {"all_candidates_match_originals"}
    assert (result.ledger.n_rejected_candidates == result.ledger.n_candidates).all()
    assert (result.ledger.n_rejected_candidates > 0).all()


# ============================================ mutant mở rộng (chỉ dùng trong giao thức cross-validation)

STATUSED = ["CREATE", "STATUS_To Do", "EDIT", "STATUS_In Progress", "LINK", "STATUS_In Test", "STATUS_DONE"]


def test_skip_status_removes_exactly_one_internal_status_event(trace_of):
    parent = make(trace_of, "bug:P", STATUSED)

    for seed in range(6):
        (mutant,) = created(generate_mutations([parent], only(["skip_status"]), seed=seed),
                            "skip_status")
        assert len(mutant) == len(parent) - 1
        removed = [t for t in triples(parent) if t not in triples(mutant)]
        assert len(removed) == 1 and removed[0][0].startswith("STATUS_")
        assert mutant.activities[0] == "CREATE" and mutant.activities[-1] == "STATUS_DONE"
        assert [t for t in triples(parent) if t in triples(mutant)] == triples(mutant)


def test_skip_status_without_an_internal_status_is_skipped_with_a_reason(trace_of):
    parent = make(trace_of, "bug:P", ["CREATE", "EDIT", "LINK", "STATUS_DONE"])

    result = generate_mutations([parent], only(["skip_status"]), seed=1)

    assert result.traces == []
    row = result.ledger.iloc[0]
    assert row.status == "skipped" and row.skip_reason == "no_internal_status"


def test_multi_edit_changes_the_sequence_keeps_the_ends_and_the_lineage(trace_of):

    parent = make(trace_of, "bug:P", ["CREATE", "S_A", "EDIT", "LINK", "S_B", "X", "Y", "S_DONE"])

    for seed in range(8):
        result = generate_mutations([parent], only(["multi_edit"]), seed=seed)
        (mutant,) = created(result, "multi_edit")
        assert mutant.activities != parent.activities
        assert mutant.activities[0] == "CREATE" and mutant.activities[-1] == "S_DONE"
        assert triples(mutant)[0] == triples(parent)[0] and triples(mutant)[-1] == triples(parent)[-1]
        assert set(triples(mutant)) <= set(triples(parent))
        assert len(mutant) >= 3 and mutant.timestamps is None
        ops = json.loads(result.ledger.iloc[0].edited_positions)
        assert len(ops) == 3 and all(op[0] in ("swap", "delete", "duplicate") for op in ops)


def test_multi_edit_is_reproducible_and_independent_of_parent_order(trace_of):
    parents = [make(trace_of, f"bug:P{i}", ["CREATE", "A", "B", "C", "D", f"E{i}", "DONE"])
               for i in range(5)]

    first = generate_mutations(parents, only(["multi_edit"]), seed=9)
    shuffled_parents = parents[:]
    random.Random(1).shuffle(shuffled_parents)
    second = generate_mutations(shuffled_parents, only(["multi_edit"]), seed=9)

    assert {t.trace_id: t.activities for t in first.traces} == {
        t.trace_id: t.activities for t in second.traces}
    assert len(first.traces) == 5


def test_multi_edit_on_a_three_event_parent_never_drops_below_three_events(trace_of):
    parent = make(trace_of, "bug:P", ["CREATE", "A", "DONE"])

    for seed in range(10):
        for mutant in generate_mutations([parent], only(["multi_edit"]), seed=seed).traces:
            assert len(mutant) >= 3 and mutant.activities[0] == "CREATE"
