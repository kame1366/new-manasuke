
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from db.connection import transaction
from domain.time_rules import UTC, to_db_utc


class ArchiveConflictError(RuntimeError):
    """編集中に学習設定のVersionが変化した。"""


class ArchiveOperationError(ValueError):
    """アーカイブ・復元できない状態である。"""


class StudyTargetArchiveService:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)

    @staticmethod
    def _validate_ids(
        participant_id: str,
        record_id: int,
        expected_version: int,
    ) -> None:
        if not participant_id.strip():
            raise ValueError("参加者IDが不正です。")

        if record_id <= 0:
            raise ValueError("対象IDが不正です。")

        if expected_version < 0:
            raise ValueError("設定Versionが不正です。")

    @staticmethod
    def _bump_version(
        connection: sqlite3.Connection,
        participant_id: str,
        expected_version: int,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE participants
            SET planning_data_version =
                planning_data_version + 1
            WHERE id = ?
              AND planning_data_version = ?
            """,
            (participant_id, expected_version),
        )

        if cursor.rowcount != 1:
            raise ArchiveConflictError(
                "学習設定が別の操作で更新されました。"
                "最新の設定を読み込んでください。"
            )

    # =================================================
    # StudyTargetをアーカイブ
    # =================================================

    def archive_study_target(
        self,
        *,
        participant_id: str,
        study_target_id: int,
        expected_version: int,
    ) -> int:
        """
        StudyTargetと有効な関連Goalをアーカイブする。
        戻り値は同時にアーカイブしたGoalの件数。
        """

        self._validate_ids(
            participant_id,
            study_target_id,
            expected_version,
        )

        with transaction(self._db_path) as connection:
            self._bump_version(
                connection,
                participant_id,
                expected_version,
            )

            row = connection.execute(
                """
                SELECT archived_at
                FROM study_targets
                WHERE id = ?
                  AND participant_id = ?
                """,
                (study_target_id, participant_id),
            ).fetchone()

            if row is None:
                raise ArchiveOperationError(
                    "学習対象が見つかりません。"
                )

            if row["archived_at"] is not None:
                raise ArchiveOperationError(
                    "この学習対象はすでに"
                    "アーカイブされています。"
                )

            now_text = to_db_utc(datetime.now(UTC))

            connection.execute(
                """
                UPDATE study_targets
                SET archived_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND participant_id = ?
                """,
                (
                    now_text,
                    now_text,
                    study_target_id,
                    participant_id,
                ),
            )

            cursor = connection.execute(
                """
                UPDATE goals
                SET archived_at = ?,
                    updated_at = ?
                WHERE participant_id = ?
                  AND study_target_id = ?
                  AND archived_at IS NULL
                """,
                (
                    now_text,
                    now_text,
                    participant_id,
                    study_target_id,
                ),
            )

            return cursor.rowcount

    # =================================================
    # StudyTargetを復元
    # =================================================

    def restore_study_target(
        self,
        *,
        participant_id: str,
        study_target_id: int,
        expected_version: int,
    ) -> None:
        self._validate_ids(
            participant_id,
            study_target_id,
            expected_version,
        )

        with transaction(self._db_path) as connection:
            self._bump_version(
                connection,
                participant_id,
                expected_version,
            )

            row = connection.execute(
                """
                SELECT archived_at
                FROM study_targets
                WHERE id = ?
                  AND participant_id = ?
                """,
                (study_target_id, participant_id),
            ).fetchone()

            if row is None:
                raise ArchiveOperationError(
                    "学習対象が見つかりません。"
                )

            if row["archived_at"] is None:
                raise ArchiveOperationError(
                    "この学習対象はすでに有効です。"
                )

            connection.execute(
                """
                UPDATE study_targets
                SET archived_at = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND participant_id = ?
                """,
                (
                    to_db_utc(datetime.now(UTC)),
                    study_target_id,
                    participant_id,
                ),
            )

            # Goalは復元しない。
            # 必要なGoalだけ後からユーザーが復元する。

    # =================================================
    # Goalのアーカイブ・復元
    # =================================================

    def archive_goal(
        self,
        *,
        participant_id: str,
        goal_id: int,
        expected_version: int,
    ) -> None:
        self._change_goal_state(
            participant_id=participant_id,
            goal_id=goal_id,
            expected_version=expected_version,
            restore=False,
        )

    def restore_goal(
        self,
        *,
        participant_id: str,
        goal_id: int,
        expected_version: int,
    ) -> None:
        self._change_goal_state(
            participant_id=participant_id,
            goal_id=goal_id,
            expected_version=expected_version,
            restore=True,
        )

    def _change_goal_state(
        self,
        *,
        participant_id: str,
        goal_id: int,
        expected_version: int,
        restore: bool,
    ) -> None:
        self._validate_ids(
            participant_id,
            goal_id,
            expected_version,
        )

        with transaction(self._db_path) as connection:
            self._bump_version(
                connection,
                participant_id,
                expected_version,
            )

            row = connection.execute(
                """
                SELECT
                    g.archived_at AS goal_archived_at,
                    s.archived_at AS target_archived_at
                FROM goals AS g
                JOIN study_targets AS s
                  ON s.id = g.study_target_id
                 AND s.participant_id = g.participant_id
                WHERE g.id = ?
                  AND g.participant_id = ?
                """,
                (goal_id, participant_id),
            ).fetchone()

            if row is None:
                raise ArchiveOperationError(
                    "目標が見つかりません。"
                )

            if restore:
                if row["goal_archived_at"] is None:
                    raise ArchiveOperationError(
                        "この目標はすでに有効です。"
                    )

                if row["target_archived_at"] is not None:
                    raise ArchiveOperationError(
                        "先に紐づく学習対象を"
                        "復元してください。"
                    )

                archived_at = None

            else:
                if row["goal_archived_at"] is not None:
                    raise ArchiveOperationError(
                        "この目標はすでに"
                        "アーカイブされています。"
                    )

                archived_at = to_db_utc(
                    datetime.now(UTC)
                )

            connection.execute(
                """
                UPDATE goals
                SET archived_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND participant_id = ?
                """,
                (
                    archived_at,
                    to_db_utc(datetime.now(UTC)),
                    goal_id,
                    participant_id,
                ),
            )
