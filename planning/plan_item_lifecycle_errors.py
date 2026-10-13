from __future__ import annotations


class PlanItemMutationNotAllowedError(
    RuntimeError
):
    """
    Plan state / start time / origin等により
    PlanItem変更が許可されない場合。
    """


class PlanItemAlreadyChangedError(
    RuntimeError
):
    """
    UI表示後にDB側PlanItemが変更され、
    stale writeを防止した場合。
    """