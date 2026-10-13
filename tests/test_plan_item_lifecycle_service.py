from datetime import datetime

import pytest

from db.connection import (
    connect,
    transaction,
)
from domain.enums import (
    PlanItemOrigin,
    StudyTargetKind,
)
from domain.models import (
    AvailableTime,
    StudyTarget,
)
from domain.time_rules import (
    JST,
    to_db_utc,
)
from planning.plan_item_lifecycle_errors import (
    PlanItemMutationNotAllowedError,
)
from repositories.participant_repository import (
    ParticipantRepository,
)
from repositories.study_target_repository import (
    StudyTargetRepository,
)
from scripts.migrate import run_migrations
from services.plan_item_lifecycle_service import (
    PlanItemLifecycleService,
    PlanMutationValidationContext,
)
from domain.plan_state import (
    PlanState,
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


def setup_plan(
    db_path,
):
    ParticipantRepository(
        db_path
    ).create(
        "participant-a",
        dt(
            13,
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

    participant_repository = (
        ParticipantRepository(
            db_path
        )
    )

    source_version = (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
    )

    assert source_version is not None

    with transaction(
        db_path
    ) as connection:
        cursor = connection.execute(
            """
            INSERT INTO plans (
                participant_id,
                version_no,
                created_at,
                effective_from,
                horizon_end,
                source_planning_data_version
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "participant-a",
                1,
                to_db_utc(
                    dt(
                        13,
                        9,
                    )
                ),
                to_db_utc(
                    dt(
                        13,
                        0,
                    )
                ),
                to_db_utc(
                    dt(
                        20,
                        0,
                    )
                ),
                source_version,
            ),
        )

        plan_id = cursor.lastrowid

        assert plan_id is not None

        cursor = connection.execute(
            """
            INSERT INTO plan_items (
                plan_id,
                study_target_id,
                start_at,
                end_at,
                origin,
                is_cancelled,
                cancelled_at,
                carried_from_plan_item_id,
                planned_minutes,
                range_start,
                range_end,
                created_at
            )
            VALUES (
                ?, ?, ?, ?, ?,
                0, NULL, NULL,
                ?, NULL, NULL, ?
            )
            """,
            (
                plan_id,
                target_id,
                to_db_utc(
                    dt(
                        13,
                        18,
                    )
                ),
                to_db_utc(
                    dt(
                        13,
                        18,
                        30,
                    )
                ),
                (
                    PlanItemOrigin
                    .SYSTEM_GENERATED
                    .value
                ),
                30,
                to_db_utc(
                    dt(
                        13,
                        9,
                    )
                ),
            ),
        )

        item_id = cursor.lastrowid

        assert item_id is not None

    target = StudyTargetRepository(
        db_path
    ).get_by_id(
        "participant-a",
        int(
            target_id
        ),
    )

    assert target is not None

    return (
        int(
            plan_id
        ),
        int(
            item_id
        ),
        target,
    )


def context(
    target,
):
    return PlanMutationValidationContext(
        study_targets=(
            target,
        ),
        goals=(),
        strict_goal_ids=frozenset(),
        weekly_available_times=(
            AvailableTime(
                # 2026-10-13 = Tuesday
                weekday=1,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    20 * 60
                ),
            ),
        ),
        extra_available_times=(),
        busy_events=(),
    )


def test_future_item_can_be_edited(
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
        plan_id,
        item_id,
        target,
    ) = setup_plan(
        db_path
    )

    service = (
        PlanItemLifecycleService(
            db_path=db_path
        )
    )

    result = service.edit(
        participant_id=(
            "participant-a"
        ),
        plan_id=plan_id,
        plan_item_id=item_id,
        plan_state=(
            PlanState.CURRENT
        ),
        current_time=dt(
            13,
            12,
        ),
        new_start_at=dt(
            13,
            18,
            30,
        ),
        new_end_at=dt(
            13,
            19,
        ),
        validation_context=(
            context(
                target
            )
        ),
    )

    assert (
        result.item.origin
        == PlanItemOrigin.USER_MODIFIED
    )

    assert (
        result.item.start_at
        == dt(
            13,
            18,
            30,
        )
    )

    assert (
        result.item.end_at
        == dt(
            13,
            19,
        )
    )


def test_item_cannot_be_edited_after_start(
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
        plan_id,
        item_id,
        target,
    ) = setup_plan(
        db_path
    )

    service = (
        PlanItemLifecycleService(
            db_path=db_path
        )
    )

    with pytest.raises(
        PlanItemMutationNotAllowedError,
        match="before start_at",
    ):
        service.edit(
            participant_id=(
                "participant-a"
            ),
            plan_id=plan_id,
            plan_item_id=item_id,
            plan_state=(
                PlanState.CURRENT
            ),
            current_time=dt(
                13,
                18,
            ),
            new_start_at=dt(
                13,
                19,
            ),
            new_end_at=dt(
                13,
                19,
                30,
            ),
            validation_context=(
                context(
                    target
                )
            ),
        )


def test_cancel_is_logical(
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
        plan_id,
        item_id,
        target,
    ) = setup_plan(
        db_path
    )

    service = (
        PlanItemLifecycleService(
            db_path=db_path
        )
    )

    result = service.cancel(
        participant_id=(
            "participant-a"
        ),
        plan_id=plan_id,
        plan_item_id=item_id,
        plan_state=(
            PlanState.CURRENT
        ),
        current_time=dt(
            13,
            12,
        ),
        validation_context=(
            context(
                target
            )
        ),
    )

    assert (
        result.item.is_cancelled
        is True
    )

    assert (
        result.item.cancelled_at
        == dt(
            13,
            12,
        )
    )

    connection = connect(
        db_path
    )

    try:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM plan_items
            WHERE id = ?
            """,
            (
                item_id,
            ),
        ).fetchone()

        assert row is not None

        # physical deleteされていない。
        assert row["count"] == 1

    finally:
        connection.close()


def test_cancel_and_restore_create_adjustments(
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
        plan_id,
        item_id,
        target,
    ) = setup_plan(
        db_path
    )

    service = (
        PlanItemLifecycleService(
            db_path=db_path
        )
    )

    service.cancel(
        participant_id=(
            "participant-a"
        ),
        plan_id=plan_id,
        plan_item_id=item_id,
        plan_state=(
            PlanState.CURRENT
        ),
        current_time=dt(
            13,
            12,
        ),
        validation_context=(
            context(
                target
            )
        ),
    )

    service.restore(
        participant_id=(
            "participant-a"
        ),
        plan_id=plan_id,
        plan_item_id=item_id,
        plan_state=(
            PlanState.CURRENT
        ),
        current_time=dt(
            13,
            13,
        ),
        validation_context=(
            context(
                target
            )
        ),
    )

    connection = connect(
        db_path
    )

    try:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM plan_item_adjustments
            WHERE plan_item_id = ?
              AND adjustment_type = 'USER_EDIT'
            """,
            (
                item_id,
            ),
        ).fetchone()

        assert row is not None

        assert row["count"] == 2

    finally:
        connection.close()


def test_outdated_valid_cannot_be_restored(
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
        plan_id,
        item_id,
        target,
    ) = setup_plan(
        db_path
    )

    service = (
        PlanItemLifecycleService(
            db_path=db_path
        )
    )

    service.cancel(
        participant_id=(
            "participant-a"
        ),
        plan_id=plan_id,
        plan_item_id=item_id,
        plan_state=(
            PlanState.CURRENT
        ),
        current_time=dt(
            13,
            12,
        ),
        validation_context=(
            context(
                target
            )
        ),
    )

    with pytest.raises(
        PlanItemMutationNotAllowedError,
        match=(
            "CURRENT or "
            "FUTURE_APPLICABLE"
        ),
    ):
        service.restore(
            participant_id=(
                "participant-a"
            ),
            plan_id=plan_id,
            plan_item_id=item_id,
            plan_state=(
                PlanState.OUTDATED_VALID
            ),
            current_time=dt(
                13,
                13,
            ),
            validation_context=(
                context(
                    target
                )
            ),
        )


def test_outdated_invalid_system_item_is_read_only(
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
        plan_id,
        item_id,
        target,
    ) = setup_plan(
        db_path
    )

    service = (
        PlanItemLifecycleService(
            db_path=db_path
        )
    )

    with pytest.raises(
        PlanItemMutationNotAllowedError,
        match="USER_MODIFIED",
    ):
        service.cancel(
            participant_id=(
                "participant-a"
            ),
            plan_id=plan_id,
            plan_item_id=item_id,
            plan_state=(
                PlanState.OUTDATED_INVALID
            ),
            current_time=dt(
                13,
                12,
            ),
            validation_context=(
                context(
                    target
                )
            ),
        )


def test_plan_edit_does_not_increment_planning_data_version(
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
        plan_id,
        item_id,
        target,
    ) = setup_plan(
        db_path
    )

    participant_repository = (
        ParticipantRepository(
            db_path
        )
    )

    before = (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
    )

    service = (
        PlanItemLifecycleService(
            db_path=db_path
        )
    )

    service.edit(
        participant_id=(
            "participant-a"
        ),
        plan_id=plan_id,
        plan_item_id=item_id,
        plan_state=(
            PlanState.CURRENT
        ),
        current_time=dt(
            13,
            12,
        ),
        new_start_at=dt(
            13,
            18,
            30,
        ),
        new_end_at=dt(
            13,
            19,
        ),
        validation_context=(
            context(
                target
            )
        ),
    )

    after = (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
    )

    assert after == before