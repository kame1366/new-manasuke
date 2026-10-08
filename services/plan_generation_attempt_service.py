from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import (
    datetime,
    time,
    timedelta,
)
from pathlib import Path

from ai.errors import (
    PlanningDataChangedError,
)
from domain.enums import (
    AttemptStage,
    AttemptStatus,
    GoalMode,
    PlanItemOrigin,
    PlanOperationType,
)
from domain.models import (
    AvailableTime,
    BusyEvent,
    ExtraAvailableTime,
    Goal,
    Plan,
    PlanItem,
    StudyTarget,
)
from domain.time_rules import (
    JST,
    ensure_aware,
    to_jst,
)
from planning.attempt_errors import (
    AttemptNotActiveError,
    AttemptStageError,
    PlanValidationFailedError,
)
from planning.feasibility_analyzer import (
    FeasibilityResult,
    GoalFeasibilityResult,
)
from planning.placement_engine import (
    ScheduledChunk,
)
from planning.plan_validator import (
    MinimumPolicyRequirement,
    PlanValidator,
)
from repositories.plan_generation_attempt_repository import (
    ERROR_PLANNING_DATA_CHANGED,
    PlanGenerationAttemptRepository,
)
from repositories.plan_generation_checkpoint_repository import (
    PlanGenerationCheckpointRepository,
)
from repositories.plan_repository import (
    PlanRepository,
)


ERROR_PLAN_VALIDATION_FAILED = (
    "PLAN_VALIDATION_FAILED"
)


