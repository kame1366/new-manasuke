from datetime import (
    datetime,
    timedelta,
)

import pytest

from domain.enums import (
    AttemptStatus,
    PlanOperationType,
)
from domain.time_rules import JST
from planning.attempt_errors import (
    AttemptAlreadyRunningError,
)
from repositories.participant_repository import (
    ParticipantRepository,
)
from repositories.plan_generation_attempt_repository import (
    ERROR_ATTEMPT_STALE_ABORTED,
    PlanGenerationAttemptRepository,
)
from scripts.migrate import run_migrations


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


def setup_participant(
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


def test_attempt_can_be_started(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    setup_participant(
        db_path
    )

    repository = (
        PlanGenerationAttemptRepository(
            db_path
        )
    )

    attempt = repository.start(
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

    assert (
        attempt.status
        == AttemptStatus.IN_PROGRESS
    )

    assert (
        attempt
        .source_planning_data_version
        == 0
    )


def test_second_active_attempt_is_rejected(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    setup_participant(
        db_path
    )

    repository = (
        PlanGenerationAttemptRepository(
            db_path
        )
    )

    repository.start(
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

    with pytest.raises(
        AttemptAlreadyRunningError
    ):
        repository.start(
            participant_id=(
                "participant-a"
            ),
            operation_type=(
                PlanOperationType.REPLAN_NOW
            ),
            now=dt(
                12,
                10,
                10,
            ),
            stale_after=timedelta(
                minutes=30
            ),
        )


def test_stale_attempt_is_abandoned_and_replaced(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    setup_participant(
        db_path
    )

    repository = (
        PlanGenerationAttemptRepository(
            db_path
        )
    )

    old = repository.start(
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

    new = repository.start(
        participant_id=(
            "participant-a"
        ),
        operation_type=(
            PlanOperationType.REPLAN_NOW
        ),
        now=dt(
            12,
            11,
        ),
        stale_after=timedelta(
            minutes=30
        ),
    )

    old_reloaded = (
        repository.get_by_id(
            "participant-a",
            old.id,
        )
    )

    assert old_reloaded is not None

    assert (
        old_reloaded.status
        == AttemptStatus.ABANDONED
    )

    assert (
        old_reloaded.error_type
        == ERROR_ATTEMPT_STALE_ABORTED
    )

    assert (
        new.status
        == AttemptStatus.IN_PROGRESS
    )

    assert new.id != old.id