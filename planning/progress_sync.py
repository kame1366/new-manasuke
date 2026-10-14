from __future__ import annotations

from dataclasses import (
    dataclass,
    replace,
)

from domain.enums import (
    PlanItemOrigin,
    StudyTargetKind,
)
from domain.errors import (
    DomainValidationError,
)
from domain.models import (
    Plan,
    PlanItem,
    StudyTarget,
)


@dataclass(
    frozen=True,
    slots=True,
)
class ProgressSyncCandidate:
    plan: Plan

    future_plan_items: tuple[
        PlanItem,
        ...,
    ]


@dataclass(
    frozen=True,
    slots=True,
)
class ProgressSyncItemUpdate:
    previous: PlanItem
    updated: PlanItem


@dataclass(
    frozen=True,
    slots=True,
)
class ProgressSyncDecision:
    plan_id: int

    syncable: bool

    item_updates: tuple[
        ProgressSyncItemUpdate,
        ...,
    ] = ()

    conflict_reason: str | None = None


class MaterialProgressSyncPlanner:
    """
    next_position変更を既存Planへ
    安全に同期できるか判定する。

    USER_MODIFIEDは自動変更しない。

    syncできないPlanは変更せず、
    source_planning_data_versionを
    古いまま残す。
    """

    def build(
        self,
        *,
        target: StudyTarget,
        new_next_position: int,
        candidates: tuple[
            ProgressSyncCandidate,
            ...,
        ],
    ) -> tuple[
        ProgressSyncDecision,
        ...,
    ]:
        if (
            target.kind
            != StudyTargetKind.MATERIAL
        ):
            raise DomainValidationError(
                "PROGRESS_SYNC requires "
                "MATERIAL StudyTarget"
            )

        path = self._material_path(
            target
        )

        index_by_position = {
            position: index
            for index, position
            in enumerate(path)
        }

        if new_next_position in (
            index_by_position
        ):
            new_index = (
                index_by_position[
                    new_next_position
                ]
            )

        elif (
            path
            and new_next_position
            == path[-1] + 1
        ):
            new_index = len(
                path
            )

        else:
            raise DomainValidationError(
                "new_next_position is outside "
                "Material ordered path"
            )

        return tuple(
            self._build_for_plan(
                candidate=candidate,
                path=path,
                index_by_position=(
                    index_by_position
                ),
                new_index=new_index,
            )
            for candidate in candidates
        )

    def _build_for_plan(
        self,
        *,
        candidate: ProgressSyncCandidate,
        path: list[int],
        index_by_position: dict[
            int,
            int,
        ],
        new_index: int,
    ) -> ProgressSyncDecision:
        items = sorted(
            candidate.future_plan_items,
            key=lambda item: (
                item.start_at,
                item.end_at,
                item.id,
            ),
        )

        if not items:
            return ProgressSyncDecision(
                plan_id=(
                    candidate.plan.id
                ),
                syncable=True,
            )

        expected_index = (
            new_index
        )

        updates: list[
            ProgressSyncItemUpdate
        ] = []

        for item in items:
            if (
                item.range_start is None
                or item.range_end is None
            ):
                return self._conflict(
                    candidate,
                    (
                        "future Material PlanItem "
                        "has no range"
                    ),
                )

            start_index = (
                index_by_position.get(
                    item.range_start
                )
            )

            end_index = (
                index_by_position.get(
                    item.range_end
                )
            )

            if (
                start_index is None
                or end_index is None
                or start_index > end_index
            ):
                return self._conflict(
                    candidate,
                    (
                        "future PlanItem range "
                        "is outside ordered path"
                    ),
                )

            if (
                path[
                    start_index:
                    end_index + 1
                ]
                != list(
                    range(
                        item.range_start,
                        item.range_end + 1,
                    )
                )
            ):
                return self._conflict(
                    candidate,
                    (
                        "future PlanItem crosses "
                        "Material path gap"
                    ),
                )

            if (
                item.origin
                == PlanItemOrigin
                .USER_MODIFIED
            ):
                # USER_MODIFIEDを自動で
                # trim/cancelしない。
                if start_index < new_index:
                    return self._conflict(
                        candidate,
                        (
                            "Material progress "
                            "overlaps USER_MODIFIED "
                            "reserved work"
                        ),
                    )

                effective_start_index = (
                    start_index
                )

            else:
                # 新しいprogressで
                # PlanItem全体を追い越した。
                #
                # CANCELLED扱いにすると意味が変わるため、
                # 自動キャンセルせずOUTDATEDへ。
                if end_index < new_index:
                    return self._conflict(
                        candidate,
                        (
                            "Material progress "
                            "fully consumed a future "
                            "generated PlanItem"
                        ),
                    )

                effective_start_index = (
                    start_index
                )

                if (
                    start_index
                    < new_index
                    <= end_index
                ):
                    updated = replace(
                        item,
                        range_start=(
                            path[
                                new_index
                            ]
                        ),
                    )

                    updates.append(
                        ProgressSyncItemUpdate(
                            previous=item,
                            updated=updated,
                        )
                    )

                    effective_start_index = (
                        new_index
                    )

            # ordered path上でgapを
            # 発生させない。
            if (
                effective_start_index
                != expected_index
            ):
                return self._conflict(
                    candidate,
                    (
                        "PROGRESS_SYNC would "
                        "create Material range gap"
                    ),
                )

            expected_index = (
                end_index + 1
            )

        return ProgressSyncDecision(
            plan_id=(
                candidate.plan.id
            ),
            syncable=True,
            item_updates=tuple(
                updates
            ),
        )

    @staticmethod
    def _conflict(
        candidate: ProgressSyncCandidate,
        reason: str,
    ) -> ProgressSyncDecision:
        return ProgressSyncDecision(
            plan_id=(
                candidate.plan.id
            ),
            syncable=False,
            conflict_reason=reason,
        )

    @staticmethod
    def _material_path(
        target: StudyTarget,
    ) -> list[int]:
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
                        "StudyTarget ranges overlap"
                    )

                seen.add(
                    position
                )

                path.append(
                    position
                )

        if not path:
            raise DomainValidationError(
                "Material ordered path is empty"
            )

        return path