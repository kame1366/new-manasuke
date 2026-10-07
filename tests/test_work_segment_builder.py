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
    GoalRange,
    StudyTarget,
    StudyTargetRange,
)
from domain.time_rules import JST
from planning.work_segment_builder import (
    WorkSegmentBuilder,
)


def material_target(
    *,
    target_id: int = 1,
    next_position: int = 1,
    estimated_minutes_per_unit: float = 5.0,
    ranges: list[
        StudyTargetRange
    ]
    | None = None,
) -> StudyTarget:
    return StudyTarget(
        id=target_id,
        participant_id="participant-a",
        kind=StudyTargetKind.MATERIAL,
        title="数学問題集",
        unit_type=UnitType.PAGE,
        next_position=next_position,
        estimated_minutes_per_unit=(
            estimated_minutes_per_unit
        ),
        ranges=(
            ranges
            if ranges is not None
            else [
                StudyTargetRange(
                    sequence_no=0,
                    start_position=1,
                    end_position=100,
                )
            ]
        ),
    )


def theme_target(
    *,
    target_id: int = 2,
) -> StudyTarget:
    return StudyTarget(
        id=target_id,
        participant_id="participant-a",
        kind=StudyTargetKind.THEME,
        title="英作文練習",
    )


def material_goal(
    *,
    goal_id: int,
    target_id: int = 1,
    start: int,
    end: int,
    deadline_day: int = 20,
) -> Goal:
    return Goal(
        id=goal_id,
        participant_id="participant-a",
        study_target_id=target_id,
        goal_type=GoalType.TEST,
        title=f"Goal {goal_id}",
        deadline_at=datetime(
            2026,
            10,
            deadline_day,
            18,
            0,
            tzinfo=JST,
        ),
        importance=Importance.HIGH,
        ranges=[
            GoalRange(
                start_position=start,
                end_position=end,
            )
        ],
    )


def theme_goal(
    *,
    goal_id: int,
    target_id: int = 2,
    target_minutes: int | None,
    deadline_day: int = 20,
) -> Goal:
    return Goal(
        id=goal_id,
        participant_id="participant-a",
        study_target_id=target_id,
        goal_type=GoalType.PERSONAL,
        title=f"Theme Goal {goal_id}",
        deadline_at=datetime(
            2026,
            10,
            deadline_day,
            18,
            0,
            tzinfo=JST,
        ),
        importance=Importance.MEDIUM,
        target_minutes=target_minutes,
    )


def test_material_goal_creates_prerequisite_and_direct_segments():
    builder = WorkSegmentBuilder()

    segments = builder.build(
        study_targets=[
            material_target(),
        ],
        goals=[
            material_goal(
                goal_id=1,
                start=20,
                end=30,
            )
        ],
    )

    assert len(segments) == 2

    prerequisite = segments[0]

    assert prerequisite.range_start == 1
    assert prerequisite.range_end == 19
    assert prerequisite.required_by_goal_ids == (
        1,
    )
    assert prerequisite.direct_goal_ids == ()
    assert prerequisite.estimated_minutes == 95.0

    direct = segments[1]

    assert direct.range_start == 20
    assert direct.range_end == 30
    assert direct.required_by_goal_ids == (
        1,
    )
    assert direct.direct_goal_ids == (
        1,
    )
    assert direct.estimated_minutes == 55.0


def test_overlapping_material_goals_are_deduplicated():
    builder = WorkSegmentBuilder()

    segments = builder.build(
        study_targets=[
            material_target(),
        ],
        goals=[
            material_goal(
                goal_id=1,
                start=10,
                end=20,
            ),
            material_goal(
                goal_id=2,
                start=15,
                end=25,
            ),
        ],
    )

    # physical workはp.1〜25だけ。
    total_units = sum(
        segment.material_unit_count
        or 0
        for segment in segments
    )

    assert total_units == 25

    total_minutes = sum(
        segment.estimated_minutes
        for segment in segments
    )

    assert total_minutes == 125.0

    assert [
        (
            segment.range_start,
            segment.range_end,
            segment.required_by_goal_ids,
            segment.direct_goal_ids,
        )
        for segment in segments
    ] == [
        (
            1,
            9,
            (1, 2),
            (),
        ),
        (
            10,
            14,
            (1, 2),
            (1,),
        ),
        (
            15,
            20,
            (1, 2),
            (1, 2),
        ),
        (
            21,
            25,
            (2,),
            (2,),
        ),
    ]


def test_material_progress_removes_completed_work():
    builder = WorkSegmentBuilder()

    segments = builder.build(
        study_targets=[
            material_target(
                next_position=15,
            )
        ],
        goals=[
            material_goal(
                goal_id=1,
                start=10,
                end=20,
            )
        ],
    )

    assert len(segments) == 1

    assert (
        segments[0].range_start
        == 15
    )
    assert (
        segments[0].range_end
        == 20
    )

    assert (
        segments[0].estimated_minutes
        == 30.0
    )


def test_completed_material_goal_creates_no_work():
    builder = WorkSegmentBuilder()

    segments = builder.build(
        study_targets=[
            material_target(
                next_position=31,
            )
        ],
        goals=[
            material_goal(
                goal_id=1,
                start=20,
                end=30,
            )
        ],
    )

    assert segments == []


