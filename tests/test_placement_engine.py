from datetime import datetime

from domain.enums import (
    StudyTargetKind,
)
from domain.time_rules import JST
from planning.free_slot_builder import (
    FreeSlot,
)
from planning.placement_engine import (
    PlacementEngine,
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
    chunk_id: str = "chunk-1",
    target_id: int = 1,
    duration: int = 30,
    sequence_no: int = 0,
    not_before=None,
    deadline=None,
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
        mandatory=True,
        required_by_goal_ids=(1,),
        not_before=not_before,
        must_finish_before=deadline,
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


def test_chunk_is_placed_in_earliest_slot():
    engine = PlacementEngine()

    outcome = engine.place_chunk(
        chunk=theme_chunk(),
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

    assert outcome.placement is not None

    assert (
        outcome.placement.start_at
        == dt(
            8,
            18,
        )
    )

    assert (
        outcome.placement.end_at
        == dt(
            8,
            18,
            30,
        )
    )


def test_not_before_is_respected():
    engine = PlacementEngine()

    outcome = engine.place_chunk(
        chunk=theme_chunk(
            not_before=dt(
                8,
                18,
                10,
            ),
        ),
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

    assert outcome.placement is not None

    assert (
        outcome.placement.start_at
        == dt(
            8,
            18,
            10,
        )
    )


def test_deadline_is_respected():
    engine = PlacementEngine()

    outcome = engine.place_chunk(
        chunk=theme_chunk(
            duration=30,
            deadline=dt(
                8,
                18,
                20,
            ),
        ),
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

    assert outcome.placement is None


def test_slot_is_consumed_and_remaining_time_is_kept():
    engine = PlacementEngine()

    outcome = engine.place_chunk(
        chunk=theme_chunk(
            duration=30,
            not_before=dt(
                8,
                18,
                15,
            ),
        ),
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

    assert outcome.placement is not None

    assert [
        (
            slot.start_at,
            slot.end_at,
        )
        for slot
        in outcome.remaining_slots
    ] == [
        (
            dt(
                8,
                18,
            ),
            dt(
                8,
                18,
                15,
            ),
        ),
        (
            dt(
                8,
                18,
                45,
            ),
            dt(
                8,
                19,
            ),
        ),
    ]


def test_unused_study_day_is_preferred():
    engine = PlacementEngine()

    outcome = engine.place_chunk(
        chunk=theme_chunk(),
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
        used_study_days={
            dt(
                8,
                18,
            ).date()
        },
    )

    assert outcome.placement is not None

    assert (
        outcome.placement.start_at.date()
        == dt(
            9,
            18,
        ).date()
    )


def test_same_day_is_allowed_when_no_other_day_exists():
    engine = PlacementEngine()

    outcome = engine.place_chunk(
        chunk=theme_chunk(),
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
        used_study_days={
            dt(
                8,
                18,
            ).date()
        },
    )

    assert outcome.placement is not None

    assert (
        outcome.placement.start_at
        == dt(
            8,
            18,
        )
    )


def test_chunk_that_does_not_fit_returns_none():
    engine = PlacementEngine()

    outcome = engine.place_chunk(
        chunk=theme_chunk(
            duration=60,
        ),
        free_slots=[
            FreeSlot(
                start_at=dt(
                    8,
                    18,
                ),
                end_at=dt(
                    8,
                    18,
                    30,
                ),
            )
        ],
    )

    assert outcome.placement is None