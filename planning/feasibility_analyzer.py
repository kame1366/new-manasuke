from __future__ import annotations

import math
from collections.abc import (
    Sequence,
    Set,
)
from dataclasses import dataclass
from datetime import datetime

from domain.errors import (
    DomainValidationError,
)
from domain.models import (
    AvailableTime,
    BusyEvent,
    ExtraAvailableTime,
    Goal,
    PlanItem,
)
from domain.time_rules import (
    ensure_aware,
    to_jst,
)
from planning.free_slot_builder import (
    FreeSlotBuilder,
)
from planning.work_segment_builder import (
    WorkSegment,
)


@dataclass(
    frozen=True,
    slots=True,
)
class MinimumReservation:
    """
    Goal deadline capacityから事前に予約すべき
    LearningPolicy minimum等の追加Hard capacity。

    WorkSegmentと重複する分を二重計上しないよう、
    呼び出し側で「追加で必要な物理capacity」のみ
    渡すこと。

    LearningPolicy minimumそのものの構築ロジックは
    minimum preflight側の責務とする。
    """

    deadline_at: datetime
    minutes: int

    def __post_init__(self) -> None:
        ensure_aware(
            self.deadline_at
        )

        if self.minutes < 0:
            raise DomainValidationError(
                "MinimumReservation minutes "
                "must be non-negative"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class GoalFeasibilityResult:
    goal_id: int

    individually_feasible: bool

    # Goal自身のphysical work量。
    # prerequisiteを含む。
    estimated_required_minutes: int

    # minimum reservationもcapacity競合として
    # 考慮した不足量。
    individual_shortage_minutes: int

    projected_capacity_minutes: int


@dataclass(
    frozen=True,
    slots=True,
)
class DeadlineFeasibilitySnapshot:
    deadline_at: datetime

    cumulative_required_minutes: int
    cumulative_available_minutes: int
    cumulative_shortage_minutes: int

    feasible: bool


@dataclass(
    frozen=True,
    slots=True,
)
class FeasibilityResult:
    """
    1回のfeasibility分析結果。
    """

    total_projected_capacity_minutes: int

    normalized_required_minutes: int

    aggregate_shortage_minutes: int

    strict_set_feasible: bool

    goal_results: tuple[
        GoalFeasibilityResult,
        ...,
    ]

    deadline_snapshots: tuple[
        DeadlineFeasibilitySnapshot,
        ...,
    ]


class DeadlineFeasibilityAnalyzer:
    """
    Goal deadlineまでの将来capacityと、
    正規化済みWorkSegmentを比較する。

    shared WorkSegmentはphysical workとして1回だけ
    capacityを消費する。

    複数deadlineがある場合、
    segmentは「そのsegmentを必要とするSTRICT Goalの
    最も早いdeadline」までに完了する必要がある。
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

    def analyze(
        self,
        *,
        effective_from: datetime,
        goals: Sequence[Goal],
        work_segments: Sequence[
            WorkSegment
        ],
        weekly_available_times: Sequence[
            AvailableTime
        ],
        extra_available_times: Sequence[
            ExtraAvailableTime
        ],
        busy_events: Sequence[
            BusyEvent
        ],
        fixed_plan_items: Sequence[
            PlanItem
        ],
        strict_goal_ids: Set[int]
        | None = None,
        minimum_reservations: Sequence[
            MinimumReservation
        ] = (),
    ) -> FeasibilityResult:
        ensure_aware(
            effective_from
        )

        effective_from_jst = to_jst(
            effective_from
        )

        goals_by_id = self._index_goals(
            goals
        )

        self._validate_work_segments(
            work_segments,
            goals_by_id,
        )

        if strict_goal_ids is None:
            strict_ids = set(
                goals_by_id
            )
        else:
            strict_ids = set(
                strict_goal_ids
            )

        unknown_strict_ids = (
            strict_ids
            - set(goals_by_id)
        )

        if unknown_strict_ids:
            raise DomainValidationError(
                "strict_goal_ids contains "
                "unknown Goal id"
            )

        normalized_deadlines = {
            goal_id: to_jst(
                goal.deadline_at
            )
            for goal_id, goal
            in goals_by_id.items()
        }

        normalized_reservations = tuple(
            MinimumReservation(
                deadline_at=to_jst(
                    reservation.deadline_at
                ),
                minutes=reservation.minutes,
            )
            for reservation
            in minimum_reservations
        )

        capacity_cache: dict[
            datetime,
            int,
        ] = {}

        def projected_capacity(
            deadline: datetime,
        ) -> int:
            cached = capacity_cache.get(
                deadline
            )

            if cached is not None:
                return cached

            capacity = self._project_capacity(
                effective_from=(
                    effective_from_jst
                ),
                deadline=deadline,
                weekly_available_times=(
                    weekly_available_times
                ),
                extra_available_times=(
                    extra_available_times
                ),
                busy_events=busy_events,
                fixed_plan_items=(
                    fixed_plan_items
                ),
            )

            capacity_cache[
                deadline
            ] = capacity

            return capacity

        goal_results = tuple(
            self._build_goal_result(
                goal_id=goal_id,
                deadline=(
                    normalized_deadlines[
                        goal_id
                    ]
                ),
                work_segments=(
                    work_segments
                ),
                minimum_reservations=(
                    normalized_reservations
                ),
                projected_capacity=(
                    projected_capacity
                ),
            )
            for goal_id
            in sorted(
                goals_by_id
            )
        )

        strict_deadlines = sorted(
            {
                normalized_deadlines[
                    goal_id
                ]
                for goal_id
                in strict_ids
            }
        )

        deadline_snapshots: list[
            DeadlineFeasibilitySnapshot
        ] = []

        for deadline in strict_deadlines:
            required_minutes = (
                self._cumulative_required_minutes(
                    deadline=deadline,
                    strict_goal_ids=(
                        strict_ids
                    ),
                    goal_deadlines=(
                        normalized_deadlines
                    ),
                    work_segments=(
                        work_segments
                    ),
                    minimum_reservations=(
                        normalized_reservations
                    ),
                )
            )

            available_minutes = (
                projected_capacity(
                    deadline
                )
            )

            shortage = max(
                0,
                required_minutes
                - available_minutes,
            )

            deadline_snapshots.append(
                DeadlineFeasibilitySnapshot(
                    deadline_at=deadline,
                    cumulative_required_minutes=(
                        required_minutes
                    ),
                    cumulative_available_minutes=(
                        available_minutes
                    ),
                    cumulative_shortage_minutes=(
                        shortage
                    ),
                    feasible=(
                        shortage == 0
                    ),
                )
            )

        strict_set_feasible = all(
            snapshot.feasible
            for snapshot
            in deadline_snapshots
        )

        aggregate_shortage = max(
            (
                snapshot
                .cumulative_shortage_minutes
                for snapshot
                in deadline_snapshots
            ),
            default=0,
        )

        if deadline_snapshots:
            final_snapshot = (
                deadline_snapshots[-1]
            )

            total_projected_capacity = (
                final_snapshot
                .cumulative_available_minutes
            )

            normalized_required = (
                final_snapshot
                .cumulative_required_minutes
            )

        else:
            total_projected_capacity = 0
            normalized_required = 0

        return FeasibilityResult(
            total_projected_capacity_minutes=(
                total_projected_capacity
            ),
            normalized_required_minutes=(
                normalized_required
            ),
            aggregate_shortage_minutes=(
                aggregate_shortage
            ),
            strict_set_feasible=(
                strict_set_feasible
            ),
            goal_results=goal_results,
            deadline_snapshots=tuple(
                deadline_snapshots
            ),
        )

    @staticmethod
    def _index_goals(
        goals: Sequence[Goal],
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
                    f"duplicate Goal id: "
                    f"{goal.id}"
                )

            result[
                goal.id
            ] = goal

        return result

    @staticmethod
    def _validate_work_segments(
        work_segments: Sequence[
            WorkSegment
        ],
        goals_by_id: dict[
            int,
            Goal,
        ],
    ) -> None:
        known_goal_ids = set(
            goals_by_id
        )

        for segment in work_segments:
            referenced_goal_ids = set(
                segment.required_by_goal_ids
            )

            referenced_goal_ids.update(
                segment.direct_goal_ids
            )

            unknown = (
                referenced_goal_ids
                - known_goal_ids
            )

            if unknown:
                raise DomainValidationError(
                    "WorkSegment references "
                    "unknown Goal id"
                )

    @staticmethod
    def _round_required_minutes(
        value: float,
    ) -> int:
        """
        float誤差で整数値が意図せず
        次の整数へceilされることを避ける。
        """
        return math.ceil(
            value - 1e-9
        )

    def _build_goal_result(
        self,
        *,
        goal_id: int,
        deadline: datetime,
        work_segments: Sequence[
            WorkSegment
        ],
        minimum_reservations: Sequence[
            MinimumReservation
        ],
        projected_capacity,
    ) -> GoalFeasibilityResult:
        goal_work_float = sum(
            segment.estimated_minutes
            for segment
            in work_segments
            if (
                goal_id
                in segment.required_by_goal_ids
            )
        )

        goal_work_minutes = (
            self._round_required_minutes(
                goal_work_float
            )
        )

        minimum_reservation_minutes = sum(
            reservation.minutes
            for reservation
            in minimum_reservations
            if (
                reservation.deadline_at
                <= deadline
            )
        )

        capacity = projected_capacity(
            deadline
        )

        shortage = max(
            0,
            (
                goal_work_minutes
                + minimum_reservation_minutes
                - capacity
            ),
        )

        return GoalFeasibilityResult(
            goal_id=goal_id,
            individually_feasible=(
                shortage == 0
            ),
            estimated_required_minutes=(
                goal_work_minutes
            ),
            individual_shortage_minutes=(
                shortage
            ),
            projected_capacity_minutes=(
                capacity
            ),
        )

    def _cumulative_required_minutes(
        self,
        *,
        deadline: datetime,
        strict_goal_ids: set[int],
        goal_deadlines: dict[
            int,
            datetime,
        ],
        work_segments: Sequence[
            WorkSegment
        ],
        minimum_reservations: Sequence[
            MinimumReservation
        ],
    ) -> int:
        required_float = 0.0

        for segment in work_segments:
            relevant_goal_ids = (
                set(
                    segment.required_by_goal_ids
                )
                & strict_goal_ids
            )

            if not relevant_goal_ids:
                continue

            # shared workは、そのWorkを必要とする
            # STRICT Goalの最短deadlineまでに
            # 終える必要がある。
            segment_deadline = min(
                goal_deadlines[
                    goal_id
                ]
                for goal_id
                in relevant_goal_ids
            )

            if (
                segment_deadline
                <= deadline
            ):
                required_float += (
                    segment.estimated_minutes
                )

        required_minutes = (
            self._round_required_minutes(
                required_float
            )
        )

        minimum_minutes = sum(
            reservation.minutes
            for reservation
            in minimum_reservations
            if (
                reservation.deadline_at
                <= deadline
            )
        )

        return (
            required_minutes
            + minimum_minutes
        )

    def _project_capacity(
        self,
        *,
        effective_from: datetime,
        deadline: datetime,
        weekly_available_times: Sequence[
            AvailableTime
        ],
        extra_available_times: Sequence[
            ExtraAvailableTime
        ],
        busy_events: Sequence[
            BusyEvent
        ],
        fixed_plan_items: Sequence[
            PlanItem
        ],
    ) -> int:
        if deadline <= effective_from:
            return 0

        slots = self._free_slot_builder.build(
            window_start=effective_from,
            window_end=deadline,
            weekly_available_times=(
                weekly_available_times
            ),
            extra_available_times=(
                extra_available_times
            ),
            busy_events=busy_events,
            fixed_plan_items=(
                fixed_plan_items
            ),
        )

        return sum(
            slot.duration_minutes
            for slot in slots
        )