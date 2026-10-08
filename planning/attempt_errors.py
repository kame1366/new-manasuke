from __future__ import annotations

from collections.abc import Sequence

from planning.plan_validator import (
    PlanValidationIssue,
)


class AttemptAlreadyRunningError(
    RuntimeError
):
    """
    participantに既存IN_PROGRESS Attemptがあり、
    まだstaleではない場合。
    """


class AttemptNotActiveError(
    RuntimeError
):
    """
    AttemptがすでにFAILED / ABANDONED /
    SUCCEEDED等になっている場合。
    """


class AttemptStageError(
    RuntimeError
):
    """
    Attemptの現在stageと、
    実行しようとしたoperationが一致しない場合。
    """


class DeadlineSelectionInfeasibleError(
    RuntimeError
):
    """
    ユーザーが選択したSTRICT集合が
    feasibilityを満たしていない場合。
    """


class PlanValidationFailedError(
    RuntimeError
):
    def __init__(
        self,
        issues: Sequence[
            PlanValidationIssue
        ],
    ) -> None:
        self.issues = tuple(
            issues
        )

        codes = ", ".join(
            issue.code
            for issue in self.issues
        )

        super().__init__(
            "generated Plan failed "
            "PlanValidator: "
            f"{codes}"
        )