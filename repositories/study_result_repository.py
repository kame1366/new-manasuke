from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from ai.errors import (
    PlanningDataChangedError,
)
from db.connection import (
    connect,
    transaction,
)
from domain.enums import (
    PlanItemOrigin,
    StudyResultStatus,
)
from domain.errors import (
    DomainValidationError,
)
from domain.models import (
    Plan,
    PlanItem,
    StudyResult,
)
from domain.time_rules import (
    from_db_utc,
    to_db_utc,
)
from planning.progress_sync import (
    ProgressSyncCandidate,
    ProgressSyncDecision,
)
from planning.study_result_errors import (
    StudyResultAlreadyExistsError,
    StudyResultNotFoundError,
)


ADJUSTMENT_PROGRESS_SYNC = (
    "PROGRESS_SYNC"
)


class StudyResultRepository:
    def __init__(
        self,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(
            db_path
        )

    # =====================================================
    # Read
    # =====================================================

    def get_plan_item(
        self,
        *,
        participant_id: str,
        plan_item_id: int,
    ) -> PlanItem | None:
        connection = connect(
            self._db_path
        )

        try:
            row = connection.execute(
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
                  AND pi.id = ?
                """,
                (
                    participant_id,
                    plan_item_id,
                ),
            ).fetchone()

            if row is None:
                return None

            return self._row_to_plan_item(
                row
            )

        finally:
            connection.close()

    def get_by_plan_item(
        self,
        *,
        participant_id: str,
        plan_item_id: int,
    ) -> StudyResult | None:
        connection = connect(
            self._db_path
        )

        try:
            row = connection.execute(
                """
                SELECT
                    id,
                    participant_id,
                    plan_item_id,
                    study_target_id,
                    status,
                    actual_end_position,
                    actual_minutes,
                    time_feeling,
                    memo
                FROM study_results
                WHERE participant_id = ?
                  AND plan_item_id = ?
                """,
                (
                    participant_id,
                    plan_item_id,
                ),
            ).fetchone()

            if row is None:
                return None

            return self._row_to_result(
                row
            )

        finally:
            connection.close()

    def has_later_result(
        self,
        *,
        participant_id: str,
        study_target_id: int,
        plan_item_id: int,
    ) -> bool:
        """
        同StudyTargetについて、
        chronologicalに後のPlanItemに
        StudyResultが存在するか。
        """
        connection = connect(
            self._db_path
        )

        try:
            current = connection.execute(
                """
                SELECT
                    pi.start_at,
                    pi.id
                FROM plan_items AS pi
                JOIN plans AS p
                  ON p.id = pi.plan_id
                WHERE p.participant_id = ?
                  AND pi.id = ?
                  AND pi.study_target_id = ?
                """,
                (
                    participant_id,
                    plan_item_id,
                    study_target_id,
                ),
            ).fetchone()

            if current is None:
                raise DomainValidationError(
                    "PlanItem not found"
                )

            row = connection.execute(
                """
                SELECT 1
                FROM study_results AS sr
                JOIN plan_items AS pi
                  ON pi.id = sr.plan_item_id
                JOIN plans AS p
                  ON p.id = pi.plan_id
                WHERE sr.participant_id = ?
                  AND sr.study_target_id = ?
                  AND (
                        pi.start_at > ?
                        OR (
                            pi.start_at = ?
                            AND pi.id > ?
                        )
                  )
                LIMIT 1
                """,
                (
                    participant_id,
                    study_target_id,
                    current["start_at"],
                    current["start_at"],
                    plan_item_id,
                ),
            ).fetchone()

            return row is not None

        finally:
            connection.close()

    # =====================================================
    # UNRECORDED
    # =====================================================

    def find_material_unrecorded_started(
        self,
        *,
        participant_id: str,
        now: datetime,
    ) -> list[PlanItem]:
        """
        現在選択されるPlanについて、
        start済みのMaterial PlanItemで

        - cancelledでない
        - resultがない

        ものを返す。
        """
        connection = connect(
            self._db_path
        )

        try:
            plan_row = connection.execute(
                """
                SELECT
                    id,
                    horizon_end
                FROM plans
                WHERE participant_id = ?
                  AND effective_from <= ?
                ORDER BY version_no DESC
                LIMIT 1
                """,
                (
                    participant_id,
                    to_db_utc(
                        now
                    ),
                ),
            ).fetchone()

            if plan_row is None:
                return []

            if (
                now
                >= from_db_utc(
                    plan_row[
                        "horizon_end"
                    ]
                )
            ):
                # no-fallback。
                return []

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
                JOIN study_targets AS st
                  ON st.id = pi.study_target_id
                LEFT JOIN study_results AS sr
                  ON sr.plan_item_id = pi.id
                WHERE pi.plan_id = ?
                  AND st.participant_id = ?
                  AND st.kind = 'MATERIAL'
                  AND pi.is_cancelled = 0
                  AND sr.id IS NULL
                  AND pi.start_at <= ?
                ORDER BY
                    pi.start_at,
                    pi.id
                """,
                (
                    int(
                        plan_row["id"]
                    ),
                    participant_id,
                    to_db_utc(
                        now
                    ),
                ),
            ).fetchall()

            return [
                self._row_to_plan_item(
                    row
                )
                for row in rows
            ]

        finally:
            connection.close()

    # =====================================================
    # PROGRESS_SYNC candidate load
    # =====================================================

    def load_progress_sync_candidates(
        self,
        *,
        participant_id: str,
        study_target_id: int,
        now: datetime,
        source_planning_data_version: int,
    ) -> tuple[
        ProgressSyncCandidate,
        ...,
    ]:
        connection = connect(
            self._db_path
        )

        try:
            plan_rows = connection.execute(
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
                  AND horizon_end > ?
                  AND source_planning_data_version = ?
                ORDER BY version_no
                """,
                (
                    participant_id,
                    to_db_utc(
                        now
                    ),
                    source_planning_data_version,
                ),
            ).fetchall()

            plans = [
                self._row_to_plan(
                    row
                )
                for row in plan_rows
            ]

            active_now = [
                plan
                for plan in plans
                if plan.effective_from <= now
            ]

            selected_current = (
                max(
                    active_now,
                    key=lambda plan: (
                        plan.version_no
                    ),
                )
                if active_now
                else None
            )

            candidates: list[
                Plan
            ] = []

            if selected_current is not None:
                candidates.append(
                    selected_current
                )

            candidates.extend(
                plan
                for plan in plans
                if plan.effective_from > now
            )

            result: list[
                ProgressSyncCandidate
            ] = []

            for plan in candidates:
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
                    WHERE pi.plan_id = ?
                      AND pi.study_target_id = ?
                      AND pi.is_cancelled = 0
                      AND pi.start_at > ?
                    ORDER BY
                        pi.start_at,
                        pi.id
                    """,
                    (
                        plan.id,
                        study_target_id,
                        to_db_utc(
                            now
                        ),
                    ),
                ).fetchall()

                result.append(
                    ProgressSyncCandidate(
                        plan=plan,
                        future_plan_items=tuple(
                            self._row_to_plan_item(
                                row
                            )
                            for row in rows
                        ),
                    )
                )

            return tuple(
                result
            )

        finally:
            connection.close()

    # =====================================================
    # Theme
    # =====================================================

    def insert_theme_result(
        self,
        *,
        participant_id: str,
        plan_item: PlanItem,
        status: StudyResultStatus,
        actual_minutes: int | None,
        time_feeling: str | None,
        memo: str | None,
        now: datetime,
    ) -> StudyResult:
        with transaction(
            self._db_path
        ) as connection:
            self._assert_plan_item_owned(
                connection,
                participant_id=(
                    participant_id
                ),
                plan_item_id=(
                    plan_item.id
                ),
            )

            existing = connection.execute(
                """
                SELECT id
                FROM study_results
                WHERE participant_id = ?
                  AND plan_item_id = ?
                """,
                (
                    participant_id,
                    plan_item.id,
                ),
            ).fetchone()

            if existing is not None:
                raise (
                    StudyResultAlreadyExistsError(
                        "StudyResult already exists"
                    )
                )

            cursor = connection.execute(
                """
                INSERT INTO study_results (
                    participant_id,
                    plan_item_id,
                    study_target_id,
                    status,
                    actual_end_position,
                    actual_minutes,
                    time_feeling,
                    memo,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?,
                    NULL,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    participant_id,
                    plan_item.id,
                    plan_item.study_target_id,
                    status.value,
                    actual_minutes,
                    time_feeling,
                    memo,
                    to_db_utc(
                        now
                    ),
                    to_db_utc(
                        now
                    ),
                ),
            )

            result_id = (
                cursor.lastrowid
            )

            if result_id is None:
                raise RuntimeError(
                    "failed to insert StudyResult"
                )

        return StudyResult(
            id=int(
                result_id
            ),
            participant_id=(
                participant_id
            ),
            plan_item_id=(
                plan_item.id
            ),
            study_target_id=(
                plan_item.study_target_id
            ),
            status=status,
            actual_end_position=None,
            actual_minutes=(
                actual_minutes
            ),
            time_feeling=(
                time_feeling
            ),
            memo=memo,
        )

    # =====================================================
    # Material
    # =====================================================

    def insert_material_result_atomic(
        self,
        *,
        participant_id: str,
        plan_item: PlanItem,
        status: StudyResultStatus,
        actual_end_position: int | None,
        new_next_position: int,
        expected_old_next_position: int,
        expected_planning_data_version: int,
        sync_decisions: tuple[
            ProgressSyncDecision,
            ...,
        ],
        now: datetime,
    ) -> StudyResult:
        with transaction(
            self._db_path
        ) as connection:
            self._assert_material_write_state(
                connection,
                participant_id=(
                    participant_id
                ),
                plan_item=plan_item,
                expected_old_next_position=(
                    expected_old_next_position
                ),
                expected_planning_data_version=(
                    expected_planning_data_version
                ),
            )

            existing = connection.execute(
                """
                SELECT id
                FROM study_results
                WHERE participant_id = ?
                  AND plan_item_id = ?
                """,
                (
                    participant_id,
                    plan_item.id,
                ),
            ).fetchone()

            if existing is not None:
                raise (
                    StudyResultAlreadyExistsError(
                        "StudyResult already exists"
                    )
                )

            cursor = connection.execute(
                """
                INSERT INTO study_results (
                    participant_id,
                    plan_item_id,
                    study_target_id,
                    status,
                    actual_end_position,
                    actual_minutes,
                    time_feeling,
                    memo,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?,
                    NULL, NULL, NULL,
                    ?, ?
                )
                """,
                (
                    participant_id,
                    plan_item.id,
                    plan_item.study_target_id,
                    status.value,
                    actual_end_position,
                    to_db_utc(
                        now
                    ),
                    to_db_utc(
                        now
                    ),
                ),
            )

            result_id = (
                cursor.lastrowid
            )

            if result_id is None:
                raise RuntimeError(
                    "failed to insert StudyResult"
                )

            new_version = (
                expected_planning_data_version
                + 1
            )

            self._update_material_progress(
                connection,
                participant_id=(
                    participant_id
                ),
                study_target_id=(
                    plan_item.study_target_id
                ),
                new_next_position=(
                    new_next_position
                ),
                now=now,
            )

            self._increment_version(
                connection,
                participant_id=(
                    participant_id
                ),
            )

            self._apply_sync_decisions(
                connection,
                participant_id=(
                    participant_id
                ),
                decisions=(
                    sync_decisions
                ),
                old_version=(
                    expected_planning_data_version
                ),
                new_version=new_version,
                now=now,
            )

        return StudyResult(
            id=int(
                result_id
            ),
            participant_id=(
                participant_id
            ),
            plan_item_id=(
                plan_item.id
            ),
            study_target_id=(
                plan_item.study_target_id
            ),
            status=status,
            actual_end_position=(
                actual_end_position
            ),
            actual_minutes=None,
            time_feeling=None,
            memo=None,
        )

    # =====================================================
    # Correction
    # =====================================================

    def correct_theme_result(
        self,
        *,
        participant_id: str,
        previous: StudyResult,
        status: StudyResultStatus,
        actual_minutes: int | None,
        time_feeling: str | None,
        memo: str | None,
        now: datetime,
    ) -> StudyResult:
        updated = StudyResult(
            id=previous.id,
            participant_id=(
                previous.participant_id
            ),
            plan_item_id=(
                previous.plan_item_id
            ),
            study_target_id=(
                previous.study_target_id
            ),
            status=status,
            actual_end_position=None,
            actual_minutes=(
                actual_minutes
            ),
            time_feeling=(
                time_feeling
            ),
            memo=memo,
        )

        with transaction(
            self._db_path
        ) as connection:
            self._assert_result_current(
                connection,
                previous,
            )

            self._insert_revision(
                connection,
                previous=previous,
                updated=updated,
                now=now,
            )

            connection.execute(
                """
                UPDATE study_results
                SET
                    status = ?,
                    actual_end_position = NULL,
                    actual_minutes = ?,
                    time_feeling = ?,
                    memo = ?,
                    updated_at = ?
                WHERE participant_id = ?
                  AND id = ?
                """,
                (
                    status.value,
                    actual_minutes,
                    time_feeling,
                    memo,
                    to_db_utc(
                        now
                    ),
                    participant_id,
                    previous.id,
                ),
            )

        return updated

    def correct_material_result_atomic(
        self,
        *,
        participant_id: str,
        plan_item: PlanItem,
        previous: StudyResult,
        status: StudyResultStatus,
        actual_end_position: int | None,
        new_next_position: int,
        expected_old_next_position: int,
        expected_planning_data_version: int,
        sync_decisions: tuple[
            ProgressSyncDecision,
            ...,
        ],
        now: datetime,
    ) -> StudyResult:
        updated = StudyResult(
            id=previous.id,
            participant_id=(
                previous.participant_id
            ),
            plan_item_id=(
                previous.plan_item_id
            ),
            study_target_id=(
                previous.study_target_id
            ),
            status=status,
            actual_end_position=(
                actual_end_position
            ),
            actual_minutes=None,
            time_feeling=None,
            memo=None,
        )

        with transaction(
            self._db_path
        ) as connection:
            self._assert_material_write_state(
                connection,
                participant_id=(
                    participant_id
                ),
                plan_item=plan_item,
                expected_old_next_position=(
                    expected_old_next_position
                ),
                expected_planning_data_version=(
                    expected_planning_data_version
                ),
            )

            self._assert_result_current(
                connection,
                previous,
            )

            self._insert_revision(
                connection,
                previous=previous,
                updated=updated,
                now=now,
            )

            connection.execute(
                """
                UPDATE study_results
                SET
                    status = ?,
                    actual_end_position = ?,
                    actual_minutes = NULL,
                    time_feeling = NULL,
                    memo = NULL,
                    updated_at = ?
                WHERE participant_id = ?
                  AND id = ?
                """,
                (
                    status.value,
                    actual_end_position,
                    to_db_utc(
                        now
                    ),
                    participant_id,
                    previous.id,
                ),
            )

            new_version = (
                expected_planning_data_version
                + 1
            )

            self._update_material_progress(
                connection,
                participant_id=(
                    participant_id
                ),
                study_target_id=(
                    plan_item.study_target_id
                ),
                new_next_position=(
                    new_next_position
                ),
                now=now,
            )

            self._increment_version(
                connection,
                participant_id=(
                    participant_id
                ),
            )

            self._apply_sync_decisions(
                connection,
                participant_id=(
                    participant_id
                ),
                decisions=(
                    sync_decisions
                ),
                old_version=(
                    expected_planning_data_version
                ),
                new_version=new_version,
                now=now,
            )

        return updated

    # =====================================================
    # Transaction helpers
    # =====================================================

    @staticmethod
    def _assert_plan_item_owned(
        connection: sqlite3.Connection,
        *,
        participant_id: str,
        plan_item_id: int,
    ) -> None:
        row = connection.execute(
            """
            SELECT 1
            FROM plan_items AS pi
            JOIN plans AS p
              ON p.id = pi.plan_id
            WHERE p.participant_id = ?
              AND pi.id = ?
            """,
            (
                participant_id,
                plan_item_id,
            ),
        ).fetchone()

        if row is None:
            raise DomainValidationError(
                "PlanItem not found"
            )

    @staticmethod
    def _assert_material_write_state(
        connection: sqlite3.Connection,
        *,
        participant_id: str,
        plan_item: PlanItem,
        expected_old_next_position: int,
        expected_planning_data_version: int,
    ) -> None:
        participant = connection.execute(
            """
            SELECT planning_data_version
            FROM participants
            WHERE id = ?
            """,
            (
                participant_id,
            ),
        ).fetchone()

        if participant is None:
            raise DomainValidationError(
                "participant not found"
            )

        if (
            int(
                participant[
                    "planning_data_version"
                ]
            )
            != expected_planning_data_version
        ):
            raise PlanningDataChangedError(
                "planning_data_version changed "
                "before StudyResult save"
            )

        target = connection.execute(
            """
            SELECT next_position
            FROM study_targets
            WHERE participant_id = ?
              AND id = ?
            """,
            (
                participant_id,
                plan_item.study_target_id,
            ),
        ).fetchone()

        if target is None:
            raise DomainValidationError(
                "StudyTarget not found"
            )

        if (
            target["next_position"]
            != expected_old_next_position
        ):
            raise PlanningDataChangedError(
                "Material next_position changed "
                "before StudyResult save"
            )

        StudyResultRepository._assert_plan_item_owned(
            connection,
            participant_id=(
                participant_id
            ),
            plan_item_id=(
                plan_item.id
            ),
        )

    @staticmethod
    def _update_material_progress(
        connection: sqlite3.Connection,
        *,
        participant_id: str,
        study_target_id: int,
        new_next_position: int,
        now: datetime,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE study_targets
            SET
                next_position = ?,
                updated_at = ?
            WHERE participant_id = ?
              AND id = ?
              AND kind = 'MATERIAL'
            """,
            (
                new_next_position,
                to_db_utc(
                    now
                ),
                participant_id,
                study_target_id,
            ),
        )

        if cursor.rowcount != 1:
            raise DomainValidationError(
                "Material StudyTarget not found"
            )

    @staticmethod
    def _increment_version(
        connection: sqlite3.Connection,
        *,
        participant_id: str,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE participants
            SET planning_data_version =
                planning_data_version + 1
            WHERE id = ?
            """,
            (
                participant_id,
            ),
        )

        if cursor.rowcount != 1:
            raise DomainValidationError(
                "participant not found"
            )

    def _apply_sync_decisions(
        self,
        connection: sqlite3.Connection,
        *,
        participant_id: str,
        decisions: tuple[
            ProgressSyncDecision,
            ...,
        ],
        old_version: int,
        new_version: int,
        now: datetime,
    ) -> None:
        for decision in decisions:
            if not decision.syncable:
                # 何も変更しない。
                #
                # Plan.source versionが古いままなので
                # OUTDATEDになる。
                continue

            for update in (
                decision.item_updates
            ):
                current = connection.execute(
                    """
                    SELECT
                        range_start,
                        range_end,
                        origin
                    FROM plan_items
                    WHERE id = ?
                      AND plan_id = ?
                    """,
                    (
                        update.previous.id,
                        decision.plan_id,
                    ),
                ).fetchone()

                if current is None:
                    raise PlanningDataChangedError(
                        "PlanItem changed before "
                        "PROGRESS_SYNC"
                    )

                if (
                    current["range_start"]
                    != update.previous.range_start
                    or current["range_end"]
                    != update.previous.range_end
                    or current["origin"]
                    != update.previous.origin.value
                ):
                    raise PlanningDataChangedError(
                        "PlanItem changed before "
                        "PROGRESS_SYNC"
                    )

                cursor = connection.execute(
                    """
                    UPDATE plan_items
                    SET range_start = ?
                    WHERE id = ?
                      AND plan_id = ?
                    """,
                    (
                        update.updated.range_start,
                        update.updated.id,
                        decision.plan_id,
                    ),
                )

                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "failed to PROGRESS_SYNC "
                        "PlanItem"
                    )

                connection.execute(
                    """
                    INSERT INTO plan_item_adjustments (
                        plan_item_id,
                        adjustment_type,
                        created_at,
                        old_snapshot_json,
                        new_snapshot_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        update.updated.id,
                        ADJUSTMENT_PROGRESS_SYNC,
                        to_db_utc(
                            now
                        ),
                        self._plan_item_snapshot(
                            update.previous
                        ),
                        self._plan_item_snapshot(
                            update.updated
                        ),
                    ),
                )

            cursor = connection.execute(
                """
                UPDATE plans
                SET source_planning_data_version = ?
                WHERE participant_id = ?
                  AND id = ?
                  AND source_planning_data_version = ?
                """,
                (
                    new_version,
                    participant_id,
                    decision.plan_id,
                    old_version,
                ),
            )

            if cursor.rowcount != 1:
                raise PlanningDataChangedError(
                    "Plan changed before "
                    "PROGRESS_SYNC"
                )

    @staticmethod
    def _assert_result_current(
        connection: sqlite3.Connection,
        previous: StudyResult,
    ) -> None:
        row = connection.execute(
            """
            SELECT
                participant_id,
                plan_item_id,
                study_target_id,
                status,
                actual_end_position,
                actual_minutes,
                time_feeling,
                memo
            FROM study_results
            WHERE id = ?
              AND participant_id = ?
            """,
            (
                previous.id,
                previous.participant_id,
            ),
        ).fetchone()

        if row is None:
            raise StudyResultNotFoundError(
                "StudyResult not found"
            )

        current = (
            StudyResultRepository
            ._row_to_result(
                row,
                result_id=(
                    previous.id
                ),
            )
        )

        if (
            StudyResultRepository
            ._result_snapshot_dict(
                current
            )
            != StudyResultRepository
            ._result_snapshot_dict(
                previous
            )
        ):
            raise PlanningDataChangedError(
                "StudyResult changed "
                "before correction"
            )

    @staticmethod
    def _insert_revision(
        connection: sqlite3.Connection,
        *,
        previous: StudyResult,
        updated: StudyResult,
        now: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO study_result_revisions (
                study_result_id,
                revised_at,
                old_snapshot_json,
                new_snapshot_json
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                previous.id,
                to_db_utc(
                    now
                ),
                StudyResultRepository
                ._result_snapshot_json(
                    previous
                ),
                StudyResultRepository
                ._result_snapshot_json(
                    updated
                ),
            ),
        )

    # =====================================================
    # Snapshot / row conversion
    # =====================================================

    @staticmethod
    def _row_to_result(
        row: sqlite3.Row,
        *,
        result_id: int | None = None,
    ) -> StudyResult:
        return StudyResult(
            id=(
                result_id
                if result_id is not None
                else int(
                    row["id"]
                )
            ),
            participant_id=str(
                row["participant_id"]
            ),
            plan_item_id=int(
                row["plan_item_id"]
            ),
            study_target_id=int(
                row[
                    "study_target_id"
                ]
            ),
            status=StudyResultStatus(
                row["status"]
            ),
            actual_end_position=(
                int(
                    row[
                        "actual_end_position"
                    ]
                )
                if (
                    row[
                        "actual_end_position"
                    ]
                    is not None
                )
                else None
            ),
            actual_minutes=(
                int(
                    row[
                        "actual_minutes"
                    ]
                )
                if (
                    row[
                        "actual_minutes"
                    ]
                    is not None
                )
                else None
            ),
            time_feeling=(
                row["time_feeling"]
            ),
            memo=row["memo"],
        )

    @staticmethod
    def _row_to_plan_item(
        row: sqlite3.Row,
    ) -> PlanItem:
        return PlanItem(
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
                    row["range_start"]
                )
                if (
                    row["range_start"]
                    is not None
                )
                else None
            ),
            range_end=(
                int(
                    row["range_end"]
                )
                if (
                    row["range_end"]
                    is not None
                )
                else None
            ),
            is_cancelled=bool(
                row["is_cancelled"]
            ),
            cancelled_at=(
                from_db_utc(
                    row["cancelled_at"]
                )
                if (
                    row["cancelled_at"]
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

    @staticmethod
    def _row_to_plan(
        row: sqlite3.Row,
    ) -> Plan:
        return Plan(
            id=int(
                row["id"]
            ),
            participant_id=str(
                row[
                    "participant_id"
                ]
            ),
            version_no=int(
                row["version_no"]
            ),
            created_at=from_db_utc(
                row["created_at"]
            ),
            effective_from=from_db_utc(
                row["effective_from"]
            ),
            horizon_end=from_db_utc(
                row["horizon_end"]
            ),
            source_planning_data_version=int(
                row[
                    "source_planning_data_version"
                ]
            ),
        )

    @staticmethod
    def _result_snapshot_dict(
        result: StudyResult,
    ) -> dict:
        return {
            "id": result.id,
            "participant_id": (
                result.participant_id
            ),
            "plan_item_id": (
                result.plan_item_id
            ),
            "study_target_id": (
                result.study_target_id
            ),
            "status": (
                result.status.value
            ),
            "actual_end_position": (
                result.actual_end_position
            ),
            "actual_minutes": (
                result.actual_minutes
            ),
            "time_feeling": (
                result.time_feeling
            ),
            "memo": result.memo,
        }

    @classmethod
    def _result_snapshot_json(
        cls,
        result: StudyResult,
    ) -> str:
        return json.dumps(
            cls._result_snapshot_dict(
                result
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )

    @staticmethod
    def _plan_item_snapshot(
        item: PlanItem,
    ) -> str:
        return json.dumps(
            {
                "id": item.id,
                "plan_id": item.plan_id,
                "study_target_id": (
                    item.study_target_id
                ),
                "start_at": to_db_utc(
                    item.start_at
                ),
                "end_at": to_db_utc(
                    item.end_at
                ),
                "origin": (
                    item.origin.value
                ),
                "is_cancelled": (
                    item.is_cancelled
                ),
                "cancelled_at": (
                    to_db_utc(
                        item.cancelled_at
                    )
                    if (
                        item.cancelled_at
                        is not None
                    )
                    else None
                ),
                "carried_from_plan_item_id": (
                    item
                    .carried_from_plan_item_id
                ),
                "planned_minutes": (
                    item.planned_minutes
                ),
                "range_start": (
                    item.range_start
                ),
                "range_end": (
                    item.range_end
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )