from datetime import datetime

import pytest

from domain.enums import (
    PlanItemOrigin,
    PlanOperationType,
    StudyTargetKind,
    UnitType,
)
from domain.models import (
    PlanItem,
    StudyTarget,
    StudyTargetRange,
)
from domain.time_rules import JST
from planning.replan_rules import (
    ReplanRules,
    UserModifiedConflictError,
)


def dt(
    day: int,
    hour: int = 0,
    minute: int = 0,
) -> datetime:
    return datetime(
        2026,
        10,
        day,
        hour,
        minute,
        tzinfo=JST,
    )


def theme_target() -> StudyTarget:
    return StudyTarget(
        id=1,
        participant_id="participant-a",
        kind=StudyTargetKind.THEME,
        title="英作文",
    )


def material_target(
    *,
    next_position: int = 1,
) -> StudyTarget:
    return StudyTarget(
        id=2,
        participant_id="participant-a",
        kind=StudyTargetKind.MATERIAL,
        title="数学",
        unit_type=UnitType.PAGE,
        next_position=next_position,
        estimated_minutes_per_unit=5.0,
        ranges=[
            StudyTargetRange(
                sequence_no=0,
                start_position=1,
                end_position=100,
            )
        ],
    )


def item(
    *,
    item_id: int,
    target_id: int,
    start_day: int,
    start_hour: int,
    origin=PlanItemOrigin.USER_MODIFIED,
    cancelled: bool = False,
    range_start=None,
    range_end=None,
) -> PlanItem:
    start = dt(
        start_day,
        start_hour,
    )

    end = dt(
        start_day,
        start_hour,
        30,
    )

    return PlanItem(
        id=item_id,
        plan_id=1,
        study_target_id=target_id,
        start_at=start,
        end_at=end,
        origin=origin,
        planned_minutes=30,
        range_start=range_start,
        range_end=range_end,
        is_cancelled=cancelled,
        cancelled_at=(
            dt(
                13,
                10,
            )
            if cancelled
            else None
        ),
    )


def test_replan_now_uses_next_five_minute_boundary():
    result = ReplanRules.effective_from(
        operation_type=(
            PlanOperationType.REPLAN_NOW
        ),
        now=dt(
            13,
            21,
            3,
        ),
    )

    assert result == dt(
        13,
        21,
        5,
    )


def test_replan_tomorrow_uses_midnight():
    result = ReplanRules.effective_from(
        operation_type=(
            PlanOperationType
            .REPLAN_TOMORROW
        ),
        now=dt(
            13,
            21,
            3,
        ),
    )

    assert result == dt(
        14,
        0,
    )


def test_only_future_user_modified_items_are_carried():
    rules = ReplanRules()

    items = [
        item(
            item_id=1,
            target_id=1,
            start_day=14,
            start_hour=18,
        ),
        item(
            item_id=2,
            target_id=1,
            start_day=14,
            start_hour=19,
            origin=(
                PlanItemOrigin
                .SYSTEM_GENERATED
            ),
        ),
        item(
            item_id=3,
            target_id=1,
            start_day=14,
            start_hour=20,
            cancelled=True,
        ),
    ]

    carried = (
        rules.collect_carry_forward(
            plan_items=items,
            study_targets=[
                theme_target()
            ],
            now=dt(
                13,
                21,
            ),
            effective_from=dt(
                14,
                0,
            ),
            horizon_end=dt(
                21,
                0,
            ),
        )
    )

    assert len(carried) == 1

    assert (
        carried[0]
        .source_plan_item_id
        == 1
    )


def test_carried_item_points_to_old_item():
    rules = ReplanRules()

    carried = (
        rules.collect_carry_forward(
            plan_items=[
                item(
                    item_id=77,
                    target_id=1,
                    start_day=14,
                    start_hour=18,
                )
            ],
            study_targets=[
                theme_target()
            ],
            now=dt(
                13,
                12,
            ),
            effective_from=dt(
                13,
                12,
            ),
            horizon_end=dt(
                20,
                0,
            ),
        )[0]
    )

    new_item = carried.to_plan_item(
        plan_id=999,
        temporary_id=1,
    )

    assert (
        new_item.origin
        == PlanItemOrigin.USER_MODIFIED
    )

    assert (
        new_item
        .carried_from_plan_item_id
        == 77
    )


def test_material_reserved_items_must_follow_path_order():
    rules = ReplanRules()

    with pytest.raises(
        UserModifiedConflictError,
        match=(
            "time order conflicts"
        ),
    ):
        rules.collect_carry_forward(
            plan_items=[
                item(
                    item_id=1,
                    target_id=2,
                    start_day=14,
                    start_hour=18,
                    range_start=20,
                    range_end=25,
                ),
                item(
                    item_id=2,
                    target_id=2,
                    start_day=14,
                    start_hour=19,
                    range_start=10,
                    range_end=15,
                ),
            ],
            study_targets=[
                material_target()
            ],
            now=dt(
                13,
                12,
            ),
            effective_from=dt(
                13,
                12,
            ),
            horizon_end=dt(
                20,
                0,
            ),
        )


def test_material_reserved_work_behind_progress_is_rejected():
    rules = ReplanRules()

    with pytest.raises(
        UserModifiedConflictError,
        match="behind current progress",
    ):
        rules.collect_carry_forward(
            plan_items=[
                item(
                    item_id=1,
                    target_id=2,
                    start_day=14,
                    start_hour=18,
                    range_start=10,
                    range_end=15,
                )
            ],
            study_targets=[
                material_target(
                    next_position=20,
                )
            ],
            now=dt(
                13,
                12,
            ),
            effective_from=dt(
                13,
                12,
            ),
            horizon_end=dt(
                20,
                0,
            ),
        )


def test_system_generated_is_never_carried():
    rules = ReplanRules()

    carried = (
        rules.collect_carry_forward(
            plan_items=[
                item(
                    item_id=1,
                    target_id=1,
                    start_day=14,
                    start_hour=18,
                    origin=(
                        PlanItemOrigin
                        .SYSTEM_GENERATED
                    ),
                )
            ],
            study_targets=[
                theme_target()
            ],
            now=dt(
                13,
                12,
            ),
            effective_from=dt(
                13,
                12,
            ),
            horizon_end=dt(
                20,
                0,
            ),
        )
    )

    assert carried == ()