from datetime import datetime

import pytest

from db.connection import (
    connect,
    transaction,
)
from domain.enums import (
    PlanItemOrigin,
    StudyResultStatus,
    StudyTargetKind,
    UnitType,
)
from domain.models import (
    StudyTarget,
    StudyTargetRange,
)
from domain.time_rules import (
    JST,
    to_db_utc,
)
from planning.study_result_errors import (
    MaterialUnrecordedBlockError,
    StudyResultCorrectionLockedError,
)
from repositories.participant_repository import (
    ParticipantRepository,
)
from repositories.study_target_repository import (
    StudyTargetRepository,
)
from scripts.migrate import run_migrations
from services.study_result_service import (
    StudyResultService,
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


def setup_material(
    db_path,
):
    ParticipantRepository(
        db_path
    ).create(
        "participant-a",
        dt(
            14,
            8,
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
                    StudyTargetKind.MATERIAL
                ),
                title="数学",
                unit_type=UnitType.PAGE,
                next_position=1,
                estimated_minutes_per_unit=5.0,
                ranges=[
                    StudyTargetRange(
                        sequence_no=0,
                        start_position=1,
                        end_position=100,
                    )
                ],
            )
        )
    )

    version = (
        ParticipantRepository(
            db_path
        )
        .get_planning_data_version(
            "participant-a"
        )
    )

    assert version is not None

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
                        14,
                        8,
                    )
                ),
                to_db_utc(
                    dt(
                        14,
                        0,
                    )
                ),
                to_db_utc(
                    dt(
                        21,
                        0,
                    )
                ),
                version,
            ),
        )

        plan_id = int(
            cursor.lastrowid
        )

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
                0,
                NULL,
                NULL,
                ?, ?, ?, ?
            )
            """,
            (
                plan_id,
                target_id,
                to_db_utc(
                    dt(
                        14,
                        10,
                    )
                ),
                to_db_utc(
                    dt(
                        14,
                        10,
                        30,
                    )
                ),
                (
                    PlanItemOrigin
                    .SYSTEM_GENERATED
                    .value
                ),
                30,
                1,
                5,
                to_db_utc(
                    dt(
                        14,
                        8,
                    )
                ),
            ),
        )

        first_item_id = int(
            cursor.lastrowid
        )

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
                0,
                NULL,
                NULL,
                ?, ?, ?, ?
            )
            """,
            (
                plan_id,
                target_id,
                to_db_utc(
                    dt(
                        14,
                        18,
                    )
                ),
                to_db_utc(
                    dt(
                        14,
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
                6,
                10,
                to_db_utc(
                    dt(
                        14,
                        8,
                    )
                ),
            ),
        )

        second_item_id = int(
            cursor.lastrowid
        )

    return (
        target_id,
        plan_id,
        first_item_id,
        second_item_id,
    )


def get_next_position(
    db_path,
    target_id,
):
    connection = connect(
        db_path
    )

    try:
        row = connection.execute(
            """
            SELECT next_position
            FROM study_targets
            WHERE id = ?
            """,
            (
                target_id,
            ),
        ).fetchone()

        assert row is not None

        return int(
            row["next_position"]
        )

    finally:
        connection.close()


def test_completed_material_updates_progress_and_version(
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
        target_id,
        _plan_id,
        first_item_id,
        _second_item_id,
    ) = setup_material(
        db_path
    )

    participant_repository = (
        ParticipantRepository(
            db_path
        )
    )

    before_version = (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
    )

    service = StudyResultService(
        db_path=db_path
    )

    result = service.record(
        participant_id=(
            "participant-a"
        ),
        plan_item_id=(
            first_item_id
        ),
        status=(
            StudyResultStatus.COMPLETED
        ),
        now=dt(
            14,
            12,
        ),
    )

    assert (
        result.actual_end_position
        == 5
    )

    assert (
        get_next_position(
            db_path,
            target_id,
        )
        == 6
    )

    after_version = (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
    )

    assert (
        after_version
        == before_version + 1
    )


def test_actual_progress_can_exceed_planned_range_and_trim_future_item(
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
        target_id,
        plan_id,
        first_item_id,
        second_item_id,
    ) = setup_material(
        db_path
    )

    service = StudyResultService(
        db_path=db_path
    )

    service.record(
        participant_id=(
            "participant-a"
        ),
        plan_item_id=(
            first_item_id
        ),
        status=(
            StudyResultStatus.COMPLETED
        ),
        actual_end_position=7,
        now=dt(
            14,
            12,
        ),
    )

    assert (
        get_next_position(
            db_path,
            target_id,
        )
        == 8
    )

    connection = connect(
        db_path
    )

    try:
        item = connection.execute(
            """
            SELECT range_start, range_end
            FROM plan_items
            WHERE id = ?
            """,
            (
                second_item_id,
            ),
        ).fetchone()

        assert item is not None

        assert (
            item["range_start"]
            == 8
        )

        assert (
            item["range_end"]
            == 10
        )

        adjustment = (
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM plan_item_adjustments
                WHERE plan_item_id = ?
                  AND adjustment_type =
                      'PROGRESS_SYNC'
                """,
                (
                    second_item_id,
                ),
            ).fetchone()
        )

        assert adjustment is not None

        assert (
            adjustment["count"]
            == 1
        )

        participant_version = (
            ParticipantRepository(
                db_path
            )
            .get_planning_data_version(
                "participant-a"
            )
        )

        plan = connection.execute(
            """
            SELECT source_planning_data_version
            FROM plans
            WHERE id = ?
            """,
            (
                plan_id,
            ),
        ).fetchone()

        assert plan is not None

        assert (
            plan[
                "source_planning_data_version"
            ]
            == participant_version
        )

    finally:
        connection.close()


def test_user_modified_conflict_does_not_rollback_result(
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
        target_id,
        plan_id,
        first_item_id,
        second_item_id,
    ) = setup_material(
        db_path
    )

    connection = connect(
        db_path
    )

    try:
        old_plan_version = (
            connection.execute(
                """
                SELECT source_planning_data_version
                FROM plans
                WHERE id = ?
                """,
                (
                    plan_id,
                ),
            ).fetchone()[
                "source_planning_data_version"
            ]
        )

    finally:
        connection.close()

    with transaction(
        db_path
    ) as connection:
        connection.execute(
            """
            UPDATE plan_items
            SET origin = ?
            WHERE id = ?
            """,
            (
                (
                    PlanItemOrigin
                    .USER_MODIFIED
                    .value
                ),
                second_item_id,
            ),
        )

    service = StudyResultService(
        db_path=db_path
    )

    result = service.record(
        participant_id=(
            "participant-a"
        ),
        plan_item_id=(
            first_item_id
        ),
        status=(
            StudyResultStatus.COMPLETED
        ),
        actual_end_position=7,
        now=dt(
            14,
            12,
        ),
    )

    # StudyResult自体は成功。
    assert (
        result.actual_end_position
        == 7
    )

    assert (
        get_next_position(
            db_path,
            target_id,
        )
        == 8
    )

    connection = connect(
        db_path
    )

    try:
        plan = connection.execute(
            """
            SELECT source_planning_data_version
            FROM plans
            WHERE id = ?
            """,
            (
                plan_id,
            ),
        ).fetchone()

        assert plan is not None

        # sync不能なので古いversionのまま。
        assert (
            plan[
                "source_planning_data_version"
            ]
            == old_plan_version
        )

        item = connection.execute(
            """
            SELECT
                range_start,
                origin
            FROM plan_items
            WHERE id = ?
            """,
            (
                second_item_id,
            ),
        ).fetchone()

        assert item is not None

        # USER_MODIFIEDを勝手にtrimしない。
        assert (
            item["range_start"]
            == 6
        )

        assert (
            item["origin"]
            == PlanItemOrigin
            .USER_MODIFIED
            .value
        )

    finally:
        connection.close()


def test_material_result_can_be_corrected_when_latest(
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
        target_id,
        _plan_id,
        first_item_id,
        _second_item_id,
    ) = setup_material(
        db_path
    )

    service = StudyResultService(
        db_path=db_path
    )

    service.record(
        participant_id=(
            "participant-a"
        ),
        plan_item_id=(
            first_item_id
        ),
        status=(
            StudyResultStatus.COMPLETED
        ),
        now=dt(
            14,
            12,
        ),
    )

    corrected = service.correct(
        participant_id=(
            "participant-a"
        ),
        plan_item_id=(
            first_item_id
        ),
        status=(
            StudyResultStatus.PARTIAL
        ),
        actual_end_position=3,
        now=dt(
            14,
            13,
        ),
    )

    assert (
        corrected.status
        == StudyResultStatus.PARTIAL
    )

    assert (
        get_next_position(
            db_path,
            target_id,
        )
        == 4
    )

    connection = connect(
        db_path
    )

    try:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM study_result_revisions
            WHERE study_result_id = ?
            """,
            (
                corrected.id,
            ),
        ).fetchone()

        assert row is not None

        assert row["count"] == 1

    finally:
        connection.close()


def test_old_material_result_is_locked_when_later_result_exists(
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
        _target_id,
        _plan_id,
        first_item_id,
        second_item_id,
    ) = setup_material(
        db_path
    )

    service = StudyResultService(
        db_path=db_path
    )

    service.record(
        participant_id=(
            "participant-a"
        ),
        plan_item_id=(
            first_item_id
        ),
        status=(
            StudyResultStatus.COMPLETED
        ),
        now=dt(
            14,
            12,
        ),
    )

    service.record(
        participant_id=(
            "participant-a"
        ),
        plan_item_id=(
            second_item_id
        ),
        status=(
            StudyResultStatus.COMPLETED
        ),
        now=dt(
            14,
            20,
        ),
    )

    with pytest.raises(
        StudyResultCorrectionLockedError,
        match="later StudyResult",
    ):
        service.correct(
            participant_id=(
                "participant-a"
            ),
            plan_item_id=(
                first_item_id
            ),
            status=(
                StudyResultStatus.NOT_DONE
            ),
            now=dt(
                14,
                21,
            ),
        )


def test_unrecorded_material_blocks_replan(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    setup_material(
        db_path
    )

    service = StudyResultService(
        db_path=db_path
    )

    with pytest.raises(
        MaterialUnrecordedBlockError,
        match="required before replan",
    ):
        service.assert_replan_ready(
            participant_id=(
                "participant-a"
            ),
            now=dt(
                14,
                12,
            ),
        )


def test_recorded_material_no_longer_blocks_replan(
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
        _target_id,
        _plan_id,
        first_item_id,
        _second_item_id,
    ) = setup_material(
        db_path
    )

    service = StudyResultService(
        db_path=db_path
    )

    service.record(
        participant_id=(
            "participant-a"
        ),
        plan_item_id=(
            first_item_id
        ),
        status=(
            StudyResultStatus.COMPLETED
        ),
        now=dt(
            14,
            12,
        ),
    )

    # 18:00のsecond itemはまだ開始していないため
    # blockしない。
    service.assert_replan_ready(
        participant_id=(
            "participant-a"
        ),
        now=dt(
            14,
            12,
        ),
    )