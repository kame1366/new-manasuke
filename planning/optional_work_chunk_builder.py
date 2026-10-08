from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime

from ai.planning_models import (
    PlanningOutput,
)
from domain.enums import (
    StudyTargetKind,
)
from domain.errors import (
    DomainValidationError,
)
from domain.models import (
    LearningPolicy,
    StudyTarget,
)
from domain.time_rules import (
    ensure_aware,
    to_jst,
)
from planning.work_chunk_builder import (
    WorkChunk,
    scheduled_duration_minutes,
)
from planning.work_segment_builder import (
    WorkSegment,
)


class OptionalWorkChunkBuilder:
    """
    validated AI② allocationを
    concrete optional WorkChunkへ変換する。

    AIはStudyTarget単位まで。
    具体的work selectionはPython。
    """

    def build(
        self,
        *,
        output: PlanningOutput,
        study_targets: Sequence[
            StudyTarget
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
        not_before: datetime,
        theme_completed_minutes_by_target: Mapping[
            int,
            int,
        ]
        | None = None,
    ) -> list[
        WorkChunk
    ]:
        ensure_aware(
            not_before
        )

        targets_by_id = {
            target.id: target
            for target in study_targets
        }

        policies_by_target = {
            policy.study_target_id: policy
            for policy in learning_policies
        }

        theme_completed = dict(
            theme_completed_minutes_by_target
            or {}
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

        mandatory_by_target: dict[
            int,
            list[WorkChunk],
        ] = {}

        for chunk in mandatory_chunks:
            mandatory_by_target.setdefault(
                chunk.study_target_id,
                [],
            ).append(
                chunk
            )

        result: list[
            WorkChunk
        ] = []

        allocations = sorted(
            output.allocations,
            key=lambda item: (
                item.planning_priority_rank,
                item.study_target_id,
            ),
        )

        for allocation in allocations:
            if (
                allocation
                .optional_extra_minutes
                == 0
            ):
                continue

            target = targets_by_id.get(
                allocation.study_target_id
            )

            if target is None:
                raise DomainValidationError(
                    "allocation references "
                    "unknown StudyTarget"
                )

            policy = (
                policies_by_target.get(
                    target.id
                )
            )

            if policy is None:
                raise DomainValidationError(
                    "LearningPolicy missing "
                    "for optional allocation"
                )

            target_mandatory = (
                mandatory_by_target.get(
                    target.id,
                    [],
                )
            )

            starting_sequence_no = (
                self._next_sequence_no(
                    target_mandatory
                )
            )

            if (
                target.kind
                == StudyTargetKind.MATERIAL
            ):
                built = (
                    self
                    ._build_material_optional(
                        target=target,
                        policy=policy,
                        allocation_minutes=(
                            allocation
                            .optional_extra_minutes
                        ),
                        planning_priority_rank=(
                            allocation
                            .planning_priority_rank
                        ),
                        segments=(
                            segments_by_target.get(
                                target.id,
                                [],
                            )
                        ),
                        strict_goal_ids=(
                            strict_goal_ids
                        ),
                        best_effort_goal_ids=(
                            best_effort_goal_ids
                        ),
                        mandatory_chunks=(
                            target_mandatory
                        ),
                        starting_sequence_no=(
                            starting_sequence_no
                        ),
                        not_before=to_jst(
                            not_before
                        ),
                    )
                )

            elif (
                target.kind
                == StudyTargetKind.THEME
            ):
                built = (
                    self
                    ._build_theme_optional(
                        target=target,
                        policy=policy,
                        allocation_minutes=(
                            allocation
                            .optional_extra_minutes
                        ),
                        planning_priority_rank=(
                            allocation
                            .planning_priority_rank
                        ),
                        segments=(
                            segments_by_target.get(
                                target.id,
                                [],
                            )
                        ),
                        best_effort_goal_ids=(
                            best_effort_goal_ids
                        ),
                        mandatory_chunks=(
                            target_mandatory
                        ),
                        starting_sequence_no=(
                            starting_sequence_no
                        ),
                        not_before=to_jst(
                            not_before
                        ),
                        completed_minutes=(
                            theme_completed.get(
                                target.id,
                                0,
                            )
                        ),
                    )
                )

            else:
                raise DomainValidationError(
                    "unsupported StudyTarget kind"
                )

            result.extend(
                built
            )

        return result

    def _build_material_optional(
        self,
        *,
        target: StudyTarget,
        policy: LearningPolicy,
        allocation_minutes: int,
        planning_priority_rank: int,
        segments: Sequence[
            WorkSegment
        ],
        strict_goal_ids: set[int],
        best_effort_goal_ids: set[int],
        mandatory_chunks: Sequence[
            WorkChunk
        ],
        starting_sequence_no: int,
        not_before: datetime,
    ) -> list[
        WorkChunk
    ]:
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

        path = (
            self._remaining_material_path(
                target
            )
        )

        mandatory_positions: set[
            int
        ] = set()

        for chunk in mandatory_chunks:
            if (
                chunk.range_start
                is None
                or chunk.range_end
                is None
            ):
                continue

            mandatory_positions.update(
                range(
                    chunk.range_start,
                    chunk.range_end + 1,
                )
            )

        available_positions = [
            position
            for position in path
            if position
            not in mandatory_positions
        ]

        best_effort_positions: set[
            int
        ] = set()

        for segment in segments:
            if (
                segment.kind
                != StudyTargetKind.MATERIAL
            ):
                continue

            goal_ids = set(
                segment.required_by_goal_ids
            )

            if goal_ids & strict_goal_ids:
                continue

            if not (
                goal_ids
                & best_effort_goal_ids
            ):
                continue

            if (
                segment.range_start is None
                or segment.range_end is None
            ):
                continue

            best_effort_positions.update(
                range(
                    segment.range_start,
                    segment.range_end + 1,
                )
            )

        self._ensure_best_effort_is_prefix(
            available_positions=(
                available_positions
            ),
            best_effort_positions=(
                best_effort_positions
            ),
        )

        preferred_minutes = max(
            policy.normal_minutes,
            scheduled_duration_minutes(
                unit_minutes
            ),
        )

        remaining_budget = (
            allocation_minutes
        )

        chunks: list[
            WorkChunk
        ] = []

        cursor = 0
        local_index = 0

        while (
            cursor
            < len(
                available_positions
            )
        ):
            if remaining_budget < (
                scheduled_duration_minutes(
                    unit_minutes
                )
            ):
                break

            block_end = cursor + 1

            while (
                block_end
                < len(
                    available_positions
                )
                and available_positions[
                    block_end
                ]
                == available_positions[
                    block_end - 1
                ] + 1
            ):
                block_end += 1

            block = available_positions[
                cursor:block_end
            ]

            block_cursor = 0

            while (
                block_cursor
                < len(block)
            ):
                chunk_budget = min(
                    preferred_minutes,
                    remaining_budget,
                )

                unit_count = (
                    self._largest_units_that_fit(
                        unit_minutes=(
                            unit_minutes
                        ),
                        maximum_units=(
                            len(block)
                            - block_cursor
                        ),
                        budget_minutes=(
                            chunk_budget
                        ),
                    )
                )

                if unit_count == 0:
                    break

                range_start = block[
                    block_cursor
                ]

                range_end = block[
                    block_cursor
                    + unit_count
                    - 1
                ]

                estimated = (
                    unit_count
                    * unit_minutes
                )

                scheduled = (
                    scheduled_duration_minutes(
                        estimated
                    )
                )

                required_goal_ids = (
                    self
                    ._material_goal_ids_for_range(
                        range_start=(
                            range_start
                        ),
                        range_end=(
                            range_end
                        ),
                        segments=segments,
                        best_effort_goal_ids=(
                            best_effort_goal_ids
                        ),
                    )
                )

                sequence_no = (
                    starting_sequence_no
                    + local_index
                )

                chunks.append(
                    WorkChunk(
                        chunk_id=(
                            f"{target.id}:"
                            f"{sequence_no:04d}:"
                            f"OPT-M:"
                            f"{range_start}-"
                            f"{range_end}"
                        ),
                        study_target_id=(
                            target.id
                        ),
                        kind=(
                            StudyTargetKind
                            .MATERIAL
                        ),
                        estimated_minutes=(
                            estimated
                        ),
                        scheduled_duration_minutes=(
                            scheduled
                        ),
                        sequence_no=(
                            sequence_no
                        ),
                        mandatory=False,
                        required_by_goal_ids=(
                            required_goal_ids
                        ),
                        not_before=(
                            not_before
                        ),
                        planning_priority_rank=(
                            planning_priority_rank
                        ),
                        range_start=(
                            range_start
                        ),
                        range_end=(
                            range_end
                        ),
                    )
                )

                remaining_budget -= (
                    scheduled
                )

                block_cursor += (
                    unit_count
                )

                local_index += 1

            if (
                block_cursor
                < len(block)
            ):
                # 残budgetでは次unitが
                # 収まらない。
                break

            cursor = block_end

        return chunks

    def _build_theme_optional(
        self,
        *,
        target: StudyTarget,
        policy: LearningPolicy,
        allocation_minutes: int,
        planning_priority_rank: int,
        segments: Sequence[
            WorkSegment
        ],
        best_effort_goal_ids: set[int],
        mandatory_chunks: Sequence[
            WorkChunk
        ],
        starting_sequence_no: int,
        not_before: datetime,
        completed_minutes: int,
    ) -> list[
        WorkChunk
    ]:
        if completed_minutes < 0:
            raise DomainValidationError(
                "completed theme minutes "
                "must be non-negative"
            )

        offset = (
            completed_minutes
        )

        for chunk in mandatory_chunks:
            if (
                chunk.theme_minute_end
                is not None
            ):
                offset = max(
                    offset,
                    chunk.theme_minute_end,
                )

        sizes = (
            self._split_theme_budget(
                total_minutes=(
                    allocation_minutes
                ),
                preferred_minutes=max(
                    policy.normal_minutes,
                    10,
                ),
            )
        )

        chunks: list[
            WorkChunk
        ] = []

        cursor = offset

        for local_index, size in enumerate(
            sizes
        ):
            end = cursor + size

            required_goal_ids = (
                self
                ._theme_goal_ids_for_interval(
                    start=cursor,
                    end=end,
                    segments=segments,
                    best_effort_goal_ids=(
                        best_effort_goal_ids
                    ),
                )
            )

            sequence_no = (
                starting_sequence_no
                + local_index
            )

            chunks.append(
                WorkChunk(
                    chunk_id=(
                        f"{target.id}:"
                        f"{sequence_no:04d}:"
                        f"OPT-T:{cursor}-{end}"
                    ),
                    study_target_id=(
                        target.id
                    ),
                    kind=(
                        StudyTargetKind.THEME
                    ),
                    estimated_minutes=float(
                        size
                    ),
                    scheduled_duration_minutes=(
                        size
                    ),
                    sequence_no=(
                        sequence_no
                    ),
                    mandatory=False,
                    required_by_goal_ids=(
                        required_goal_ids
                    ),
                    not_before=(
                        not_before
                    ),
                    planning_priority_rank=(
                        planning_priority_rank
                    ),
                    theme_minute_start=(
                        cursor
                    ),
                    theme_minute_end=(
                        end
                    ),
                )
            )

            cursor = end

        return chunks

    @staticmethod
    def _remaining_material_path(
        target: StudyTarget,
    ) -> list[int]:
        if target.next_position is None:
            raise DomainValidationError(
                "MATERIAL StudyTarget requires "
                "next_position"
            )

        path: list[int] = []

        for target_range in sorted(
            target.ranges,
            key=lambda item: (
                item.sequence_no
            ),
        ):
            path.extend(
                range(
                    target_range.start_position,
                    target_range.end_position
                    + 1,
                )
            )

        if not path:
            return []

        try:
            index = path.index(
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
                "on Material ordered path"
            )

        return path[index:]

    @staticmethod
    def _largest_units_that_fit(
        *,
        unit_minutes: float,
        maximum_units: int,
        budget_minutes: int,
    ) -> int:
        result = 0

        for unit_count in range(
            1,
            maximum_units + 1,
        ):
            scheduled = (
                scheduled_duration_minutes(
                    unit_count
                    * unit_minutes
                )
            )

            if scheduled > budget_minutes:
                break

            result = unit_count

        return result

    @staticmethod
    def _ensure_best_effort_is_prefix(
        *,
        available_positions: Sequence[
            int
        ],
        best_effort_positions: set[int],
    ) -> None:
        seen_normal = False

        for position in available_positions:
            is_best_effort = (
                position
                in best_effort_positions
            )

            if not is_best_effort:
                seen_normal = True
                continue

            if seen_normal:
                raise DomainValidationError(
                    "BEST_EFFORT Material work "
                    "must remain an ordered prefix"
                )

    @staticmethod
    def _material_goal_ids_for_range(
        *,
        range_start: int,
        range_end: int,
        segments: Sequence[
            WorkSegment
        ],
        best_effort_goal_ids: set[int],
    ) -> tuple[int, ...]:
        result: set[int] = set()

        for segment in segments:
            if (
                segment.kind
                != StudyTargetKind.MATERIAL
            ):
                continue

            if (
                segment.range_start is None
                or segment.range_end is None
            ):
                continue

            overlaps = not (
                segment.range_end
                < range_start
                or segment.range_start
                > range_end
            )

            if not overlaps:
                continue

            result.update(
                set(
                    segment.required_by_goal_ids
                )
                & best_effort_goal_ids
            )

        return tuple(
            sorted(
                result
            )
        )

    @staticmethod
    def _theme_goal_ids_for_interval(
        *,
        start: int,
        end: int,
        segments: Sequence[
            WorkSegment
        ],
        best_effort_goal_ids: set[int],
    ) -> tuple[int, ...]:
        result: set[int] = set()

        for segment in segments:
            if (
                segment.kind
                != StudyTargetKind.THEME
            ):
                continue

            if (
                segment.theme_minute_start
                is None
                or segment.theme_minute_end
                is None
            ):
                continue

            overlaps = not (
                segment.theme_minute_end
                <= start
                or segment.theme_minute_start
                >= end
            )

            if not overlaps:
                continue

            result.update(
                set(
                    segment.required_by_goal_ids
                )
                & best_effort_goal_ids
            )

        return tuple(
            sorted(
                result
            )
        )

    @staticmethod
    def _split_theme_budget(
        *,
        total_minutes: int,
        preferred_minutes: int,
    ) -> list[int]:
        if total_minutes == 0:
            return []

        if (
            total_minutes < 10
            or total_minutes % 5 != 0
        ):
            raise DomainValidationError(
                "Theme optional budget must "
                "be >=10 and multiple of 5"
            )

        preferred = max(
            10,
            preferred_minutes
            - preferred_minutes % 5,
        )

        remaining = (
            total_minutes
        )

        result: list[int] = []

        while remaining > 0:
            if remaining <= preferred:
                size = remaining

            else:
                size = preferred

                remainder = (
                    remaining
                    - size
                )

                if (
                    0
                    < remainder
                    < 10
                ):
                    size -= (
                        10
                        - remainder
                    )

            if size < 10:
                raise DomainValidationError(
                    "cannot split Theme "
                    "optional budget into "
                    "valid WorkChunks"
                )

            result.append(
                size
            )

            remaining -= size

        return result

    @staticmethod
    def _next_sequence_no(
        chunks: Sequence[
            WorkChunk
        ],
    ) -> int:
        if not chunks:
            return 0

        return (
            max(
                chunk.sequence_no
                for chunk in chunks
            )
            + 1
        )