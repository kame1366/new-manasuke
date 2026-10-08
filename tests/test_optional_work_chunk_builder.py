from datetime import datetime

from ai.planning_models import (
    PlanningAllocation,
    PlanningOutput,
)
from domain.enums import (
    Importance,
    StudyTargetKind,
    UnitType,
)
from domain.models import (
    LearningPolicy,
    StudyTarget,
    StudyTargetRange,
)
from domain.time_rules import JST
from planning.optional_work_chunk_builder import (
    OptionalWorkChunkBuilder,
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


def material_target():
    return StudyTarget(
        id=1,
        participant_id="participant-a",
        kind=StudyTargetKind.MATERIAL,
        title="数学",
        unit_type=UnitType.PAGE,
        next_position=1,
        estimated_minutes_per_unit=12.0,
        ranges=[
            StudyTargetRange(
                sequence_no=0,
                start_position=1,
                end_position=10,
            )
        ],
    )


def theme_target():
    return StudyTarget(
        id=2,
        participant_id="participant-a",
        kind=StudyTargetKind.THEME,
        title="英作文",
    )


def policy(
    target_id: int,
    normal_minutes: int,
):
    return LearningPolicy(
        study_target_id=target_id,
        purpose="学習",
        policy_priority=Importance.HIGH,
        normal_sessions_per_week=3,
        normal_minutes=normal_minutes,
        minimum_sessions_per_week=1,
        minimum_minutes=15,
    )


def test_material_optional_budget_is_upper_bound():
    builder = (
        OptionalWorkChunkBuilder()
    )

    output = PlanningOutput(
        allocations=[
            PlanningAllocation(
                study_target_id=1,
                optional_extra_minutes=20,
                planning_priority_rank=1,
                reason="追加",
            )
        ]
    )

    chunks = builder.build(
        output=output,
        study_targets=[
            material_target()
        ],
        learning_policies=[
            policy(
                1,
                30,
            )
        ],
        work_segments=[],
        strict_goal_ids=set(),
        best_effort_goal_ids=set(),
        mandatory_chunks=[],
        not_before=dt(
            11
        ),
    )

    # 12分/unit
    # 1 unit -> scheduled 15分
    # 2 units -> scheduled 25分
    #
    # budget 20なので1 unitだけ。
    assert len(chunks) == 1

    assert (
        chunks[0].range_start
        == 1
    )

    assert (
        chunks[0].range_end
        == 1
    )

    assert (
        chunks[0]
        .scheduled_duration_minutes
        == 15
    )

    assert chunks[0].mandatory is False

    assert (
        chunks[0]
        .planning_priority_rank
        == 1
    )


def test_material_optional_keeps_order():
    builder = (
        OptionalWorkChunkBuilder()
    )

    output = PlanningOutput(
        allocations=[
            PlanningAllocation(
                study_target_id=1,
                optional_extra_minutes=45,
                planning_priority_rank=1,
                reason="追加",
            )
        ]
    )

    chunks = builder.build(
        output=output,
        study_targets=[
            material_target()
        ],
        learning_policies=[
            policy(
                1,
                30,
            )
        ],
        work_segments=[],
        strict_goal_ids=set(),
        best_effort_goal_ids=set(),
        mandatory_chunks=[],
        not_before=dt(
            11
        ),
    )

    assert (
        chunks[0].range_start
        == 1
    )

    for previous, current in zip(
        chunks,
        chunks[1:],
    ):
        assert (
            previous.range_end
            is not None
        )

        assert (
            current.range_start
            == previous.range_end + 1
        )


def test_theme_35_minutes_does_not_create_five_minute_chunk():
    builder = (
        OptionalWorkChunkBuilder()
    )

    output = PlanningOutput(
        allocations=[
            PlanningAllocation(
                study_target_id=2,
                optional_extra_minutes=35,
                planning_priority_rank=1,
                reason="追加",
            )
        ]
    )

    chunks = builder.build(
        output=output,
        study_targets=[
            theme_target()
        ],
        learning_policies=[
            policy(
                2,
                30,
            )
        ],
        work_segments=[],
        strict_goal_ids=set(),
        best_effort_goal_ids=set(),
        mandatory_chunks=[],
        not_before=dt(
            11
        ),
    )

    assert [
        chunk.scheduled_duration_minutes
        for chunk in chunks
    ] == [
        25,
        10,
    ]

    assert sum(
        chunk.scheduled_duration_minutes
        for chunk in chunks
    ) == 35


def test_zero_optional_allocation_creates_no_chunks():
    builder = (
        OptionalWorkChunkBuilder()
    )

    output = PlanningOutput(
        allocations=[
            PlanningAllocation(
                study_target_id=2,
                optional_extra_minutes=0,
                planning_priority_rank=1,
                reason="追加不要",
            )
        ]
    )

    chunks = builder.build(
        output=output,
        study_targets=[
            theme_target()
        ],
        learning_policies=[
            policy(
                2,
                30,
            )
        ],
        work_segments=[],
        strict_goal_ids=set(),
        best_effort_goal_ids=set(),
        mandatory_chunks=[],
        not_before=dt(
            11
        ),
    )

    assert chunks == []