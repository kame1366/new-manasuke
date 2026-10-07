from datetime import datetime

import pytest

from domain.enums import (
    GoalType,
    Importance,
    StudyTargetKind,
    UnitType,
)
from domain.errors import (
    DomainValidationError,
)
from domain.models import (
    Goal,
    StudyTarget,
    StudyTargetRange,
)
from domain.time_rules import JST
from planning.work_chunk_builder import (
    WorkChunkBuilder,
    scheduled_duration_minutes,
)
from planning.work_segment_builder import (
    WorkSegment,
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
        0,
        tzinfo=JST,
    )


def material_target(
    *,
    target_id: int = 1,
    unit_minutes: float = 5.0,
) -> StudyTarget:
    return StudyTarget(
        id=target_id,
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
                end_position=100,
            )
        ],
    )


def theme_target(
    *,
    target_id: int = 2,
) -> StudyTarget:
    return StudyTarget(
        id=target_id,
        participant_id="participant-a",
        kind=StudyTargetKind.THEME,
        title="英作文",
    )


def goal(
    *,
    goal_id: int,
    target_id: int,
    deadline_day: int,
) -> Goal:
    return Goal(
        id=goal_id,
        participant_id="participant-a",
        study_target_id=target_id,
        goal_type=GoalType.TEST,
        title=f"Goal {goal_id}",
        deadline_at=dt(
            deadline_day,
            18,
        ),
        importance=Importance.HIGH,
    )


@pytest.mark.parametrize(
    "estimated,expected",
    [
        (6.0, 10),
        (10.0, 10),
        (12.0, 15),
        (18.0, 20),
        (25.0, 25),
        (26.0, 30),
    ],
)
def test_scheduled_duration_is_rounded_correctly(
    estimated: float,
    expected: int,
):
    assert (
        scheduled_duration_minutes(
            estimated
        )
        == expected
    )


def test_material_segment_is_split_by_preferred_minutes():
    builder = WorkChunkBuilder()

    target = material_target(
        unit_minutes=6.0,
    )

    segment = WorkSegment(
        study_target_id=1,
        kind=StudyTargetKind.MATERIAL,
        estimated_minutes=60.0,
        required_by_goal_ids=(1,),
        direct_goal_ids=(1,),
        range_start=1,
        range_end=10,
    )

    chunks = (
        builder
        .build_mandatory_deadline_chunks(
            study_targets=[
                target
            ],
            goals=[
                goal(
                    goal_id=1,
                    target_id=1,
                    deadline_day=20,
                )
            ],
            work_segments=[
                segment
            ],
            strict_goal_ids={
                1
            },
            preferred_chunk_minutes_by_target={
                1: 25
            },
            not_before=dt(
                8,
            ),
        )
    )

    assert [
        (
            chunk.range_start,
            chunk.range_end,
            chunk.estimated_minutes,
            chunk.scheduled_duration_minutes,
        )
        for chunk in chunks
    ] == [
        (
            1,
            4,
            24.0,
            25,
        ),
        (
            5,
            8,
            24.0,
            25,
        ),
        (
            9,
            10,
            12.0,
            15,
        ),
    ]


def test_material_chunks_keep_order():
    builder = WorkChunkBuilder()

    target = material_target()

    segments = [
        WorkSegment(
            study_target_id=1,
            kind=StudyTargetKind.MATERIAL,
            estimated_minutes=25.0,
            required_by_goal_ids=(1,),
            direct_goal_ids=(1,),
            range_start=6,
            range_end=10,
        ),
        WorkSegment(
            study_target_id=1,
            kind=StudyTargetKind.MATERIAL,
            estimated_minutes=25.0,
            required_by_goal_ids=(1,),
            direct_goal_ids=(),
            range_start=1,
            range_end=5,
        ),
    ]

    chunks = (
        builder
        .build_mandatory_deadline_chunks(
            study_targets=[
                target
            ],
            goals=[
                goal(
                    goal_id=1,
                    target_id=1,
                    deadline_day=20,
                )
            ],
            work_segments=segments,
            strict_goal_ids={
                1
            },
            preferred_chunk_minutes_by_target={
                1: 30
            },
            not_before=dt(
                8
            ),
        )
    )

    assert chunks[0].range_start == 1
    assert chunks[-1].range_end == 10

    assert [
        chunk.sequence_no
        for chunk in chunks
    ] == list(
        range(
            len(chunks)
        )
    )


