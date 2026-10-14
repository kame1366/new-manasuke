from __future__ import annotations

from dataclasses import dataclass

from domain.enums import (
    StudyResultStatus,
    StudyTargetKind,
)
from domain.errors import (
    DomainValidationError,
)
from domain.models import (
    PlanItem,
    StudyResult,
    StudyTarget,
)


@dataclass(
    frozen=True,
    slots=True,
)
class MaterialResultEvaluation:
    """
    Material StudyResultを検証した結果。

    normalized_actual_end_position:
        DBへ保存するactual_end_position。

    new_next_position:
        StudyTarget.next_positionへ保存する値。
    """

    normalized_actual_end_position: (
        int | None
    )

    new_next_position: int


class MaterialStudyResultRules:
    def evaluate(
        self,
        *,
        target: StudyTarget,
        plan_item: PlanItem,
        status: StudyResultStatus,
        actual_end_position: (
            int | None
        ),
        correction: bool = False,
    ) -> MaterialResultEvaluation:
        if (
            target.kind
            != StudyTargetKind.MATERIAL
        ):
            raise DomainValidationError(
                "MaterialStudyResultRules "
                "requires MATERIAL StudyTarget"
            )

        if (
            plan_item.study_target_id
            != target.id
        ):
            raise DomainValidationError(
                "PlanItem and StudyTarget "
                "do not match"
            )

        if (
            plan_item.range_start is None
            or plan_item.range_end is None
        ):
            raise DomainValidationError(
                "Material PlanItem requires range"
            )

        if plan_item.is_cancelled:
            raise DomainValidationError(
                "cancelled PlanItem cannot "
                "receive StudyResult"
            )

        path = self._material_path(
            target
        )

        index_by_position = {
            position: index
            for index, position
            in enumerate(path)
        }

        start_index = (
            index_by_position.get(
                plan_item.range_start
            )
        )

        end_index = (
            index_by_position.get(
                plan_item.range_end
            )
        )

        if (
            start_index is None
            or end_index is None
            or start_index > end_index
        ):
            raise DomainValidationError(
                "PlanItem range is outside "
                "Material ordered path"
            )

        # PlanItem自身がStudyTargetRangeのgapを
        # またいでいないことも確認する。
        path_slice = path[
            start_index:
            end_index + 1
        ]

        numeric_slice = list(
            range(
                plan_item.range_start,
                plan_item.range_end + 1,
            )
        )

        if path_slice != numeric_slice:
            raise DomainValidationError(
                "PlanItem range crosses "
                "Material path gap"
            )

        if (
            not correction
            and target.next_position
            != plan_item.range_start
        ):
            raise DomainValidationError(
                "Material StudyResult must "
                "continue from current "
                "next_position"
            )

        if (
            status
            == StudyResultStatus.NOT_DONE
        ):
            if actual_end_position is not None:
                raise DomainValidationError(
                    "NOT_DONE must not have "
                    "actual_end_position"
                )

            return MaterialResultEvaluation(
                normalized_actual_end_position=(
                    None
                ),
                new_next_position=(
                    plan_item.range_start
                ),
            )

        if (
            status
            == StudyResultStatus.PARTIAL
        ):
            if actual_end_position is None:
                raise DomainValidationError(
                    "PARTIAL requires "
                    "actual_end_position"
                )

            actual_index = (
                index_by_position.get(
                    actual_end_position
                )
            )

            if actual_index is None:
                raise DomainValidationError(
                    "actual_end_position is "
                    "outside ordered path"
                )

            # PARTIALは予定Rangeの途中まで。
            #
            # range_endまで終わったなら
            # COMPLETEDで記録する。
            if not (
                start_index
                <= actual_index
                < end_index
            ):
                raise DomainValidationError(
                    "PARTIAL actual_end_position "
                    "must be inside planned range "
                    "and before range_end"
                )

            return MaterialResultEvaluation(
                normalized_actual_end_position=(
                    actual_end_position
                ),
                new_next_position=(
                    self._position_after(
                        path,
                        actual_index,
                    )
                ),
            )

        if (
            status
            == StudyResultStatus.COMPLETED
        ):
            # 通常COMPLETEDなら予定末尾。
            #
            # ただし予定より先まで連続して
            # 進んだ場合はactual_end_positionを
            # 指定してよい。
            normalized_end = (
                actual_end_position
                if actual_end_position
                is not None
                else plan_item.range_end
            )

            actual_index = (
                index_by_position.get(
                    normalized_end
                )
            )

            if actual_index is None:
                raise DomainValidationError(
                    "actual_end_position is "
                    "outside ordered path"
                )

            if actual_index < end_index:
                raise DomainValidationError(
                    "COMPLETED cannot finish "
                    "before planned range_end"
                )

            return MaterialResultEvaluation(
                normalized_actual_end_position=(
                    normalized_end
                ),
                new_next_position=(
                    self._position_after(
                        path,
                        actual_index,
                    )
                ),
            )

        raise DomainValidationError(
            "unsupported StudyResultStatus"
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
                    raise DomainValidationError(
                        "StudyTarget ranges overlap"
                    )

                seen.add(
                    position
                )

                result.append(
                    position
                )

        if not result:
            raise DomainValidationError(
                "Material StudyTarget "
                "requires ordered path"
            )

        return result

    @staticmethod
    def _position_after(
        path: list[int],
        index: int,
    ) -> int:
        next_index = (
            index + 1
        )

        if next_index < len(
            path
        ):
            return path[
                next_index
            ]

        # ordered path完了後を表す。
        return path[-1] + 1


class ThemeStudyResultRules:
    @staticmethod
    def validate(
        *,
        target: StudyTarget,
        plan_item: PlanItem,
        status: StudyResultStatus,
        actual_end_position: (
            int | None
        ),
        actual_minutes: (
            int | None
        ),
        requires_actual_minutes: bool,
    ) -> None:
        if (
            target.kind
            != StudyTargetKind.THEME
        ):
            raise DomainValidationError(
                "ThemeStudyResultRules "
                "requires THEME StudyTarget"
            )

        if (
            plan_item.study_target_id
            != target.id
        ):
            raise DomainValidationError(
                "PlanItem and StudyTarget "
                "do not match"
            )

        if plan_item.is_cancelled:
            raise DomainValidationError(
                "cancelled PlanItem cannot "
                "receive StudyResult"
            )

        if actual_end_position is not None:
            raise DomainValidationError(
                "Theme StudyResult must not "
                "have actual_end_position"
            )

        if (
            actual_minutes is not None
            and actual_minutes < 0
        ):
            raise DomainValidationError(
                "actual_minutes must be "
                "non-negative"
            )

        if (
            requires_actual_minutes
            and actual_minutes is None
        ):
            raise DomainValidationError(
                "Theme Goal with "
                "target_minutes requires "
                "actual_minutes"
            )

        if status not in {
            StudyResultStatus.COMPLETED,
            StudyResultStatus.PARTIAL,
            StudyResultStatus.NOT_DONE,
        }:
            raise DomainValidationError(
                "unsupported StudyResultStatus"
            )


def derive_study_result_state(
    *,
    plan_item: PlanItem,
    result: StudyResult | None,
) -> str:
    """
    CANCELLED / UNRECORDEDは
    StudyResult.statusとして保存しない。
    """

    if plan_item.is_cancelled:
        return "CANCELLED"

    if result is None:
        return "UNRECORDED"

    return result.status.value