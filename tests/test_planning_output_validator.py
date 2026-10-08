import pytest

from ai.errors import (
    AIOutputInvalidError,
)
from ai.planning_models import (
    PlanningAllocation,
    PlanningOutput,
)
from ai.planning_output_validator import (
    PlanningOutputValidator,
)
from planning.optional_allocation import (
    OptionalAllocationBounds,
    PlanningAIContext,
)


def context():
    return PlanningAIContext(
        bounds=(
            OptionalAllocationBounds(
                study_target_id=1,
                minimum_optional_increment_minutes=15,
                maximum_optional_minutes=60,
                normal_target_minutes=90,
                mandatory_scheduled_minutes=30,
                best_effort_goal_ids=(),
            ),
            OptionalAllocationBounds(
                study_target_id=2,
                minimum_optional_increment_minutes=10,
                maximum_optional_minutes=40,
                normal_target_minutes=60,
                mandatory_scheduled_minutes=0,
                best_effort_goal_ids=(),
            ),
        ),
        total_soft_capacity_minutes=70,
        daily_remaining_capacity=(),
    )


def test_valid_output_passes():
    validator = (
        PlanningOutputValidator()
    )

    validator.validate(
        context=context(),
        output=PlanningOutput(
            allocations=[
                PlanningAllocation(
                    study_target_id=1,
                    optional_extra_minutes=30,
                    planning_priority_rank=1,
                    reason="優先",
                ),
                PlanningAllocation(
                    study_target_id=2,
                    optional_extra_minutes=40,
                    planning_priority_rank=2,
                    reason="次点",
                ),
            ]
        ),
    )


def test_unknown_or_missing_target_is_rejected():
    validator = (
        PlanningOutputValidator()
    )

    with pytest.raises(
        AIOutputInvalidError,
        match=(
            "StudyTarget IDs "
            "do not match"
        ),
    ):
        validator.validate(
            context=context(),
            output=PlanningOutput(
                allocations=[
                    PlanningAllocation(
                        study_target_id=1,
                        optional_extra_minutes=30,
                        planning_priority_rank=1,
                        reason="only one",
                    )
                ]
            ),
        )


def test_duplicate_rank_is_rejected():
    validator = (
        PlanningOutputValidator()
    )

    with pytest.raises(
        AIOutputInvalidError,
        match=(
            "unique 1..N"
        ),
    ):
        validator.validate(
            context=context(),
            output=PlanningOutput(
                allocations=[
                    PlanningAllocation(
                        study_target_id=1,
                        optional_extra_minutes=30,
                        planning_priority_rank=1,
                        reason="a",
                    ),
                    PlanningAllocation(
                        study_target_id=2,
                        optional_extra_minutes=20,
                        planning_priority_rank=1,
                        reason="b",
                    ),
                ]
            ),
        )


def test_target_maximum_is_enforced():
    validator = (
        PlanningOutputValidator()
    )

    with pytest.raises(
        AIOutputInvalidError,
        match="exceeds target maximum",
    ):
        validator.validate(
            context=context(),
            output=PlanningOutput(
                allocations=[
                    PlanningAllocation(
                        study_target_id=1,
                        optional_extra_minutes=65,
                        planning_priority_rank=1,
                        reason="too much",
                    ),
                    PlanningAllocation(
                        study_target_id=2,
                        optional_extra_minutes=0,
                        planning_priority_rank=2,
                        reason="none",
                    ),
                ]
            ),
        )


def test_positive_allocation_below_minimum_is_rejected():
    validator = (
        PlanningOutputValidator()
    )

    with pytest.raises(
        AIOutputInvalidError,
        match=(
            "below minimum increment"
        ),
    ):
        validator.validate(
            context=context(),
            output=PlanningOutput(
                allocations=[
                    PlanningAllocation(
                        study_target_id=1,
                        optional_extra_minutes=10,
                        planning_priority_rank=1,
                        reason="too small",
                    ),
                    PlanningAllocation(
                        study_target_id=2,
                        optional_extra_minutes=0,
                        planning_priority_rank=2,
                        reason="none",
                    ),
                ]
            ),
        )


def test_total_soft_capacity_is_enforced():
    validator = (
        PlanningOutputValidator()
    )

    with pytest.raises(
        AIOutputInvalidError,
        match="total_soft_capacity",
    ):
        validator.validate(
            context=context(),
            output=PlanningOutput(
                allocations=[
                    PlanningAllocation(
                        study_target_id=1,
                        optional_extra_minutes=60,
                        planning_priority_rank=1,
                        reason="a",
                    ),
                    PlanningAllocation(
                        study_target_id=2,
                        optional_extra_minutes=20,
                        planning_priority_rank=2,
                        reason="b",
                    ),
                ]
            ),
        )