from dataclasses import dataclass, field
from datetime import datetime, time, timedelta


from domain.enums import (
    StudyTargetKind,
    UnitType,
    GoalType,
    Importance,
    StudyResultStatus,
    PlanOperationType,
    AttemptStatus,
    AttemptStage,
    PlanItemOrigin,
)
from domain.errors import DomainValidationError, InvalidTimeRangeError, InvalidMaterialRangeError
from domain.time_rules import to_jst, ensure_aware
from domain.time_rules import ensure_aware


@dataclass(frozen=True)
class StudyTargetRange:
    sequence_no: int
    start_position: int
    end_position: int

    def __post_init__(self):
        if self.sequence_no < 0:
            raise ValueError("sequence_no must be non-negative")

        if self.start_position > self.end_position:
            raise ValueError(
                "start_position must be <= end_position"
            )


@dataclass
class StudyTarget:
    id: int
    participant_id: str
    kind: StudyTargetKind
    title: str

    unit_type: UnitType | None = None
    next_position: int | None = None
    estimated_minutes_per_unit: float | None = None
    note: str | None = None

    ranges: list[StudyTargetRange] = field(default_factory=list)

    def __post_init__(self):
        if not self.title.strip():
            raise ValueError("title must not be empty")

        if self.kind == StudyTargetKind.MATERIAL:
            if self.unit_type is None:
                raise ValueError(
                    "MATERIAL requires unit_type"
                )

            if self.next_position is None:
                raise ValueError(
                    "MATERIAL requires next_position"
                )

            if self.estimated_minutes_per_unit is None:
                raise ValueError(
                    "MATERIAL requires estimated_minutes_per_unit"
                )


@dataclass(frozen=True)
class GoalRange:
    start_position: int
    end_position: int

    def __post_init__(self):
        if self.start_position > self.end_position:
            raise ValueError(
                "start_position must be <= end_position"
            )


@dataclass
class Goal:
    id: int
    participant_id: str
    study_target_id: int
    goal_type: GoalType
    title: str
    deadline_at: datetime
    importance: Importance

    target_minutes: int | None = None
    note: str | None = None
    ranges: list[GoalRange] = field(default_factory=list)


@dataclass
class LearningPolicy:
    study_target_id: int
    purpose: str
    policy_priority: Importance
    normal_sessions_per_week: int
    normal_minutes: int
    minimum_sessions_per_week: int
    minimum_minutes: int

    def __post_init__(self) -> None:
        if not self.purpose.strip():
            raise DomainValidationError(
                "purpose must not be empty"
            )

        if not 0 <= self.normal_sessions_per_week <= 7:
            raise DomainValidationError(
                "normal_sessions_per_week must be between 0 and 7"
            )

        if not 0 <= self.minimum_sessions_per_week <= 7:
            raise DomainValidationError(
                "minimum_sessions_per_week must be between 0 and 7"
            )

        if self.normal_minutes < 0:
            raise DomainValidationError(
                "normal_minutes must be non-negative"
            )

        if self.minimum_minutes < 0:
            raise DomainValidationError(
                "minimum_minutes must be non-negative"
            )

        if self.normal_minutes % 5 != 0:
            raise DomainValidationError(
                "normal_minutes must be a multiple of 5"
            )

        if self.minimum_minutes % 5 != 0:
            raise DomainValidationError(
                "minimum_minutes must be a multiple of 5"
            )


@dataclass(frozen=True)
class AvailableTime:
    weekday: int
    start_minute_of_day: int
    end_minute_of_day: int

    def __post_init__(self):
        if not 0 <= self.weekday <= 6:
            raise ValueError("weekday must be 0..6")

        if not (
            0 <= self.start_minute_of_day
            < self.end_minute_of_day
            <= 1440
        ):
            raise ValueError("invalid time range")


@dataclass(frozen=True)
class BusyEvent:
    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        ensure_aware(self.start_at)
        ensure_aware(self.end_at)

        if self.start_at >= self.end_at:
            raise InvalidTimeRangeError(
                "BusyEvent start_at must be earlier than end_at"
            )


@dataclass(frozen=True)
class ExtraAvailableTime:
    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        ensure_aware(self.start_at)
        ensure_aware(self.end_at)

        if self.start_at >= self.end_at:
            raise InvalidTimeRangeError(
                "ExtraAvailableTime start_at must be earlier than end_at"
            )


@dataclass
class Plan:
    id: int
    participant_id: str
    version_no: int
    created_at: datetime
    effective_from: datetime
    horizon_end: datetime
    source_planning_data_version: int

    def __post_init__(self) -> None:
        ensure_aware(self.created_at)
        ensure_aware(self.effective_from)
        ensure_aware(self.horizon_end)

        if not self.participant_id.strip():
            raise DomainValidationError(
                "participant_id must not be empty"
            )

        if self.version_no < 1:
            raise DomainValidationError(
                "version_no must be at least 1"
            )

        if self.source_planning_data_version < 0:
            raise DomainValidationError(
                "source_planning_data_version must be non-negative"
            )

        if self.effective_from >= self.horizon_end:
            raise InvalidTimeRangeError(
                "effective_from must be earlier than horizon_end"
            )


@dataclass
class PlanItem:
    id: int
    plan_id: int
    study_target_id: int
    start_at: datetime
    end_at: datetime
    origin: PlanItemOrigin
    planned_minutes: int

    range_start: int | None = None
    range_end: int | None = None

    is_cancelled: bool = False
    cancelled_at: datetime | None = None
    carried_from_plan_item_id: int | None = None

    def __post_init__(self) -> None:
        ensure_aware(self.start_at)
        ensure_aware(self.end_at)

        if self.cancelled_at is not None:
            ensure_aware(self.cancelled_at)

        if self.start_at >= self.end_at:
            raise InvalidTimeRangeError(
                "PlanItem start_at must be earlier than end_at"
            )

        start_jst = to_jst(self.start_at)
        end_jst = to_jst(self.end_at)

        same_calendar_day = (
            start_jst.date() == end_jst.date()
        )

        ends_exactly_at_next_midnight = (
            end_jst.date()
            == start_jst.date() + timedelta(days=1)
            and end_jst.time() == time(0, 0)
        )

        if not (
            same_calendar_day
            or ends_exactly_at_next_midnight
        ):
            raise InvalidTimeRangeError(
                "PlanItem must fit within one JST calendar day"
            )

        if self.planned_minutes <= 0:
            raise DomainValidationError(
                "planned_minutes must be positive"
            )

        if (
            self.range_start is not None
            and self.range_end is not None
            and self.range_start > self.range_end
        ):
            raise InvalidMaterialRangeError(
                "range_start must be <= range_end"
            )


@dataclass
class StudyResult:
    id: int
    participant_id: str
    plan_item_id: int
    study_target_id: int
    status: StudyResultStatus

    actual_end_position: int | None = None
    actual_minutes: int | None = None

    time_feeling: str | None = None
    memo: str | None = None


@dataclass
class PlanGenerationAttempt:
    id: int
    participant_id: str
    operation_type: PlanOperationType
    source_planning_data_version: int

    status: AttemptStatus
    stage: AttemptStage

    started_at: datetime
    updated_at: datetime

    completed_at: datetime | None = None
    error_type: str | None = None
    resulting_plan_id: int | None = None