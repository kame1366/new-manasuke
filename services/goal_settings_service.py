
from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

from db.connection import transaction
from domain.enums import (
    GoalType,
    Importance,
    StudyTargetKind,
)
from domain.models import Goal, GoalRange
from domain.time_rules import UTC, ensure_aware
from repositories.goal_repository import GoalRepository

from collections.abc import Sequence

from domain.time_rules import JST, to_db_utc


class GoalSettingsConflictError(RuntimeError):
    """編集中に学習設定が変更された。"""


class GoalSettingsService:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._goals = GoalRepository(db_path)

    def create(
        self,
        *,
        participant_id: str,
        study_target_id: int,
        goal_type: GoalType,
        title: str,
        deadline_at: datetime,
        importance: Importance,
        range_start: int | None,
        range_end: int | None,
        target_minutes: int | None,
        note: str | None,
        expected_version: int,
        deadline_is_date_only: bool = False,
    ) -> int:
        title = title.strip()
        note = (note or "").strip() or None

        if not participant_id.strip():
            raise ValueError("参加者IDが不正です。")

        if not title:
            raise ValueError("目標名を入力してください。")

        if len(title) > 200:
            raise ValueError(
                "目標名は200文字以内にしてください。"
            )

        if note is not None and len(note) > 500:
            raise ValueError(
                "メモは500文字以内にしてください。"
            )

        if study_target_id <= 0:
            raise ValueError("学習対象IDが不正です。")

        if expected_version < 0:
            raise ValueError(
                "設定Versionが不正です。"
            )

        if not isinstance(goal_type, GoalType):
            raise ValueError("目標の種類が不正です。")

        if not isinstance(importance, Importance):
            raise ValueError("重要度が不正です。")

        ensure_aware(deadline_at)

        # タイムゾーンの検証
        ensure_aware(deadline_at)

        # 追加：期限の指定形式を検証
        if not isinstance(deadline_is_date_only, bool):
            raise ValueError(
                "期限の指定形式が不正です。"
            )

        if (
            deadline_is_date_only
            and deadline_at.astimezone(JST).time()
            != time(0, 0)
        ):
            raise ValueError(
                "日付のみの期限は翌日00:00を"
                "指定してください。"
            )

        # 既存の期限チェック
        if deadline_at <= datetime.now(UTC):
            raise ValueError(
                "期限は現在より後に設定してください。"
            )

        if (
            deadline_at.minute % 5 != 0
            or deadline_at.second != 0
            or deadline_at.microsecond != 0
        ):
            raise ValueError(
                "期限の時刻は5分単位で指定してください。"
            )

        # この下に既存の
        # with transaction(self._db_path) as connection:
        # が続く

        if deadline_at <= datetime.now(UTC):
            raise ValueError(
                "期限は現在より後に設定してください。"
            )

        if (
            deadline_at.minute % 5 != 0
            or deadline_at.second != 0
            or deadline_at.microsecond != 0
        ):
            raise ValueError(
                "期限の時刻は5分単位で指定してください。"
            )

        with transaction(self._db_path) as connection:
            # 設定Versionの比較と更新を同時に実行
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
                raise GoalSettingsConflictError(
                    "別の操作で学習設定が変更されました。"
                    "最新情報を読み込み直してください。"
                )

            # アーカイブ済みStudyTargetへの登録は禁止
            target_row = connection.execute(
                """
                SELECT kind
                FROM study_targets
                WHERE id = ?
                  AND participant_id = ?
                  AND archived_at IS NULL
                """,
                (study_target_id, participant_id),
            ).fetchone()

            if target_row is None:
                raise ValueError(
                    "有効な学習対象が見つかりません。"
                )

            kind = StudyTargetKind(target_row["kind"])
            goal_ranges: list[GoalRange] = []

            if kind == StudyTargetKind.MATERIAL:
                if range_start is None or range_end is None:
                    raise ValueError(
                        "教材の目標範囲を入力してください。"
                    )

                if (
                    range_start < 1
                    or range_start > range_end
                ):
                    raise ValueError(
                        "目標範囲が不正です。"
                    )

                if target_minutes is not None:
                    raise ValueError(
                        "教材の目標には目標時間を"
                        "指定できません。"
                    )

                source_ranges = connection.execute(
                    """
                    SELECT
                        start_position,
                        end_position
                    FROM study_target_ranges
                    WHERE study_target_id = ?
                    ORDER BY sequence_no
                    """,
                    (study_target_id,),
                ).fetchall()

                def is_on_path(position: int) -> bool:
                    return any(
                        row["start_position"]
                        <= position
                        <= row["end_position"]
                        for row in source_ranges
                    )

                if (
                    not is_on_path(range_start)
                    or not is_on_path(range_end)
                ):
                    raise ValueError(
                        "開始位置と終了位置は、登録済みの"
                        "学習範囲から選んでください。"
                    )

                # 教材の経路と重なる部分だけをGoalRange化
                for row in source_ranges:
                    start = max(
                        range_start,
                        int(row["start_position"]),
                    )
                    end = min(
                        range_end,
                        int(row["end_position"]),
                    )

                    if start <= end:
                        goal_ranges.append(
                            GoalRange(
                                start_position=start,
                                end_position=end,
                            )
                        )

                if not goal_ranges:
                    raise ValueError(
                        "有効な目標範囲がありません。"
                    )

            else:
                if (
                    range_start is not None
                    or range_end is not None
                ):
                    raise ValueError(
                        "テーマには教材の目標範囲を"
                        "指定できません。"
                    )

                if (
                    target_minutes is None
                    or target_minutes <= 0
                    or target_minutes % 5 != 0
                ):
                    raise ValueError(
                        "目標時間は5分単位の"
                        "正の整数で指定してください。"
                    )

            goal = Goal(
                id=0,
                participant_id=participant_id,
                study_target_id=study_target_id,
                goal_type=goal_type,
                title=title,
                deadline_at=deadline_at,
                importance=importance,
                target_minutes=target_minutes,
                note=note,
                ranges=goal_ranges,
                deadline_is_date_only=deadline_is_date_only,
            )

            # 既存Repositoryを同じTransaction内で利用
            goal_id = self._goals.insert(
                connection,
                participant_id,
                goal,
            )

        return goal_id



    def update(
        self,
        *,
        participant_id: str,
        goal_id: int,
        goal_type: GoalType,
        title: str,
        deadline_at: datetime,
        deadline_is_date_only: bool,
        importance: Importance,
        requested_ranges: Sequence[tuple[int, int]],
        target_minutes: int | None,
        note: str | None,
        expected_version: int,
    ) -> None:
        """有効なGoalを編集する。StudyTargetの変更は禁止。"""

        title = title.strip()
        note = (note or "").strip() or None

        if not participant_id.strip():
            raise ValueError("参加者IDが不正です。")

        if goal_id <= 0 or expected_version < 0:
            raise ValueError("Goal IDまたはVersionが不正です。")

        if not title or len(title) > 200:
            raise ValueError(
                "目標名は1〜200文字で入力してください。"
            )

        if note is not None and len(note) > 500:
            raise ValueError("メモは500文字以内です。")

        if not isinstance(goal_type, GoalType):
            raise ValueError("目標の種類が不正です。")

        if not isinstance(importance, Importance):
            raise ValueError("重要度が不正です。")

        if not isinstance(deadline_is_date_only, bool):
            raise ValueError("期限の指定形式が不正です。")

        ensure_aware(deadline_at)

        if deadline_at <= datetime.now(UTC):
            raise ValueError(
                "期限は現在より後にしてください。"
            )

        if (
            deadline_at.minute % 5 != 0
            or deadline_at.second != 0
            or deadline_at.microsecond != 0
        ):
            raise ValueError(
                "期限の時刻は5分単位で指定してください。"
            )

        if (
            deadline_is_date_only
            and deadline_at.astimezone(JST).time()
            != datetime.min.time()
        ):
            raise ValueError(
                "日付のみの期限は翌日00:00を"
                "終了境界にしてください。"
            )

        with transaction(self._db_path) as connection:
            # Versionを比較して原子的に更新
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
                raise GoalSettingsConflictError(
                    "学習設定が別の操作で変更されました。"
                    "最新の設定を読み込んでください。"
                )

            # 有効なGoalと有効なStudyTargetを確認
            row = connection.execute(
                """
                SELECT
                    g.study_target_id,
                    s.kind
                FROM goals AS g
                JOIN study_targets AS s
                  ON s.id = g.study_target_id
                 AND s.participant_id = g.participant_id
                WHERE g.id = ?
                  AND g.participant_id = ?
                  AND g.archived_at IS NULL
                  AND s.archived_at IS NULL
                """,
                (goal_id, participant_id),
            ).fetchone()

            if row is None:
                raise ValueError(
                    "編集可能な目標が見つかりません。"
                )

            target_id = int(row["study_target_id"])
            kind = StudyTargetKind(row["kind"])

            goal_ranges: list[GoalRange] = []

            if kind == StudyTargetKind.MATERIAL:
                if target_minutes is not None:
                    raise ValueError(
                        "教材の目標には目標時間を"
                        "設定できません。"
                    )

                if not requested_ranges:
                    raise ValueError(
                        "教材の目標範囲を指定してください。"
                    )

                source_ranges = connection.execute(
                    """
                    SELECT start_position, end_position
                    FROM study_target_ranges
                    WHERE study_target_id = ?
                    ORDER BY sequence_no
                    """,
                    (target_id,),
                ).fetchall()

                def is_on_path(position: int) -> bool:
                    return any(
                        int(item["start_position"])
                        <= position
                        <= int(item["end_position"])
                        for item in source_ranges
                    )

                intersections: list[tuple[int, int]] = []

                for start, end in requested_ranges:
                    if start < 1 or start > end:
                        raise ValueError(
                            "目標範囲の開始・終了が不正です。"
                        )

                    if (
                        not is_on_path(start)
                        or not is_on_path(end)
                    ):
                        raise ValueError(
                            "目標範囲は登録済み教材の"
                            "学習経路内で指定してください。"
                        )

                    for source in source_ranges:
                        a = max(
                            start,
                            int(source["start_position"]),
                        )
                        b = min(
                            end,
                            int(source["end_position"]),
                        )

                        if a <= b:
                            intersections.append((a, b))

                # 重複した範囲を統合する
                intersections.sort()
                merged: list[list[int]] = []

                for start, end in intersections:
                    if (
                        merged
                        and start <= merged[-1][1] + 1
                    ):
                        merged[-1][1] = max(
                            merged[-1][1],
                            end,
                        )
                    else:
                        merged.append([start, end])

                goal_ranges = [
                    GoalRange(
                        start_position=start,
                        end_position=end,
                    )
                    for start, end in merged
                ]

                if not goal_ranges:
                    raise ValueError(
                        "有効な目標範囲がありません。"
                    )

            else:
                if requested_ranges:
                    raise ValueError(
                        "テーマには教材の目標範囲を"
                        "設定できません。"
                    )

                if (
                    target_minutes is None
                    or target_minutes <= 0
                    or target_minutes % 5 != 0
                ):
                    raise ValueError(
                        "目標時間は5分単位の正の整数で"
                        "指定してください。"
                    )

            now_text = to_db_utc(datetime.now(UTC))

            # Goal本体を更新
            cursor = connection.execute(
                """
                UPDATE goals
                SET goal_type = ?,
                    title = ?,
                    deadline_at = ?,
                    deadline_is_date_only = ?,
                    importance = ?,
                    target_minutes = ?,
                    note = ?,
                    updated_at = ?
                WHERE id = ?
                  AND participant_id = ?
                  AND archived_at IS NULL
                """,
                (
                    goal_type.value,
                    title,
                    to_db_utc(deadline_at),
                    int(deadline_is_date_only),
                    importance.value,
                    target_minutes,
                    note,
                    now_text,
                    goal_id,
                    participant_id,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "目標の更新に失敗しました。"
                )

            # 既存GoalRangeを新しい範囲に置換
            connection.execute(
                """
                DELETE FROM goal_ranges
                WHERE goal_id = ?
                """,
                (goal_id,),
            )

            for item in goal_ranges:
                connection.execute(
                    """
                    INSERT INTO goal_ranges (
                        goal_id,
                        start_position,
                        end_position
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        goal_id,
                        item.start_position,
                        item.end_position,
                    ),
                )

