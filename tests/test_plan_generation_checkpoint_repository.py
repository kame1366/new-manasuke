from datetime import (
    datetime,
    timedelta,
)

from domain.enums import (
    AttemptStage,
    GoalType,
    GoalMode,
    Importance,
    PlanOperationType,
    StudyTargetKind,
)
from domain.time_rules import JST
from domain.models import Goal, StudyTarget
from repositories.goal_repository import GoalRepository
from planning.feasibility_analyzer import (
    DeadlineFeasibilitySnapshot,
    FeasibilityResult,
    GoalFeasibilityResult,
)
from repositories.participant_repository import (
    ParticipantRepository,
)
from repositories.study_target_repository import (
    StudyTargetRepository,
)
from repositories.plan_generation_attempt_repository import (
    PlanGenerationAttemptRepository,
)
from repositories.plan_generation_checkpoint_repository import (
    PlanGenerationCheckpointRepository,
)
from scripts.migrate import run_migrations


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


def setup_attempt(
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

    target_repository = StudyTargetRepository(
        db_path
    )
    goal_repository = GoalRepository(
        db_path
    )

    for title in ("Goal 1", "Goal 2"):
        target_id = target_repository.create(
            StudyTarget(
                id=0,
                participant_id="participant-a",
                kind=StudyTargetKind.THEME,
                title=title,
            )
        )
        goal_repository.create(
            Goal(
                id=0,
                participant_id="participant-a",
                study_target_id=target_id,
                goal_type=GoalType.PERSONAL,
                title=title,
                deadline_at=dt(20, 18),
                importance=Importance.MEDIUM,
            )
        )

    return (
        PlanGenerationAttemptRepository(
            db_path
        ).start(
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


def goal_result(
    goal_id: int,
    *,
    feasible: bool,
    required: int,
    shortage: int,
):
    return GoalFeasibilityResult(
        goal_id=goal_id,
        individually_feasible=(
            feasible
        ),
        estimated_required_minutes=(
            required
        ),
        individual_shortage_minutes=(
            shortage
        ),
        projected_capacity_minutes=120,
    )


def feasibility(
    *,
    feasible: bool,
    shortage: int,
):
    return FeasibilityResult(
        total_projected_capacity_minutes=(
            120
        ),
        normalized_required_minutes=(
            120 + shortage
        ),
        aggregate_shortage_minutes=(
            shortage
        ),
        strict_set_feasible=(
            feasible
        ),
        goal_results=(
            goal_result(
                1,
                feasible=feasible,
                required=60,
                shortage=(
                    shortage
                ),
            ),
            goal_result(
                2,
                feasible=True,
                required=60,
                shortage=0,
            ),
        ),
        deadline_snapshots=(
            DeadlineFeasibilitySnapshot(
                deadline_at=dt(
                    20,
                    18,
                ),
                cumulative_required_minutes=(
                    120 + shortage
                ),
                cumulative_available_minutes=(
                    120
                ),
                cumulative_shortage_minutes=(
                    shortage
                ),
                feasible=feasible,
            ),
        ),
    )


def test_infeasible_baseline_waits_for_user(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    attempt = setup_attempt(
        db_path
    )

    repository = (
        PlanGenerationCheckpointRepository(
            db_path
        )
    )

    stage = repository.record_baseline(
        participant_id=(
            "participant-a"
        ),
        attempt_id=(
            attempt.id
        ),
        result=feasibility(
            feasible=False,
            shortage=30,
        ),
        now=dt(
            12,
            10,
        ),
    )

    assert (
        stage
        == AttemptStage
        .AWAITING_GOAL_DECISION
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
        == AttemptStage
        .AWAITING_GOAL_DECISION
    )


def test_feasible_baseline_auto_advances_to_ai(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    attempt = setup_attempt(
        db_path
    )

    repository = (
        PlanGenerationCheckpointRepository(
            db_path
        )
    )

    stage = repository.record_baseline(
        participant_id=(
            "participant-a"
        ),
        attempt_id=(
            attempt.id
        ),
        result=feasibility(
            feasible=True,
            shortage=0,
        ),
        now=dt(
            12,
            10,
        ),
    )

    assert (
        stage
        == AttemptStage.AI_PLANNING
    )


def test_user_selection_advances_to_ai_planning(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    attempt = setup_attempt(
        db_path
    )

    repository = (
        PlanGenerationCheckpointRepository(
            db_path
        )
    )

    baseline = feasibility(
        feasible=False,
        shortage=30,
    )

    repository.record_baseline(
        participant_id=(
            "participant-a"
        ),
        attempt_id=(
            attempt.id
        ),
        result=baseline,
        now=dt(
            12,
            10,
        ),
    )

    final = FeasibilityResult(
        total_projected_capacity_minutes=120,
        normalized_required_minutes=60,
        aggregate_shortage_minutes=0,
        strict_set_feasible=True,
        goal_results=(
            baseline.goal_results
        ),
        deadline_snapshots=(
            DeadlineFeasibilitySnapshot(
                deadline_at=dt(
                    20,
                    18,
                ),
                cumulative_required_minutes=60,
                cumulative_available_minutes=120,
                cumulative_shortage_minutes=0,
                feasible=True,
            ),
        ),
    )

    repository.record_user_selection(
        participant_id=(
            "participant-a"
        ),
        attempt_id=(
            attempt.id
        ),
        baseline_goal_results=(
            baseline.goal_results
        ),
        goal_modes={
            1: GoalMode.BEST_EFFORT,
            2: GoalMode.STRICT,
        },
        final_result=final,
        now=dt(
            12,
            10,
        ),
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
        == AttemptStage.AI_PLANNING
    )