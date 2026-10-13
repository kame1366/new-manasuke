from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domain.enums import (
    PlanItemOrigin,
    PlanOperationType,
    StudyTargetKind,
)
from domain.errors import DomainValidationError
from domain.models import (
    PlanItem,
    StudyTarget,
)
from domain.time_rules import (
    ceil_to_5_minutes,
    ensure_aware,
    start_of_next_day_jst,
    to_jst,
)


class UserModifiedConflictError(
    DomainValidationError
):
    """
    carry-forward対象USER_MODIFIEDが、
    現在のSource Data / ordered pathと
    両立しない場合。
    """


@dataclass(
    frozen=True,
    slots=True,
)
class CarryForwardPlanItem:
    """
    新Planへcarry-forwardする
    USER_MODIFIED PlanItem。

    DB IDはまだ持たない。
    """

    source_plan_item_id: int

    study_target_id: int

    start_at: datetime
    end_at: datetime

    planned_minutes: int

    range_start: int | None
    range_end: int | None

    def __post_init__(self) -> None:
        ensure_aware(
            self.start_at
        )

        ensure_aware(
            self.end_at
        )

        if self.start_at >= self.end_at:
            raise DomainValidationError(
                "carry-forward item "
                "start_at must be earlier "
                "than end_at"
            )

        if self.planned_minutes <= 0:
            raise DomainValidationError(
                "carry-forward planned_minutes "
                "must be positive"
            )

    def to_plan_item(
        self,
        *,
        plan_id: int,
        temporary_id: int,
    ) -> PlanItem:
        return PlanItem(
            id=temporary_id,
            plan_id=plan_id,
            study_target_id=(
                self.study_target_id
            ),
            start_at=self.start_at,
            end_at=self.end_at,
            origin=(
                PlanItemOrigin.USER_MODIFIED
            ),
            planned_minutes=(
                self.planned_minutes
            ),
            range_start=(
                self.range_start
            ),
            range_end=(
                self.range_end
            ),
            is_cancelled=False,
            cancelled_at=None,
            carried_from_plan_item_id=(
                self.source_plan_item_id
            ),
        )


