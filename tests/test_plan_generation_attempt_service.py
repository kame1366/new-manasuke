from datetime import (
    datetime,
    timedelta,
)

import pytest

from ai.errors import (
    PlanningDataChangedError,
)
from db.connection import transaction
from domain.enums import (
    AttemptStatus,
    PlanOperationType,
    StudyTargetKind,
)
from domain.models import (
    AvailableTime,
    StudyTarget,
)
from domain.time_rules import JST
from planning.feasibility_analyzer import (
    FeasibilityResult,
)
from planning.free_slot_builder import (
    FreeSlot,
)
from planning.placement_engine import (
    ScheduledChunk,
)
from planning.work_chunk_builder import (
    WorkChunk,
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
from repositories.plan_repository import (
    PlanRepository,
)
from repositories.study_target_repository import (
    StudyTargetRepository,
)
from scripts.migrate import run_migrations
from services.plan_generation_attempt_service import (
    PlanGenerationAttemptService,
)


def dt(
    day: int,
    hour: int = 0,
    minute: int = 0,
) -> datetime:
    return datetime(
        2026,
        10,
        day,
        hour,
        minute,
        tzinfo=JST,
    )


def setup_scheduling_attempt(
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

    target_id = (
        StudyTargetRepository(
            db_path
        ).create(
            StudyTarget(
                id=0,
                participant_id=(
                    "participant-a"
                ),
                kind=(
                    StudyTargetKind.THEME
                ),
                title="英作文",
            )
        )
    )

    attempt_repository = (
        PlanGenerationAttemptRepository(
            db_path
        )
    )

    attempt = attempt_repository.start(
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

    checkpoint = (
        PlanGenerationCheckpointRepository(
            db_path
        )
    )

    checkpoint.record_baseline(
        participant_id=(
            "participant-a"
        ),
        attempt_id=(
            attempt.id
        ),
        result=FeasibilityResult(
            total_projected_capacity_minutes=60,
            normalized_required_minutes=0,
            aggregate_shortage_minutes=0,
            strict_set_feasible=True,
            goal_results=(),
            deadline_snapshots=(),
        ),
        now=dt(
            12,
            10,
        ),
    )

    # AI②を実際には呼ばず、
    # SCHEDULING checkpointだけ作る。
    from repositories.ai_interaction_repository import (
        AIInteractionRepository,
    )

    ai_repo = (
        AIInteractionRepository(
            db_path
        )
    )

    interaction_id = (
        ai_repo.start_for_attempt(
            participant_id=(
                "participant-a"
            ),
            attempt_id=(
                attempt.id
            ),
            prompt_version="test",
            model_name="test",
            now=dt(
                12,
                10,
            ),
        )
    )

    checkpoint.record_planning_ai_success(
        participant_id=(
            "participant-a"
        ),
        attempt_id=(
            attempt.id
        ),
        interaction_id=(
            interaction_id
        ),
        structured_output_json=(
            '{"allocations":[]}'
        ),
        now=dt(
            12,
            10,
        ),
    )

    target = StudyTargetRepository(
        db_path
    ).get_by_id(
        "participant-a",
        target_id,
    )

    assert target is not None

    return (
        attempt,
        target,
    )


def scheduled_chunk(
    target_id: int,
):
    chunk = WorkChunk(
        chunk_id="theme-1",
        study_target_id=(
            target_id
        ),
        kind=StudyTargetKind.THEME,
        estimated_minutes=30.0,
        scheduled_duration_minutes=30,
        sequence_no=0,
        mandatory=False,
        required_by_goal_ids=(),
        planning_priority_rank=1,
        theme_minute_start=0,
        theme_minute_end=30,
    )

    return ScheduledChunk(
        chunk=chunk,
        start_at=dt(
            12,
            18,
        ),
        end_at=dt(
            12,
            18,
            30,
        ),
    )


def test_successful_finalize_saves_plan_and_marks_attempt_succeeded(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    (
        attempt,
        target,
    ) = setup_scheduling_attempt(
        db_path
    )

    service = (
        PlanGenerationAttemptService(
            db_path=db_path
        )
    )

    plan = service.finalize(
        participant_id=(
            "participant-a"
        ),
        attempt_id=(
            attempt.id
        ),
        effective_from=dt(
            12,
            18,
        ),
        scheduled_chunks=[
            scheduled_chunk(
                target.id
            )
        ],
        study_targets=[
            target
        ],
        goals=[],
        strict_goal_ids=set(),
        weekly_available_times=[
            # 2026-10-12 Monday
            AvailableTime(
                weekday=0,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    19 * 60
                ),
            )
        ],
        extra_available_times=[],
        busy_events=[],
        now=dt(
            12,
            12,
        ),
    )

    assert plan.version_no == 1

    plans = PlanRepository(
        db_path
    ).list_by_participant(
        "participant-a"
    )

    assert len(plans) == 1

    items = PlanRepository(
        db_path
    ).list_items(
        participant_id=(
            "participant-a"
        ),
        plan_id=(
            plan.id
        ),
    )

    assert len(items) == 1

    reloaded_attempt = (
        PlanGenerationAttemptRepository(
            db_path
        ).get_by_id(
            "participant-a",
            attempt.id,
        )
    )

    assert (
        reloaded_attempt is not None
    )

    assert (
        reloaded_attempt.status
        == AttemptStatus.SUCCEEDED
    )

    assert (
        reloaded_attempt
        .resulting_plan_id
        == plan.id
    )


def test_source_data_change_prevents_plan_save(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    (
        attempt,
        target,
    ) = setup_scheduling_attempt(
        db_path
    )

    # Attempt開始後にSource Dataが変わった。
    with transaction(
        db_path
    ) as connection:
        ParticipantRepository.increment_planning_data_version(
            connection,
            "participant-a",
        )

    service = (
        PlanGenerationAttemptService(
            db_path=db_path
        )
    )

    with pytest.raises(
        PlanningDataChangedError
    ):
        service.finalize(
            participant_id=(
                "participant-a"
            ),
            attempt_id=(
                attempt.id
            ),
            effective_from=dt(
                12,
                18,
            ),
            scheduled_chunks=[
                scheduled_chunk(
                    target.id
                )
            ],
            study_targets=[
                target
            ],
            goals=[],
            strict_goal_ids=set(),
            weekly_available_times=[
                AvailableTime(
                    weekday=0,
                    start_minute_of_day=(
                        18 * 60
                    ),
                    end_minute_of_day=(
                        19 * 60
                    ),
                )
            ],
            extra_available_times=[],
            busy_events=[],
            now=dt(
                12,
                12,
            ),
        )

    # 新Planは一切残らない。
    plans = PlanRepository(
        db_path
    ).list_by_participant(
        "participant-a"
    )

    assert plans == []

    reloaded_attempt = (
        PlanGenerationAttemptRepository(
            db_path
        ).get_by_id(
            "participant-a",
            attempt.id,
        )
    )

    assert reloaded_attempt is not None

    assert (
        reloaded_attempt.status
        == AttemptStatus.FAILED
    )

    assert (
        reloaded_attempt.error_type
        == "PLANNING_DATA_CHANGED"
    )