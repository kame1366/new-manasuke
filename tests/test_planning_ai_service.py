import pytest

from ai.errors import (
    AIOutputInvalidError,
)
from ai.planning_models import (
    PlanningAllocation,
    PlanningOutput,
)
from planning.optional_allocation import (
    OptionalAllocationBounds,
    PlanningAIContext,
)
from services.planning_ai_service import (
    PlanningAIService,
)


class FakeGenerator:
    def __init__(
        self,
        outputs,
    ):
        self.outputs = list(
            outputs
        )

        self.calls = []

    def generate(
        self,
        *,
        context,
        study_targets,
        goals,
        learning_policies,
        correction_feedback=None,
    ):
        self.calls.append(
            correction_feedback
        )

        return self.outputs[
            len(self.calls) - 1
        ]


def context():
    return PlanningAIContext(
        bounds=(
            OptionalAllocationBounds(
                study_target_id=1,
                minimum_optional_increment_minutes=10,
                maximum_optional_minutes=60,
                normal_target_minutes=60,
                mandatory_scheduled_minutes=0,
                best_effort_goal_ids=(),
            ),
        ),
        total_soft_capacity_minutes=60,
        daily_remaining_capacity=(),
    )


def valid_output():
    return PlanningOutput(
        allocations=[
            PlanningAllocation(
                study_target_id=1,
                optional_extra_minutes=30,
                planning_priority_rank=1,
                reason="valid",
            )
        ]
    )


def invalid_output():
    return PlanningOutput(
        allocations=[
            PlanningAllocation(
                study_target_id=1,
                optional_extra_minutes=100,
                planning_priority_rank=1,
                reason="too much",
            )
        ]
    )


def test_valid_first_output_uses_one_generation():
    generator = FakeGenerator(
        [
            valid_output()
        ]
    )

    service = PlanningAIService(
        generator=generator
    )

    result = (
        service
        .generate_validated_output(
            context=context(),
            study_targets=[],
            goals=[],
            learning_policies=[],
        )
    )

    assert result == valid_output()

    assert len(
        generator.calls
    ) == 1

    assert (
        generator.calls[0]
        is None
    )


def test_invalid_output_gets_one_corrective_generation():
    generator = FakeGenerator(
        [
            invalid_output(),
            valid_output(),
        ]
    )

    service = PlanningAIService(
        generator=generator
    )

    result = (
        service
        .generate_validated_output(
            context=context(),
            study_targets=[],
            goals=[],
            learning_policies=[],
        )
    )

    assert result == valid_output()

    assert len(
        generator.calls
    ) == 2

    assert (
        generator.calls[1]
        is not None
    )

    assert (
        "semantically invalid"
        in generator.calls[1]
    )


def test_second_invalid_output_fails():
    generator = FakeGenerator(
        [
            invalid_output(),
            invalid_output(),
        ]
    )

    service = PlanningAIService(
        generator=generator
    )

    with pytest.raises(
        AIOutputInvalidError,
        match=(
            "remained invalid "
            "after one corrective"
        ),
    ):
        (
            service
            .generate_validated_output(
                context=context(),
                study_targets=[],
                goals=[],
                learning_policies=[],
            )
        )

    assert len(
        generator.calls
    ) == 2


def test_empty_context_skips_ai():
    generator = FakeGenerator(
        []
    )

    service = PlanningAIService(
        generator=generator
    )

    result = (
        service
        .generate_validated_output(
            context=PlanningAIContext(
                bounds=(),
                total_soft_capacity_minutes=0,
                daily_remaining_capacity=(),
            ),
            study_targets=[],
            goals=[],
            learning_policies=[],
        )
    )

    assert result.allocations == []

    assert generator.calls == []