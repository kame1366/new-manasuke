from datetime import datetime

import pytest

from domain.enums import (
    AttemptStage,
    AttemptStatus,
    GoalType,
    Importance,
    PlanItemOrigin,
    PlanOperationType,
    StudyResultStatus,
    StudyTargetKind,
    UnitType,
)
from domain.models import (
    AvailableTime,
    BusyEvent,
    ExtraAvailableTime,
    Goal,
    GoalRange,
    LearningPolicy,
    Plan,
    PlanGenerationAttempt,
    PlanItem,
    StudyResult,
    StudyTarget,
    StudyTargetRange,
)
from domain.errors import (
    DomainValidationError,
    InvalidTimeRangeError,
)
from domain.time_rules import JST


# =========================================================
# StudyTargetRange
# =========================================================


def test_study_target_range_can_be_created():
    target_range = StudyTargetRange(
        sequence_no=0,
        start_position=1,
        end_position=50,
    )

    assert target_range.sequence_no == 0
    assert target_range.start_position == 1
    assert target_range.end_position == 50


def test_study_target_range_allows_single_position():
    target_range = StudyTargetRange(
        sequence_no=0,
        start_position=10,
        end_position=10,
    )

    assert target_range.start_position == target_range.end_position


def test_study_target_range_rejects_negative_sequence_no():
    with pytest.raises(ValueError):
        StudyTargetRange(
            sequence_no=-1,
            start_position=1,
            end_position=10,
        )


def test_study_target_range_rejects_reversed_range():
    with pytest.raises(ValueError):
        StudyTargetRange(
            sequence_no=0,
            start_position=20,
            end_position=10,
        )


# =========================================================
# StudyTarget
# =========================================================


def test_material_study_target_can_be_created(
    material_target: StudyTarget,
):
    assert material_target.kind == StudyTargetKind.MATERIAL
    assert material_target.unit_type == UnitType.PAGE
    assert material_target.next_position == 1
    assert material_target.estimated_minutes_per_unit == 5.0


def test_theme_study_target_can_be_created(
    theme_target: StudyTarget,
):
    assert theme_target.kind == StudyTargetKind.THEME
    assert theme_target.unit_type is None
    assert theme_target.next_position is None


def test_study_target_rejects_blank_title(
    participant_id: str,
):
    with pytest.raises(ValueError):
        StudyTarget(
            id=1,
            participant_id=participant_id,
            kind=StudyTargetKind.THEME,
            title="   ",
        )


def test_material_requires_unit_type(
    participant_id: str,
):
    with pytest.raises(ValueError):
        StudyTarget(
            id=1,
            participant_id=participant_id,
            kind=StudyTargetKind.MATERIAL,
            title="数学問題集",
            next_position=1,
            estimated_minutes_per_unit=5.0,
        )


def test_material_requires_next_position(
    participant_id: str,
):
    with pytest.raises(ValueError):
        StudyTarget(
            id=1,
            participant_id=participant_id,
            kind=StudyTargetKind.MATERIAL,
            title="数学問題集",
            unit_type=UnitType.PAGE,
            estimated_minutes_per_unit=5.0,
        )


def test_material_requires_estimated_minutes_per_unit(
    participant_id: str,
):
    with pytest.raises(ValueError):
        StudyTarget(
            id=1,
            participant_id=participant_id,
            kind=StudyTargetKind.MATERIAL,
            title="数学問題集",
            unit_type=UnitType.PAGE,
            next_position=1,
        )


# =========================================================
# GoalRange
# =========================================================


def test_goal_range_can_be_created():
    goal_range = GoalRange(
        start_position=1,
        end_position=100,
    )

    assert goal_range.start_position == 1
    assert goal_range.end_position == 100


def test_goal_range_rejects_reversed_range():
    with pytest.raises(ValueError):
        GoalRange(
            start_position=100,
            end_position=50,
        )


# =========================================================
# Goal
# =========================================================


def test_goal_can_be_created(goal: Goal):
    assert goal.goal_type == GoalType.TEST
    assert goal.importance == Importance.HIGH
    assert goal.study_target_id == 1


def test_goal_keeps_target_minutes_optional(
    participant_id: str,
):
    goal = Goal(
        id=1,
        participant_id=participant_id,
        study_target_id=2,
        goal_type=GoalType.PERSONAL,
        title="英作文を練習する",
        deadline_at=datetime(
            2026,
            10,
            20,
            18,
            0,
            tzinfo=JST,
        ),
        importance=Importance.MEDIUM,
        target_minutes=None,
    )

    assert goal.target_minutes is None


# =========================================================
# LearningPolicy
# =========================================================


