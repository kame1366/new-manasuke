import pytest

from pydantic import ValidationError

from ai.planning_models import (
    PlanningAllocation,
    PlanningOutput,
)


def test_valid_planning_allocation():
    allocation = (
        PlanningAllocation(
            study_target_id=1,
            optional_extra_minutes=30,
            planning_priority_rank=1,
            reason="期限と通常学習を考慮",
        )
    )

    assert (
        allocation.optional_extra_minutes
        == 30
    )


def test_optional_minutes_must_be_five_minute_multiple():
    with pytest.raises(
        ValidationError
    ):
        PlanningAllocation(
            study_target_id=1,
            optional_extra_minutes=13,
            planning_priority_rank=1,
            reason="test",
        )


def test_priority_rank_must_be_positive():
    with pytest.raises(
        ValidationError
    ):
        PlanningAllocation(
            study_target_id=1,
            optional_extra_minutes=30,
            planning_priority_rank=0,
            reason="test",
        )


def test_unknown_field_is_rejected():
    with pytest.raises(
        ValidationError
    ):
        PlanningAllocation(
            study_target_id=1,
            optional_extra_minutes=30,
            planning_priority_rank=1,
            reason="test",
            unknown="value",
        )


def test_empty_output_is_allowed():
    output = PlanningOutput(
        allocations=[]
    )

    assert output.allocations == []