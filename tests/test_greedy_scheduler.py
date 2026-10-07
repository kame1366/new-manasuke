from datetime import datetime

from domain.enums import (
    StudyTargetKind,
)
from domain.time_rules import JST
from planning.free_slot_builder import (
    FreeSlot,
)
from planning.greedy_scheduler import (
    GreedyScheduler,
)
from planning.work_chunk_builder import (
    WorkChunk,
)


def dt(
    day: int,
    hour: int,
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


def theme_chunk(
    *,
    chunk_id: str,
    target_id: int,
    sequence_no: int = 0,
    duration: int = 30,
    deadline=None,
    mandatory: bool = True,
    priority: int | None = None,
) -> WorkChunk:
    return WorkChunk(
        chunk_id=chunk_id,
        study_target_id=target_id,
        kind=StudyTargetKind.THEME,
        estimated_minutes=float(
            duration
        ),
        scheduled_duration_minutes=(
            duration
        ),
        sequence_no=sequence_no,
        mandatory=mandatory,
        required_by_goal_ids=(
            (1,)
            if mandatory
            else ()
        ),
        must_finish_before=deadline,
        planning_priority_rank=(
            priority
        ),
        theme_minute_start=(
            sequence_no
            * duration
        ),
        theme_minute_end=(
            (
                sequence_no + 1
            )
            * duration
        ),
    )


def material_chunk(
    *,
    chunk_id: str,
    sequence_no: int,
    start: int,
    end: int,
    deadline=None,
) -> WorkChunk:
    return WorkChunk(
        chunk_id=chunk_id,
        study_target_id=1,
        kind=StudyTargetKind.MATERIAL,
        estimated_minutes=20.0,
        scheduled_duration_minutes=20,
        sequence_no=sequence_no,
        mandatory=True,
        required_by_goal_ids=(1,),
        must_finish_before=deadline,
        range_start=start,
        range_end=end,
    )


def test_earlier_deadline_is_scheduled_first():
    scheduler = GreedyScheduler()

    early = theme_chunk(
        chunk_id="early",
        target_id=1,
        deadline=dt(
            9,
            20,
        ),
    )

    late = theme_chunk(
        chunk_id="late",
        target_id=2,
        deadline=dt(
            10,
            20,
        ),
    )

    result = scheduler.schedule(
        chunks=[
            late,
            early,
        ],
        free_slots=[
            FreeSlot(
                start_at=dt(
                    8,
                    18,
                ),
                end_at=dt(
                    8,
                    19,
                ),
            )
        ],
    )

    assert result.success is True

    assert [
        placement.chunk.chunk_id
        for placement
        in result.placements
    ] == [
        "early",
        "late",
    ]


def test_material_precedence_is_preserved():
    scheduler = GreedyScheduler()

    first = material_chunk(
        chunk_id="first",
        sequence_no=0,
        start=1,
        end=4,
        deadline=dt(
            10,
            20,
        ),
    )

    second = material_chunk(
        chunk_id="second",
        sequence_no=1,
        start=5,
        end=8,
        deadline=dt(
            9,
            20,
        ),
    )

    result = scheduler.schedule(
        chunks=[
            second,
            first,
        ],
        free_slots=[
            FreeSlot(
                start_at=dt(
                    8,
                    18,
                ),
                end_at=dt(
                    8,
                    19,
                ),
            )
        ],
    )

    assert result.success is True

    assert [
        placement.chunk.chunk_id
        for placement
        in result.placements
    ] == [
        "first",
        "second",
    ]

    assert (
        result.placements[1].start_at
        >= result.placements[0].end_at
    )


def test_same_target_is_distributed_across_days_when_possible():
    scheduler = GreedyScheduler()

    first = theme_chunk(
        chunk_id="a",
        target_id=1,
        sequence_no=0,
    )

    second = theme_chunk(
        chunk_id="b",
        target_id=1,
        sequence_no=1,
    )

    result = scheduler.schedule(
        chunks=[
            first,
            second,
        ],
        free_slots=[
            FreeSlot(
                start_at=dt(
                    8,
                    18,
                ),
                end_at=dt(
                    8,
                    19,
                ),
            ),
            FreeSlot(
                start_at=dt(
                    9,
                    18,
                ),
                end_at=dt(
                    9,
                    19,
                ),
            ),
        ],
    )

    assert result.success is True

    assert (
        result.placements[0]
        .start_at
        .date()
        != result.placements[1]
        .start_at
        .date()
    )


def test_same_day_multiple_sessions_are_allowed_when_needed():
    scheduler = GreedyScheduler()

    first = theme_chunk(
        chunk_id="a",
        target_id=1,
        sequence_no=0,
    )

    second = theme_chunk(
        chunk_id="b",
        target_id=1,
        sequence_no=1,
    )

    result = scheduler.schedule(
        chunks=[
            first,
            second,
        ],
        free_slots=[
            FreeSlot(
                start_at=dt(
                    8,
                    18,
                ),
                end_at=dt(
                    8,
                    19,
                ),
            )
        ],
    )

    assert result.success is True

    assert (
        result.placements[0]
        .start_at
        .date()
        == result.placements[1]
        .start_at
        .date()
    )


def test_mandatory_chunk_is_before_optional_chunk():
    scheduler = GreedyScheduler()

    optional = theme_chunk(
        chunk_id="optional",
        target_id=2,
        mandatory=False,
        priority=1,
    )

    mandatory = theme_chunk(
        chunk_id="mandatory",
        target_id=1,
        mandatory=True,
    )

    result = scheduler.schedule(
        chunks=[
            optional,
            mandatory,
        ],
        free_slots=[
            FreeSlot(
                start_at=dt(
                    8,
                    18,
                ),
                end_at=dt(
                    8,
                    19,
                ),
            )
        ],
    )

    assert result.success is True

    assert (
        result.placements[0]
        .chunk
        .chunk_id
        == "mandatory"
    )


def test_optional_priority_rank_is_respected():
    scheduler = GreedyScheduler()

    lower_priority = theme_chunk(
        chunk_id="rank-2",
        target_id=2,
        mandatory=False,
        priority=2,
    )

    higher_priority = theme_chunk(
        chunk_id="rank-1",
        target_id=1,
        mandatory=False,
        priority=1,
    )

    result = scheduler.schedule(
        chunks=[
            lower_priority,
            higher_priority,
        ],
        free_slots=[
            FreeSlot(
                start_at=dt(
                    8,
                    18,
                ),
                end_at=dt(
                    8,
                    19,
                ),
            )
        ],
    )

    assert result.success is True

    assert [
        placement.chunk.chunk_id
        for placement
        in result.placements
    ] == [
        "rank-1",
        "rank-2",
    ]


def test_scheduler_reports_unplaced_chunk():
    scheduler = GreedyScheduler()

    too_large = theme_chunk(
        chunk_id="too-large",
        target_id=1,
        duration=90,
    )

    result = scheduler.schedule(
        chunks=[
            too_large
        ],
        free_slots=[
            FreeSlot(
                start_at=dt(
                    8,
                    18,
                ),
                end_at=dt(
                    8,
                    19,
                ),
            )
        ],
    )

    assert result.success is False

    assert result.placements == ()

    assert len(
        result.unplaced_chunks
    ) == 1

    assert (
        result.unplaced_chunks[0]
        .chunk_id
        == "too-large"
    )


def test_scheduler_is_deterministic():
    scheduler = GreedyScheduler()

    chunks = [
        theme_chunk(
            chunk_id="b",
            target_id=2,
        ),
        theme_chunk(
            chunk_id="a",
            target_id=1,
        ),
    ]

    slots = [
        FreeSlot(
            start_at=dt(
                8,
                18,
            ),
            end_at=dt(
                8,
                19,
            ),
        )
    ]

    first = scheduler.schedule(
        chunks=chunks,
        free_slots=slots,
    )

    second = scheduler.schedule(
        chunks=chunks,
        free_slots=slots,
    )

    assert [
        (
            placement.chunk.chunk_id,
            placement.start_at,
            placement.end_at,
        )
        for placement
        in first.placements
    ] == [
        (
            placement.chunk.chunk_id,
            placement.start_at,
            placement.end_at,
        )
        for placement
        in second.placements
    ]