from datetime import datetime

from domain.enums import (
    GoalType,
    Importance,
    StudyTargetKind,
)
from domain.models import (
    AvailableTime,
    BusyEvent,
    ExtraAvailableTime,
    Goal,
)
from domain.time_rules import JST
from planning.feasibility_analyzer import (
    DeadlineFeasibilityAnalyzer,
    MinimumReservation,
)
from planning.work_segment_builder import (
    WorkSegment,
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


def goal(
    *,
    goal_id: int,
    target_id: int,
    deadline_day: int,
    deadline_hour: int = 23,
) -> Goal:
    return Goal(
        id=goal_id,
        participant_id="participant-a",
        study_target_id=target_id,
        goal_type=GoalType.TEST,
        title=f"Goal {goal_id}",
        deadline_at=dt(
            deadline_day,
            deadline_hour,
        ),
        importance=Importance.HIGH,
    )


def material_segment(
    *,
    target_id: int,
    start: int,
    end: int,
    minutes: float,
    required_by: tuple[int, ...],
    direct: tuple[int, ...] | None = None,
) -> WorkSegment:
    return WorkSegment(
        study_target_id=target_id,
        kind=StudyTargetKind.MATERIAL,
        range_start=start,
        range_end=end,
        estimated_minutes=minutes,
        required_by_goal_ids=(
            required_by
        ),
        direct_goal_ids=(
            direct
            if direct is not None
            else required_by
        ),
    )


def test_single_goal_is_feasible_when_capacity_is_enough():
    analyzer = (
        DeadlineFeasibilityAnalyzer()
    )

    result = analyzer.analyze(
        effective_from=dt(
            7,
            0,
        ),
        goals=[
            goal(
                goal_id=1,
                target_id=1,
                deadline_day=8,
            )
        ],
        work_segments=[
            material_segment(
                target_id=1,
                start=1,
                end=12,
                minutes=60,
                required_by=(1,),
            )
        ],
        # 2026-10-07 = Wednesday = 2
        weekly_available_times=[
            AvailableTime(
                weekday=2,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    20 * 60
                ),
            )
        ],
        extra_available_times=[],
        busy_events=[],
        fixed_plan_items=[],
    )

    assert (
        result.strict_set_feasible
        is True
    )

    assert (
        result.normalized_required_minutes
        == 60
    )

    assert (
        result.total_projected_capacity_minutes
        == 120
    )

    assert (
        result.aggregate_shortage_minutes
        == 0
    )


def test_single_goal_reports_shortage():
    analyzer = (
        DeadlineFeasibilityAnalyzer()
    )

    result = analyzer.analyze(
        effective_from=dt(
            7,
            0,
        ),
        goals=[
            goal(
                goal_id=1,
                target_id=1,
                deadline_day=8,
            )
        ],
        work_segments=[
            material_segment(
                target_id=1,
                start=1,
                end=30,
                minutes=150,
                required_by=(1,),
            )
        ],
        weekly_available_times=[
            AvailableTime(
                weekday=2,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    20 * 60
                ),
            )
        ],
        extra_available_times=[],
        busy_events=[],
        fixed_plan_items=[],
    )

    assert (
        result.strict_set_feasible
        is False
    )

    assert (
        result.aggregate_shortage_minutes
        == 30
    )

    assert (
        result.deadline_snapshots[0]
        .cumulative_shortage_minutes
        == 30
    )


