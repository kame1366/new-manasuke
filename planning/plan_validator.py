from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from domain.enums import StudyTargetKind
from domain.errors import DomainValidationError
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
from planning.free_slot_builder import (
    FreeSlot,
    FreeSlotBuilder,
)


@dataclass(
    frozen=True,
    slots=True,
)
class MinimumPolicyRequirement:
    """
    PlanValidatorへ渡す、
    すでにpartial-week補正済みの
    LearningPolicy minimum requirement。

    required_distinct_days:
        このPlan horizon内で必要な学習日数。

    minimum_minutes_per_day:
        1学習日として数えるために必要な最低時間。

    partial-week補正そのものは、
    PlanValidatorの責務ではない。
    """

    study_target_id: int
    required_distinct_days: int
    minimum_minutes_per_day: int

    def __post_init__(self) -> None:
        if not (
            0
            <= self.required_distinct_days
            <= 7
        ):
            raise DomainValidationError(
                "required_distinct_days must "
                "be between 0 and 7"
            )

        if self.minimum_minutes_per_day < 0:
            raise DomainValidationError(
                "minimum_minutes_per_day must "
                "be non-negative"
            )

        if (
            self.minimum_minutes_per_day
            % 5
            != 0
        ):
            raise DomainValidationError(
                "minimum_minutes_per_day must "
                "be a multiple of 5"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class PlanValidationIssue:
    """
    PlanValidation失敗理由。

    codeはUI・Service・テストから
    安定して扱える識別子。
    """

    code: str
    message: str

    plan_item_id: int | None = None
    study_target_id: int | None = None
    goal_id: int | None = None


@dataclass(
    frozen=True,
    slots=True,
)
class PlanValidationResult:
    issues: tuple[
        PlanValidationIssue,
        ...,
    ]

    @property
    def is_valid(self) -> bool:
        return not self.issues

    @property
    def issue_codes(
        self,
    ) -> set[str]:
        return {
            issue.code
            for issue in self.issues
        }


class PlanValidator:
    """
    完成したproposed PlanのHard Constraintを
    最終検証する。

    Schedulerが成功していても、
    このValidatorを通らないPlanは保存しない。
    """

    def __init__(
        self,
        free_slot_builder: FreeSlotBuilder
        | None = None,
    ) -> None:
        self._free_slot_builder = (
            free_slot_builder
            or FreeSlotBuilder()
        )

    def validate(
        self,
        *,
        plan: Plan,
        plan_items: Sequence[
            PlanItem
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
    ) -> PlanValidationResult:
        ensure_aware(
            plan.effective_from
        )
        ensure_aware(
            plan.horizon_end
        )

        targets_by_id = (
            self._index_study_targets(
                study_targets
            )
        )

        goals_by_id = (
            self._index_goals(
                goals
            )
        )

        unknown_strict_ids = (
            strict_goal_ids
            - set(goals_by_id)
        )

        if unknown_strict_ids:
            raise DomainValidationError(
                "strict_goal_ids contains "
                "unknown Goal id"
            )

        for requirement in (
            minimum_requirements
        ):
            if (
                requirement.study_target_id
                not in targets_by_id
            ):
                raise DomainValidationError(
                    "MinimumPolicyRequirement "
                    "references unknown StudyTarget"
                )

        theme_completed = dict(
            theme_completed_minutes_by_target
            or {}
        )

        for minutes in (
            theme_completed.values()
        ):
            if minutes < 0:
                raise DomainValidationError(
                    "theme completed minutes "
                    "must be non-negative"
                )

        issues: list[
            PlanValidationIssue
        ] = []

        self._validate_horizon(
            plan,
            issues,
        )

        base_free_slots = (
            self._free_slot_builder.build(
                window_start=(
                    plan.effective_from
                ),
                window_end=(
                    plan.horizon_end
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
                fixed_plan_items=[],
            )
        )

        active_items: list[
            PlanItem
        ] = []

        for item in plan_items:
            target = targets_by_id.get(
                item.study_target_id
            )

            if item.plan_id != plan.id:
                issues.append(
                    PlanValidationIssue(
                        code=(
                            "PLAN_ITEM_WRONG_PLAN"
                        ),
                        message=(
                            "PlanItem belongs to "
                            "a different Plan"
                        ),
                        plan_item_id=item.id,
                        study_target_id=(
                            item.study_target_id
                        ),
                    )
                )

            if target is None:
                issues.append(
                    PlanValidationIssue(
                        code=(
                            "UNKNOWN_STUDY_TARGET"
                        ),
                        message=(
                            "PlanItem references "
                            "unknown StudyTarget"
                        ),
                        plan_item_id=item.id,
                        study_target_id=(
                            item.study_target_id
                        ),
                    )
                )

                continue

            if (
                target.participant_id
                != plan.participant_id
            ):
                issues.append(
                    PlanValidationIssue(
                        code=(
                            "PARTICIPANT_MISMATCH"
                        ),
                        message=(
                            "Plan and StudyTarget "
                            "participant_id do not match"
                        ),
                        plan_item_id=item.id,
                        study_target_id=(
                            target.id
                        ),
                    )
                )

            if item.is_cancelled:
                continue

            active_items.append(
                item
            )

            self._validate_plan_item(
                plan=plan,
                item=item,
                target=target,
                base_free_slots=(
                    base_free_slots
                ),
                issues=issues,
            )

        self._validate_no_overlap(
            active_items,
            issues,
        )

        self._validate_material_order(
            active_items=(
                active_items
            ),
            study_targets=(
                study_targets
            ),
            issues=issues,
        )

        self._validate_strict_deadlines(
            plan=plan,
            active_items=(
                active_items
            ),
            targets_by_id=(
                targets_by_id
            ),
            goals_by_id=(
                goals_by_id
            ),
            strict_goal_ids=(
                strict_goal_ids
            ),
            theme_completed_minutes=(
                theme_completed
            ),
            issues=issues,
        )

        self._validate_minimum_requirements(
            active_items=(
                active_items
            ),
            requirements=(
                minimum_requirements
            ),
            issues=issues,
        )

        return PlanValidationResult(
            issues=tuple(
                issues
            )
        )

    @staticmethod
    def _index_study_targets(
        study_targets: Sequence[
            StudyTarget
        ],
    ) -> dict[int, StudyTarget]:
        result: dict[
            int,
            StudyTarget,
        ] = {}

        for target in study_targets:
            if target.id in result:
                raise DomainValidationError(
                    "duplicate StudyTarget id"
                )

            result[
                target.id
            ] = target

        return result

    @staticmethod
    def _index_goals(
        goals: Sequence[
            Goal
        ],
    ) -> dict[int, Goal]:
        result: dict[
            int,
            Goal,
        ] = {}

        for goal in goals:
            ensure_aware(
                goal.deadline_at
            )

            if goal.id in result:
                raise DomainValidationError(
                    "duplicate Goal id"
                )

            result[
                goal.id
            ] = goal

        return result

    @staticmethod
    def _validate_horizon(
        plan: Plan,
        issues: list[
            PlanValidationIssue
        ],
    ) -> None:
        effective_jst = to_jst(
            plan.effective_from
        )

        horizon_jst = to_jst(
            plan.horizon_end
        )

        expected_horizon = (
            datetime.combine(
                effective_jst.date()
                + timedelta(days=7),
                time.min,
                tzinfo=JST,
            )
        )

        if (
            horizon_jst
            != expected_horizon
        ):
            issues.append(
                PlanValidationIssue(
                    code=(
                        "INVALID_PLAN_HORIZON"
                    ),
                    message=(
                        "Plan horizon_end must be "
                        "00:00 JST after 7 calendar days "
                        "from the effective start date"
                    ),
                )
            )

    def _validate_plan_item(
        self,
        *,
        plan: Plan,
        item: PlanItem,
        target: StudyTarget,
        base_free_slots: Sequence[
            FreeSlot
        ],
        issues: list[
            PlanValidationIssue
        ],
    ) -> None:
        ensure_aware(
            item.start_at
        )
        ensure_aware(
            item.end_at
        )

        if (
            item.start_at
            < plan.effective_from
            or item.end_at
            > plan.horizon_end
        ):
            issues.append(
                PlanValidationIssue(
                    code=(
                        "PLAN_ITEM_OUTSIDE_EFFECTIVE_INTERVAL"
                    ),
                    message=(
                        "PlanItem is outside "
                        "the Plan effective interval"
                    ),
                    plan_item_id=item.id,
                    study_target_id=(
                        target.id
                    ),
                )
            )

        if not (
            self._is_on_five_minute_grid(
                item.start_at
            )
            and self._is_on_five_minute_grid(
                item.end_at
            )
        ):
            issues.append(
                PlanValidationIssue(
                    code=(
                        "PLAN_ITEM_NOT_ON_FIVE_MINUTE_GRID"
                    ),
                    message=(
                        "PlanItem start/end must "
                        "be on the 5-minute grid"
                    ),
                    plan_item_id=item.id,
                    study_target_id=(
                        target.id
                    ),
                )
            )

        if (
            target.kind
            == StudyTargetKind.MATERIAL
        ):
            if (
                item.range_start is None
                or item.range_end is None
            ):
                issues.append(
                    PlanValidationIssue(
                        code=(
                            "MATERIAL_RANGE_REQUIRED"
                        ),
                        message=(
                            "Material PlanItem "
                            "requires range"
                        ),
                        plan_item_id=item.id,
                        study_target_id=(
                            target.id
                        ),
                    )
                )

        elif (
            target.kind
            == StudyTargetKind.THEME
        ):
            if (
                item.range_start is not None
                or item.range_end is not None
            ):
                issues.append(
                    PlanValidationIssue(
                        code=(
                            "THEME_RANGE_NOT_ALLOWED"
                        ),
                        message=(
                            "Theme PlanItem must not "
                            "contain Material range"
                        ),
                        plan_item_id=item.id,
                        study_target_id=(
                            target.id
                        ),
                    )
                )

        if not self._is_inside_any_free_slot(
            item,
            base_free_slots,
        ):
            issues.append(
                PlanValidationIssue(
                    code=(
                        "PLAN_ITEM_OUTSIDE_FREE_SLOT"
                    ),
                    message=(
                        "PlanItem is not fully "
                        "inside an available FreeSlot"
                    ),
                    plan_item_id=item.id,
                    study_target_id=(
                        target.id
                    ),
                )
            )

    @staticmethod
    def _is_on_five_minute_grid(
        value: datetime,
    ) -> bool:
        local = to_jst(
            value
        )

        return (
            local.minute % 5 == 0
            and local.second == 0
            and local.microsecond == 0
        )

    @staticmethod
    def _is_inside_any_free_slot(
        item: PlanItem,
        free_slots: Sequence[
            FreeSlot
        ],
    ) -> bool:
        return any(
            (
                slot.start_at
                <= item.start_at
                and item.end_at
                <= slot.end_at
            )
            for slot in free_slots
        )

    @staticmethod
    def _validate_no_overlap(
        active_items: Sequence[
            PlanItem
        ],
        issues: list[
            PlanValidationIssue
        ],
    ) -> None:
        ordered_items = sorted(
            active_items,
            key=lambda item: (
                item.start_at,
                item.end_at,
                item.id,
            ),
        )

        for previous, current in zip(
            ordered_items,
            ordered_items[1:],
        ):
            if (
                current.start_at
                < previous.end_at
            ):
                issues.append(
                    PlanValidationIssue(
                        code=(
                            "PLAN_ITEM_OVERLAP"
                        ),
                        message=(
                            "Active PlanItems "
                            "must not overlap"
                        ),
                        plan_item_id=(
                            current.id
                        ),
                        study_target_id=(
                            current
                            .study_target_id
                        ),
                    )
                )

    def _validate_material_order(
        self,
        *,
        active_items: Sequence[
            PlanItem
        ],
        study_targets: Sequence[
            StudyTarget
        ],
        issues: list[
            PlanValidationIssue
        ],
    ) -> None:
        items_by_target: dict[
            int,
            list[PlanItem],
        ] = {}

        for item in active_items:
            items_by_target.setdefault(
                item.study_target_id,
                [],
            ).append(
                item
            )

        for target in study_targets:
            if (
                target.kind
                != StudyTargetKind.MATERIAL
            ):
                continue

            target_items = (
                items_by_target.get(
                    target.id,
                    [],
                )
            )

            if not target_items:
                continue

            path = self._build_material_path(
                target,
                issues,
            )

            if path is None:
                continue

            current_index = (
                self._find_current_index(
                    target,
                    path,
                    issues,
                )
            )

            if current_index is None:
                continue

            position_to_index = {
                position: index
                for index, position
                in enumerate(path)
            }

            ordered_items = sorted(
                target_items,
                key=lambda item: (
                    item.start_at,
                    item.end_at,
                    item.id,
                ),
            )

            expected_index = (
                current_index
            )

            for item in ordered_items:
                if (
                    item.range_start is None
                    or item.range_end is None
                ):
                    continue

                start_index = (
                    position_to_index.get(
                        item.range_start
                    )
                )

                end_index = (
                    position_to_index.get(
                        item.range_end
                    )
                )

                if (
                    start_index is None
                    or end_index is None
                    or end_index
                    < start_index
                ):
                    issues.append(
                        PlanValidationIssue(
                            code=(
                                "MATERIAL_RANGE_OUTSIDE_PATH"
                            ),
                            message=(
                                "Material PlanItem range "
                                "is outside the ordered path"
                            ),
                            plan_item_id=(
                                item.id
                            ),
                            study_target_id=(
                                target.id
                            ),
                        )
                    )

                    continue

                path_slice = path[
                    start_index:
                    end_index + 1
                ]

                numeric_range = list(
                    range(
                        item.range_start,
                        item.range_end + 1,
                    )
                )

                if (
                    path_slice
                    != numeric_range
                ):
                    issues.append(
                        PlanValidationIssue(
                            code=(
                                "MATERIAL_RANGE_CROSSES_PATH_GAP"
                            ),
                            message=(
                                "Material PlanItem must not "
                                "cross a non-contiguous "
                                "StudyTarget range gap"
                            ),
                            plan_item_id=(
                                item.id
                            ),
                            study_target_id=(
                                target.id
                            ),
                        )
                    )

                    continue

                if (
                    start_index
                    != expected_index
                ):
                    issues.append(
                        PlanValidationIssue(
                            code=(
                                "MATERIAL_ORDER_VIOLATION"
                            ),
                            message=(
                                "Material PlanItems must "
                                "follow the ordered path "
                                "without a gap or jump"
                            ),
                            plan_item_id=(
                                item.id
                            ),
                            study_target_id=(
                                target.id
                            ),
                        )
                    )

                    # 以降の不要なcascadeを減らすため、
                    # 実際のrange末尾から追跡を続ける。
                    expected_index = (
                        end_index + 1
                    )

                    continue

                expected_index = (
                    end_index + 1
                )

    @staticmethod
    def _build_material_path(
        target: StudyTarget,
        issues: list[
            PlanValidationIssue
        ],
    ) -> list[int] | None:
        path: list[int] = []
        seen: set[int] = set()

        for target_range in sorted(
            target.ranges,
            key=lambda item: (
                item.sequence_no
            ),
        ):
            for position in range(
                target_range.start_position,
                target_range.end_position + 1,
            ):
                if position in seen:
                    issues.append(
                        PlanValidationIssue(
                            code=(
                                "MATERIAL_PATH_OVERLAP"
                            ),
                            message=(
                                "StudyTarget ranges "
                                "must not overlap"
                            ),
                            study_target_id=(
                                target.id
                            ),
                        )
                    )

                    return None

                seen.add(
                    position
                )

                path.append(
                    position
                )

        if not path:
            issues.append(
                PlanValidationIssue(
                    code=(
                        "MATERIAL_PATH_EMPTY"
                    ),
                    message=(
                        "Material StudyTarget "
                        "requires an ordered path"
                    ),
                    study_target_id=(
                        target.id
                    ),
                )
            )

            return None

        return path

    @staticmethod
    def _find_current_index(
        target: StudyTarget,
        path: Sequence[int],
        issues: list[
            PlanValidationIssue
        ],
    ) -> int | None:
        if target.next_position is None:
            issues.append(
                PlanValidationIssue(
                    code=(
                        "MATERIAL_NEXT_POSITION_REQUIRED"
                    ),
                    message=(
                        "Material StudyTarget "
                        "requires next_position"
                    ),
                    study_target_id=(
                        target.id
                    ),
                )
            )

            return None

        try:
            return path.index(
                target.next_position
            )

        except ValueError:
            pass

        if (
            path
            and target.next_position
            == path[-1] + 1
        ):
            return len(
                path
            )

        issues.append(
            PlanValidationIssue(
                code=(
                    "MATERIAL_NEXT_POSITION_INVALID"
                ),
                message=(
                    "next_position must point "
                    "to the ordered path or "
                    "immediately after its end"
                ),
                study_target_id=(
                    target.id
                ),
            )
        )

        return None

    def _validate_strict_deadlines(
        self,
        *,
        plan: Plan,
        active_items: Sequence[
            PlanItem
        ],
        targets_by_id: Mapping[
            int,
            StudyTarget
        ],
        goals_by_id: Mapping[
            int,
            Goal
        ],
        strict_goal_ids: set[int],
        theme_completed_minutes: Mapping[
            int,
            int
        ],
        issues: list[
            PlanValidationIssue
        ],
    ) -> None:
        for goal_id in sorted(
            strict_goal_ids
        ):
            goal = goals_by_id[
                goal_id
            ]

            target = targets_by_id.get(
                goal.study_target_id
            )

            if target is None:
                issues.append(
                    PlanValidationIssue(
                        code=(
                            "GOAL_UNKNOWN_STUDY_TARGET"
                        ),
                        message=(
                            "Goal references unknown "
                            "StudyTarget"
                        ),
                        goal_id=goal.id,
                        study_target_id=(
                            goal.study_target_id
                        ),
                    )
                )

                continue

            if (
                goal.participant_id
                != plan.participant_id
                or target.participant_id
                != plan.participant_id
            ):
                issues.append(
                    PlanValidationIssue(
                        code=(
                            "GOAL_PARTICIPANT_MISMATCH"
                        ),
                        message=(
                            "Goal/StudyTarget does not "
                            "belong to Plan participant"
                        ),
                        goal_id=goal.id,
                        study_target_id=(
                            target.id
                        ),
                    )
                )

                continue

            # deadlineが7日Planの外なら、
            # full completionはfuture projection側で保証する。
            #
            # PlanValidatorは、このPlan horizon内で
            # 到来するdeadlineだけを最終coverage確認する。
            if (
                goal.deadline_at
                > plan.horizon_end
            ):
                continue

            if (
                target.kind
                == StudyTargetKind.MATERIAL
            ):
                self._validate_material_goal_deadline(
                    goal=goal,
                    target=target,
                    active_items=(
                        active_items
                    ),
                    issues=issues,
                )

            elif (
                target.kind
                == StudyTargetKind.THEME
            ):
                self._validate_theme_goal_deadline(
                    goal=goal,
                    target=target,
                    active_items=(
                        active_items
                    ),
                    completed_minutes=(
                        theme_completed_minutes.get(
                            target.id,
                            0,
                        )
                    ),
                    issues=issues,
                )

    def _validate_material_goal_deadline(
        self,
        *,
        goal: Goal,
        target: StudyTarget,
        active_items: Sequence[
            PlanItem
        ],
        issues: list[
            PlanValidationIssue
        ],
    ) -> None:
        path = self._build_material_path(
            target,
            issues,
        )

        if path is None:
            return

        current_index = (
            self._find_current_index(
                target,
                path,
                issues,
            )
        )

        if current_index is None:
            return

        if not goal.ranges:
            issues.append(
                PlanValidationIssue(
                    code=(
                        "MATERIAL_GOAL_RANGE_REQUIRED"
                    ),
                    message=(
                        "Material Goal requires "
                        "at least one GoalRange"
                    ),
                    goal_id=goal.id,
                    study_target_id=(
                        target.id
                    ),
                )
            )

            return

        position_to_index = {
            position: index
            for index, position
            in enumerate(path)
        }

        required_positions: set[int] = set()

        for goal_range in goal.ranges:
            numeric_positions = set(
                range(
                    goal_range.start_position,
                    goal_range.end_position + 1,
                )
            )

            if not numeric_positions.issubset(
                position_to_index
            ):
                issues.append(
                    PlanValidationIssue(
                        code=(
                            "GOAL_RANGE_OUTSIDE_PATH"
                        ),
                        message=(
                            "GoalRange contains "
                            "positions outside "
                            "StudyTarget path"
                        ),
                        goal_id=goal.id,
                        study_target_id=(
                            target.id
                        ),
                    )
                )

                return

            for position in numeric_positions:
                if (
                    position_to_index[
                        position
                    ]
                    >= current_index
                ):
                    required_positions.add(
                        position
                    )

        if not required_positions:
            return

        covered_positions: set[
            int
        ] = set()

        for item in active_items:
            if (
                item.study_target_id
                != target.id
            ):
                continue

            if (
                item.end_at
                > goal.deadline_at
            ):
                continue

            if (
                item.range_start is None
                or item.range_end is None
            ):
                continue

            covered_positions.update(
                range(
                    item.range_start,
                    item.range_end + 1,
                )
            )

        missing = (
            required_positions
            - covered_positions
        )

        if missing:
            issues.append(
                PlanValidationIssue(
                    code=(
                        "STRICT_MATERIAL_DEADLINE_UNCOVERED"
                    ),
                    message=(
                        "STRICT Material Goal "
                        "is not fully covered "
                        "before its deadline"
                    ),
                    goal_id=goal.id,
                    study_target_id=(
                        target.id
                    ),
                )
            )

    @staticmethod
    def _validate_theme_goal_deadline(
        *,
        goal: Goal,
        target: StudyTarget,
        active_items: Sequence[
            PlanItem
        ],
        completed_minutes: int,
        issues: list[
            PlanValidationIssue
        ],
    ) -> None:
        if goal.target_minutes is None:
            return

        remaining_required = max(
            0,
            goal.target_minutes
            - completed_minutes,
        )

        if remaining_required == 0:
            return

        planned_before_deadline = sum(
            PlanValidator._duration_minutes(
                item
            )
            for item in active_items
            if (
                item.study_target_id
                == target.id
                and item.end_at
                <= goal.deadline_at
            )
        )

        if (
            planned_before_deadline
            < remaining_required
        ):
            issues.append(
                PlanValidationIssue(
                    code=(
                        "STRICT_THEME_DEADLINE_UNCOVERED"
                    ),
                    message=(
                        "STRICT Theme Goal does "
                        "not have enough planned "
                        "minutes before its deadline"
                    ),
                    goal_id=goal.id,
                    study_target_id=(
                        target.id
                    ),
                )
            )

    @staticmethod
    def _validate_minimum_requirements(
        *,
        active_items: Sequence[
            PlanItem
        ],
        requirements: Sequence[
            MinimumPolicyRequirement
        ],
        issues: list[
            PlanValidationIssue
        ],
    ) -> None:
        minutes_by_target_day: dict[
            int,
            dict[
                object,
                int,
            ],
        ] = {}

        for item in active_items:
            study_day = to_jst(
                item.start_at
            ).date()

            target_days = (
                minutes_by_target_day
                .setdefault(
                    item.study_target_id,
                    {},
                )
            )

            target_days[
                study_day
            ] = (
                target_days.get(
                    study_day,
                    0,
                )
                + PlanValidator
                ._duration_minutes(
                    item
                )
            )

        for requirement in requirements:
            if (
                requirement
                .required_distinct_days
                == 0
            ):
                continue

            day_totals = (
                minutes_by_target_day.get(
                    requirement
                    .study_target_id,
                    {},
                )
            )

            qualifying_days = sum(
                1
                for minutes
                in day_totals.values()
                if (
                    minutes > 0
                    and minutes
                    >= requirement
                    .minimum_minutes_per_day
                )
            )

            if (
                qualifying_days
                < requirement
                .required_distinct_days
            ):
                issues.append(
                    PlanValidationIssue(
                        code=(
                            "MINIMUM_POLICY_UNSATISFIED"
                        ),
                        message=(
                            "Plan does not satisfy "
                            "the required number of "
                            "minimum study days"
                        ),
                        study_target_id=(
                            requirement
                            .study_target_id
                        ),
                    )
                )

    @staticmethod
    def _duration_minutes(
        item: PlanItem,
    ) -> int:
        return int(
            (
                item.end_at
                - item.start_at
            ).total_seconds()
            // 60
        )