from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias

from domain.enums import StudyTargetKind
from domain.errors import DomainValidationError
from domain.models import Goal, StudyTarget


@dataclass(
    frozen=True,
    slots=True,
)
class WorkSegment:
    """
    正規化された物理Work。

    DBへ保存しない派生オブジェクト。

    MATERIAL:
        range_start / range_end を使用する。

    THEME:
        theme_minute_start / theme_minute_end を使用する。

    required_by_goal_ids:
        このWorkを完了する必要があるGoal。
        prerequisiteとして必要なGoalも含む。

    direct_goal_ids:
        このWork自体がGoalの直接対象であるGoal。

        MATERIALではprerequisiteとの区別に使用する。
        THEMEではrequired_by_goal_idsと同じになる。
    """

    study_target_id: int
    kind: StudyTargetKind

    estimated_minutes: float

    required_by_goal_ids: tuple[int, ...]
    direct_goal_ids: tuple[int, ...]

    range_start: int | None = None
    range_end: int | None = None

    theme_minute_start: int | None = None
    theme_minute_end: int | None = None

    def __post_init__(self) -> None:
        if self.estimated_minutes <= 0:
            raise DomainValidationError(
                "WorkSegment estimated_minutes must be positive"
            )

        if not self.required_by_goal_ids:
            raise DomainValidationError(
                "WorkSegment must be required by at least one Goal"
            )

        required_set = set(
            self.required_by_goal_ids
        )

        direct_set = set(
            self.direct_goal_ids
        )

        if len(required_set) != len(
            self.required_by_goal_ids
        ):
            raise DomainValidationError(
                "required_by_goal_ids must not contain duplicates"
            )

        if len(direct_set) != len(
            self.direct_goal_ids
        ):
            raise DomainValidationError(
                "direct_goal_ids must not contain duplicates"
            )

        if not direct_set.issubset(
            required_set
        ):
            raise DomainValidationError(
                "direct_goal_ids must be a subset "
                "of required_by_goal_ids"
            )

        if self.kind == StudyTargetKind.MATERIAL:
            if (
                self.range_start is None
                or self.range_end is None
            ):
                raise DomainValidationError(
                    "MATERIAL WorkSegment requires range"
                )

            if (
                self.theme_minute_start is not None
                or self.theme_minute_end is not None
            ):
                raise DomainValidationError(
                    "MATERIAL WorkSegment must not "
                    "have theme minute offsets"
                )

            if self.range_start > self.range_end:
                raise DomainValidationError(
                    "range_start must be <= range_end"
                )

        elif self.kind == StudyTargetKind.THEME:
            if (
                self.theme_minute_start is None
                or self.theme_minute_end is None
            ):
                raise DomainValidationError(
                    "THEME WorkSegment requires "
                    "theme minute offsets"
                )

            if (
                self.range_start is not None
                or self.range_end is not None
            ):
                raise DomainValidationError(
                    "THEME WorkSegment must not "
                    "have Material range"
                )

            if (
                self.theme_minute_start
                >= self.theme_minute_end
            ):
                raise DomainValidationError(
                    "theme_minute_start must be "
                    "earlier than theme_minute_end"
                )

        else:
            raise DomainValidationError(
                f"unsupported StudyTarget kind: {self.kind}"
            )

    @property
    def material_unit_count(self) -> int | None:
        if self.kind != StudyTargetKind.MATERIAL:
            return None

        assert self.range_start is not None
        assert self.range_end is not None

        return (
            self.range_end
            - self.range_start
            + 1
        )

    @property
    def theme_minutes(self) -> int | None:
        if self.kind != StudyTargetKind.THEME:
            return None

        assert self.theme_minute_start is not None
        assert self.theme_minute_end is not None

        return (
            self.theme_minute_end
            - self.theme_minute_start
        )


WorkSegments: TypeAlias = list[
    WorkSegment
]