class PlanGenerationAttemptService:
    def __init__(
        self,
        *,
        db_path: str | Path,
        validator: PlanValidator
        | None = None,
    ) -> None:
        self._db_path = Path(
            db_path
        )

        self._attempt_repository = (
            PlanGenerationAttemptRepository(
                self._db_path
            )
        )

        self._checkpoint_repository = (
            PlanGenerationCheckpointRepository(
                self._db_path
            )
        )

        self._plan_repository = (
            PlanRepository(
                self._db_path
            )
        )

        self._validator = (
            validator
            or PlanValidator()
        )

    def start(
        self,
        *,
        participant_id: str,
        operation_type: PlanOperationType,
        now: datetime,
        stale_after: timedelta,
    ):
        return (
            self._attempt_repository
            .start(
                participant_id=(
                    participant_id
                ),
                operation_type=(
                    operation_type
                ),
                now=now,
                stale_after=(
                    stale_after
                ),
            )
        )

    def record_baseline(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        result: FeasibilityResult,
        now: datetime,
    ) -> AttemptStage:
        try:
            return (
                self
                ._checkpoint_repository
                .record_baseline(
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    result=result,
                    now=now,
                )
            )

        except PlanningDataChangedError:
            self._mark_planning_data_changed(
                participant_id=(
                    participant_id
                ),
                attempt_id=(
                    attempt_id
                ),
                now=now,
            )

            raise

    def record_user_selection(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        baseline_goal_results: Sequence[
            GoalFeasibilityResult
        ],
        goal_modes: Mapping[
            int,
            GoalMode,
        ],
        final_result: FeasibilityResult,
        now: datetime,
    ) -> None:
        try:
            (
                self
                ._checkpoint_repository
                .record_user_selection(
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    baseline_goal_results=(
                        baseline_goal_results
                    ),
                    goal_modes=(
                        goal_modes
                    ),
                    final_result=(
                        final_result
                    ),
                    now=now,
                )
            )

        except PlanningDataChangedError:
            self._mark_planning_data_changed(
                participant_id=(
                    participant_id
                ),
                attempt_id=(
                    attempt_id
                ),
                now=now,
            )

            raise

    def finalize(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        effective_from: datetime,
        scheduled_chunks: Sequence[
            ScheduledChunk
        ],
        study_targets: Sequence[
            StudyTarget
        ],
        goals: Sequence[
            Goal
        ],
        strict_goal_ids: set[int],
        weekly_available_times: Sequence[
            AvailableTime
        ],
        extra_available_times: Sequence[
            ExtraAvailableTime
        ],
        busy_events: Sequence[
            BusyEvent
        ],
        minimum_requirements: Sequence[
            MinimumPolicyRequirement
        ] = (),
        theme_completed_minutes_by_target: Mapping[
            int,
            int,
        ]
        | None = None,
        now: datetime,
    ) -> Plan:
        """
        Scheduler成功後:

        1. in-memory proposed Plan作成
        2. PlanValidator
        3. atomic final save
        """
        ensure_aware(
            effective_from
        )
        ensure_aware(
            now
        )

        attempt = (
            self._attempt_repository
            .get_by_id(
                participant_id,
                attempt_id,
            )
        )

        if attempt is None:
            raise AttemptNotActiveError(
                "Attempt not found"
            )

        if (
            attempt.status
            != AttemptStatus.IN_PROGRESS
        ):
            raise AttemptNotActiveError(
                "Attempt is not IN_PROGRESS"
            )

        if (
            attempt.stage
            != AttemptStage.SCHEDULING
        ):
            raise AttemptStageError(
                "finalize requires "
                "SCHEDULING stage"
            )

        horizon_end = (
            self._horizon_end(
                effective_from
            )
        )

        proposed_plan = Plan(
            # DB保存前のin-memory ID。
            id=1,
            participant_id=(
                participant_id
            ),
            version_no=1,
            created_at=now,
            effective_from=(
                effective_from
            ),
            horizon_end=(
                horizon_end
            ),
            source_planning_data_version=(
                attempt
                .source_planning_data_version
            ),
        )

        proposed_items = (
            self._to_plan_items(
                scheduled_chunks
            )
        )

        validation = (
            self._validator.validate(
                plan=proposed_plan,
                plan_items=(
                    proposed_items
                ),
                study_targets=(
                    study_targets
                ),
                goals=goals,
                strict_goal_ids=(
                    strict_goal_ids
                ),
                weekly_available_times=(
                    weekly_available_times
                ),
                extra_available_times=(
                    extra_available_times
                ),
                busy_events=(
                    busy_events
                ),
                minimum_requirements=(
                    minimum_requirements
                ),
                theme_completed_minutes_by_target=(
                    theme_completed_minutes_by_target
                ),
            )
        )

        if not validation.is_valid:
            self._attempt_repository.mark_failed(
                participant_id=(
                    participant_id
                ),
                attempt_id=(
                    attempt_id
                ),
                error_type=(
                    ERROR_PLAN_VALIDATION_FAILED
                ),
                now=now,
            )

            raise PlanValidationFailedError(
                validation.issues
            )

        try:
            return (
                self._plan_repository
                .save_generated_plan_atomic(
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    effective_from=(
                        effective_from
                    ),
                    horizon_end=(
                        horizon_end
                    ),
                    scheduled_chunks=(
                        scheduled_chunks
                    ),
                    now=now,
                )
            )

        except PlanningDataChangedError:
            self._mark_planning_data_changed(
                participant_id=(
                    participant_id
                ),
                attempt_id=(
                    attempt_id
                ),
                now=now,
            )

            raise

    def fail(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        error_type: str,
        now: datetime,
    ) -> None:
        self._attempt_repository.mark_failed(
            participant_id=(
                participant_id
            ),
            attempt_id=(
                attempt_id
            ),
            error_type=(
                error_type
            ),
            now=now,
        )

    def _mark_planning_data_changed(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        now: datetime,
    ) -> None:
        try:
            self._attempt_repository.mark_failed(
                participant_id=(
                    participant_id
                ),
                attempt_id=(
                    attempt_id
                ),
                error_type=(
                    ERROR_PLANNING_DATA_CHANGED
                ),
                now=now,
            )

        except AttemptNotActiveError:
            # stale Attemptなどがすでに
            # ABANDONEDになっていた場合、
            # terminal stateを上書きしない。
            pass

    @staticmethod
    def _horizon_end(
        effective_from: datetime,
    ) -> datetime:
        local = to_jst(
            effective_from
        )

        return datetime.combine(
            local.date()
            + timedelta(
                days=7
            ),
            time.min,
            tzinfo=JST,
        )

    @staticmethod
    def _to_plan_items(
        scheduled_chunks: Sequence[
            ScheduledChunk
        ],
    ) -> list[
        PlanItem
    ]:
        result: list[
            PlanItem
        ] = []

        for index, placement in enumerate(
            sorted(
                scheduled_chunks,
                key=lambda item: (
                    item.start_at,
                    item.end_at,
                    item.chunk.chunk_id,
                ),
            ),
            start=1,
        ):
            result.append(
                PlanItem(
                    id=index,
                    # proposed Plan.idと合わせる。
                    plan_id=1,
                    study_target_id=(
                        placement
                        .chunk
                        .study_target_id
                    ),
                    start_at=(
                        placement.start_at
                    ),
                    end_at=(
                        placement.end_at
                    ),
                    origin=(
                        PlanItemOrigin
                        .SYSTEM_GENERATED
                    ),
                    planned_minutes=(
                        placement
                        .chunk
                        .scheduled_duration_minutes
                    ),
                    range_start=(
                        placement
                        .chunk
                        .range_start
                    ),
                    range_end=(
                        placement
                        .chunk
                        .range_end
                    ),
                )
            )

        return result