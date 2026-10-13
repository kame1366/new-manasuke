from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from db.connection import (
    connect,
    transaction,
)
from domain.enums import (
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
from planning.plan_item_lifecycle_errors import (
    PlanItemAlreadyChangedError,
)


ADJUSTMENT_USER_EDIT = "USER_EDIT"


class PlanItemLifecycleRepository:
    def __init__(
        self,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(
            db_path
        )

    def get_plan(
        self,
        *,
        participant_id: str,
        plan_id: int,
    ) -> Plan | None:
        connection = connect(
            self._db_path
        )

        try:
            row = connection.execute(
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
                  AND id = ?
                """,
                (
                    participant_id,
                    plan_id,
                ),
            ).fetchone()

            if row is None:
                return None

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
                    row[
                        "version_no"
                    ]
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

        finally:
            connection.close()

    def list_items(
        self,
        *,
        participant_id: str,
        plan_id: int,
    ) -> list[PlanItem]:
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
                self._row_to_item(
                    row
                )
                for row in rows
            ]

        finally:
            connection.close()

    def replace_item_with_adjustment(
        self,
        *,
        participant_id: str,
        previous: PlanItem,
        updated: PlanItem,
        now: datetime,
    ) -> None:
        """
        PlanItem update + USER_EDIT adjustmentを
        同じshort transactionで保存する。

        planning_data_versionは変更しない。
        PlanItem編集はSource Dataではないため。
        """
        if (
            previous.id
            != updated.id
            or previous.plan_id
            != updated.plan_id
        ):
            raise DomainValidationError(
                "PlanItem identity "
                "must not change"
            )

        with transaction(
            self._db_path
        ) as connection:
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
                  AND pi.plan_id = ?
                  AND pi.id = ?
                """,
                (
                    participant_id,
                    previous.plan_id,
                    previous.id,
                ),
            ).fetchone()

            if row is None:
                raise DomainValidationError(
                    "PlanItem not found"
                )

            current = (
                self._row_to_item(
                    row
                )
            )

            if (
                self._snapshot_dict(
                    current
                )
                != self._snapshot_dict(
                    previous
                )
            ):
                raise (
                    PlanItemAlreadyChangedError(
                        "PlanItem changed "
                        "before save"
                    )
                )

            cursor = connection.execute(
                """
                UPDATE plan_items
                SET
                    study_target_id = ?,
                    start_at = ?,
                    end_at = ?,
                    origin = ?,
                    is_cancelled = ?,
                    cancelled_at = ?,
                    carried_from_plan_item_id = ?,
                    planned_minutes = ?,
                    range_start = ?,
                    range_end = ?
                WHERE plan_id = ?
                  AND id = ?
                """,
                (
                    updated.study_target_id,
                    to_db_utc(
                        updated.start_at
                    ),
                    to_db_utc(
                        updated.end_at
                    ),
                    updated.origin.value,
                    (
                        1
                        if updated.is_cancelled
                        else 0
                    ),
                    (
                        to_db_utc(
                            updated.cancelled_at
                        )
                        if (
                            updated.cancelled_at
                            is not None
                        )
                        else None
                    ),
                    (
                        updated
                        .carried_from_plan_item_id
                    ),
                    updated.planned_minutes,
                    updated.range_start,
                    updated.range_end,
                    updated.plan_id,
                    updated.id,
                ),
            )

            if cursor.rowcount != 1:
                raise RuntimeError(
                    "failed to update PlanItem"
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
                    updated.id,
                    ADJUSTMENT_USER_EDIT,
                    to_db_utc(
                        now
                    ),
                    self._snapshot_json(
                        previous
                    ),
                    self._snapshot_json(
                        updated
                    ),
                ),
            )

    @staticmethod
    def _row_to_item(
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
    def _snapshot_dict(
        item: PlanItem,
    ) -> dict:
        return {
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
        }

    @classmethod
    def _snapshot_json(
        cls,
        item: PlanItem,
    ) -> str:
        return json.dumps(
            cls._snapshot_dict(
                item
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )