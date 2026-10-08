from datetime import datetime

from domain.enums import (
    GoalType,
    Importance,
    StudyTargetKind,
    UnitType,
)
from domain.models import (
    Goal,
    LearningPolicy,
    StudyTarget,
    StudyTargetRange,
)
from domain.time_rules import JST
from planning.free_slot_builder import (
    FreeSlot,
)
from planning.optional_allocation import (
    OptionalAllocationContextBuilder,
)
from planning.work_chunk_builder import (
    WorkChunk,
)
from planning.work_segment_builder import (
    WorkSegment,
)


def dt(
    day: int,
    hour: int,
) -> datetime:
    return datetime(
        2026,
        10,
        day,
        hour,
        tzinfo=JST,
    )


def material_target(
    *,
    unit_minutes: float = 12.0,
) -> StudyTarget:
    return StudyTarget(
        id=1,
        participant_id="participant-a",
        kind=StudyTargetKind.MATERIAL,
        title="数学",
        unit_type=UnitType.PAGE,
        next_position=1,
        estimated_minutes_per_unit=(
            unit_minutes
        ),
        ranges=[
            StudyTargetRange(
                sequence_no=0,
                start_position=1,
                end_position=20,
            )
        ],
    )


def theme_target() -> StudyTarget:
    return StudyTarget(
        id=2,
        participant_id="participant-a",
        kind=StudyTargetKind.THEME,
        title="英作文",
    )


def policy(
    target_id: int,
    *,
    sessions: int = 3,
    minutes: int = 30,
) -> LearningPolicy:
    return LearningPolicy(
        study_target_id=target_id,
        purpose="学習する",
        policy_priority=(
            Importance.HIGH
        ),
        normal_sessions_per_week=(
            sessions
        ),
        normal_minutes=minutes,
        minimum_sessions_per_week=1,
        minimum_minutes=15,
    )


def goal(
    *,
    goal_id: int,
    target_id: int,
    target_minutes=None,
) -> Goal:
    return Goal(
        id=goal_id,
        participant_id="participant-a",
        study_target_id=target_id,
        goal_type=GoalType.TEST,
        title=f"Goal {goal_id}",
        deadline_at=dt(
            20,
            18,
        ),
        importance=Importance.HIGH,
        target_minutes=target_minutes,
    )


def test_material_minimum_increment_uses_one_unit():
    builder = (
        OptionalAllocationContextBuilder()
    )

    context = builder.build(
        study_targets=[
            material_target(
                unit_minutes=12.0
            )
        ],
        goals=[],
        learning_policies=[
            policy(
                1,
                sessions=3,
                minutes=30,
            )
        ],
        work_segments=[],
        strict_goal_ids=set(),
        best_effort_goal_ids=set(),
        mandatory_chunks=[],
        remaining_free_slots=[
            FreeSlot(
                start_at=dt(
                    11,
                    18,
                ),
                end_at=dt(
                    11,
                    20,
                ),
            )
        ],
    )

    assert len(
        context.bounds
    ) == 1

    bound = context.bounds[0]

    assert (
        bound
        .minimum_optional_increment_minutes
        == 15
    )

    assert (
        bound.maximum_optional_minutes
        == 90
    )


def test_mandatory_minutes_reduce_normal_target():
    builder = (
        OptionalAllocationContextBuilder()
    )

    mandatory = WorkChunk(
        chunk_id="mandatory",
        study_target_id=1,
        kind=StudyTargetKind.MATERIAL,
        estimated_minutes=24.0,
        scheduled_duration_minutes=25,
        sequence_no=0,
        mandatory=True,
        required_by_goal_ids=(1,),
        range_start=1,
        range_end=2,
    )

    context = builder.build(
        study_targets=[
            material_target()
        ],
        goals=[],
        learning_policies=[
            policy(
                1,
                sessions=2,
                minutes=30,
            )
        ],
        work_segments=[],
        strict_goal_ids=set(),
        best_effort_goal_ids=set(),
        mandatory_chunks=[
            mandatory
        ],
        remaining_free_slots=[
            FreeSlot(
                start_at=dt(
                    11,
                    18,
                ),
                end_at=dt(
                    11,
                    20,
                ),
            )
        ],
    )

    bound = context.bounds[0]

    assert (
        bound.normal_target_minutes
        == 60
    )

    assert (
        bound.mandatory_scheduled_minutes
        == 25
    )

    assert (
        bound.maximum_optional_minutes
        == 35
    )


