from __future__ import annotations

from datetime import datetime
from pathlib import Path

from domain.enums import (
    StudyResultStatus,
    StudyTargetKind,
)
from domain.errors import (
    DomainValidationError,
)
from domain.models import (
    StudyResult,
)
from domain.time_rules import (
    ensure_aware,
)
from planning.progress_sync import (
    MaterialProgressSyncPlanner,
)
from planning.study_result_errors import (
    MaterialUnrecordedBlockError,
    StudyResultAlreadyExistsError,
    StudyResultCorrectionLockedError,
    StudyResultNotFoundError,
)
from planning.study_result_rules import (
    MaterialStudyResultRules,
    ThemeStudyResultRules,
    derive_study_result_state,
)
from repositories.goal_repository import (
    GoalRepository,
)
from repositories.participant_repository import (
    ParticipantRepository,
)
from repositories.study_result_repository import (
    StudyResultRepository,
)
from repositories.study_target_repository import (
    StudyTargetRepository,
)


class StudyResultService:
    def __init__(
        self,
        *,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(
            db_path
        )

        self._result_repository = (
            StudyResultRepository(
                self._db_path
            )
        )

        self._target_repository = (
            StudyTargetRepository(
                self._db_path
            )
        )

        self._goal_repository = (
            GoalRepository(
                self._db_path
            )
        )

        self._participant_repository = (
            ParticipantRepository(
                self._db_path
            )
        )

        self._material_rules = (
            MaterialStudyResultRules()
        )

        self._sync_planner = (
            MaterialProgressSyncPlanner()
        )

    # =====================================================
    # Create
    # =====================================================

    def record(
        self,
        *,
        participant_id: str,
        plan_item_id: int,
        status: StudyResultStatus,
        now: datetime,
        actual_end_position: (
            int | None
        ) = None,
        actual_minutes: (
            int | None
        ) = None,
        time_feeling: (
            str | None
        ) = None,
        memo: str | None = None,
    ) -> StudyResult:
        ensure_aware(
            now
        )

        plan_item = (
            self._require_plan_item(
                participant_id,
                plan_item_id,
            )
        )

        if plan_item.is_cancelled:
            raise DomainValidationError(
                "cancelled PlanItem cannot "
                "receive StudyResult"
            )

        existing = (
            self._result_repository
            .get_by_plan_item(
                participant_id=(
                    participant_id
                ),
                plan_item_id=(
                    plan_item_id
                ),
            )
        )

        if existing is not None:
            raise (
                StudyResultAlreadyExistsError(
                    "StudyResult already exists; "
                    "use correct()"
                )
            )

        target = (
            self._require_target(
                participant_id,
                plan_item.study_target_id,
            )
        )

        if (
            target.kind
            == StudyTargetKind.MATERIAL
        ):
            if (
                actual_minutes is not None
                or time_feeling is not None
                or memo is not None
            ):
                raise DomainValidationError(
                    "Material StudyResult does "
                    "not use actual_minutes, "
                    "time_feeling or memo"
                )

            evaluation = (
                self._material_rules
                .evaluate(
                    target=target,
                    plan_item=plan_item,
                    status=status,
                    actual_end_position=(
                        actual_end_position
                    ),
                    correction=False,
                )
            )

            current_version = (
                self._require_version(
                    participant_id
                )
            )

            candidates = (
                self
                ._result_repository
                .load_progress_sync_candidates(
                    participant_id=(
                        participant_id
                    ),
                    study_target_id=(
                        target.id
                    ),
                    now=now,
                    source_planning_data_version=(
                        current_version
                    ),
                )
            )

            decisions = (
                self._sync_planner.build(
                    target=target,
                    new_next_position=(
                        evaluation
                        .new_next_position
                    ),
                    candidates=candidates,
                )
            )

            assert (
                target.next_position
                is not None
            )

            return (
                self._result_repository
                .insert_material_result_atomic(
                    participant_id=(
                        participant_id
                    ),
                    plan_item=(
                        plan_item
                    ),
                    status=status,
                    actual_end_position=(
                        evaluation
                        .normalized_actual_end_position
                    ),
                    new_next_position=(
                        evaluation
                        .new_next_position
                    ),
                    expected_old_next_position=(
                        target.next_position
                    ),
                    expected_planning_data_version=(
                        current_version
                    ),
                    sync_decisions=(
                        decisions
                    ),
                    now=now,
                )
            )

        if (
            target.kind
            == StudyTargetKind.THEME
        ):
            if actual_end_position is not None:
                raise DomainValidationError(
                    "Theme does not use "
                    "actual_end_position"
                )

            requires_actual_minutes = (
                self
                ._theme_requires_actual_minutes(
                    participant_id=(
                        participant_id
                    ),
                    study_target_id=(
                        target.id
                    ),
                )
            )

            ThemeStudyResultRules.validate(
                target=target,
                plan_item=plan_item,
                status=status,
                actual_end_position=None,
                actual_minutes=(
                    actual_minutes
                ),
                requires_actual_minutes=(
                    requires_actual_minutes
                ),
            )

            return (
                self._result_repository
                .insert_theme_result(
                    participant_id=(
                        participant_id
                    ),
                    plan_item=(
                        plan_item
                    ),
                    status=status,
                    actual_minutes=(
                        actual_minutes
                    ),
                    time_feeling=(
                        time_feeling
                    ),
                    memo=memo,
                    now=now,
                )
            )

        raise DomainValidationError(
            "unsupported StudyTarget kind"
        )

    # =====================================================
    # Correct
    # =====================================================

    def correct(
        self,
        *,
        participant_id: str,
        plan_item_id: int,
        status: StudyResultStatus,
        now: datetime,
        actual_end_position: (
            int | None
        ) = None,
        actual_minutes: (
            int | None
        ) = None,
        time_feeling: (
            str | None
        ) = None,
        memo: str | None = None,
    ) -> StudyResult:
        ensure_aware(
            now
        )

        plan_item = (
            self._require_plan_item(
                participant_id,
                plan_item_id,
            )
        )

        previous = (
            self._result_repository
            .get_by_plan_item(
                participant_id=(
                    participant_id
                ),
                plan_item_id=(
                    plan_item_id
                ),
            )
        )

        if previous is None:
            raise StudyResultNotFoundError(
                "StudyResult not found"
            )

        target = (
            self._require_target(
                participant_id,
                previous.study_target_id,
            )
        )

        # Material / Themeとも、
        # 同StudyTargetの後続Resultがある
        # 古い記録は修正しない。
        if (
            self._result_repository
            .has_later_result(
                participant_id=(
                    participant_id
                ),
                study_target_id=(
                    target.id
                ),
                plan_item_id=(
                    plan_item_id
                ),
            )
        ):
            raise (
                StudyResultCorrectionLockedError(
                    "a later StudyResult exists "
                    "for this StudyTarget"
                )
            )

        if (
            target.kind
            == StudyTargetKind.MATERIAL
        ):
            if (
                actual_minutes is not None
                or time_feeling is not None
                or memo is not None
            ):
                raise DomainValidationError(
                    "Material StudyResult does "
                    "not use Theme fields"
                )

            evaluation = (
                self._material_rules
                .evaluate(
                    target=target,
                    plan_item=plan_item,
                    status=status,
                    actual_end_position=(
                        actual_end_position
                    ),
                    correction=True,
                )
            )

            current_version = (
                self._require_version(
                    participant_id
                )
            )

            candidates = (
                self
                ._result_repository
                .load_progress_sync_candidates(
                    participant_id=(
                        participant_id
                    ),
                    study_target_id=(
                        target.id
                    ),
                    now=now,
                    source_planning_data_version=(
                        current_version
                    ),
                )
            )

            decisions = (
                self._sync_planner.build(
                    target=target,
                    new_next_position=(
                        evaluation
                        .new_next_position
                    ),
                    candidates=candidates,
                )
            )

            assert (
                target.next_position
                is not None
            )

            return (
                self._result_repository
                .correct_material_result_atomic(
                    participant_id=(
                        participant_id
                    ),
                    plan_item=(
                        plan_item
                    ),
                    previous=previous,
                    status=status,
                    actual_end_position=(
                        evaluation
                        .normalized_actual_end_position
                    ),
                    new_next_position=(
                        evaluation
                        .new_next_position
                    ),
                    expected_old_next_position=(
                        target.next_position
                    ),
                    expected_planning_data_version=(
                        current_version
                    ),
                    sync_decisions=(
                        decisions
                    ),
                    now=now,
                )
            )

        if (
            target.kind
            == StudyTargetKind.THEME
        ):
            requires_actual_minutes = (
                self
                ._theme_requires_actual_minutes(
                    participant_id=(
                        participant_id
                    ),
                    study_target_id=(
                        target.id
                    ),
                )
            )

            ThemeStudyResultRules.validate(
                target=target,
                plan_item=plan_item,
                status=status,
                actual_end_position=(
                    actual_end_position
                ),
                actual_minutes=(
                    actual_minutes
                ),
                requires_actual_minutes=(
                    requires_actual_minutes
                ),
            )

            return (
                self._result_repository
                .correct_theme_result(
                    participant_id=(
                        participant_id
                    ),
                    previous=previous,
                    status=status,
                    actual_minutes=(
                        actual_minutes
                    ),
                    time_feeling=(
                        time_feeling
                    ),
                    memo=memo,
                    now=now,
                )
            )

        raise DomainValidationError(
            "unsupported StudyTarget kind"
        )

    # =====================================================
    # Query / UNRECORDED
    # =====================================================

    def get_state(
        self,
        *,
        participant_id: str,
        plan_item_id: int,
    ) -> str:
        plan_item = (
            self._require_plan_item(
                participant_id,
                plan_item_id,
            )
        )

        result = (
            self._result_repository
            .get_by_plan_item(
                participant_id=(
                    participant_id
                ),
                plan_item_id=(
                    plan_item_id
                ),
            )
        )

        return derive_study_result_state(
            plan_item=plan_item,
            result=result,
        )

    def assert_replan_ready(
        self,
        *,
        participant_id: str,
        now: datetime,
    ) -> None:
        """
        replan前に呼ぶ。

        start済みMaterial PlanItemに
        UNRECORDEDが残っていれば、
        concrete rangeを安全に決められない。
        """
        ensure_aware(
            now
        )

        blocking_items = (
            self._result_repository
            .find_material_unrecorded_started(
                participant_id=(
                    participant_id
                ),
                now=now,
            )
        )

        if blocking_items:
            ids = [
                item.id
                for item in blocking_items
            ]

            raise (
                MaterialUnrecordedBlockError(
                    "Material StudyResult is "
                    "required before replan; "
                    f"plan_item_ids={ids}"
                )
            )

    # =====================================================
    # Helpers
    # =====================================================

    def _require_plan_item(
        self,
        participant_id: str,
        plan_item_id: int,
    ):
        plan_item = (
            self._result_repository
            .get_plan_item(
                participant_id=(
                    participant_id
                ),
                plan_item_id=(
                    plan_item_id
                ),
            )
        )

        if plan_item is None:
            raise DomainValidationError(
                "PlanItem not found"
            )

        return plan_item

    def _require_target(
        self,
        participant_id: str,
        study_target_id: int,
    ):
        target = (
            self._target_repository
            .get_by_id(
                participant_id,
                study_target_id,
            )
        )

        if target is None:
            raise DomainValidationError(
                "StudyTarget not found"
            )

        return target

    def _require_version(
        self,
        participant_id: str,
    ) -> int:
        version = (
            self._participant_repository
            .get_planning_data_version(
                participant_id
            )
        )

        if version is None:
            raise DomainValidationError(
                "participant not found"
            )

        return version

    def _theme_requires_actual_minutes(
        self,
        *,
        participant_id: str,
        study_target_id: int,
    ) -> bool:
        goals = (
            self._goal_repository
            .list_by_participant(
                participant_id
            )
        )

        return any(
            (
                goal.study_target_id
                == study_target_id
                and goal.target_minutes
                is not None
            )
            for goal in goals
        )