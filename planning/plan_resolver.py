from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from domain.plan_state import PlanState
from domain.errors import DomainValidationError
from domain.models import Plan
from domain.time_rules import ensure_aware
from planning.plan_validator import (
    PlanValidationResult,
)


class PlanResolver:
    """
    時刻tで適用するPlanを決定する。

    重要:
        最大version_noの候補を先に選ぶ。

        その候補がEXPIREDでも、
        older Planへfallbackしない。
    """

    def resolve(
        self,
        *,
        participant_id: str,
        plans: Sequence[Plan],
        at: datetime,
    ) -> Plan | None:
        ensure_aware(
            at
        )

        participant_plans = (
            self._prepare_plans(
                participant_id=(
                    participant_id
                ),
                plans=plans,
            )
        )

        selected = (
            self._select_candidate(
                participant_plans,
                at,
            )
        )

        if selected is None:
            return None

        if (
            at
            >= selected.horizon_end
        ):
            # older Planへfallbackしない。
            return None

        return selected

    def derive_states(
        self,
        *,
        participant_id: str,
        plans: Sequence[Plan],
        at: datetime,
        current_planning_data_version: int,
        validation_results_by_version: Mapping[
            int,
            PlanValidationResult
        ],
    ) -> dict[
        int,
        PlanState,
    ]:
        """
        participantの各Planの派生状態を返す。

        key:
            version_no

        FUTURE / SHADOWED / EXPIREDは、
        current/outdated判定より先に
       時間軸から決定する。

        選択中Planだけ、
        planning_data_version + Validator結果から
        CURRENT / OUTDATED_* を決める。
        """
        ensure_aware(
            at
        )

        if (
            current_planning_data_version
            < 0
        ):
            raise DomainValidationError(
                "current_planning_data_version "
                "must be non-negative"
            )

        participant_plans = (
            self._prepare_plans(
                participant_id=(
                    participant_id
                ),
                plans=plans,
            )
        )

        selected = (
            self._select_candidate(
                participant_plans,
                at,
            )
        )

        states: dict[
            int,
            PlanState,
        ] = {}

        for plan in participant_plans:
            if (
                plan.effective_from
                > at
            ):
                states[
                    plan.version_no
                ] = (
                    PlanState
                    .FUTURE_APPLICABLE
                )

                continue

            if (
                selected is not None
                and plan.version_no
                != selected.version_no
            ):
                states[
                    plan.version_no
                ] = (
                    PlanState.SHADOWED
                )

                continue

            if (
                at
                >= plan.horizon_end
            ):
                states[
                    plan.version_no
                ] = (
                    PlanState.EXPIRED
                )

                continue

            if (
                plan
                .source_planning_data_version
                > current_planning_data_version
            ):
                raise DomainValidationError(
                    "Plan source_planning_data_version "
                    "cannot be newer than current "
                    "planning_data_version"
                )

            validation_result = (
                validation_results_by_version
                .get(
                    plan.version_no
                )
            )

            if (
                validation_result
                is None
            ):
                raise DomainValidationError(
                    "validation result missing "
                    "for active selected Plan"
                )

            if not (
                validation_result.is_valid
            ):
                states[
                    plan.version_no
                ] = (
                    PlanState
                    .OUTDATED_INVALID
                )

                continue

            if (
                plan
                .source_planning_data_version
                == current_planning_data_version
            ):
                states[
                    plan.version_no
                ] = (
                    PlanState.CURRENT
                )

            else:
                states[
                    plan.version_no
                ] = (
                    PlanState
                    .OUTDATED_VALID
                )

        return states

    @staticmethod
    def _prepare_plans(
        *,
        participant_id: str,
        plans: Sequence[Plan],
    ) -> list[Plan]:
        participant_plans = [
            plan
            for plan in plans
            if (
                plan.participant_id
                == participant_id
            )
        ]

        version_numbers = [
            plan.version_no
            for plan in participant_plans
        ]

        if len(
            version_numbers
        ) != len(
            set(
                version_numbers
            )
        ):
            raise DomainValidationError(
                "duplicate Plan version_no "
                "for participant"
            )

        return sorted(
            participant_plans,
            key=lambda plan: (
                plan.version_no
            ),
        )

    @staticmethod
    def _select_candidate(
        plans: Sequence[Plan],
        at: datetime,
    ) -> Plan | None:
        candidates = [
            plan
            for plan in plans
            if (
                plan.effective_from
                <= at
            )
        ]

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda plan: (
                plan.version_no
            ),
        )