def test_shared_strict_best_effort_work_is_not_counted_twice():
    builder = (
        OptionalAllocationContextBuilder()
    )

    target = theme_target()

    shared_segment = WorkSegment(
        study_target_id=2,
        kind=StudyTargetKind.THEME,
        estimated_minutes=30.0,
        required_by_goal_ids=(
            1,
            2,
        ),
        direct_goal_ids=(
            1,
            2,
        ),
        theme_minute_start=0,
        theme_minute_end=30,
    )

    mandatory = WorkChunk(
        chunk_id="mandatory-theme",
        study_target_id=2,
        kind=StudyTargetKind.THEME,
        estimated_minutes=30.0,
        scheduled_duration_minutes=30,
        sequence_no=0,
        mandatory=True,
        required_by_goal_ids=(
            1,
            2,
        ),
        theme_minute_start=0,
        theme_minute_end=30,
    )

    context = builder.build(
        study_targets=[
            target
        ],
        goals=[
            goal(
                goal_id=1,
                target_id=2,
                target_minutes=30,
            ),
            goal(
                goal_id=2,
                target_id=2,
                target_minutes=30,
            ),
        ],
        learning_policies=[
            policy(
                2,
                sessions=1,
                minutes=30,
            )
        ],
        work_segments=[
            shared_segment
        ],
        strict_goal_ids={
            1
        },
        best_effort_goal_ids={
            2
        },
        mandatory_chunks=[
            mandatory
        ],
        remaining_free_slots=[
            FreeSlot(
                start_at=dt(
                    11,
                    18,
                ),
                end_at=dt(
                    11,
                    19,
                ),
            )
        ],
        theme_completed_minutes_by_target={
            2: 0
        },
    )

    # STRICT workとして30分すでに配置済み。
    # Goal 2とsharedだからoptionalへ
    # もう一度30分出してはいけない。
    assert context.bounds == ()

    assert (
        context.total_soft_capacity_minutes
        == 0
    )


def test_total_soft_capacity_is_limited_by_free_slots():
    builder = (
        OptionalAllocationContextBuilder()
    )

    context = builder.build(
        study_targets=[
            theme_target()
        ],
        goals=[],
        learning_policies=[
            policy(
                2,
                sessions=5,
                minutes=30,
            )
        ],
        work_segments=[],
        strict_goal_ids=set(),
        best_effort_goal_ids=set(),
        mandatory_chunks=[],
        remaining_free_slots=[
            FreeSlot(
                start_at=dt(
                    11,
                    18,
                ),
                end_at=dt(
                    11,
                    19,
                ),
            )
        ],
    )

    assert (
        context.bounds[0]
        .maximum_optional_minutes
        == 150
    )

    assert (
        context.total_soft_capacity_minutes
        == 60
    )


def test_daily_remaining_capacity_is_reference_information():
    builder = (
        OptionalAllocationContextBuilder()
    )

    context = builder.build(
        study_targets=[
            theme_target()
        ],
        goals=[],
        learning_policies=[
            policy(
                2,
                sessions=5,
                minutes=30,
            )
        ],
        work_segments=[],
        strict_goal_ids=set(),
        best_effort_goal_ids=set(),
        mandatory_chunks=[],
        remaining_free_slots=[
            FreeSlot(
                start_at=dt(
                    11,
                    18,
                ),
                end_at=dt(
                    11,
                    19,
                ),
            ),
            FreeSlot(
                start_at=dt(
                    12,
                    18,
                ),
                end_at=dt(
                    12,
                    19,
                ),
            ),
        ],
    )

    assert [
        item.minutes
        for item
        in context.daily_remaining_capacity
    ] == [
        60,
        60,
    ]