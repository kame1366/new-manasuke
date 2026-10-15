
from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

from db.connection import transaction
from domain.enums import StudyTargetKind
from domain.models import StudyTarget, LearningPolicy
from repositories.study_target_repository import (
    StudyTargetRepository,
)
from repositories.learning_policy_repository import (
    LearningPolicyRepository,
)

from datetime import datetime

from domain.time_rules import UTC, to_db_utc


class StudyTargetSettingsConflictError(RuntimeError):
    pass


class StudyTargetSettingsService:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._targets = StudyTargetRepository(db_path)
        self._policies = LearningPolicyRepository(db_path)

    @staticmethod
    def _validate(
        target: StudyTarget,
        policy: LearningPolicy,
    ) -> None:
        if target.id != 0 or policy.study_target_id != 0:
            raise ValueError(
                "新規登録用のIDには0を指定してください。"
            )

        if not target.participant_id.strip():
            raise ValueError("参加者IDが不正です。")

        if len(target.title.strip()) > 200:
            raise ValueError("学習対象名は200文字以内です。")

        if not policy.purpose.strip():
            raise ValueError("学習目的を入力してください。")

        if (
            policy.minimum_sessions_per_week
            > policy.normal_sessions_per_week
            or policy.minimum_minutes > policy.normal_minutes
        ):
            raise ValueError(
                "最低ラインは通常ライン以下にしてください。"
            )

        if target.kind == StudyTargetKind.MATERIAL:
            if not target.ranges:
                raise ValueError(
                    "教材には学習範囲が必要です。"
                )

            if target.next_position is None:
                raise ValueError(
                    "教材の現在位置を指定してください。"
                )

            estimate = target.estimated_minutes_per_unit
            if (
                estimate is None
                or not math.isfinite(estimate)
                or estimate <= 0
            ):
                raise ValueError(
                    "1単位の予想時間は正の数にしてください。"
                )

            previous_end = None
            ordered_ranges = sorted(
                target.ranges,
                key=lambda item: item.sequence_no,
            )

            if [
                r.sequence_no for r in ordered_ranges
            ] != list(range(len(ordered_ranges))):
                raise ValueError(
                    "学習範囲の順序が不正です。"
                )

            for item in ordered_ranges:
                if item.start_position < 1:
                    raise ValueError(
                        "学習範囲は1以上で指定してください。"
                    )

                if (
                    previous_end is not None
                    and item.start_position <= previous_end
                ):
                    raise ValueError(
                        "学習範囲が重複、または"
                        "学習順序が逆転しています。"
                    )

                previous_end = item.end_position

            if not any(
                item.start_position
                <= target.next_position
                <= item.end_position
                for item in ordered_ranges
            ):
                raise ValueError(
                    "現在位置は登録した学習範囲内に"
                    "指定してください。"
                )

        else:
            if (
                target.unit_type is not None
                or target.next_position is not None
                or target.estimated_minutes_per_unit is not None
                or target.ranges
            ):
                raise ValueError(
                    "テーマに教材用の進捗情報は"
                    "設定できません。"
                )

    def create_with_policy(
        self,
        *,
        target: StudyTarget,
        policy: LearningPolicy,
        expected_version: int,
    ) -> int:
        self._validate(target, policy)

        if expected_version < 0:
            raise ValueError("設定バージョンが不正です。")

        with transaction(self._db_path) as connection:
            # Compare-and-swap:
            # バージョン確認と更新を原子的に実行する
            cursor = connection.execute(
                """
                UPDATE participants
                SET planning_data_version =
                    planning_data_version + 1
                WHERE id = ?
                  AND planning_data_version = ?
                """,
                (
                    target.participant_id,
                    expected_version,
                ),
            )

            if cursor.rowcount != 1:
                raise StudyTargetSettingsConflictError(
                    "別の操作で学習設定が変更されました。"
                    "最新の設定を読み込んでください。"
                )

            new_target_id = self._targets.insert(
                connection,
                target.participant_id,
                target,
            )

            persisted_policy = replace(
                policy,
                study_target_id=new_target_id,
            )

            self._policies.insert(
                connection,
                target.participant_id,
                persisted_policy,
            )

        return new_target_id

    
    def update_settings(
        self,
        *,
        participant_id: str,
        study_target_id: int,
        title: str,
        note: str | None,
        estimated_minutes_per_unit: float | None,
        policy: LearningPolicy,
        expected_version: int,
    ) -> None:
        """学習対象の基本情報と学習方針を一括更新する。"""

        normalized_title = title.strip()
        normalized_note = (note or "").strip() or None

        if not normalized_title:
            raise ValueError("学習対象名を入力してください。")

        if len(normalized_title) > 200:
            raise ValueError(
                "学習対象名は200文字以内にしてください。"
            )

        if (
            policy.study_target_id != study_target_id
        ):
            raise ValueError(
                "学習方針と学習対象のIDが一致しません。"
            )

        if (
            policy.minimum_sessions_per_week
            > policy.normal_sessions_per_week
            or policy.minimum_minutes > policy.normal_minutes
        ):
            raise ValueError(
                "最低ラインは通常ライン以下にしてください。"
            )

        if expected_version < 0:
            raise ValueError(
                "設定バージョンが不正です。"
            )

        with transaction(self._db_path) as connection:
            # バージョンの確認・更新を原子的に実行
            version_cursor = connection.execute(
                """
                UPDATE participants
                SET planning_data_version =
                    planning_data_version + 1
                WHERE id = ?
                  AND planning_data_version = ?
                """,
                (participant_id, expected_version),
            )

            if version_cursor.rowcount != 1:
                raise StudyTargetSettingsConflictError(
                    "別の操作で学習設定が更新されました。"
                    "最新の設定を読み込み直してください。"
                )

            row = connection.execute(
                """
                SELECT kind
                FROM study_targets
                WHERE id = ?
                  AND participant_id = ?
                """,
                (study_target_id, participant_id),
            ).fetchone()

            if row is None:
                raise ValueError(
                    "編集対象の学習対象が見つかりません。"
                )

            kind = StudyTargetKind(row["kind"])

            if kind == StudyTargetKind.MATERIAL:
                estimate = estimated_minutes_per_unit

                if (
                    estimate is None
                    or not math.isfinite(estimate)
                    or estimate <= 0
                ):
                    raise ValueError(
                        "1単位の予想所要時間は"
                        "正の数で指定してください。"
                    )
            else:
                if estimated_minutes_per_unit is not None:
                    raise ValueError(
                        "THEMEには単位あたりの時間を"
                        "設定できません。"
                    )
                estimate = None

            now_text = to_db_utc(datetime.now(UTC))

            cursor = connection.execute(
                """
                UPDATE study_targets
                SET title = ?,
                    note = ?,
                    estimated_minutes_per_unit = ?,
                    updated_at = ?
                WHERE id = ?
                  AND participant_id = ?
                """,
                (
                    normalized_title,
                    normalized_note,
                    estimate,
                    now_text,
                    study_target_id,
                    participant_id,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "学習対象の更新に失敗しました。"
                )

            self._policies.upsert(
                connection,
                participant_id,
                policy,
            )
