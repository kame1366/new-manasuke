from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from domain.enums import StudyTargetKind
from domain.errors import DomainValidationError
from domain.models import Goal, StudyTarget
from domain.time_rules import ensure_aware, to_jst
from planning.work_segment_builder import WorkSegment


SCHEDULER_MINIMUM_MINUTES = 10
TIME_GRID_MINUTES = 5


@dataclass(
    frozen=True,
    slots=True,
)
class WorkChunk:
    """
    Schedulerへ渡す配置可能な作業単位。

    DBへ保存しない派生オブジェクト。

    estimated_minutes:
        実際の推定作業量。

    scheduled_duration_minutes:
        calendar上で確保する時間。
        5分単位。

    sequence_no:
        同じStudyTarget内での順番。
        特にMATERIAL precedenceに使用する。
    """

    chunk_id: str

    study_target_id: int
    kind: StudyTargetKind

    estimated_minutes: float
    scheduled_duration_minutes: int

    sequence_no: int

    mandatory: bool

    required_by_goal_ids: tuple[int, ...]

    must_finish_before: datetime | None = None
    not_before: datetime | None = None

    planning_priority_rank: int | None = None

    range_start: int | None = None
    range_end: int | None = None

    theme_minute_start: int | None = None
    theme_minute_end: int | None = None

    def __post_init__(self) -> None:
        if not self.chunk_id.strip():
            raise DomainValidationError(
                "WorkChunk chunk_id must not be empty"
            )

        if self.estimated_minutes <= 0:
            raise DomainValidationError(
                "WorkChunk estimated_minutes must be positive"
            )

        if (
            self.scheduled_duration_minutes
            < SCHEDULER_MINIMUM_MINUTES
        ):
            raise DomainValidationError(
                "WorkChunk scheduled duration "
                "must be at least 10 minutes"
            )

        if (
            self.scheduled_duration_minutes
            % TIME_GRID_MINUTES
            != 0
        ):
            raise DomainValidationError(
                "WorkChunk scheduled duration "
                "must be a multiple of 5"
            )

        if self.sequence_no < 0:
            raise DomainValidationError(
                "WorkChunk sequence_no must be non-negative"
            )

        if (
            self.planning_priority_rank is not None
            and self.planning_priority_rank < 1
        ):
            raise DomainValidationError(
                "planning_priority_rank must be positive"
            )

        if self.not_before is not None:
            ensure_aware(
                self.not_before
            )

        if self.must_finish_before is not None:
            ensure_aware(
                self.must_finish_before
            )

        if (
            self.not_before is not None
            and self.must_finish_before is not None
            and self.not_before
            >= self.must_finish_before
        ):
            raise DomainValidationError(
                "WorkChunk not_before must be "
                "earlier than must_finish_before"
            )

        required_goal_ids = set(
            self.required_by_goal_ids
        )

        if len(required_goal_ids) != len(
            self.required_by_goal_ids
        ):
            raise DomainValidationError(
                "required_by_goal_ids "
                "must not contain duplicates"
            )

        if self.kind == StudyTargetKind.MATERIAL:
            if (
                self.range_start is None
                or self.range_end is None
            ):
                raise DomainValidationError(
                    "MATERIAL WorkChunk requires range"
                )

            if self.range_start > self.range_end:
                raise DomainValidationError(
                    "range_start must be <= range_end"
                )

            if (
                self.theme_minute_start is not None
                or self.theme_minute_end is not None
            ):
                raise DomainValidationError(
                    "MATERIAL WorkChunk must not "
                    "have theme minute offsets"
                )

        elif self.kind == StudyTargetKind.THEME:
            if (
                self.theme_minute_start is None
                or self.theme_minute_end is None
            ):
                raise DomainValidationError(
                    "THEME WorkChunk requires "
                    "theme minute offsets"
                )

            if (
                self.theme_minute_start
                >= self.theme_minute_end
            ):
                raise DomainValidationError(
                    "theme_minute_start must be "
                    "earlier than theme_minute_end"
                )

            if (
                self.range_start is not None
                or self.range_end is not None
            ):
                raise DomainValidationError(
                    "THEME WorkChunk must not "
                    "have Material range"
                )

        else:
            raise DomainValidationError(
                f"unsupported StudyTarget kind: {self.kind}"
            )


def scheduled_duration_minutes(
    estimated_minutes: float,
) -> int:
    """
    calendar上でSchedulerが確保する時間へ変換する。

    ceil5(max(estimated_minutes, 10))

    例:
        6  -> 10
        10 -> 10
        12 -> 15
        18 -> 20
    """
    if estimated_minutes <= 0:
        raise DomainValidationError(
            "estimated_minutes must be positive"
        )

    minimum_applied = max(
        estimated_minutes,
        float(
            SCHEDULER_MINIMUM_MINUTES
        ),
    )

    return int(
        math.ceil(
            minimum_applied
            / TIME_GRID_MINUTES
            - 1e-12
        )
        * TIME_GRID_MINUTES
    )


