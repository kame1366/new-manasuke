import pytest

from domain.enums import (
    PlanItemOrigin,
    StudyResultStatus,
    StudyTargetKind,
    UnitType,
)
from domain.errors import (
    DomainValidationError,
)
from domain.models import (
    PlanItem,
    StudyTarget,
    StudyTargetRange,
)
from domain.time_rules import JST
from datetime import datetime

from planning.study_result_rules import (
    MaterialStudyResultRules,
    ThemeStudyResultRules,
)


def dt(
    day: int,
    hour: int = 0,
) -> datetime:
    return datetime(
        2026,
        10,
        day,
        hour,
        tzinfo=JST,
    )


def material_target(
    *,
    next_position: int = 43,
) -> StudyTarget:
    return StudyTarget(
        id=1,
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


def material_item() -> PlanItem:
    return PlanItem(
        id=1,
        plan_id=1,
        study_target_id=1,
        start_at=dt(
            14,
            18,
        ),
        end_at=dt(
            14,
            18,
        ).replace(
            minute=30
        ),
        origin=(
            PlanItemOrigin
            .SYSTEM_GENERATED
        ),
        planned_minutes=30,
        range_start=43,
        range_end=48,
    )


def theme_target() -> StudyTarget:
    return StudyTarget(
        id=2,
        participant_id="participant-a",
        kind=StudyTargetKind.THEME,
        title="英作文",
    )


def theme_item() -> PlanItem:
    return PlanItem(
        id=2,
        plan_id=1,
        study_target_id=2,
        start_at=dt(
            14,
            19,
        ),
        end_at=dt(
            14,
            19,
        ).replace(
            minute=30
        ),
        origin=(
            PlanItemOrigin
            .SYSTEM_GENERATED
        ),
        planned_minutes=30,
    )


def test_material_completed_moves_to_after_range():
    rules = (
        MaterialStudyResultRules()
    )

    result = rules.evaluate(
        target=material_target(),
        plan_item=material_item(),
        status=(
            StudyResultStatus.COMPLETED
        ),
        actual_end_position=None,
    )

    assert (
        result
        .normalized_actual_end_position
        == 48
    )

    assert (
        result.new_next_position
        == 49
    )


def test_material_completed_can_go_beyond_plan():
    rules = (
        MaterialStudyResultRules()
    )

    result = rules.evaluate(
        target=material_target(),
        plan_item=material_item(),
        status=(
            StudyResultStatus.COMPLETED
        ),
        actual_end_position=51,
    )

    assert (
        result
        .normalized_actual_end_position
        == 51
    )

    assert (
        result.new_next_position
        == 52
    )


def test_material_partial_moves_to_next_position():
    rules = (
        MaterialStudyResultRules()
    )

    result = rules.evaluate(
        target=material_target(),
        plan_item=material_item(),
        status=(
            StudyResultStatus.PARTIAL
        ),
        actual_end_position=45,
    )

    assert (
        result.new_next_position
        == 46
    )


def test_material_partial_requires_actual_end():
    rules = (
        MaterialStudyResultRules()
    )

    with pytest.raises(
        DomainValidationError,
        match="PARTIAL requires",
    ):
        rules.evaluate(
            target=material_target(),
            plan_item=material_item(),
            status=(
                StudyResultStatus.PARTIAL
            ),
            actual_end_position=None,
        )


def test_partial_cannot_equal_planned_end():
    rules = (
        MaterialStudyResultRules()
    )

    with pytest.raises(
        DomainValidationError,
        match="before range_end",
    ):
        rules.evaluate(
            target=material_target(),
            plan_item=material_item(),
            status=(
                StudyResultStatus.PARTIAL
            ),
            actual_end_position=48,
        )


def test_not_done_does_not_advance_progress():
    rules = (
        MaterialStudyResultRules()
    )

    result = rules.evaluate(
        target=material_target(),
        plan_item=material_item(),
        status=(
            StudyResultStatus.NOT_DONE
        ),
        actual_end_position=None,
    )

    assert (
        result.new_next_position
        == 43
    )


def test_first_material_result_must_start_at_current_progress():
    rules = (
        MaterialStudyResultRules()
    )

    with pytest.raises(
        DomainValidationError,
        match="next_position",
    ):
        rules.evaluate(
            target=material_target(
                next_position=40
            ),
            plan_item=material_item(),
            status=(
                StudyResultStatus.COMPLETED
            ),
            actual_end_position=None,
        )


def test_theme_target_minutes_requires_actual_minutes():
    with pytest.raises(
        DomainValidationError,
        match="requires actual_minutes",
    ):
        ThemeStudyResultRules.validate(
            target=theme_target(),
            plan_item=theme_item(),
            status=(
                StudyResultStatus.COMPLETED
            ),
            actual_end_position=None,
            actual_minutes=None,
            requires_actual_minutes=True,
        )


def test_theme_actual_minutes_can_exceed_planned_minutes():
    ThemeStudyResultRules.validate(
        target=theme_target(),
        plan_item=theme_item(),
        status=(
            StudyResultStatus.COMPLETED
        ),
        actual_end_position=None,
        actual_minutes=50,
        requires_actual_minutes=True,
    )