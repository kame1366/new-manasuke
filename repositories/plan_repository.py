from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from db.connection import (
    connect,
    transaction,
)
from domain.enums import (
    AttemptStage,
    AttemptStatus,
    PlanItemOrigin,
)
from domain.errors import (
    DomainValidationError,
)
from domain.models import (
    Plan,
    PlanItem,
)
from domain.time_rules import (
    from_db_utc,
    to_db_utc,
)
from planning.placement_engine import (
    ScheduledChunk,
)
from repositories.plan_generation_attempt_repository import (
    PlanGenerationAttemptRepository,
)


class PlanRepository:
    def __init__(
        self,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(
            db_path
        )

    def save_generated_plan_atomic(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        effective_from: datetime,
        horizon_end: datetime,
        scheduled_chunks: Sequence[
            ScheduledChunk
        ],
        now: datetime,
    ) -> Plan:
        """
        最終Plan保存。

        同一Transaction内で:

        1. Attempt IN_PROGRESS確認
        2. stage=SCHEDULING確認
        3. planning_data_version確認
        4. next version_no採番
        5. Plan INSERT
        6. PlanItems INSERT
        7. resulting_plan_id
        8. Attempt SUCCEEDED

        を行う。
        """
        with transaction(
            self._db_path
        ) as connection:
            attempt = (
                PlanGenerationAttemptRepository
                .assert_in_progress_in_transaction(
                    connection,
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    expected_stage=(
                        AttemptStage
                        .SCHEDULING
                    ),
                )
            )

            (
                PlanGenerationAttemptRepository
                .assert_source_version_in_transaction(
                    connection,
                    participant_id=(
                        participant_id
                    ),
                    attempt=attempt,
                )
            )

            row = connection.execute(
                """
                SELECT
                    COALESCE(
                        MAX(version_no),
                        0
                    ) + 1 AS next_version_no
                FROM plans
                WHERE participant_id = ?
                """,
                (
                    participant_id,
                ),
            ).fetchone()

            if row is None:
                raise RuntimeError(
                    "failed to allocate "
                    "Plan version"
                )

            next_version_no = int(
                row[
                    "next_version_no"
                ]
            )

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
                    participant_id,
                    next_version_no,
                    to_db_utc(
                        now
                    ),
                    to_db_utc(
                        effective_from
                    ),
                    to_db_utc(
                        horizon_end
                    ),
                    (
                        attempt
                        .source_planning_data_version
                    ),
                ),
            )

            plan_id = (
                cursor.lastrowid
            )

            if plan_id is None:
                raise RuntimeError(
                    "failed to insert Plan"
                )

            for placement in sorted(
                scheduled_chunks,
                key=lambda item: (
                    item.start_at,
                    item.end_at,
                    item.chunk.chunk_id,
                ),
            ):
                target_exists = (
                    connection.execute(
                        """
                        SELECT 1
                        FROM study_targets
                        WHERE participant_id = ?
                          AND id = ?
                        """,
                        (
                            participant_id,
                            (
                                placement
                                .chunk
                                .study_target_id
                            ),
                        ),
                    ).fetchone()
                )

                if target_exists is None:
                    raise DomainValidationError(
                        "ScheduledChunk references "
                        "StudyTarget outside participant"
                    )

                connection.execute(
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
                        ?, ?, ?, ?
                    )
                    """,
                    (
                        plan_id,
                        (
                            placement
                            .chunk
                            .study_target_id
                        ),
                        to_db_utc(
                            placement.start_at
                        ),
                        to_db_utc(
                            placement.end_at
                        ),
                        (
                            PlanItemOrigin
                            .SYSTEM_GENERATED
                            .value
                        ),
                        (
                            placement
                            .chunk
                            .scheduled_duration_minutes
                        ),
                        (
                            placement
                            .chunk
                            .range_start
                        ),
                        (
                            placement
                            .chunk
                            .range_end
                        ),
                        to_db_utc(
                            now
                        ),
                    ),
                )

            cursor = connection.execute(
                """
                UPDATE plan_generation_attempts
                SET
                    status = ?,
                    updated_at = ?,
                    completed_at = ?,
                    error_type = NULL,
                    resulting_plan_id = ?
                WHERE participant_id = ?
                  AND id = ?
                  AND status = ?
                  AND stage = ?
                """,
                (
                    AttemptStatus
                    .SUCCEEDED
                    .value,
                    to_db_utc(
                        now
                    ),
                    to_db_utc(
                        now
                    ),
                    plan_id,
                    participant_id,
                    attempt_id,
                    AttemptStatus
                    .IN_PROGRESS
                    .value,
                    AttemptStage
                    .SCHEDULING
                    .value,
                ),
            )

            if cursor.rowcount != 1:
                raise RuntimeError(
                    "failed to complete Attempt"
                )

        return Plan(
            id=int(
                plan_id
            ),
            participant_id=(
                participant_id
            ),
            version_no=(
                next_version_no
            ),
            created_at=now,
            effective_from=(
                effective_from
            ),
            horizon_end=(
                horizon_end
            ),
            source_planning_data_version=(
                attempt
                .source_planning_data_version
            ),
        )

    def list_by_participant(
        self,
        participant_id: str,
    ) -> list[Plan]:
        connection = connect(
            self._db_path
        )

        try:
            rows = connection.execute(
                """
                SELECT
                    id,
                    participant_id,
                    version_no,
                    created_at,
                    effective_from,
                    horizon_end,
                    source_planning_data_version
                FROM plans
                WHERE participant_id = ?
                ORDER BY version_no
                """,
                (
                    participant_id,
                ),
            ).fetchall()

            return [
                Plan(
                    id=int(
                        row["id"]
                    ),
                    participant_id=str(
                        row[
                            "participant_id"
                        ]
                    ),
                    version_no=int(
                        row[
                            "version_no"
                        ]
                    ),
                    created_at=(
                        from_db_utc(
                            row[
                                "created_at"
                            ]
                        )
                    ),
                    effective_from=(
                        from_db_utc(
                            row[
                                "effective_from"
                            ]
                        )
                    ),
                    horizon_end=(
                        from_db_utc(
                            row[
                                "horizon_end"
                            ]
                        )
                    ),
                    source_planning_data_version=int(
                        row[
                            "source_planning_data_version"
                        ]
                    ),
                )
                for row in rows
            ]

        finally:
            connection.close()

    def list_items(
        self,
        *,
        participant_id: str,
        plan_id: int,
    ) -> list[PlanItem]:
        """
        Plan自体もparticipant scopeしてから
        PlanItemsを取得する。
        """
        connection = connect(
            self._db_path
        )

        try:
            rows = connection.execute(
                """
                SELECT
                    pi.id,
                    pi.plan_id,
                    pi.study_target_id,
                    pi.start_at,
                    pi.end_at,
                    pi.origin,
                    pi.is_cancelled,
                    pi.cancelled_at,
                    pi.carried_from_plan_item_id,
                    pi.planned_minutes,
                    pi.range_start,
                    pi.range_end
                FROM plan_items AS pi
                JOIN plans AS p
                  ON p.id = pi.plan_id
                WHERE p.participant_id = ?
                  AND p.id = ?
                ORDER BY
                    pi.start_at,
                    pi.id
                """,
                (
                    participant_id,
                    plan_id,
                ),
            ).fetchall()

            return [
                PlanItem(
                    id=int(
                        row["id"]
                    ),
                    plan_id=int(
                        row["plan_id"]
                    ),
                    study_target_id=int(
                        row[
                            "study_target_id"
                        ]
                    ),
                    start_at=from_db_utc(
                        row["start_at"]
                    ),
                    end_at=from_db_utc(
                        row["end_at"]
                    ),
                    origin=PlanItemOrigin(
                        row["origin"]
                    ),
                    planned_minutes=int(
                        row[
                            "planned_minutes"
                        ]
                    ),
                    range_start=(
                        int(
                            row[
                                "range_start"
                            ]
                        )
                        if (
                            row[
                                "range_start"
                            ]
                            is not None
                        )
                        else None
                    ),
                    range_end=(
                        int(
                            row[
                                "range_end"
                            ]
                        )
                        if (
                            row[
                                "range_end"
                            ]
                            is not None
                        )
                        else None
                    ),
                    is_cancelled=bool(
                        row[
                            "is_cancelled"
                        ]
                    ),
                    cancelled_at=(
                        from_db_utc(
                            row[
                                "cancelled_at"
                            ]
                        )
                        if (
                            row[
                                "cancelled_at"
                            ]
                            is not None
                        )
                        else None
                    ),
                    carried_from_plan_item_id=(
                        int(
                            row[
                                "carried_from_plan_item_id"
                            ]
                        )
                        if (
                            row[
                                "carried_from_plan_item_id"
                            ]
                            is not None
                        )
                        else None
                    ),
                )
                for row in rows
            ]

        finally:
            connection.close()