class WorkSegmentBuilder:
    """
    StudyTarget + Goalから、
    重複を除去したWorkSegmentを構築する。

    MATERIAL:
        ordered learning pathを尊重し、
        Goal Rangeへ到達するための
        prerequisiteもrequired workへ含める。

    THEME:
        target_minutesを累積時間として扱い、
        複数Goal間の時間重複を正規化する。
    """

    def build(
        self,
        *,
        study_targets: Sequence[StudyTarget],
        goals: Sequence[Goal],
        theme_completed_minutes_by_target: Mapping[
            int,
            int,
        ]
        | None = None,
    ) -> WorkSegments:
        completed_theme_minutes = dict(
            theme_completed_minutes_by_target
            or {}
        )

        targets_by_id = self._index_study_targets(
            study_targets
        )

        goals_by_target = self._group_goals_by_target(
            goals,
            targets_by_id,
        )

        segments: list[WorkSegment] = []

        for target in sorted(
            study_targets,
            key=lambda item: item.id,
        ):
            target_goals = goals_by_target.get(
                target.id,
                [],
            )

            if not target_goals:
                continue

            if target.kind == StudyTargetKind.MATERIAL:
                segments.extend(
                    self._build_material_segments(
                        target,
                        target_goals,
                    )
                )

            elif target.kind == StudyTargetKind.THEME:
                completed_minutes = (
                    completed_theme_minutes.get(
                        target.id,
                        0,
                    )
                )

                if completed_minutes < 0:
                    raise DomainValidationError(
                        "theme completed minutes "
                        "must be non-negative"
                    )

                segments.extend(
                    self._build_theme_segments(
                        target,
                        target_goals,
                        completed_minutes,
                    )
                )

            else:
                raise DomainValidationError(
                    f"unsupported StudyTarget kind: "
                    f"{target.kind}"
                )

        return segments

    @staticmethod
    def _index_study_targets(
        study_targets: Sequence[StudyTarget],
    ) -> dict[int, StudyTarget]:
        targets_by_id: dict[
            int,
            StudyTarget,
        ] = {}

        for target in study_targets:
            if target.id in targets_by_id:
                raise DomainValidationError(
                    f"duplicate StudyTarget id: "
                    f"{target.id}"
                )

            targets_by_id[
                target.id
            ] = target

        return targets_by_id

    @staticmethod
    def _group_goals_by_target(
        goals: Sequence[Goal],
        targets_by_id: Mapping[
            int,
            StudyTarget,
        ],
    ) -> dict[int, list[Goal]]:
        goals_by_target: dict[
            int,
            list[Goal],
        ] = {}

        seen_goal_ids: set[int] = set()

        for goal in goals:
            if goal.id in seen_goal_ids:
                raise DomainValidationError(
                    f"duplicate Goal id: {goal.id}"
                )

            seen_goal_ids.add(
                goal.id
            )

            target = targets_by_id.get(
                goal.study_target_id
            )

            if target is None:
                raise DomainValidationError(
                    "Goal references unknown StudyTarget: "
                    f"{goal.study_target_id}"
                )

            if (
                goal.participant_id
                != target.participant_id
            ):
                raise DomainValidationError(
                    "Goal and StudyTarget participant_id "
                    "must match"
                )

            goals_by_target.setdefault(
                target.id,
                [],
            ).append(
                goal
            )

        return goals_by_target

    def _build_material_segments(
        self,
        target: StudyTarget,
        goals: Sequence[Goal],
    ) -> list[WorkSegment]:
        if target.next_position is None:
            raise DomainValidationError(
                "MATERIAL StudyTarget requires next_position"
            )

        if (
            target.estimated_minutes_per_unit
            is None
        ):
            raise DomainValidationError(
                "MATERIAL StudyTarget requires "
                "estimated_minutes_per_unit"
            )

        positions = self._build_material_path(
            target
        )

        if not positions:
            raise DomainValidationError(
                "MATERIAL StudyTarget requires "
                "at least one StudyTargetRange"
            )

        position_to_index = {
            position: index
            for index, position
            in enumerate(positions)
        }

        current_index = self._find_current_index(
            target.next_position,
            positions,
            position_to_index,
        )

        # 教材完了済み
        if current_index >= len(
            positions
        ):
            return []

        required_by: list[
            set[int]
        ] = [
            set()
            for _ in positions
        ]

        direct_goal_ids: list[
            set[int]
        ] = [
            set()
            for _ in positions
        ]

        for goal in goals:
            if not goal.ranges:
                raise DomainValidationError(
                    "MATERIAL Goal requires at least "
                    "one GoalRange"
                )

            direct_indices: set[int] = set()

            for goal_range in goal.ranges:
                for position in range(
                    goal_range.start_position,
                    goal_range.end_position + 1,
                ):
                    index = position_to_index.get(
                        position
                    )

                    if index is None:
                        raise DomainValidationError(
                            "GoalRange contains a position "
                            "outside StudyTarget ranges: "
                            f"{position}"
                        )

                    direct_indices.add(
                        index
                    )

            if not direct_indices:
                continue

            farthest_index = max(
                direct_indices
            )

            # Goal対象がすべて完了済み
            if farthest_index < current_index:
                continue

            # ordered learning pathなので、
            # 現在位置からGoal最終位置までが
            # physical required work。
            for index in range(
                current_index,
                farthest_index + 1,
            ):
                required_by[
                    index
                ].add(
                    goal.id
                )

            # Goal Rangeそのもの。
            # 完了済み位置は除外する。
            for index in direct_indices:
                if index < current_index:
                    continue

                direct_goal_ids[
                    index
                ].add(
                    goal.id
                )

        return self._compress_material_positions(
            target=target,
            positions=positions,
            current_index=current_index,
            required_by=required_by,
            direct_goal_ids=direct_goal_ids,
        )

    @staticmethod
    def _build_material_path(
        target: StudyTarget,
    ) -> list[int]:
        sorted_ranges = sorted(
            target.ranges,
            key=lambda item: (
                item.sequence_no
            ),
        )

        positions: list[int] = []
        seen_positions: set[int] = set()

        for target_range in sorted_ranges:
            for position in range(
                target_range.start_position,
                target_range.end_position + 1,
            ):
                if position in seen_positions:
                    raise DomainValidationError(
                        "StudyTarget ranges must not "
                        "overlap"
                    )

                seen_positions.add(
                    position
                )

                positions.append(
                    position
                )

        return positions

    @staticmethod
    def _find_current_index(
        next_position: int,
        positions: Sequence[int],
        position_to_index: Mapping[
            int,
            int,
        ],
    ) -> int:
        existing_index = (
            position_to_index.get(
                next_position
            )
        )

        if existing_index is not None:
            return existing_index

        # 最後のunitを終えた直後だけ
        # path完了状態として許可する。
        if (
            positions
            and next_position
            == positions[-1] + 1
        ):
            return len(
                positions
            )

        raise DomainValidationError(
            "next_position must point to "
            "the ordered StudyTarget path "
            "or immediately after its end"
        )

    @staticmethod
    def _compress_material_positions(
        *,
        target: StudyTarget,
        positions: Sequence[int],
        current_index: int,
        required_by: Sequence[set[int]],
        direct_goal_ids: Sequence[set[int]],
    ) -> list[WorkSegment]:
        assert (
            target.estimated_minutes_per_unit
            is not None
        )

        segments: list[
            WorkSegment
        ] = []

        index = current_index

        while index < len(
            positions
        ):
            if not required_by[index]:
                index += 1
                continue

            start_index = index

            required_tuple = tuple(
                sorted(
                    required_by[index]
                )
            )

            direct_tuple = tuple(
                sorted(
                    direct_goal_ids[index]
                )
            )

            end_index = index

            while (
                end_index + 1
                < len(positions)
            ):
                next_index = (
                    end_index + 1
                )

                # この先はrequired workでない。
                if not required_by[
                    next_index
                ]:
                    break

                # Goal contributionの組合せが変わる
                # 場所でsegmentを分ける。
                if tuple(
                    sorted(
                        required_by[
                            next_index
                        ]
                    )
                ) != required_tuple:
                    break

                if tuple(
                    sorted(
                        direct_goal_ids[
                            next_index
                        ]
                    )
                ) != direct_tuple:
                    break

                # 非連続StudyTargetRangeを跨いで
                # 1 rangeにまとめない。
                if (
                    positions[next_index]
                    != positions[end_index] + 1
                ):
                    break

                end_index = (
                    next_index
                )

            range_start = positions[
                start_index
            ]

            range_end = positions[
                end_index
            ]

            unit_count = (
                end_index
                - start_index
                + 1
            )

            segments.append(
                WorkSegment(
                    study_target_id=target.id,
                    kind=StudyTargetKind.MATERIAL,
                    range_start=range_start,
                    range_end=range_end,
                    estimated_minutes=(
                        unit_count
                        * target.estimated_minutes_per_unit
                    ),
                    required_by_goal_ids=(
                        required_tuple
                    ),
                    direct_goal_ids=(
                        direct_tuple
                    ),
                )
            )

            index = (
                end_index + 1
            )

        return segments

    @staticmethod
    def _build_theme_segments(
        target: StudyTarget,
        goals: Sequence[Goal],
        completed_minutes: int,
    ) -> list[WorkSegment]:
        quantified_goals: list[
            Goal
        ] = []

        for goal in goals:
            # target_minutesがないTHEME Goalは
            # deadline feasibilityを時間で
            # 定量化できないためWorkSegment化しない。
            if goal.target_minutes is None:
                continue

            if goal.target_minutes < 0:
                raise DomainValidationError(
                    "Goal target_minutes must "
                    "be non-negative"
                )

            if (
                goal.target_minutes
                <= completed_minutes
            ):
                continue

            quantified_goals.append(
                goal
            )

        if not quantified_goals:
            return []

        boundaries: set[int] = {
            completed_minutes
        }

        for goal in quantified_goals:
            assert (
                goal.target_minutes
                is not None
            )

            boundaries.add(
                goal.target_minutes
            )

        ordered_boundaries = sorted(
            boundaries
        )

        segments: list[
            WorkSegment
        ] = []

        for index in range(
            len(ordered_boundaries) - 1
        ):
            start_minute = (
                ordered_boundaries[index]
            )

            end_minute = (
                ordered_boundaries[
                    index + 1
                ]
            )

            required_goals = tuple(
                sorted(
                    goal.id
                    for goal
                    in quantified_goals
                    if (
                        goal.target_minutes
                        is not None
                        and goal.target_minutes
                        >= end_minute
                    )
                )
            )

            if not required_goals:
                continue

            segments.append(
                WorkSegment(
                    study_target_id=target.id,
                    kind=StudyTargetKind.THEME,
                    theme_minute_start=(
                        start_minute
                    ),
                    theme_minute_end=(
                        end_minute
                    ),
                    estimated_minutes=float(
                        end_minute
                        - start_minute
                    ),
                    required_by_goal_ids=(
                        required_goals
                    ),
                    direct_goal_ids=(
                        required_goals
                    ),
                )
            )

        return segments