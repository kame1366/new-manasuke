from __future__ import annotations

from dataclasses import (
    dataclass,
    replace,
)
from datetime import datetime
from pathlib import Path

from domain.enums import (
    PlanItemOrigin,
    StudyTargetKind,
)
from domain.errors import (
    DomainValidationError,
)
from domain.models import (
    AvailableTime,
    BusyEvent,
    ExtraAvailableTime,
    Goal,
    PlanItem,
    StudyTarget,
)
from domain.time_rules import ensure_aware
from planning.attempt_errors import (
    PlanValidationFailedError,
)
from planning.plan_item_lifecycle_errors import (
    PlanItemMutationNotAllowedError,
)
from planning.plan_validator import (
    MinimumPolicyRequirement,
    PlanValidator,
)
from repositories.plan_item_lifecycle_repository import (
    PlanItemLifecycleRepository,
)
from domain.plan_state import (
    PlanState,
)


@dataclass(
    frozen=True,
    slots=True,
)
class PlanMutationValidationContext:
    study_targets: tuple[
        StudyTarget,
        ...,
    ]

    goals: tuple[
        Goal,
        ...,
    ]

    strict_goal_ids: frozenset[int]

    weekly_available_times: tuple[
        AvailableTime,
        ...,
    ]

    extra_available_times: tuple[
        ExtraAvailableTime,
        ...,
    ]

    busy_events: tuple[
        BusyEvent,
        ...,
    ]

    minimum_requirements: tuple[
        MinimumPolicyRequirement,
        ...,
    ] = ()

    theme_completed_minutes_by_target: (
        dict[int, int] | None
    ) = None


@dataclass(
    frozen=True,
    slots=True,
)
class PlanItemMutationResult:
    item: PlanItem

    pace_warning: bool = False


