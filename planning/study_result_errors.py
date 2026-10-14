from __future__ import annotations


class StudyResultAlreadyExistsError(
    RuntimeError
):
    """
    同じPlanItemにすでにStudyResultがある場合。
    修正はcorrect()を使う。
    """


class StudyResultNotFoundError(
    RuntimeError
):
    """
    修正対象StudyResultが存在しない場合。
    """


class StudyResultCorrectionLockedError(
    RuntimeError
):
    """
    後続StudyResultが存在し、
    古いResultの修正が禁止される場合。
    """


class MaterialUnrecordedBlockError(
    RuntimeError
):
    """
    MaterialのUNRECORDEDが存在し、
    concrete range replanを安全に行えない場合。
    """


class ProgressSyncConflictError(
    RuntimeError
):
    """
    内部用。

    Material progressを既存Planへ
    安全に同期できないことを示す。

    StudyResult自体は失敗させず、
    そのPlanをOUTDATEDにするために使う。
    """