def test_shared_work_counts_once_in_aggregate_requirement():
    analyzer = (
        DeadlineFeasibilityAnalyzer()
    )

    result = analyzer.analyze(
        effective_from=dt(
            7,
            0,
        ),
        goals=[
            goal(
                goal_id=1,
                target_id=1,
                deadline_day=8,
            ),
            goal(
                goal_id=2,
                target_id=1,
                deadline_day=8,
            ),
        ],
        work_segments=[
            material_segment(
                target_id=1,
                start=1,
                end=12,
                minutes=60,
                required_by=(
                    1,
                    2,
                ),
            )
        ],
        weekly_available_times=[
            AvailableTime(
                weekday=2,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    19 * 60
                ),
            )
        ],
        extra_available_times=[],
        busy_events=[],
        fixed_plan_items=[],
    )

    # 60分のWorkが2 Goalに貢献するが、
    # physical requirementは120分ではない。
    assert (
        result.normalized_required_minutes
        == 60
    )

    assert (
        result.strict_set_feasible
        is True
    )

    goal_results = {
        item.goal_id: item
        for item
        in result.goal_results
    }

    # 各Goalへのcontributionは60分まで。
    assert (
        goal_results[1]
        .estimated_required_minutes
        == 60
    )

    assert (
        goal_results[2]
        .estimated_required_minutes
        == 60
    )


def test_two_study_targets_compete_for_same_capacity():
    analyzer = (
        DeadlineFeasibilityAnalyzer()
    )

    result = analyzer.analyze(
        effective_from=dt(
            7,
            0,
        ),
        goals=[
            goal(
                goal_id=1,
                target_id=1,
                deadline_day=8,
            ),
            goal(
                goal_id=2,
                target_id=2,
                deadline_day=8,
            ),
        ],
        work_segments=[
            material_segment(
                target_id=1,
                start=1,
                end=12,
                minutes=60,
                required_by=(1,),
            ),
            material_segment(
                target_id=2,
                start=1,
                end=12,
                minutes=60,
                required_by=(2,),
            ),
        ],
        weekly_available_times=[
            AvailableTime(
                weekday=2,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    19 * 60
                ),
            )
        ],
        extra_available_times=[],
        busy_events=[],
        fixed_plan_items=[],
    )

    assert (
        result.normalized_required_minutes
        == 120
    )

    assert (
        result.total_projected_capacity_minutes
        == 60
    )

    assert (
        result.aggregate_shortage_minutes
        == 60
    )

    assert (
        result.strict_set_feasible
        is False
    )


def test_requirements_are_cumulative_by_deadline():
    analyzer = (
        DeadlineFeasibilityAnalyzer()
    )

    result = analyzer.analyze(
        effective_from=dt(
            7,
            0,
        ),
        goals=[
            goal(
                goal_id=1,
                target_id=1,
                deadline_day=8,
                # 10/8 18:00開始の空き時間は、
                # deadlineより後なので含まれない。
                deadline_hour=18,
            ),
            goal(
                goal_id=2,
                target_id=2,
                deadline_day=9,
                deadline_hour=23,
            ),
        ],
        work_segments=[
            material_segment(
                target_id=1,
                start=1,
                end=12,
                minutes=60,
                required_by=(1,),
            ),
            material_segment(
                target_id=2,
                start=1,
                end=12,
                minutes=60,
                required_by=(2,),
            ),
        ],
        weekly_available_times=[
            # Wednesday 10/7
            AvailableTime(
                weekday=2,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    19 * 60
                ),
            ),
            # Thursday 10/8
            AvailableTime(
                weekday=3,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    19 * 60
                ),
            ),
        ],
        extra_available_times=[],
        busy_events=[],
        fixed_plan_items=[],
    )

    assert len(
        result.deadline_snapshots
    ) == 2

    first = (
        result.deadline_snapshots[0]
    )

    second = (
        result.deadline_snapshots[1]
    )

    # Goal 1は10/8 18:00 deadline。
    #
    # 利用できるのは、
    # 10/7(水) 18:00〜19:00
    # の60分のみ。
    #
    # 10/8(木)のAvailableTimeは18:00開始なので、
    # deadline以降となり含まれない。
    assert (
        first.cumulative_required_minutes
        == 60
    )

    assert (
        first.cumulative_available_minutes
        == 60
    )

    assert (
        first.cumulative_shortage_minutes
        == 0
    )

    assert (
        first.feasible
        is True
    )

    # Goal 2は10/9 23:00 deadline。
    #
    # この時点では、
    # 10/7(水) 60分
    # +
    # 10/8(木) 60分
    # =
    # 120分
    #
    # が利用可能。
    #
    # 必要WorkもGoal 1 + Goal 2で
    # cumulative 120分。
    assert (
        second.cumulative_required_minutes
        == 120
    )

    assert (
        second.cumulative_available_minutes
        == 120
    )

    assert (
        second.cumulative_shortage_minutes
        == 0
    )

    assert (
        second.feasible
        is True
    )

    assert (
        result.strict_set_feasible
        is True
    )

    assert (
        result.normalized_required_minutes
        == 120
    )

    assert (
        result.total_projected_capacity_minutes
        == 120
    )

    assert (
        result.aggregate_shortage_minutes
        == 0
    )


