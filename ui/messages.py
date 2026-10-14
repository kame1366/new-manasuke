from __future__ import annotations

from ai.errors import (
    AIGenerationError,
    AIOutputInvalidError,
    PlanningDataChangedError,
)
from planning.attempt_errors import (
    AttemptAlreadyRunningError,
    DeadlineSelectionInfeasibleError,
    PlanValidationFailedError,
)
from planning.plan_item_lifecycle_errors import (
    PlanItemMutationNotAllowedError,
)
from planning.study_result_errors import (
    MaterialUnrecordedBlockError,
    StudyResultAlreadyExistsError,
    StudyResultCorrectionLockedError,
)
from services.plan_generation_pipeline_service import (
    SourceDataIncompleteError,
)


def user_message_for_exception(
    exc: Exception,
) -> str:
    if isinstance(
        exc,
        MaterialUnrecordedBlockError,
    ):
        return (
            "まだ実績が入力されていない教材学習があります。"
            "先に「今日の学習・実績」から結果を入力してください。"
        )

    if isinstance(
        exc,
        SourceDataIncompleteError,
    ) and "LearningPolicy" in str(exc):
        return (
            "学習方針が未生成です。"
            "先に学習方針を生成してから、"
            "学習計画を作成してください。"
            "開発環境では "
            "`uv run python scripts/generate_learning_policies.py "
            "<参加者ID>` を実行します。"
        )

    if isinstance(
        exc,
        AttemptAlreadyRunningError,
    ):
        return (
            "現在、学習計画を生成しています。"
            "同時に複数の計画生成はできません。"
        )

    if isinstance(
        exc,
        DeadlineSelectionInfeasibleError,
    ):
        return (
            "選択した条件では期限内に配置できません。"
            "STRICT / BEST_EFFORTの選択を見直してください。"
        )

    if isinstance(
        exc,
        PlanItemMutationNotAllowedError,
    ):
        return (
            "この予定は現在の状態では変更できません。"
        )

    if isinstance(
        exc,
        StudyResultAlreadyExistsError,
    ):
        return (
            "この予定にはすでに実績があります。"
            "修正機能を利用してください。"
        )

    if isinstance(
        exc,
        StudyResultCorrectionLockedError,
    ):
        return (
            "この実績の後に別の実績が記録されているため、"
            "現在は修正できません。"
        )

    if isinstance(
        exc,
        PlanningDataChangedError,
    ):
        return (
            "操作中に学習設定が変更されました。"
            "最新の状態を読み込み直して、もう一度試してください。"
        )

    if isinstance(
        exc,
        PlanValidationFailedError,
    ):
        return (
            "変更後の計画が条件を満たさないため、"
            "保存できませんでした。"
        )

    if isinstance(
        exc,
        AIOutputInvalidError,
    ):
        return (
            "AIから有効な計画案を取得できませんでした。"
            "もう一度試してください。"
        )

    if isinstance(
        exc,
        AIGenerationError,
    ):
        return (
            "AIとの通信に失敗しました。"
            "もう一度試してください。"
        )

    return (
        "処理中にエラーが発生しました。"
        "同じ操作を繰り返しても解決しない場合は、"
        "開発者へ連絡してください。"
    )