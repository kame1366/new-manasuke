from __future__ import annotations


class AIGenerationError(RuntimeError):
    """
    OpenAI API呼び出しそのものが
    成功しなかった場合。
    """


class AIOutputInvalidError(AIGenerationError):
    """
    AIのStructured Outputが
    Manasuke Domainとして不正な場合。
    """


class AIInteractionAlreadyRunningError(
    AIGenerationError
):
    """
    同じparticipantで同じAI operationが
    すでにRUNNINGの場合。
    """


class PlanningDataChangedError(
    AIGenerationError
):
    """
    AI処理中にSource Dataが変更されたため、
    staleなAI結果を保存できない場合。
    """