def test_shared_work_uses_earliest_relevant_deadline():
    analyzer = (
        DeadlineFeasibilityAnalyzer()
    )

    result = analyzer.analyze(
        effective_from=dt(
            7,
            0,
        ),
        goals=[
            goal(
                goal_id=1,
                target_id=1,
                deadline_day=8,
            ),
            goal(
                goal_id=2,
                target_id=1,
                deadline_day=9,
            ),
        ],
        work_segments=[
            material_segment(
                target_id=1,
                start=1,
                end=12,
                minutes=60,
                required_by=(
                    1,
                    2,
                ),
            )
        ],
        weekly_available_times=[
            AvailableTime(
                weekday=2,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    19 * 60
                ),
            ),
            AvailableTime(
                weekday=3,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    19 * 60
                ),
            ),
        ],
        extra_available_times=[],
        busy_events=[],
        fixed_plan_items=[],
    )

    # shared workはGoal 1にも必要なので
    # 早い10/8 deadlineまでに60分必要。
    first = (
        result.deadline_snapshots[0]
    )

    assert (
        first.cumulative_required_minutes
        == 60
    )


def test_busy_event_reduces_projected_capacity():
    analyzer = (
        DeadlineFeasibilityAnalyzer()
    )

    result = analyzer.analyze(
        effective_from=dt(
            7,
            0,
        ),
        goals=[
            goal(
                goal_id=1,
                target_id=1,
                deadline_day=8,
            )
        ],
        work_segments=[
            material_segment(
                target_id=1,
                start=1,
                end=12,
                minutes=60,
                required_by=(1,),
            )
        ],
        weekly_available_times=[
            AvailableTime(
                weekday=2,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    20 * 60
                ),
            )
        ],
        extra_available_times=[],
        busy_events=[
            BusyEvent(
                start_at=dt(
                    7,
                    19,
                ),
                end_at=dt(
                    7,
                    20,
                ),
            )
        ],
        fixed_plan_items=[],
    )

    assert (
        result.total_projected_capacity_minutes
        == 60
    )

    assert (
        result.strict_set_feasible
        is True
    )


def test_extra_available_time_increases_projected_capacity():
    analyzer = (
        DeadlineFeasibilityAnalyzer()
    )

    result = analyzer.analyze(
        effective_from=dt(
            7,
            0,
        ),
        goals=[
            goal(
                goal_id=1,
                target_id=1,
                deadline_day=8,
            )
        ],
        work_segments=[
            material_segment(
                target_id=1,
                start=1,
                end=18,
                minutes=90,
                required_by=(1,),
            )
        ],
        weekly_available_times=[
            AvailableTime(
                weekday=2,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    19 * 60
                ),
            )
        ],
        extra_available_times=[
            ExtraAvailableTime(
                start_at=dt(
                    7,
                    20,
                ),
                end_at=dt(
                    7,
                    20,
                    30,
                ),
            )
        ],
        busy_events=[],
        fixed_plan_items=[],
    )

    assert (
        result.total_projected_capacity_minutes
        == 90
    )

    assert (
        result.strict_set_feasible
        is True
    )