def test_learning_policy_can_be_created(
    learning_policy: LearningPolicy,
):
    assert learning_policy.normal_sessions_per_week == 5
    assert learning_policy.normal_minutes == 30
    assert learning_policy.minimum_sessions_per_week == 3
    assert learning_policy.minimum_minutes == 15


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("normal_minutes", 13),
        ("minimum_minutes", 17),
    ],
)
def test_learning_policy_rejects_non_five_minute_values(
    field_name: str,
    value: int,
):
    kwargs = {
        "study_target_id": 1,
        "purpose": "数学学習",
        "policy_priority": Importance.HIGH,
        "normal_sessions_per_week": 5,
        "normal_minutes": 30,
        "minimum_sessions_per_week": 3,
        "minimum_minutes": 15,
    }

    kwargs[field_name] = value

    with pytest.raises(DomainValidationError):
        LearningPolicy(**kwargs)


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("normal_sessions_per_week", -1),
        ("normal_sessions_per_week", 8),
        ("minimum_sessions_per_week", -1),
        ("minimum_sessions_per_week", 8),
    ],
)
def test_learning_policy_rejects_invalid_session_count(
    field_name: str,
    value: int,
):
    kwargs = {
        "study_target_id": 1,
        "purpose": "数学学習",
        "policy_priority": Importance.HIGH,
        "normal_sessions_per_week": 5,
        "normal_minutes": 30,
        "minimum_sessions_per_week": 3,
        "minimum_minutes": 15,
    }

    kwargs[field_name] = value

    with pytest.raises(DomainValidationError):
        LearningPolicy(**kwargs)


# =========================================================
# AvailableTime
# =========================================================


def test_available_time_can_be_created(
    available_time: AvailableTime,
):
    assert available_time.weekday == 0
    assert available_time.start_minute_of_day == 1080
    assert available_time.end_minute_of_day == 1200


@pytest.mark.parametrize(
    "weekday",
    [-1, 7],
)
def test_available_time_rejects_invalid_weekday(
    weekday: int,
):
    with pytest.raises(ValueError):
        AvailableTime(
            weekday=weekday,
            start_minute_of_day=600,
            end_minute_of_day=720,
        )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (-1, 600),
        (600, 600),
        (700, 600),
        (0, 1441),
    ],
)
def test_available_time_rejects_invalid_interval(
    start: int,
    end: int,
):
    with pytest.raises(ValueError):
        AvailableTime(
            weekday=0,
            start_minute_of_day=start,
            end_minute_of_day=end,
        )


def test_available_time_accepts_full_day_boundary():
    available = AvailableTime(
        weekday=0,
        start_minute_of_day=0,
        end_minute_of_day=1440,
    )

    assert available.start_minute_of_day == 0
    assert available.end_minute_of_day == 1440


# =========================================================
# BusyEvent / ExtraAvailableTime
# =========================================================


def test_busy_event_can_cross_midnight():
    event = BusyEvent(
        start_at=datetime(
            2026,
            10,
            3,
            23,
            0,
            tzinfo=JST,
        ),
        end_at=datetime(
            2026,
            10,
            4,
            1,
            0,
            tzinfo=JST,
        ),
    )

    assert event.start_at < event.end_at


def test_busy_event_rejects_end_before_start():
    with pytest.raises(
        InvalidTimeRangeError,
        match="BusyEvent start_at must be earlier than end_at",
    ):
        BusyEvent(
            start_at=datetime(
                2026,
                10,
                3,
                20,
                0,
                tzinfo=JST,
            ),
            end_at=datetime(
                2026,
                10,
                3,
                19,
                0,
                tzinfo=JST,
            ),
        )


def test_extra_available_time_can_cross_midnight():
    extra = ExtraAvailableTime(
        start_at=datetime(
            2026,
            10,
            3,
            23,
            0,
            tzinfo=JST,
        ),
        end_at=datetime(
            2026,
            10,
            4,
            1,
            0,
            tzinfo=JST,
        ),
    )

    assert extra.start_at < extra.end_at


def test_extra_available_time_rejects_zero_length():
    dt = datetime(
        2026,
        10,
        3,
        20,
        0,
        tzinfo=JST,
    )

    with pytest.raises(
        InvalidTimeRangeError,
        match=(
            "ExtraAvailableTime start_at "
            "must be earlier than end_at"
        ),
    ):
        ExtraAvailableTime(
            start_at=dt,
            end_at=dt,
        )


# =========================================================
# Plan
# =========================================================


def test_plan_can_be_created(plan: Plan):
    assert plan.version_no == 1
    assert plan.effective_from < plan.horizon_end


