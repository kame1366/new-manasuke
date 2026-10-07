from datetime import datetime

from domain.enums import (
    GoalType,
    Importance,
    PlanItemOrigin,
    StudyTargetKind,
    UnitType,
)
from domain.models import (
    AvailableTime,
    BusyEvent,
    Goal,
    GoalRange,
    Plan,
    PlanItem,
    StudyTarget,
    StudyTargetRange,
)
from domain.time_rules import JST
from planning.plan_validator import (
    MinimumPolicyRequirement,
    PlanValidator,
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


def plan(
    *,
    horizon_day: int = 16,
    source_version: int = 1,
) -> Plan:
    return Plan(
        id=1,
        participant_id="participant-a",
        version_no=1,
        created_at=dt(
            9,
            12,
        ),
        effective_from=dt(
            9,
            18,
        ),
        horizon_end=dt(
            horizon_day,
            0,
        ),
        source_planning_data_version=(
            source_version
        ),
    )


def material_target(
    *,
    next_position: int = 1,
) -> StudyTarget:
    return StudyTarget(
        id=1,
        participant_id="participant-a",
        kind=StudyTargetKind.MATERIAL,
        title="数学問題集",
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


def theme_target() -> StudyTarget:
    return StudyTarget(
        id=2,
        participant_id="participant-a",
        kind=StudyTargetKind.THEME,
        title="英作文",
    )


def material_item(
    *,
    item_id: int,
    start_at: datetime,
    end_at: datetime,
    range_start: int,
    range_end: int,
    origin=(
        PlanItemOrigin.SYSTEM_GENERATED
    ),
) -> PlanItem:
    return PlanItem(
        id=item_id,
        plan_id=1,
        study_target_id=1,
        start_at=start_at,
        end_at=end_at,
        origin=origin,
        planned_minutes=int(
            (
                end_at
                - start_at
            ).total_seconds()
            // 60
        ),
        range_start=range_start,
        range_end=range_end,
    )


def theme_item(
    *,
    item_id: int,
    start_at: datetime,
    end_at: datetime,
) -> PlanItem:
    return PlanItem(
        id=item_id,
        plan_id=1,
        study_target_id=2,
        start_at=start_at,
        end_at=end_at,
        origin=(
            PlanItemOrigin.SYSTEM_GENERATED
        ),
        planned_minutes=int(
            (
                end_at
                - start_at
            ).total_seconds()
            // 60
        ),
    )


def weekly_availability():
    return [
        # Friday
        AvailableTime(
            weekday=4,
            start_minute_of_day=(
                18 * 60
            ),
            end_minute_of_day=(
                21 * 60
            ),
        ),
        # Saturday
        AvailableTime(
            weekday=5,
            start_minute_of_day=(
                18 * 60
            ),
            end_minute_of_day=(
                21 * 60
            ),
        ),
    ]


def validate(
    *,
    plan_value=None,
    items=None,
    targets=None,
    goals=None,
    strict_goal_ids=None,
    busy_events=None,
    minimum_requirements=(),
    theme_completed=None,
):
    validator = PlanValidator()

    return validator.validate(
        plan=(
            plan_value
            or plan()
        ),
        plan_items=(
            items
            if items is not None
            else []
        ),
        study_targets=(
            targets
            if targets is not None
            else []
        ),
        goals=(
            goals
            if goals is not None
            else []
        ),
        strict_goal_ids=(
            strict_goal_ids
            if strict_goal_ids
            is not None
            else set()
        ),
        weekly_available_times=(
            weekly_availability()
        ),
        extra_available_times=[],
        busy_events=(
            busy_events
            if busy_events is not None
            else []
        ),
        minimum_requirements=(
            minimum_requirements
        ),
        theme_completed_minutes_by_target=(
            theme_completed
        ),
    )


def test_valid_material_plan_passes():
    result = validate(
        items=[
            material_item(
                item_id=1,
                start_at=dt(
                    9,
                    18,
                ),
                end_at=dt(
                    9,
                    18,
                    30,
                ),
                range_start=1,
                range_end=6,
            )
        ],
        targets=[
            material_target()
        ],
    )

    assert result.is_valid is True
    assert result.issues == ()


def test_invalid_horizon_is_rejected():
    result = validate(
        plan_value=plan(
            horizon_day=15,
        ),
    )

    assert result.is_valid is False

    assert (
        "INVALID_PLAN_HORIZON"
        in result.issue_codes
    )


def test_plan_item_outside_availability_is_rejected():
    result = validate(
        items=[
            material_item(
                item_id=1,
                start_at=dt(
                    9,
                    15,
                ),
                end_at=dt(
                    9,
                    15,
                    30,
                ),
                range_start=1,
                range_end=6,
            )
        ],
        targets=[
            material_target()
        ],
    )

    assert result.is_valid is False

    assert (
        "PLAN_ITEM_OUTSIDE_FREE_SLOT"
        in result.issue_codes
    )


def test_busy_event_invalidates_plan_item():
    item = material_item(
        item_id=1,
        start_at=dt(
            9,
            18,
        ),
        end_at=dt(
            9,
            18,
            30,
        ),
        range_start=1,
        range_end=6,
    )

    result = validate(
        items=[
            item
        ],
        targets=[
            material_target()
        ],
        busy_events=[
            BusyEvent(
                start_at=dt(
                    9,
                    18,
                    15,
                ),
                end_at=dt(
                    9,
                    18,
                    20,
                ),
            )
        ],
    )

    assert result.is_valid is False

    assert (
        "PLAN_ITEM_OUTSIDE_FREE_SLOT"
        in result.issue_codes
    )


def test_overlapping_plan_items_are_rejected():
    result = validate(
        items=[
            theme_item(
                item_id=1,
                start_at=dt(
                    9,
                    18,
                ),
                end_at=dt(
                    9,
                    18,
                    30,
                ),
            ),
            theme_item(
                item_id=2,
                start_at=dt(
                    9,
                    18,
                    20,
                ),
                end_at=dt(
                    9,
                    18,
                    50,
                ),
            ),
        ],
        targets=[
            theme_target()
        ],
    )

    assert result.is_valid is False

    assert (
        "PLAN_ITEM_OVERLAP"
        in result.issue_codes
    )


def test_material_illegal_jump_is_rejected():
    result = validate(
        items=[
            material_item(
                item_id=1,
                start_at=dt(
                    9,
                    18,
                ),
                end_at=dt(
                    9,
                    18,
                    30,
                ),
                range_start=5,
                range_end=10,
            )
        ],
        targets=[
            material_target(
                next_position=1
            )
        ],
    )

    assert result.is_valid is False

    assert (
        "MATERIAL_ORDER_VIOLATION"
        in result.issue_codes
    )


def test_material_progress_allows_next_range():
    result = validate(
        items=[
            material_item(
                item_id=1,
                start_at=dt(
                    9,
                    18,
                ),
                end_at=dt(
                    9,
                    18,
                    30,
                ),
                range_start=10,
                range_end=15,
            )
        ],
        targets=[
            material_target(
                next_position=10
            )
        ],
    )

    assert result.is_valid is True


def test_user_modified_reserved_work_must_respect_precedence():
    result = validate(
        items=[
            # USER_MODIFIED p.5-8が時間的に先
            material_item(
                item_id=2,
                start_at=dt(
                    9,
                    18,
                ),
                end_at=dt(
                    9,
                    18,
                    30,
                ),
                range_start=5,
                range_end=8,
                origin=(
                    PlanItemOrigin.USER_MODIFIED
                ),
            ),

            # prerequisite p.1-4が後
            material_item(
                item_id=1,
                start_at=dt(
                    9,
                    19,
                ),
                end_at=dt(
                    9,
                    19,
                    30,
                ),
                range_start=1,
                range_end=4,
            ),
        ],
        targets=[
            material_target()
        ],
    )

    assert result.is_valid is False

    assert (
        "MATERIAL_ORDER_VIOLATION"
        in result.issue_codes
    )


def test_strict_material_goal_must_be_covered_before_deadline():
    goal = Goal(
        id=1,
        participant_id="participant-a",
        study_target_id=1,
        goal_type=GoalType.TEST,
        title="数学テスト",
        deadline_at=dt(
            9,
            20,
        ),
        importance=Importance.HIGH,
        ranges=[
            GoalRange(
                start_position=1,
                end_position=10,
            )
        ],
    )

    result = validate(
        items=[
            material_item(
                item_id=1,
                start_at=dt(
                    9,
                    18,
                ),
                end_at=dt(
                    9,
                    18,
                    30,
                ),
                range_start=1,
                range_end=6,
            )
        ],
        targets=[
            material_target()
        ],
        goals=[
            goal
        ],
        strict_goal_ids={
            1
        },
    )

    assert result.is_valid is False

    assert (
        "STRICT_MATERIAL_DEADLINE_UNCOVERED"
        in result.issue_codes
    )


def test_strict_material_goal_passes_when_covered():
    goal = Goal(
        id=1,
        participant_id="participant-a",
        study_target_id=1,
        goal_type=GoalType.TEST,
        title="数学テスト",
        deadline_at=dt(
            9,
            20,
        ),
        importance=Importance.HIGH,
        ranges=[
            GoalRange(
                start_position=1,
                end_position=10,
            )
        ],
    )

    result = validate(
        items=[
            material_item(
                item_id=1,
                start_at=dt(
                    9,
                    18,
                ),
                end_at=dt(
                    9,
                    19,
                ),
                range_start=1,
                range_end=10,
            )
        ],
        targets=[
            material_target()
        ],
        goals=[
            goal
        ],
        strict_goal_ids={
            1
        },
    )

    assert result.is_valid is True


def test_goal_after_plan_horizon_is_not_required_to_finish_now():
    goal = Goal(
        id=1,
        participant_id="participant-a",
        study_target_id=1,
        goal_type=GoalType.TEST,
        title="将来の数学テスト",
        deadline_at=dt(
            20,
            20,
        ),
        importance=Importance.HIGH,
        ranges=[
            GoalRange(
                start_position=1,
                end_position=100,
            )
        ],
    )

    result = validate(
        items=[
            material_item(
                item_id=1,
                start_at=dt(
                    9,
                    18,
                ),
                end_at=dt(
                    9,
                    18,
                    30,
                ),
                range_start=1,
                range_end=6,
            )
        ],
        targets=[
            material_target()
        ],
        goals=[
            goal
        ],
        strict_goal_ids={
            1
        },
    )

    assert result.is_valid is True


def test_theme_deadline_requires_enough_minutes():
    goal = Goal(
        id=1,
        participant_id="participant-a",
        study_target_id=2,
        goal_type=GoalType.PERSONAL,
        title="英作文60分",
        deadline_at=dt(
            9,
            20,
        ),
        importance=Importance.HIGH,
        target_minutes=60,
    )

    result = validate(
        items=[
            theme_item(
                item_id=1,
                start_at=dt(
                    9,
                    18,
                ),
                end_at=dt(
                    9,
                    18,
                    30,
                ),
            )
        ],
        targets=[
            theme_target()
        ],
        goals=[
            goal
        ],
        strict_goal_ids={
            1
        },
    )

    assert result.is_valid is False

    assert (
        "STRICT_THEME_DEADLINE_UNCOVERED"
        in result.issue_codes
    )


def test_theme_completed_minutes_reduce_remaining_requirement():
    goal = Goal(
        id=1,
        participant_id="participant-a",
        study_target_id=2,
        goal_type=GoalType.PERSONAL,
        title="英作文60分",
        deadline_at=dt(
            9,
            20,
        ),
        importance=Importance.HIGH,
        target_minutes=60,
    )

    result = validate(
        items=[
            theme_item(
                item_id=1,
                start_at=dt(
                    9,
                    18,
                ),
                end_at=dt(
                    9,
                    18,
                    30,
                ),
            )
        ],
        targets=[
            theme_target()
        ],
        goals=[
            goal
        ],
        strict_goal_ids={
            1
        },
        theme_completed={
            2: 30
        },
    )

    assert result.is_valid is True


def test_minimum_policy_requires_distinct_study_days():
    result = validate(
        items=[
            theme_item(
                item_id=1,
                start_at=dt(
                    9,
                    18,
                ),
                end_at=dt(
                    9,
                    18,
                    30,
                ),
            ),
            theme_item(
                item_id=2,
                start_at=dt(
                    10,
                    18,
                ),
                end_at=dt(
                    10,
                    18,
                    30,
                ),
            ),
        ],
        targets=[
            theme_target()
        ],
        minimum_requirements=[
            MinimumPolicyRequirement(
                study_target_id=2,
                required_distinct_days=2,
                minimum_minutes_per_day=30,
            )
        ],
    )

    assert result.is_valid is True


def test_minimum_policy_fails_when_only_one_day_qualifies():
    result = validate(
        items=[
            theme_item(
                item_id=1,
                start_at=dt(
                    9,
                    18,
                ),
                end_at=dt(
                    9,
                    18,
                    30,
                ),
            )
        ],
        targets=[
            theme_target()
        ],
        minimum_requirements=[
            MinimumPolicyRequirement(
                study_target_id=2,
                required_distinct_days=2,
                minimum_minutes_per_day=30,
            )
        ],
    )

    assert result.is_valid is False

    assert (
        "MINIMUM_POLICY_UNSATISFIED"
        in result.issue_codes
    )


def test_cancelled_item_does_not_participate_in_plan_validation():
    cancelled = PlanItem(
        id=1,
        plan_id=1,
        study_target_id=1,
        start_at=dt(
            9,
            15,
        ),
        end_at=dt(
            9,
            15,
            30,
        ),
        origin=(
            PlanItemOrigin.SYSTEM_GENERATED
        ),
        planned_minutes=30,
        range_start=50,
        range_end=55,
        is_cancelled=True,
        cancelled_at=dt(
            9,
            14,
        ),
    )

    result = validate(
        items=[
            cancelled
        ],
        targets=[
            material_target()
        ],
    )

    assert result.is_valid is True