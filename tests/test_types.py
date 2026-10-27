from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from jira_ad.types import CaseSplits, FeatureSet, MutationResult, Trace


def make_trace(n: int = 3, **overrides) -> Trace:
    kwargs = dict(
        trace_id="bug:TI-1",
        parent_case_id="bug:TI-1",
        issue_type="bug",
        activities=tuple(f"A{i}" for i in range(n)),
        roles=tuple("PO" for _ in range(n)),
        event_ids=tuple(f"e{i}" for i in range(n)),
        timestamps=tuple(datetime(2022, 1, 1, 0, 0, i, tzinfo=UTC) for i in range(n)),
        terminal_status="DONE",
    )
    kwargs.update(overrides)
    return Trace(**kwargs)


def test_valid_trace_exposes_length():
    trace = make_trace(4)

    assert len(trace) == 4
    assert trace.activities[0] == "A0"


def test_structural_mutant_may_have_no_timestamps():
    trace = make_trace(timestamps=None)

    assert trace.timestamps is None


@pytest.mark.parametrize("field", ["roles", "event_ids", "timestamps"])
def test_trace_rejects_mismatched_lengths(field):
    with pytest.raises(ValueError, match=field):
        make_trace(3, **{field: make_trace(2).__dict__[field]})


def test_trace_rejects_empty_sequences():
    with pytest.raises(ValueError, match="rỗng|empty"):
        make_trace(0)


def test_trace_requires_tuples_so_it_cannot_be_mutated_in_place():
    with pytest.raises(TypeError, match="tuple"):
        make_trace(3, activities=["A0", "A1", "A2"])


def test_case_splits_must_be_disjoint():
    with pytest.raises(ValueError, match="giao|overlap"):
        CaseSplits(train_ids=("a", "b"), validation_ids=("b",), test_ids=("c",))

    ok = CaseSplits(train_ids=("a",), validation_ids=("b",), test_ids=("c",))
    assert ok.all_ids == ("a", "b", "c")


def test_feature_set_shape_must_match_ids_and_names():
    values = np.zeros((2, 3))
    fs = FeatureSet(values=values, trace_ids=("t1", "t2"), feature_names=("a", "b", "c"))
    assert fs.values.shape == (2, 3)

    with pytest.raises(ValueError, match="shape|hình dạng"):
        FeatureSet(values=values, trace_ids=("t1",), feature_names=("a", "b", "c"))
    with pytest.raises(ValueError, match="shape|hình dạng"):
        FeatureSet(values=values, trace_ids=("t1", "t2"), feature_names=("a",))


def test_mutation_result_holds_traces_and_ledger():
    result = MutationResult(traces=[make_trace()], ledger=pd.DataFrame({"mutation_id": ["m1"]}))

    assert len(result.traces) == 1
    assert list(result.ledger["mutation_id"]) == ["m1"]
