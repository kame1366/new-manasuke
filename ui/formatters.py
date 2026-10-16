from __future__ import annotations

from datetime import datetime, timedelta

from domain.plan_state import (
    PlanState,
)
from domain.enums import (
    StudyTargetKind,
    UnitType,
    Importance,
)
from domain.models import (
    Goal,
    PlanItem,
    StudyTarget,
)
from domain.time_rules import to_jst


PLAN_STATE_LABELS = {
    PlanState.CURRENT:
        "最新の計画",

    PlanState.OUTDATED_VALID:
        "設定変更前の計画",

    PlanState.OUTDATED_INVALID:
        "現在の条件では実行できない計画",

    PlanState.FUTURE_APPLICABLE:
        "これから有効になる計画",

    PlanState.SHADOWED:
        "過去の計画",

    PlanState.EXPIRED:
        "期限切れの計画",
}


def format_datetime(
    value: datetime,
) -> str:
    local = to_jst(
        value
    )

    return local.strftime(
        "%m/%d %H:%M"
    )


def format_time(
    value: datetime,
) -> str:
    local = to_jst(
        value
    )

    return local.strftime(
        "%H:%M"
    )



UNIT_TYPE_LABELS = {
    UnitType.PAGE: "ページ",
    UnitType.PROBLEM: "問題",
    UnitType.WORD: "単語",
    UnitType.SECTION: "セクション",
    UnitType.OTHER: "項目",
}

IMPORTANCE_LABELS = {
    Importance.HIGH: "高",
    Importance.MEDIUM: "中",
    Importance.LOW: "低",
}


def format_unit_type(unit_type: UnitType | None) -> str:
    if unit_type is None:
        return ""
    return UNIT_TYPE_LABELS.get(unit_type, unit_type.value)


def format_importance(importance: Importance) -> str:
    return IMPORTANCE_LABELS.get(importance, importance.value)


def format_goal_deadline(goal: Goal) -> str:
    """日付のみの期限はユーザーが選んだ日付として表示する。"""
    local = to_jst(goal.deadline_at)
    if goal.deadline_is_date_only:
        return (local.date() - timedelta(days=1)).strftime("%m/%dまで")
    return local.strftime("%m/%d %H:%M")


def format_plan_item_work(
    *,
    item: PlanItem,
    target: StudyTarget,
) -> str:
    if (
        target.kind
        == StudyTargetKind.MATERIAL
    ):
        if (
            item.range_start is None
            or item.range_end is None
        ):
            return target.title

        unit_label = format_unit_type(target.unit_type)

        return (
            f"{target.title} "
            f"{unit_label}{item.range_start}〜{item.range_end}"
        )

    return target.title