def test_plan_rejects_horizon_before_effective_from(
    participant_id: str,
):
    effective_from = datetime(
        2026,
        10,
        3,
        10,
        0,
        tzinfo=JST,
    )

    with pytest.raises(
        InvalidTimeRangeError,
        match="effective_from must be earlier than horizon_end",
    ):
        Plan(
            id=1,
            participant_id=participant_id,
            version_no=1,
            created_at=effective_from,
            effective_from=effective_from,
            horizon_end=datetime(
                2026,
                10,
                2,
                0,
                0,
                tzinfo=JST,
            ),
            source_planning_data_version=0,
        )


# =========================================================
# PlanItem
# =========================================================


def test_plan_item_can_be_created(
    plan_item: PlanItem,
):
    assert plan_item.planned_minutes == 30
    assert plan_item.start_at < plan_item.end_at
    assert plan_item.is_cancelled is False


def test_plan_item_rejects_end_before_start():
    with pytest.raises(
        InvalidTimeRangeError,
        match="PlanItem start_at must be earlier than end_at",
    ):
        PlanItem(
            id=1,
            plan_id=1,
            study_target_id=1,
            start_at=datetime(
                2026,
                10,
                3,
                12,
                0,
                tzinfo=JST,
            ),
            end_at=datetime(
                2026,
                10,
                3,
                11,
                0,
                tzinfo=JST,
            ),
            origin=PlanItemOrigin.SYSTEM_GENERATED,
            planned_minutes=30,
        )


def test_plan_item_rejects_cross_midnight():
    with pytest.raises(
        InvalidTimeRangeError,
        match="PlanItem must fit within one JST calendar day",
    ):
        PlanItem(
            id=1,
            plan_id=1,
            study_target_id=1,
            start_at=datetime(
                2026,
                10,
                3,
                23,
                30,
                tzinfo=JST,
            ),
            end_at=datetime(
                2026,
                10,
                4,
                0,
                30,
                tzinfo=JST,
            ),
            origin=PlanItemOrigin.SYSTEM_GENERATED,
            planned_minutes=60,
        )


def test_plan_item_allows_item_ending_at_midnight():
    item = PlanItem(
        id=1,
        plan_id=1,
        study_target_id=1,
        start_at=datetime(
            2026,
            10,
            3,
            23,
            30,
            tzinfo=JST,
        ),
        end_at=datetime(
            2026,
            10,
            4,
            0,
            0,
            tzinfo=JST,
        ),
        origin=PlanItemOrigin.SYSTEM_GENERATED,
        planned_minutes=30,
    )

    assert item.planned_minutes == 30


# =========================================================
# StudyResult
# =========================================================


@pytest.mark.parametrize(
    "status",
    [
        StudyResultStatus.COMPLETED,
        StudyResultStatus.PARTIAL,
        StudyResultStatus.NOT_DONE,
    ],
)
def test_study_result_accepts_defined_statuses(
    participant_id: str,
    status: StudyResultStatus,
):
    result = StudyResult(
        id=1,
        participant_id=participant_id,
        plan_item_id=1,
        study_target_id=1,
        status=status,
    )

    assert result.status == status


def test_study_result_status_does_not_include_unrecorded():
    values = {
        status.value
        for status in StudyResultStatus
    }

    assert "UNRECORDED" not in values


def test_study_result_status_does_not_include_cancelled():
    values = {
        status.value
        for status in StudyResultStatus
    }

    assert "CANCELLED" not in values


# =========================================================
# PlanGenerationAttempt
# =========================================================


def test_plan_generation_attempt_can_be_created(
    plan_attempt: PlanGenerationAttempt,
):
    assert (
        plan_attempt.operation_type
        == PlanOperationType.INITIAL
    )
    assert plan_attempt.status == AttemptStatus.IN_PROGRESS
    assert plan_attempt.stage == AttemptStage.FEASIBILITY


@pytest.mark.parametrize(
    "operation_type",
    [
        PlanOperationType.INITIAL,
        PlanOperationType.REPLAN_NOW,
        PlanOperationType.REPLAN_TOMORROW,
    ],
)
def test_plan_generation_attempt_accepts_operation_types(
    participant_id: str,
    jst_datetime: datetime,
    operation_type: PlanOperationType,
):
    attempt = PlanGenerationAttempt(
        id=1,
        participant_id=participant_id,
        operation_type=operation_type,
        source_planning_data_version=0,
        status=AttemptStatus.IN_PROGRESS,
        stage=AttemptStage.FEASIBILITY,
        started_at=jst_datetime,
        updated_at=jst_datetime,
    )

    assert attempt.operation_type == operation_type