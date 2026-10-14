from __future__ import annotations

from datetime import datetime

from domain.plan_state import (
    PlanState,
)
from domain.enums import (
    StudyTargetKind,
)
from domain.models import (
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

        unit_label = (
            target.unit_type.value
            if target.unit_type
            is not None
            else ""
        )

        return (
            f"{target.title} "
            f"{unit_label} "
            f"{item.range_start}"
            f"〜"
            f"{item.range_end}"
        )

    return target.title