class PlanItemLifecycleService:
    def __init__(
        self,
        *,
        db_path: str | Path,
        validator: PlanValidator
        | None = None,
    ) -> None:
        self._repository = (
            PlanItemLifecycleRepository(
                db_path
            )
        )

        self._validator = (
            validator
            or PlanValidator()
        )

    def edit(
        self,
        *,
        participant_id: str,
        plan_id: int,
        plan_item_id: int,
        plan_state: PlanState,
        current_time: datetime,
        new_start_at: datetime,
        new_end_at: datetime,
        validation_context: (
            PlanMutationValidationContext
        ),
        new_range_start: (
            int | None
        ) = None,
        new_range_end: (
            int | None
        ) = None,
    ) -> PlanItemMutationResult:
        ensure_aware(
            current_time
        )

        ensure_aware(
            new_start_at
        )

        ensure_aware(
            new_end_at
        )

        plan, items, item = (
            self._load(
                participant_id=(
                    participant_id
                ),
                plan_id=plan_id,
                plan_item_id=(
                    plan_item_id
                ),
            )
        )

        self._assert_edit_or_cancel_allowed(
            item=item,
            plan_state=plan_state,
            current_time=(
                current_time
            ),
        )

        if item.is_cancelled:
            raise (
                PlanItemMutationNotAllowedError(
                    "cancelled PlanItem "
                    "cannot be edited"
                )
            )

        target = self._find_target(
            item.study_target_id,
            validation_context,
        )

        duration_minutes = int(
            (
                new_end_at
                - new_start_at
            ).total_seconds()
            // 60
        )

        if duration_minutes <= 0:
            raise DomainValidationError(
                "new PlanItem duration "
                "must be positive"
            )

        if (
            target.kind
            == StudyTargetKind.MATERIAL
        ):
            # Material開始位置は固定。
            effective_range_start = (
                item.range_start
                if new_range_start
                is None
                else new_range_start
            )

            if (
                effective_range_start
                != item.range_start
            ):
                raise (
                    PlanItemMutationNotAllowedError(
                        "Material range_start "
                        "cannot be changed"
                    )
                )

            if new_range_end is None:
                effective_range_end = (
                    item.range_end
                )
            else:
                effective_range_end = (
                    new_range_end
                )

            if (
                effective_range_start
                is None
                or effective_range_end
                is None
            ):
                raise DomainValidationError(
                    "Material PlanItem "
                    "requires range"
                )

        else:
            if (
                new_range_start is not None
                or new_range_end is not None
            ):
                raise (
                    PlanItemMutationNotAllowedError(
                        "Theme PlanItem does not "
                        "accept Material range"
                    )
                )

            effective_range_start = None
            effective_range_end = None

        proposed = replace(
            item,
            start_at=new_start_at,
            end_at=new_end_at,
            origin=(
                PlanItemOrigin.USER_MODIFIED
            ),
            planned_minutes=(
                duration_minutes
            ),
            range_start=(
                effective_range_start
            ),
            range_end=(
                effective_range_end
            ),
        )

        self._validate_proposed_plan(
            plan=plan,
            items=items,
            previous=item,
            proposed=proposed,
            context=validation_context,
        )

        self._repository.replace_item_with_adjustment(
            participant_id=(
                participant_id
            ),
            previous=item,
            updated=proposed,
            now=current_time,
        )

        return PlanItemMutationResult(
            item=proposed,
            pace_warning=(
                self._pace_warning(
                    target=target,
                    item=proposed,
                )
            ),
        )

    def cancel(
        self,
        *,
        participant_id: str,
        plan_id: int,
        plan_item_id: int,
        plan_state: PlanState,
        current_time: datetime,
        validation_context: (
            PlanMutationValidationContext
        ),
    ) -> PlanItemMutationResult:
        ensure_aware(
            current_time
        )

        plan, items, item = (
            self._load(
                participant_id=(
                    participant_id
                ),
                plan_id=plan_id,
                plan_item_id=(
                    plan_item_id
                ),
            )
        )

        self._assert_edit_or_cancel_allowed(
            item=item,
            plan_state=plan_state,
            current_time=(
                current_time
            ),
        )

        if item.is_cancelled:
            raise (
                PlanItemMutationNotAllowedError(
                    "PlanItem is already cancelled"
                )
            )

        proposed = replace(
            item,
            is_cancelled=True,
            cancelled_at=(
                current_time
            ),
        )

        self._validate_proposed_plan(
            plan=plan,
            items=items,
            previous=item,
            proposed=proposed,
            context=validation_context,
        )

        self._repository.replace_item_with_adjustment(
            participant_id=(
                participant_id
            ),
            previous=item,
            updated=proposed,
            now=current_time,
        )

        return PlanItemMutationResult(
            item=proposed
        )

    def restore(
        self,
        *,
        participant_id: str,
        plan_id: int,
        plan_item_id: int,
        plan_state: PlanState,
        current_time: datetime,
        validation_context: (
            PlanMutationValidationContext
        ),
    ) -> PlanItemMutationResult:
        ensure_aware(
            current_time
        )

        plan, items, item = (
            self._load(
                participant_id=(
                    participant_id
                ),
                plan_id=plan_id,
                plan_item_id=(
                    plan_item_id
                ),
            )
        )

        # Product設計でrestoreは
        # CURRENT / FUTURE_APPLICABLEだけ。
        if plan_state not in {
            PlanState.CURRENT,
            PlanState.FUTURE_APPLICABLE,
        }:
            raise (
                PlanItemMutationNotAllowedError(
                    "PlanItem restore requires "
                    "CURRENT or "
                    "FUTURE_APPLICABLE Plan"
                )
            )

        if current_time >= item.start_at:
            raise (
                PlanItemMutationNotAllowedError(
                    "PlanItem cannot be restored "
                    "after original start_at"
                )
            )

        if not item.is_cancelled:
            raise (
                PlanItemMutationNotAllowedError(
                    "PlanItem is not cancelled"
                )
            )

        proposed = replace(
            item,
            is_cancelled=False,
            cancelled_at=None,
        )

        self._validate_proposed_plan(
            plan=plan,
            items=items,
            previous=item,
            proposed=proposed,
            context=validation_context,
        )

        self._repository.replace_item_with_adjustment(
            participant_id=(
                participant_id
            ),
            previous=item,
            updated=proposed,
            now=current_time,
        )

        return PlanItemMutationResult(
            item=proposed
        )

    @staticmethod
    def _assert_edit_or_cancel_allowed(
        *,
        item: PlanItem,
        plan_state: PlanState,
        current_time: datetime,
    ) -> None:
        if current_time >= item.start_at:
            raise (
                PlanItemMutationNotAllowedError(
                    "PlanItem can be changed "
                    "only before start_at"
                )
            )

        if plan_state in {
            PlanState.SHADOWED,
            PlanState.EXPIRED,
        }:
            raise (
                PlanItemMutationNotAllowedError(
                    "SHADOWED / EXPIRED Plan "
                    "is read-only"
                )
            )

        if (
            plan_state
            == PlanState.OUTDATED_INVALID
            and item.origin
            != PlanItemOrigin.USER_MODIFIED
        ):
            raise (
                PlanItemMutationNotAllowedError(
                    "OUTDATED_INVALID permits "
                    "repair only for future "
                    "USER_MODIFIED PlanItems"
                )
            )

    def _validate_proposed_plan(
        self,
        *,
        plan,
        items: list[PlanItem],
        previous: PlanItem,
        proposed: PlanItem,
        context: (
            PlanMutationValidationContext
        ),
    ) -> None:
        proposed_items = [
            (
                proposed
                if item.id
                == previous.id
                else item
            )
            for item in items
        ]

        result = self._validator.validate(
            plan=plan,
            plan_items=(
                proposed_items
            ),
            study_targets=(
                context.study_targets
            ),
            goals=(
                context.goals
            ),
            strict_goal_ids=set(
                context.strict_goal_ids
            ),
            weekly_available_times=(
                context
                .weekly_available_times
            ),
            extra_available_times=(
                context
                .extra_available_times
            ),
            busy_events=(
                context.busy_events
            ),
            minimum_requirements=(
                context
                .minimum_requirements
            ),
            theme_completed_minutes_by_target=(
                context
                .theme_completed_minutes_by_target
            ),
        )

        if not result.is_valid:
            raise (
                PlanValidationFailedError(
                    result.issues
                )
            )

    def _load(
        self,
        *,
        participant_id: str,
        plan_id: int,
        plan_item_id: int,
    ):
        plan = self._repository.get_plan(
            participant_id=(
                participant_id
            ),
            plan_id=plan_id,
        )

        if plan is None:
            raise DomainValidationError(
                "Plan not found"
            )

        items = self._repository.list_items(
            participant_id=(
                participant_id
            ),
            plan_id=plan_id,
        )

        item = next(
            (
                candidate
                for candidate in items
                if candidate.id
                == plan_item_id
            ),
            None,
        )

        if item is None:
            raise DomainValidationError(
                "PlanItem not found"
            )

        return (
            plan,
            items,
            item,
        )

    @staticmethod
    def _find_target(
        target_id: int,
        context: (
            PlanMutationValidationContext
        ),
    ) -> StudyTarget:
        target = next(
            (
                candidate
                for candidate
                in context.study_targets
                if candidate.id
                == target_id
            ),
            None,
        )

        if target is None:
            raise DomainValidationError(
                "StudyTarget not found "
                "in validation context"
            )

        return target

    @staticmethod
    def _pace_warning(
        *,
        target: StudyTarget,
        item: PlanItem,
    ) -> bool:
        if (
            target.kind
            != StudyTargetKind.MATERIAL
        ):
            return False

        if (
            target
            .estimated_minutes_per_unit
            is None
            or item.range_start
            is None
            or item.range_end
            is None
        ):
            return False

        unit_count = (
            item.range_end
            - item.range_start
            + 1
        )

        estimated_required = (
            unit_count
            * target
            .estimated_minutes_per_unit
        )

        scheduled = (
            item.planned_minutes
        )

        difference = (
            estimated_required
            - scheduled
        )

        return (
            estimated_required
            > scheduled * 1.5
            and difference >= 10
        )