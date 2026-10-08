from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from domain.enums import StudyTargetKind
from domain.errors import DomainValidationError
from domain.models import (
    Goal,
    LearningPolicy,
    StudyTarget,
)
from domain.time_rules import to_jst
from planning.free_slot_builder import FreeSlot
from planning.work_chunk_builder import (
    WorkChunk,
    scheduled_duration_minutes,
)
from planning.work_segment_builder import WorkSegment


TIME_GRID_MINUTES = 5
THEME_MINIMUM_OPTIONAL_MINUTES = 10


@dataclass(
    frozen=True,
    slots=True,
)
class OptionalAllocationBounds:
    """
    AI②へ渡すStudyTargetごとの
    optional allocationの物理的な範囲。
    """

    study_target_id: int

    minimum_optional_increment_minutes: int
    maximum_optional_minutes: int

    normal_target_minutes: int
    mandatory_scheduled_minutes: int

    best_effort_goal_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.study_target_id <= 0:
            raise DomainValidationError(
                "study_target_id must be positive"
            )

        if (
            self.minimum_optional_increment_minutes
            < THEME_MINIMUM_OPTIONAL_MINUTES
        ):
            raise DomainValidationError(
                "minimum optional increment "
                "must be at least 10 minutes"
            )

        if (
            self.minimum_optional_increment_minutes
            % TIME_GRID_MINUTES
            != 0
        ):
            raise DomainValidationError(
                "minimum optional increment "
                "must be a multiple of 5"
            )

        if self.maximum_optional_minutes < 0:
            raise DomainValidationError(
                "maximum_optional_minutes "
                "must be non-negative"
            )

        if (
            self.maximum_optional_minutes
            % TIME_GRID_MINUTES
            != 0
        ):
            raise DomainValidationError(
                "maximum_optional_minutes "
                "must be a multiple of 5"
            )

        if self.normal_target_minutes < 0:
            raise DomainValidationError(
                "normal_target_minutes "
                "must be non-negative"
            )

        if self.mandatory_scheduled_minutes < 0:
            raise DomainValidationError(
                "mandatory_scheduled_minutes "
                "must be non-negative"
            )

        if len(
            self.best_effort_goal_ids
        ) != len(
            set(
                self.best_effort_goal_ids
            )
        ):
            raise DomainValidationError(
                "best_effort_goal_ids "
                "must not contain duplicates"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class DailySoftCapacity:
    day: date
    minutes: int

    def __post_init__(self) -> None:
        if self.minutes < 0:
            raise DomainValidationError(
                "DailySoftCapacity minutes "
                "must be non-negative"
            )

        if (
            self.minutes
            % TIME_GRID_MINUTES
            != 0
        ):
            raise DomainValidationError(
                "DailySoftCapacity minutes "
                "must be a multiple of 5"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class PlanningAIContext:
    """
    AI②に渡す前にPythonが確定する
    Soft allocationの境界。
    """

    bounds: tuple[
        OptionalAllocationBounds,
        ...,
    ]

    total_soft_capacity_minutes: int

    daily_remaining_capacity: tuple[
        DailySoftCapacity,
        ...,
    ]

    def __post_init__(self) -> None:
        target_ids = [
            bound.study_target_id
            for bound in self.bounds
        ]

        if len(target_ids) != len(
            set(target_ids)
        ):
            raise DomainValidationError(
                "PlanningAIContext contains "
                "duplicate StudyTarget IDs"
            )

        if self.total_soft_capacity_minutes < 0:
            raise DomainValidationError(
                "total_soft_capacity_minutes "
                "must be non-negative"
            )

        if (
            self.total_soft_capacity_minutes
            % TIME_GRID_MINUTES
            != 0
        ):
            raise DomainValidationError(
                "total_soft_capacity_minutes "
                "must be a multiple of 5"
            )

    @property
    def study_target_ids(
        self,
    ) -> tuple[int, ...]:
        return tuple(
            bound.study_target_id
            for bound in self.bounds
        )


class OptionalAllocationContextBuilder:
    """
    mandatory placement後の状態から、
    AI②へ渡せるoptional min/maxと
    capacityを決定論的に計算する。
    """

    def build(
        self,
        *,
        study_targets: Sequence[
            StudyTarget
        ],
        goals: Sequence[
            Goal
        ],
        learning_policies: Sequence[
            LearningPolicy
        ],
        work_segments: Sequence[
            WorkSegment
        ],
        strict_goal_ids: set[int],
        best_effort_goal_ids: set[int],
        mandatory_chunks: Sequence[
            WorkChunk
        ],
        remaining_free_slots: Sequence[
            FreeSlot
        ],
        theme_completed_minutes_by_target: Mapping[
            int,
            int,
        ]
        | None = None,
    ) -> PlanningAIContext:
        if (
            strict_goal_ids
            & best_effort_goal_ids
        ):
            raise DomainValidationError(
                "a Goal cannot be both "
                "STRICT and BEST_EFFORT"
            )

        targets_by_id = {
            target.id: target
            for target in study_targets
        }

        if len(targets_by_id) != len(
            study_targets
        ):
            raise DomainValidationError(
                "duplicate StudyTarget id"
            )

        goals_by_id = {
            goal.id: goal
            for goal in goals
        }

        if len(goals_by_id) != len(
            goals
        ):
            raise DomainValidationError(
                "duplicate Goal id"
            )

        known_goal_ids = set(
            goals_by_id
        )

        if not strict_goal_ids.issubset(
            known_goal_ids
        ):
            raise DomainValidationError(
                "strict_goal_ids contains "
                "unknown Goal"
            )

        if not best_effort_goal_ids.issubset(
            known_goal_ids
        ):
            raise DomainValidationError(
                "best_effort_goal_ids contains "
                "unknown Goal"
            )

        policies_by_target = {
            policy.study_target_id: policy
            for policy in learning_policies
        }

        if len(
            policies_by_target
        ) != len(
            learning_policies
        ):
            raise DomainValidationError(
                "duplicate LearningPolicy "
                "for StudyTarget"
            )

        missing_policy_ids = (
            set(targets_by_id)
            - set(policies_by_target)
        )

        if missing_policy_ids:
            raise DomainValidationError(
                "LearningPolicy missing for "
                f"StudyTarget IDs: "
                f"{sorted(missing_policy_ids)}"
            )

        theme_completed = dict(
            theme_completed_minutes_by_target
            or {}
        )

        if any(
            minutes < 0
            for minutes
            in theme_completed.values()
        ):
            raise DomainValidationError(
                "theme completed minutes "
                "must be non-negative"
            )

        mandatory_minutes_by_target: dict[
            int,
            int,
        ] = {}

        mandatory_material_positions: dict[
            int,
            set[int],
        ] = {}

        for chunk in mandatory_chunks:
            if not chunk.mandatory:
                continue

            mandatory_minutes_by_target[
                chunk.study_target_id
            ] = (
                mandatory_minutes_by_target.get(
                    chunk.study_target_id,
                    0,
                )
                + chunk.scheduled_duration_minutes
            )

            if (
                chunk.kind
                == StudyTargetKind.MATERIAL
                and chunk.range_start
                is not None
                and chunk.range_end
                is not None
            ):
                positions = (
                    mandatory_material_positions
                    .setdefault(
                        chunk.study_target_id,
                        set(),
                    )
                )

                positions.update(
                    range(
                        chunk.range_start,
                        chunk.range_end + 1,
                    )
                )

        segments_by_target: dict[
            int,
            list[WorkSegment],
        ] = {}

        for segment in work_segments:
            segments_by_target.setdefault(
                segment.study_target_id,
                [],
            ).append(
                segment
            )

        goals_by_target: dict[
            int,
            list[Goal],
        ] = {}

        for goal in goals:
            goals_by_target.setdefault(
                goal.study_target_id,
                [],
            ).append(
                goal
            )

        bounds: list[
            OptionalAllocationBounds
        ] = []

        for target in sorted(
            study_targets,
            key=lambda item: item.id,
        ):
            policy = policies_by_target[
                target.id
            ]

            mandatory_minutes = (
                mandatory_minutes_by_target.get(
                    target.id,
                    0,
                )
            )

            normal_target_minutes = (
                policy.normal_sessions_per_week
                * policy.normal_minutes
            )

            normal_remaining = max(
                0,
                normal_target_minutes
                - mandatory_minutes,
            )

            target_best_effort_goal_ids = tuple(
                sorted(
                    goal.id
                    for goal in goals_by_target.get(
                        target.id,
                        [],
                    )
                    if goal.id
                    in best_effort_goal_ids
                )
            )

            target_segments = (
                segments_by_target.get(
                    target.id,
                    []
                )
            )

            if (
                target.kind
                == StudyTargetKind.MATERIAL
            ):
                minimum_increment = (
                    self
                    ._material_minimum_increment(
                        target
                    )
                )

                mandatory_positions = (
                    mandatory_material_positions.get(
                        target.id,
                        set(),
                    )
                )

                physical_remaining = (
                    self
                    ._material_remaining_capacity(
                        target=target,
                        mandatory_positions=(
                            mandatory_positions
                        ),
                        preferred_minutes=max(
                            policy.normal_minutes,
                            minimum_increment,
                        ),
                    )
                )

                best_effort_capacity = (
                    self
                    ._material_best_effort_capacity(
                        target=target,
                        segments=target_segments,
                        strict_goal_ids=(
                            strict_goal_ids
                        ),
                        best_effort_goal_ids=(
                            best_effort_goal_ids
                        ),
                        mandatory_positions=(
                            mandatory_positions
                        ),
                        preferred_minutes=max(
                            policy.normal_minutes,
                            minimum_increment,
                        ),
                    )
                )

                desired_maximum = max(
                    normal_remaining,
                    best_effort_capacity,
                )

                maximum_optional = min(
                    desired_maximum,
                    physical_remaining,
                )

            elif (
                target.kind
                == StudyTargetKind.THEME
            ):
                minimum_increment = (
                    THEME_MINIMUM_OPTIONAL_MINUTES
                )

                best_effort_capacity = (
                    self
                    ._theme_best_effort_capacity(
                        segments=target_segments,
                        strict_goal_ids=(
                            strict_goal_ids
                        ),
                        best_effort_goal_ids=(
                            best_effort_goal_ids
                        ),
                    )
                )

                desired_maximum = max(
                    normal_remaining,
                    best_effort_capacity,
                )

                target_minutes_values = [
                    goal.target_minutes
                    for goal
                    in goals_by_target.get(
                        target.id,
                        [],
                    )
                    if (
                        goal.target_minutes
                        is not None
                    )
                ]

                if target_minutes_values:
                    completed = (
                        theme_completed.get(
                            target.id,
                            0,
                        )
                    )

                    remaining_target_minutes = max(
                        0,
                        max(
                            target_minutes_values
                        )
                        - completed
                        - mandatory_minutes,
                    )

                    maximum_optional = min(
                        desired_maximum,
                        self._floor_to_grid(
                            remaining_target_minutes
                        ),
                    )

                else:
                    maximum_optional = (
                        desired_maximum
                    )

            else:
                raise DomainValidationError(
                    "unsupported StudyTarget kind"
                )

            maximum_optional = (
                self._floor_to_grid(
                    maximum_optional
                )
            )

            if (
                maximum_optional
                < minimum_increment
            ):
                maximum_optional = 0

            if maximum_optional == 0:
                continue

            bounds.append(
                OptionalAllocationBounds(
                    study_target_id=target.id,
                    minimum_optional_increment_minutes=(
                        minimum_increment
                    ),
                    maximum_optional_minutes=(
                        maximum_optional
                    ),
                    normal_target_minutes=(
                        normal_target_minutes
                    ),
                    mandatory_scheduled_minutes=(
                        mandatory_minutes
                    ),
                    best_effort_goal_ids=(
                        target_best_effort_goal_ids
                    ),
                )
            )

        raw_soft_capacity = sum(
            slot.duration_minutes
            for slot in remaining_free_slots
        )

        useful_optional_capacity = sum(
            bound.maximum_optional_minutes
            for bound in bounds
        )

        total_soft_capacity = min(
            raw_soft_capacity,
            useful_optional_capacity,
        )

        total_soft_capacity = (
            self._floor_to_grid(
                total_soft_capacity
            )
        )

        capacity_by_day: dict[
            date,
            int,
        ] = {}

        for slot in remaining_free_slots:
            study_day = to_jst(
                slot.start_at
            ).date()

            capacity_by_day[
                study_day
            ] = (
                capacity_by_day.get(
                    study_day,
                    0,
                )
                + slot.duration_minutes
            )

        daily_capacity = tuple(
            DailySoftCapacity(
                day=day,
                minutes=minutes,
            )
            for day, minutes
            in sorted(
                capacity_by_day.items()
            )
        )

        return PlanningAIContext(
            bounds=tuple(
                bounds
            ),
            total_soft_capacity_minutes=(
                total_soft_capacity
            ),
            daily_remaining_capacity=(
                daily_capacity
            ),
        )

    @staticmethod
    def _material_minimum_increment(
        target: StudyTarget,
    ) -> int:
        unit_minutes = (
            target
            .estimated_minutes_per_unit
        )

        if (
            unit_minutes is None
            or unit_minutes <= 0
        ):
            raise DomainValidationError(
                "MATERIAL StudyTarget requires "
                "positive "
                "estimated_minutes_per_unit"
            )

        return scheduled_duration_minutes(
            unit_minutes
        )

    def _material_remaining_capacity(
        self,
        *,
        target: StudyTarget,
        mandatory_positions: set[int],
        preferred_minutes: int,
    ) -> int:
        positions = (
            self._remaining_material_positions(
                target
            )
        )

        positions = [
            position
            for position in positions
            if position
            not in mandatory_positions
        ]

        return self._canonical_material_cost(
            target=target,
            positions=positions,
            preferred_minutes=(
                preferred_minutes
            ),
        )

    def _material_best_effort_capacity(
        self,
        *,
        target: StudyTarget,
        segments: Sequence[
            WorkSegment
        ],
        strict_goal_ids: set[int],
        best_effort_goal_ids: set[int],
        mandatory_positions: set[int],
        preferred_minutes: int,
    ) -> int:
        positions: set[int] = set()

        for segment in segments:
            if (
                segment.kind
                != StudyTargetKind.MATERIAL
            ):
                continue

            segment_goal_ids = set(
                segment.required_by_goal_ids
            )

            if (
                segment_goal_ids
                & strict_goal_ids
            ):
                # shared STRICT/BEST workは
                # mandatory側ですでに配置される。
                continue

            if not (
                segment_goal_ids
                & best_effort_goal_ids
            ):
                continue

            if (
                segment.range_start is None
                or segment.range_end is None
            ):
                raise DomainValidationError(
                    "MATERIAL WorkSegment "
                    "requires range"
                )

            positions.update(
                range(
                    segment.range_start,
                    segment.range_end + 1,
                )
            )

        positions.difference_update(
            mandatory_positions
        )

        return self._canonical_material_cost(
            target=target,
            positions=sorted(
                positions
            ),
            preferred_minutes=(
                preferred_minutes
            ),
        )

    @staticmethod
    def _theme_best_effort_capacity(
        *,
        segments: Sequence[
            WorkSegment
        ],
        strict_goal_ids: set[int],
        best_effort_goal_ids: set[int],
    ) -> int:
        minutes = 0.0

        for segment in segments:
            if (
                segment.kind
                != StudyTargetKind.THEME
            ):
                continue

            segment_goal_ids = set(
                segment.required_by_goal_ids
            )

            if (
                segment_goal_ids
                & strict_goal_ids
            ):
                continue

            if not (
                segment_goal_ids
                & best_effort_goal_ids
            ):
                continue

            minutes += (
                segment.estimated_minutes
            )

        return (
            OptionalAllocationContextBuilder
            ._floor_to_grid(
                int(
                    math.floor(
                        minutes
                        + 1e-9
                    )
                )
            )
        )

    @staticmethod
    def _remaining_material_positions(
        target: StudyTarget,
    ) -> list[int]:
        if target.next_position is None:
            raise DomainValidationError(
                "MATERIAL StudyTarget "
                "requires next_position"
            )

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
                    raise DomainValidationError(
                        "StudyTarget ranges "
                        "must not overlap"
                    )

                seen.add(
                    position
                )

                path.append(
                    position
                )

        if not path:
            return []

        try:
            current_index = path.index(
                target.next_position
            )

        except ValueError:
            if (
                target.next_position
                == path[-1] + 1
            ):
                return []

            raise DomainValidationError(
                "next_position must be "
                "on the ordered path"
            )

        return path[
            current_index:
        ]

    @staticmethod
    def _canonical_material_cost(
        *,
        target: StudyTarget,
        positions: Sequence[int],
        preferred_minutes: int,
    ) -> int:
        if not positions:
            return 0

        unit_minutes = (
            target
            .estimated_minutes_per_unit
        )

        if (
            unit_minutes is None
            or unit_minutes <= 0
        ):
            raise DomainValidationError(
                "MATERIAL StudyTarget requires "
                "estimated_minutes_per_unit"
            )

        preferred = max(
            preferred_minutes,
            scheduled_duration_minutes(
                unit_minutes
            ),
        )

        ordered = sorted(
            set(
                positions
            )
        )

        contiguous_blocks: list[
            list[int]
        ] = []

        current_block: list[int] = []

        for position in ordered:
            if (
                current_block
                and position
                != current_block[-1] + 1
            ):
                contiguous_blocks.append(
                    current_block
                )

                current_block = []

            current_block.append(
                position
            )

        if current_block:
            contiguous_blocks.append(
                current_block
            )

        total = 0

        for block in contiguous_blocks:
            cursor = 0

            while cursor < len(
                block
            ):
                unit_count = 0

                while (
                    cursor + unit_count
                    < len(block)
                ):
                    candidate_count = (
                        unit_count + 1
                    )

                    candidate_duration = (
                        scheduled_duration_minutes(
                            candidate_count
                            * unit_minutes
                        )
                    )

                    if (
                        candidate_duration
                        > preferred
                        and unit_count
                        > 0
                    ):
                        break

                    if (
                        candidate_duration
                        > preferred
                        and unit_count
                        == 0
                    ):
                        unit_count = 1
                        break

                    unit_count = (
                        candidate_count
                    )

                estimated = (
                    unit_count
                    * unit_minutes
                )

                total += (
                    scheduled_duration_minutes(
                        estimated
                    )
                )

                cursor += (
                    unit_count
                )

        return total

    @staticmethod
    def _floor_to_grid(
        value: int,
    ) -> int:
        if value <= 0:
            return 0

        return (
            value
            - value
            % TIME_GRID_MINUTES
        )