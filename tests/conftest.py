from datetime import datetime

import pytest

from domain.enums import (
    AttemptStage,
    AttemptStatus,
    GoalType,
    Importance,
    PlanItemOrigin,
    PlanOperationType,
    StudyTargetKind,
    UnitType,
)
from domain.models import (
    AvailableTime,
    Goal,
    LearningPolicy,
    Plan,
    PlanGenerationAttempt,
    PlanItem,
    StudyTarget,
)
from domain.time_rules import JST


@pytest.fixture
def participant_id() -> str:
    return "participant-test-001"


@pytest.fixture
def jst_datetime() -> datetime:
    return datetime(
        2026,
        10,
        3,
        10,
        0,
        tzinfo=JST,
    )


@pytest.fixture
def material_target(participant_id: str) -> StudyTarget:
    return StudyTarget(
        id=1,
        participant_id=participant_id,
        kind=StudyTargetKind.MATERIAL,
        title="数学問題集",
        unit_type=UnitType.PAGE,
        next_position=1,
        estimated_minutes_per_unit=5.0,
    )


@pytest.fixture
def theme_target(participant_id: str) -> StudyTarget:
    return StudyTarget(
        id=2,
        participant_id=participant_id,
        kind=StudyTargetKind.THEME,
        title="英作文練習",
        note="自由英作文",
    )


@pytest.fixture
def goal(
    participant_id: str,
    jst_datetime: datetime,
) -> Goal:
    return Goal(
        id=1,
        participant_id=participant_id,
        study_target_id=1,
        goal_type=GoalType.TEST,
        title="数学テスト",
        deadline_at=jst_datetime,
        importance=Importance.HIGH,
    )


@pytest.fixture
def learning_policy() -> LearningPolicy:
    return LearningPolicy(
        study_target_id=1,
        purpose="数学の継続学習",
        policy_priority=Importance.HIGH,
        normal_sessions_per_week=5,
        normal_minutes=30,
        minimum_sessions_per_week=3,
        minimum_minutes=15,
    )


@pytest.fixture
def available_time() -> AvailableTime:
    return AvailableTime(
        weekday=0,
        start_minute_of_day=18 * 60,
        end_minute_of_day=20 * 60,
    )


@pytest.fixture
def plan(
    participant_id: str,
    jst_datetime: datetime,
) -> Plan:
    return Plan(
        id=1,
        participant_id=participant_id,
        version_no=1,
        created_at=jst_datetime,
        effective_from=jst_datetime,
        horizon_end=datetime(
            2026,
            10,
            10,
            0,
            0,
            tzinfo=JST,
        ),
        source_planning_data_version=0,
    )


@pytest.fixture
def plan_item(
    jst_datetime: datetime,
) -> PlanItem:
    return PlanItem(
        id=1,
        plan_id=1,
        study_target_id=1,
        start_at=jst_datetime,
        end_at=datetime(
            2026,
            10,
            3,
            10,
            30,
            tzinfo=JST,
        ),
        origin=PlanItemOrigin.SYSTEM_GENERATED,
        planned_minutes=30,
        range_start=1,
        range_end=6,
    )


@pytest.fixture
def plan_attempt(
    participant_id: str,
    jst_datetime: datetime,
) -> PlanGenerationAttempt:
    return PlanGenerationAttempt(
        id=1,
        participant_id=participant_id,
        operation_type=PlanOperationType.INITIAL,
        source_planning_data_version=0,
        status=AttemptStatus.IN_PROGRESS,
        stage=AttemptStage.FEASIBILITY,
        started_at=jst_datetime,
        updated_at=jst_datetime,
    )