def test_minimum_reservation_consumes_capacity():
    analyzer = (
        DeadlineFeasibilityAnalyzer()
    )

    result = analyzer.analyze(
        effective_from=dt(
            7,
            0,
        ),
        goals=[
            goal(
                goal_id=1,
                target_id=1,
                deadline_day=8,
            )
        ],
        work_segments=[
            material_segment(
                target_id=1,
                start=1,
                end=12,
                minutes=60,
                required_by=(1,),
            )
        ],
        weekly_available_times=[
            AvailableTime(
                weekday=2,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    19 * 60
                ),
            )
        ],
        extra_available_times=[],
        busy_events=[],
        fixed_plan_items=[],
        minimum_reservations=[
            MinimumReservation(
                deadline_at=dt(
                    8,
                    23,
                ),
                minutes=30,
            )
        ],
    )

    assert (
        result.normalized_required_minutes
        == 90
    )

    assert (
        result.aggregate_shortage_minutes
        == 30
    )

    assert (
        result.strict_set_feasible
        is False
    )

    goal_result = (
        result.goal_results[0]
    )

    # Goal workそのものは60分。
    assert (
        goal_result
        .estimated_required_minutes
        == 60
    )

    # ただしminimum 30分ともcapacity競合する。
    assert (
        goal_result
        .individual_shortage_minutes
        == 30
    )


def test_strict_subset_excludes_best_effort_goal_from_hard_requirement():
    analyzer = (
        DeadlineFeasibilityAnalyzer()
    )

    result = analyzer.analyze(
        effective_from=dt(
            7,
            0,
        ),
        goals=[
            goal(
                goal_id=1,
                target_id=1,
                deadline_day=8,
            ),
            goal(
                goal_id=2,
                target_id=2,
                deadline_day=8,
            ),
        ],
        work_segments=[
            material_segment(
                target_id=1,
                start=1,
                end=12,
                minutes=60,
                required_by=(1,),
            ),
            material_segment(
                target_id=2,
                start=1,
                end=12,
                minutes=60,
                required_by=(2,),
            ),
        ],
        weekly_available_times=[
            AvailableTime(
                weekday=2,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    19 * 60
                ),
            )
        ],
        extra_available_times=[],
        busy_events=[],
        fixed_plan_items=[],
        # Goal 2はBEST_EFFORT扱いを想定。
        strict_goal_ids={
            1,
        },
    )

    assert (
        result.normalized_required_minutes
        == 60
    )

    assert (
        result.strict_set_feasible
        is True
    )


def test_goal_deadline_before_effective_from_has_zero_capacity():
    analyzer = (
        DeadlineFeasibilityAnalyzer()
    )

    result = analyzer.analyze(
        effective_from=dt(
            8,
            12,
        ),
        goals=[
            goal(
                goal_id=1,
                target_id=1,
                deadline_day=8,
                deadline_hour=10,
            )
        ],
        work_segments=[
            material_segment(
                target_id=1,
                start=1,
                end=2,
                minutes=10,
                required_by=(1,),
            )
        ],
        weekly_available_times=[],
        extra_available_times=[],
        busy_events=[],
        fixed_plan_items=[],
    )

    assert (
        result.total_projected_capacity_minutes
        == 0
    )

    assert (
        result.aggregate_shortage_minutes
        == 10
    )

    assert (
        result.strict_set_feasible
        is False
    )


def test_no_strict_goals_produces_empty_hard_snapshot():
    analyzer = (
        DeadlineFeasibilityAnalyzer()
    )

    result = analyzer.analyze(
        effective_from=dt(
            7,
            0,
        ),
        goals=[
            goal(
                goal_id=1,
                target_id=1,
                deadline_day=8,
            )
        ],
        work_segments=[
            material_segment(
                target_id=1,
                start=1,
                end=12,
                minutes=60,
                required_by=(1,),
            )
        ],
        weekly_available_times=[],
        extra_available_times=[],
        busy_events=[],
        fixed_plan_items=[],
        strict_goal_ids=set(),
    )

    assert (
        result.deadline_snapshots
        == ()
    )

    assert (
        result.normalized_required_minutes
        == 0
    )

    assert (
        result.strict_set_feasible
        is True
    )