class ReplanRules:
    @staticmethod
    def effective_from(
        *,
        operation_type: PlanOperationType,
        now: datetime,
    ) -> datetime:
        ensure_aware(
            now
        )

        if (
            operation_type
            == PlanOperationType
            .REPLAN_TOMORROW
        ):
            return (
                start_of_next_day_jst(
                    now
                )
            )

        if operation_type in {
            PlanOperationType.INITIAL,
            PlanOperationType.REPLAN_NOW,
        }:
            return ceil_to_5_minutes(
                now
            )

        raise DomainValidationError(
            "unsupported PlanOperationType"
        )

    def collect_carry_forward(
        self,
        *,
        plan_items: list[PlanItem],
        study_targets: list[
            StudyTarget
        ],
        now: datetime,
        effective_from: datetime,
        horizon_end: datetime,
    ) -> tuple[
        CarryForwardPlanItem,
        ...,
    ]:
        ensure_aware(
            now
        )

        ensure_aware(
            effective_from
        )

        ensure_aware(
            horizon_end
        )

        targets_by_id = {
            target.id: target
            for target in study_targets
        }

        if len(
            targets_by_id
        ) != len(
            study_targets
        ):
            raise DomainValidationError(
                "duplicate StudyTarget id"
            )

        result: list[
            CarryForwardPlanItem
        ] = []

        for item in plan_items:
            # SYSTEM_GENERATEDは
            # carry-forwardしない。
            if (
                item.origin
                != PlanItemOrigin
                .USER_MODIFIED
            ):
                continue

            if item.is_cancelled:
                continue

            # すでに開始済みなら未来予定ではない。
            if now >= item.start_at:
                continue

            # 新Planのeffective interval外。
            if (
                item.start_at
                < effective_from
            ):
                continue

            if (
                item.end_at
                > horizon_end
            ):
                continue

            target = targets_by_id.get(
                item.study_target_id
            )

            if target is None:
                raise (
                    UserModifiedConflictError(
                        "USER_MODIFIED references "
                        "unknown StudyTarget"
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
                    raise (
                        UserModifiedConflictError(
                            "Material USER_MODIFIED "
                            "requires range"
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
                    raise (
                        UserModifiedConflictError(
                            "Theme USER_MODIFIED "
                            "must not have range"
                        )
                    )

            result.append(
                CarryForwardPlanItem(
                    source_plan_item_id=(
                        item.id
                    ),
                    study_target_id=(
                        item.study_target_id
                    ),
                    start_at=(
                        item.start_at
                    ),
                    end_at=(
                        item.end_at
                    ),
                    planned_minutes=(
                        item.planned_minutes
                    ),
                    range_start=(
                        item.range_start
                    ),
                    range_end=(
                        item.range_end
                    ),
                )
            )

        self._validate_material_reservations(
            items=result,
            targets_by_id=(
                targets_by_id
            ),
        )

        result.sort(
            key=lambda item: (
                item.start_at,
                item.end_at,
                item.source_plan_item_id,
            )
        )

        return tuple(
            result
        )

    def _validate_material_reservations(
        self,
        *,
        items: list[
            CarryForwardPlanItem
        ],
        targets_by_id: dict[
            int,
            StudyTarget
        ],
    ) -> None:
        items_by_target: dict[
            int,
            list[
                CarryForwardPlanItem
            ],
        ] = {}

        for item in items:
            target = targets_by_id[
                item.study_target_id
            ]

            if (
                target.kind
                != StudyTargetKind.MATERIAL
            ):
                continue

            items_by_target.setdefault(
                target.id,
                [],
            ).append(
                item
            )

        for target_id, target_items in (
            items_by_target.items()
        ):
            target = targets_by_id[
                target_id
            ]

            path = self._material_path(
                target
            )

            if target.next_position is None:
                raise (
                    UserModifiedConflictError(
                        "Material StudyTarget "
                        "requires next_position"
                    )
                )

            position_to_index = {
                position: index
                for index, position
                in enumerate(path)
            }

            current_index = (
                position_to_index.get(
                    target.next_position
                )
            )

            if current_index is None:
                if (
                    path
                    and target.next_position
                    == path[-1] + 1
                ):
                    current_index = len(
                        path
                    )

                else:
                    raise (
                        UserModifiedConflictError(
                            "next_position is outside "
                            "Material ordered path"
                        )
                    )

            ordered = sorted(
                target_items,
                key=lambda item: (
                    item.start_at,
                    item.end_at,
                    item.source_plan_item_id,
                ),
            )

            previous_end_index: (
                int | None
            ) = None

            for item in ordered:
                assert (
                    item.range_start
                    is not None
                )

                assert (
                    item.range_end
                    is not None
                )

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
                    or start_index
                    > end_index
                ):
                    raise (
                        UserModifiedConflictError(
                            "reserved Material range "
                            "is outside ordered path"
                        )
                    )

                path_slice = path[
                    start_index:
                    end_index + 1
                ]

                numeric_slice = list(
                    range(
                        item.range_start,
                        item.range_end + 1,
                    )
                )

                if (
                    path_slice
                    != numeric_slice
                ):
                    raise (
                        UserModifiedConflictError(
                            "reserved Material range "
                            "crosses a path gap"
                        )
                    )

                # 進捗済みRangeを未来予定として
                # 勝手に残さない。
                if (
                    start_index
                    < current_index
                ):
                    raise (
                        UserModifiedConflictError(
                            "reserved Material work "
                            "is behind current progress"
                        )
                    )

                # 時間順と教材順が逆転したり、
                # Rangeが重複してはいけない。
                if (
                    previous_end_index
                    is not None
                    and start_index
                    <= previous_end_index
                ):
                    raise (
                        UserModifiedConflictError(
                            "USER_MODIFIED Material "
                            "time order conflicts with "
                            "ordered path"
                        )
                    )

                previous_end_index = (
                    end_index
                )

    @staticmethod
    def _material_path(
        target: StudyTarget,
    ) -> list[int]:
        result: list[int] = []
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
                    raise (
                        UserModifiedConflictError(
                            "StudyTarget ranges overlap"
                        )
                    )

                seen.add(
                    position
                )

                result.append(
                    position
                )

        if not result:
            raise UserModifiedConflictError(
                "Material StudyTarget "
                "has no ordered path"
            )

        return result