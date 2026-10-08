import json
from types import SimpleNamespace

from ai.planning_generator import (
    PlanningGenerator,
)
from ai.planning_models import (
    PlanningAllocation,
    PlanningOutput,
)
from domain.enums import (
    Importance,
    StudyTargetKind,
)
from domain.models import (
    LearningPolicy,
    StudyTarget,
)
from planning.optional_allocation import (
    OptionalAllocationBounds,
    PlanningAIContext,
)


class FakeResponses:
    def __init__(
        self,
        parsed,
    ):
        self.parsed = parsed
        self.last_kwargs = None

    def parse(
        self,
        **kwargs,
    ):
        self.last_kwargs = kwargs

        return SimpleNamespace(
            output_parsed=(
                self.parsed
            ),
            status="completed",
        )


class FakeClient:
    def __init__(
        self,
        parsed,
    ):
        self.responses = (
            FakeResponses(
                parsed
            )
        )


def context():
    return PlanningAIContext(
        bounds=(
            OptionalAllocationBounds(
                study_target_id=1,
                minimum_optional_increment_minutes=10,
                maximum_optional_minutes=60,
                normal_target_minutes=90,
                mandatory_scheduled_minutes=30,
                best_effort_goal_ids=(),
            ),
        ),
        total_soft_capacity_minutes=60,
        daily_remaining_capacity=(),
    )


def target():
    return StudyTarget(
        id=1,
        participant_id="participant-a",
        kind=StudyTargetKind.THEME,
        title="英作文",
    )


def policy():
    return LearningPolicy(
        study_target_id=1,
        purpose="英作文の練習",
        policy_priority=Importance.HIGH,
        normal_sessions_per_week=3,
        normal_minutes=30,
        minimum_sessions_per_week=1,
        minimum_minutes=15,
    )


def output():
    return PlanningOutput(
        allocations=[
            PlanningAllocation(
                study_target_id=1,
                optional_extra_minutes=30,
                planning_priority_rank=1,
                reason="通常学習を追加",
            )
        ]
    )


def test_generator_uses_structured_outputs():
    client = FakeClient(
        output()
    )

    generator = PlanningGenerator(
        client=client,
        model_name="test-model",
    )

    result = generator.generate(
        context=context(),
        study_targets=[
            target()
        ],
        goals=[],
        learning_policies=[
            policy()
        ],
    )

    assert result == output()

    kwargs = (
        client.responses.last_kwargs
    )

    assert (
        kwargs["model"]
        == "test-model"
    )

    assert (
        kwargs["text_format"]
        is PlanningOutput
    )

    assert (
        kwargs["store"]
        is False
    )


def test_generator_payload_contains_hard_bounds():
    client = FakeClient(
        output()
    )

    generator = PlanningGenerator(
        client=client,
        model_name="test-model",
    )

    generator.generate(
        context=context(),
        study_targets=[
            target()
        ],
        goals=[],
        learning_policies=[
            policy()
        ],
    )

    payload = json.loads(
        client
        .responses
        .last_kwargs[
            "input"
        ]
    )

    bound = (
        payload[
            "optional_bounds"
        ][0]
    )

    assert (
        bound[
            "minimum_optional_increment_minutes"
        ]
        == 10
    )

    assert (
        bound[
            "maximum_optional_minutes"
        ]
        == 60
    )

    assert (
        payload[
            "total_soft_capacity_minutes"
        ]
        == 60
    )


def test_empty_context_does_not_call_api():
    client = FakeClient(
        None
    )

    generator = PlanningGenerator(
        client=client,
        model_name="test-model",
    )

    result = generator.generate(
        context=PlanningAIContext(
            bounds=(),
            total_soft_capacity_minutes=0,
            daily_remaining_capacity=(),
        ),
        study_targets=[],
        goals=[],
        learning_policies=[],
    )

    assert result.allocations == []

    assert (
        client.responses.last_kwargs
        is None
    )