def test_shared_work_uses_earliest_strict_deadline():
    builder = WorkChunkBuilder()

    segment = WorkSegment(
        study_target_id=1,
        kind=StudyTargetKind.MATERIAL,
        estimated_minutes=25.0,
        required_by_goal_ids=(
            1,
            2,
        ),
        direct_goal_ids=(
            1,
            2,
        ),
        range_start=1,
        range_end=5,
    )

    chunks = (
        builder
        .build_mandatory_deadline_chunks(
            study_targets=[
                material_target()
            ],
            goals=[
                goal(
                    goal_id=1,
                    target_id=1,
                    deadline_day=12,
                ),
                goal(
                    goal_id=2,
                    target_id=1,
                    deadline_day=20,
                ),
            ],
            work_segments=[
                segment
            ],
            strict_goal_ids={
                1,
                2,
            },
            preferred_chunk_minutes_by_target={
                1: 30
            },
            not_before=dt(
                8
            ),
        )
    )

    assert len(chunks) == 1

    assert (
        chunks[0].must_finish_before
        == dt(
            12,
            18,
        )
    )


def test_best_effort_only_work_is_not_mandatory():
    builder = WorkChunkBuilder()

    segment = WorkSegment(
        study_target_id=1,
        kind=StudyTargetKind.MATERIAL,
        estimated_minutes=25.0,
        required_by_goal_ids=(2,),
        direct_goal_ids=(2,),
        range_start=1,
        range_end=5,
    )

    chunks = (
        builder
        .build_mandatory_deadline_chunks(
            study_targets=[
                material_target()
            ],
            goals=[
                goal(
                    goal_id=1,
                    target_id=1,
                    deadline_day=12,
                ),
                goal(
                    goal_id=2,
                    target_id=1,
                    deadline_day=20,
                ),
            ],
            work_segments=[
                segment
            ],
            strict_goal_ids={
                1
            },
            preferred_chunk_minutes_by_target={
                1: 30
            },
            not_before=dt(
                8
            ),
        )
    )

    assert chunks == []


def test_theme_segment_is_split():
    builder = WorkChunkBuilder()

    segment = WorkSegment(
        study_target_id=2,
        kind=StudyTargetKind.THEME,
        estimated_minutes=50.0,
        required_by_goal_ids=(1,),
        direct_goal_ids=(1,),
        theme_minute_start=0,
        theme_minute_end=50,
    )

    chunks = (
        builder
        .build_mandatory_deadline_chunks(
            study_targets=[
                theme_target()
            ],
            goals=[
                goal(
                    goal_id=1,
                    target_id=2,
                    deadline_day=20,
                )
            ],
            work_segments=[
                segment
            ],
            strict_goal_ids={
                1
            },
            preferred_chunk_minutes_by_target={
                2: 30
            },
            not_before=dt(
                8
            ),
        )
    )

    assert [
        (
            chunk.theme_minute_start,
            chunk.theme_minute_end,
            chunk.scheduled_duration_minutes,
        )
        for chunk in chunks
    ] == [
        (
            0,
            30,
            30,
        ),
        (
            30,
            50,
            20,
        ),
    ]


def test_missing_preferred_chunk_minutes_is_rejected():
    builder = WorkChunkBuilder()

    segment = WorkSegment(
        study_target_id=1,
        kind=StudyTargetKind.MATERIAL,
        estimated_minutes=25.0,
        required_by_goal_ids=(1,),
        direct_goal_ids=(1,),
        range_start=1,
        range_end=5,
    )

    with pytest.raises(
        DomainValidationError,
        match="preferred chunk minutes missing",
    ):
        (
            builder
            .build_mandatory_deadline_chunks(
                study_targets=[
                    material_target()
                ],
                goals=[
                    goal(
                        goal_id=1,
                        target_id=1,
                        deadline_day=20,
                    )
                ],
                work_segments=[
                    segment
                ],
                strict_goal_ids={
                    1
                },
                preferred_chunk_minutes_by_target={},
                not_before=dt(
                    8
                ),
            )
        )