class WorkChunkBuilder:
    """
    正規化済みWorkSegmentを
    Scheduler用WorkChunkへ変換する。

    今回はdeadline Hard requirement用の
    mandatory WorkChunkを構築する。

    BEST_EFFORTのみへ貢献するWorkは
    mandatoryには含めない。
    """

    def build_mandatory_deadline_chunks(
        self,
        *,
        study_targets: Sequence[
            StudyTarget
        ],
        goals: Sequence[Goal],
        work_segments: Sequence[
            WorkSegment
        ],
        strict_goal_ids: set[int],
        preferred_chunk_minutes_by_target: Mapping[
            int,
            int,
        ],
        not_before: datetime,
    ) -> list[WorkChunk]:
        ensure_aware(
            not_before
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

        unknown_strict_ids = (
            strict_goal_ids
            - set(goals_by_id)
        )

        if unknown_strict_ids:
            raise DomainValidationError(
                "strict_goal_ids contains "
                "unknown Goal id"
            )

        for goal in goals:
            ensure_aware(
                goal.deadline_at
            )

        segments_by_target: dict[
            int,
            list[WorkSegment],
        ] = {}

        for segment in work_segments:
            target = targets_by_id.get(
                segment.study_target_id
            )

            if target is None:
                raise DomainValidationError(
                    "WorkSegment references "
                    "unknown StudyTarget"
                )

            if target.kind != segment.kind:
                raise DomainValidationError(
                    "WorkSegment kind does not match "
                    "StudyTarget kind"
                )

            segments_by_target.setdefault(
                target.id,
                [],
            ).append(
                segment
            )

        chunks: list[
            WorkChunk
        ] = []

        for target in sorted(
            study_targets,
            key=lambda item: item.id,
        ):
            target_segments = (
                segments_by_target.get(
                    target.id,
                    [],
                )
            )

            if not target_segments:
                continue

            preferred_minutes = (
                preferred_chunk_minutes_by_target.get(
                    target.id
                )
            )

            if preferred_minutes is None:
                raise DomainValidationError(
                    "preferred chunk minutes missing "
                    f"for StudyTarget {target.id}"
                )

            if preferred_minutes < 0:
                raise DomainValidationError(
                    "preferred chunk minutes "
                    "must be non-negative"
                )

            if (
                preferred_minutes
                % TIME_GRID_MINUTES
                != 0
            ):
                raise DomainValidationError(
                    "preferred chunk minutes "
                    "must be a multiple of 5"
                )

            preferred_minutes = max(
                preferred_minutes,
                SCHEDULER_MINIMUM_MINUTES,
            )

            ordered_segments = (
                self._sort_segments(
                    target,
                    target_segments,
                )
            )

            sequence_no = 0

            for segment in ordered_segments:
                relevant_goal_ids = tuple(
                    sorted(
                        set(
                            segment
                            .required_by_goal_ids
                        )
                        & strict_goal_ids
                    )
                )

                if not relevant_goal_ids:
                    continue

                deadline = min(
                    to_jst(
                        goals_by_id[
                            goal_id
                        ].deadline_at
                    )
                    for goal_id
                    in relevant_goal_ids
                )

                if target.kind == StudyTargetKind.MATERIAL:
                    built = (
                        self._build_material_chunks(
                            target=target,
                            segment=segment,
                            required_goal_ids=(
                                relevant_goal_ids
                            ),
                            deadline=deadline,
                            not_before=to_jst(
                                not_before
                            ),
                            preferred_minutes=(
                                preferred_minutes
                            ),
                            starting_sequence_no=(
                                sequence_no
                            ),
                        )
                    )

                else:
                    built = (
                        self._build_theme_chunks(
                            target=target,
                            segment=segment,
                            required_goal_ids=(
                                relevant_goal_ids
                            ),
                            deadline=deadline,
                            not_before=to_jst(
                                not_before
                            ),
                            preferred_minutes=(
                                preferred_minutes
                            ),
                            starting_sequence_no=(
                                sequence_no
                            ),
                        )
                    )

                chunks.extend(
                    built
                )

                sequence_no += len(
                    built
                )

        return chunks

    @staticmethod
    def _sort_segments(
        target: StudyTarget,
        segments: Sequence[
            WorkSegment
        ],
    ) -> list[WorkSegment]:
        if target.kind == StudyTargetKind.THEME:
            return sorted(
                segments,
                key=lambda segment: (
                    segment.theme_minute_start
                    if segment.theme_minute_start
                    is not None
                    else -1
                ),
            )

        position_order: dict[
            int,
            int,
        ] = {}

        position_index = 0

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
                position_order[
                    position
                ] = position_index

                position_index += 1

        def key(
            segment: WorkSegment,
        ) -> int:
            if segment.range_start is None:
                raise DomainValidationError(
                    "MATERIAL WorkSegment "
                    "requires range_start"
                )

            index = position_order.get(
                segment.range_start
            )

            if index is None:
                raise DomainValidationError(
                    "WorkSegment range is outside "
                    "StudyTarget path"
                )

            return index

        return sorted(
            segments,
            key=key,
        )

    @staticmethod
    def _build_material_chunks(
        *,
        target: StudyTarget,
        segment: WorkSegment,
        required_goal_ids: tuple[
            int,
            ...,
        ],
        deadline: datetime,
        not_before: datetime,
        preferred_minutes: int,
        starting_sequence_no: int,
    ) -> list[WorkChunk]:
        if (
            target.estimated_minutes_per_unit
            is None
        ):
            raise DomainValidationError(
                "MATERIAL StudyTarget requires "
                "estimated_minutes_per_unit"
            )

        if (
            segment.range_start is None
            or segment.range_end is None
        ):
            raise DomainValidationError(
                "MATERIAL WorkSegment requires range"
            )

        unit_minutes = (
            target.estimated_minutes_per_unit
        )

        if unit_minutes <= 0:
            raise DomainValidationError(
                "estimated_minutes_per_unit "
                "must be positive"
            )

        units_per_chunk = max(
            1,
            int(
                math.floor(
                    preferred_minutes
                    / unit_minutes
                    + 1e-12
                )
            ),
        )

        chunks: list[
            WorkChunk
        ] = []

        cursor = (
            segment.range_start
        )

        local_index = 0

        while cursor <= segment.range_end:
            chunk_end = min(
                cursor
                + units_per_chunk
                - 1,
                segment.range_end,
            )

            unit_count = (
                chunk_end
                - cursor
                + 1
            )

            estimated = (
                unit_count
                * unit_minutes
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
                        f"M:{cursor}-{chunk_end}"
                    ),
                    study_target_id=(
                        target.id
                    ),
                    kind=(
                        StudyTargetKind.MATERIAL
                    ),
                    estimated_minutes=(
                        estimated
                    ),
                    scheduled_duration_minutes=(
                        scheduled_duration_minutes(
                            estimated
                        )
                    ),
                    sequence_no=(
                        sequence_no
                    ),
                    mandatory=True,
                    required_by_goal_ids=(
                        required_goal_ids
                    ),
                    must_finish_before=(
                        deadline
                    ),
                    not_before=(
                        not_before
                    ),
                    range_start=cursor,
                    range_end=chunk_end,
                )
            )

            cursor = (
                chunk_end + 1
            )

            local_index += 1

        return chunks

    @staticmethod
    def _build_theme_chunks(
        *,
        target: StudyTarget,
        segment: WorkSegment,
        required_goal_ids: tuple[
            int,
            ...,
        ],
        deadline: datetime,
        not_before: datetime,
        preferred_minutes: int,
        starting_sequence_no: int,
    ) -> list[WorkChunk]:
        if (
            segment.theme_minute_start
            is None
            or segment.theme_minute_end
            is None
        ):
            raise DomainValidationError(
                "THEME WorkSegment requires "
                "theme minute offsets"
            )

        chunks: list[
            WorkChunk
        ] = []

        cursor = (
            segment.theme_minute_start
        )

        local_index = 0

        while (
            cursor
            < segment.theme_minute_end
        ):
            chunk_end = min(
                cursor
                + preferred_minutes,
                segment.theme_minute_end,
            )

            estimated = float(
                chunk_end
                - cursor
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
                        f"T:{cursor}-{chunk_end}"
                    ),
                    study_target_id=(
                        target.id
                    ),
                    kind=(
                        StudyTargetKind.THEME
                    ),
                    estimated_minutes=(
                        estimated
                    ),
                    scheduled_duration_minutes=(
                        scheduled_duration_minutes(
                            estimated
                        )
                    ),
                    sequence_no=(
                        sequence_no
                    ),
                    mandatory=True,
                    required_by_goal_ids=(
                        required_goal_ids
                    ),
                    must_finish_before=(
                        deadline
                    ),
                    not_before=(
                        not_before
                    ),
                    theme_minute_start=(
                        cursor
                    ),
                    theme_minute_end=(
                        chunk_end
                    ),
                )
            )

            cursor = chunk_end

            local_index += 1

        return chunks