def test_non_contiguous_study_target_ranges_remain_separate():
    builder = WorkSegmentBuilder()

    target = material_target(
        ranges=[
            StudyTargetRange(
                sequence_no=0,
                start_position=1,
                end_position=5,
            ),
            StudyTargetRange(
                sequence_no=1,
                start_position=10,
                end_position=15,
            ),
        ],
    )

    segments = builder.build(
        study_targets=[
            target,
        ],
        goals=[
            material_goal(
                goal_id=1,
                start=10,
                end=12,
            )
        ],
    )

    assert [
        (
            segment.range_start,
            segment.range_end,
        )
        for segment in segments
    ] == [
        (
            1,
            5,
        ),
        (
            10,
            12,
        ),
    ]

    # 1〜5 = 5 units
    # 10〜12 = 3 units
    # total 8 units
    assert sum(
        segment.material_unit_count
        or 0
        for segment in segments
    ) == 8


def test_goal_range_outside_material_path_is_rejected():
    builder = WorkSegmentBuilder()

    with pytest.raises(
        DomainValidationError,
        match=(
            "GoalRange contains a position "
            "outside StudyTarget ranges"
        ),
    ):
        builder.build(
            study_targets=[
                material_target(
                    ranges=[
                        StudyTargetRange(
                            sequence_no=0,
                            start_position=1,
                            end_position=10,
                        )
                    ],
                )
            ],
            goals=[
                material_goal(
                    goal_id=1,
                    start=8,
                    end=15,
                )
            ],
        )


def test_overlapping_study_target_ranges_are_rejected():
    builder = WorkSegmentBuilder()

    target = material_target(
        ranges=[
            StudyTargetRange(
                sequence_no=0,
                start_position=1,
                end_position=10,
            ),
            StudyTargetRange(
                sequence_no=1,
                start_position=10,
                end_position=20,
            ),
        ],
    )

    with pytest.raises(
        DomainValidationError,
        match=(
            "StudyTarget ranges must not overlap"
        ),
    ):
        builder.build(
            study_targets=[
                target,
            ],
            goals=[
                material_goal(
                    goal_id=1,
                    start=1,
                    end=20,
                )
            ],
        )


def test_theme_goals_share_physical_minutes():
    builder = WorkSegmentBuilder()

    segments = builder.build(
        study_targets=[
            theme_target(),
        ],
        goals=[
            theme_goal(
                goal_id=1,
                target_minutes=30,
            ),
            theme_goal(
                goal_id=2,
                target_minutes=60,
            ),
        ],
    )

    assert len(segments) == 2

    assert (
        segments[0].theme_minute_start
        == 0
    )
    assert (
        segments[0].theme_minute_end
        == 30
    )
    assert (
        segments[0].required_by_goal_ids
        == (1, 2)
    )

    assert (
        segments[1].theme_minute_start
        == 30
    )
    assert (
        segments[1].theme_minute_end
        == 60
    )
    assert (
        segments[1].required_by_goal_ids
        == (2,)
    )

    # Goal 30分 + Goal 60分でも
    # physical workは90分ではなく60分。
    assert sum(
        segment.estimated_minutes
        for segment in segments
    ) == 60.0


def test_theme_completed_minutes_reduce_remaining_work():
    builder = WorkSegmentBuilder()

    segments = builder.build(
        study_targets=[
            theme_target(),
        ],
        goals=[
            theme_goal(
                goal_id=1,
                target_minutes=30,
            ),
            theme_goal(
                goal_id=2,
                target_minutes=60,
            ),
        ],
        theme_completed_minutes_by_target={
            2: 20,
        },
    )

    assert [
        (
            segment.theme_minute_start,
            segment.theme_minute_end,
            segment.required_by_goal_ids,
        )
        for segment in segments
    ] == [
        (
            20,
            30,
            (1, 2),
        ),
        (
            30,
            60,
            (2,),
        ),
    ]

    assert sum(
        segment.estimated_minutes
        for segment in segments
    ) == 40.0


def test_theme_goal_without_target_minutes_creates_no_segment():
    builder = WorkSegmentBuilder()

    segments = builder.build(
        study_targets=[
            theme_target(),
        ],
        goals=[
            theme_goal(
                goal_id=1,
                target_minutes=None,
            )
        ],
    )

    assert segments == []


def test_goal_referencing_unknown_target_is_rejected():
    builder = WorkSegmentBuilder()

    with pytest.raises(
        DomainValidationError,
        match=(
            "Goal references unknown StudyTarget"
        ),
    ):
        builder.build(
            study_targets=[
                material_target(
                    target_id=1,
                )
            ],
            goals=[
                material_goal(
                    goal_id=1,
                    target_id=999,
                    start=1,
                    end=10,
                )
            ],
        )


def test_duplicate_goal_id_is_rejected():
    builder = WorkSegmentBuilder()

    with pytest.raises(
        DomainValidationError,
        match="duplicate Goal id",
    ):
        builder.build(
            study_targets=[
                material_target(),
            ],
            goals=[
                material_goal(
                    goal_id=1,
                    start=1,
                    end=10,
                ),
                material_goal(
                    goal_id=1,
                    start=20,
                    end=30,
                ),
            ],
        )