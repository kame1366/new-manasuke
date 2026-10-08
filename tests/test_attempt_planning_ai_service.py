from datetime import (
    datetime,
    timedelta,
)

from ai.planning_models import (
    PlanningAllocation,
    PlanningOutput,
)
from domain.enums import (
    AttemptStage,
    Importance,
    PlanOperationType,
    StudyTargetKind,
)
from domain.models import (
    LearningPolicy,
    StudyTarget,
)
from domain.time_rules import JST
from planning.feasibility_analyzer import (
    FeasibilityResult,
)
from planning.optional_allocation import (
    OptionalAllocationBounds,
    PlanningAIContext,
)
from repositories.ai_interaction_repository import (
    AI_STATUS_SUCCEEDED,
    AIInteractionRepository,
)
from repositories.participant_repository import (
    ParticipantRepository,
)
from repositories.plan_generation_attempt_repository import (
    PlanGenerationAttemptRepository,
)
from repositories.plan_generation_checkpoint_repository import (
    PlanGenerationCheckpointRepository,
)
from scripts.migrate import run_migrations
from services.attempt_planning_ai_service import (
    AttemptPlanningAIService,
)


class FakePlanningAIService:
    def generate_validated_output(
        self,
        *,
        context,
        study_targets,
        goals,
        learning_policies,
    ):
        return PlanningOutput(
            allocations=[
                PlanningAllocation(
                    study_target_id=1,
                    optional_extra_minutes=30,
                    planning_priority_rank=1,
                    reason="test",
                )
            ]
        )


def dt(
    day: int,
    hour: int = 0,
) -> datetime:
    return datetime(
        2026,
        10,
        day,
        hour,
        tzinfo=JST,
    )


def setup_ai_planning_attempt(
    db_path,
):
    ParticipantRepository(
        db_path
    ).create(
        "participant-a",
        dt(
            12,
            9,
        ),
    )

    attempt_repository = (
        PlanGenerationAttemptRepository(
            db_path
        )
    )

    attempt = (
        attempt_repository.start(
            participant_id=(
                "participant-a"
            ),
            operation_type=(
                PlanOperationType.INITIAL
            ),
            now=dt(
                12,
                10,
            ),
            stale_after=timedelta(
                minutes=30
            ),
        )
    )

    # goalなしならbaseline strict_set_feasible=True
    result = FeasibilityResult(
        total_projected_capacity_minutes=60,
        normalized_required_minutes=0,
        aggregate_shortage_minutes=0,
        strict_set_feasible=True,
        goal_results=(),
        deadline_snapshots=(),
    )

    PlanGenerationCheckpointRepository(
        db_path
    ).record_baseline(
        participant_id=(
            "participant-a"
        ),
        attempt_id=(
            attempt.id
        ),
        result=result,
        now=dt(
            12,
            10,
        ),
    )

    return attempt


def test_ai_output_and_stage_are_checkpointed(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    attempt = (
        setup_ai_planning_attempt(
            db_path
        )
    )

    service = (
        AttemptPlanningAIService(
            db_path=db_path,
            planning_ai_service=(
                FakePlanningAIService()
            ),
            prompt_version=(
                "planning-test-v1"
            ),
            model_name="test-model",
        )
    )

    context = PlanningAIContext(
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

    target = StudyTarget(
        id=1,
        participant_id="participant-a",
        kind=StudyTargetKind.THEME,
        title="英作文",
    )

    policy = LearningPolicy(
        study_target_id=1,
        purpose="英作文",
        policy_priority=Importance.HIGH,
        normal_sessions_per_week=3,
        normal_minutes=30,
        minimum_sessions_per_week=1,
        minimum_minutes=15,
    )

    output = service.execute(
        participant_id=(
            "participant-a"
        ),
        attempt_id=(
            attempt.id
        ),
        context=context,
        study_targets=[
            target
        ],
        goals=[],
        learning_policies=[
            policy
        ],
        now=dt(
            12,
            11,
        ),
    )

    assert (
        output.allocations[0]
        .optional_extra_minutes
        == 30
    )

    reloaded = (
        PlanGenerationAttemptRepository(
            db_path
        ).get_by_id(
            "participant-a",
            attempt.id,
        )
    )

    assert reloaded is not None

    assert (
        reloaded.stage
        == AttemptStage.SCHEDULING
    )

    interaction = (
        AIInteractionRepository(
            db_path
        ).get_latest_for_operation(
            participant_id=(
                "participant-a"
            ),
            operation_type=(
                "PLANNING_GENERATION"
            ),
        )
    )

    assert interaction is not None

    assert (
        interaction.attempt_id
        == attempt.id
    )

    assert (
        interaction.status
        == AI_STATUS_SUCCEEDED
    )

    assert (
        interaction
        .structured_output_json
        is not None
    )