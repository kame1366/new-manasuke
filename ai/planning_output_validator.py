from __future__ import annotations

from ai.errors import (
    AIOutputInvalidError,
)
from ai.planning_models import (
    PlanningOutput,
)
from planning.optional_allocation import (
    PlanningAIContext,
)


class PlanningOutputValidator:
    def validate(
        self,
        *,
        context: PlanningAIContext,
        output: PlanningOutput,
    ) -> None:
        expected_ids = set(
            context.study_target_ids
        )

        output_ids = [
            allocation.study_target_id
            for allocation
            in output.allocations
        ]

        if len(output_ids) != len(
            set(output_ids)
        ):
            raise AIOutputInvalidError(
                "planning output contains "
                "duplicate StudyTarget IDs"
            )

        actual_ids = set(
            output_ids
        )

        if (
            actual_ids
            != expected_ids
        ):
            missing = sorted(
                expected_ids
                - actual_ids
            )

            unknown = sorted(
                actual_ids
                - expected_ids
            )

            raise AIOutputInvalidError(
                "planning output StudyTarget IDs "
                "do not match context; "
                f"missing={missing}, "
                f"unknown={unknown}"
            )

        bounds_by_target = {
            bound.study_target_id: bound
            for bound in context.bounds
        }

        ranks = [
            allocation
            .planning_priority_rank
            for allocation
            in output.allocations
        ]

        expected_ranks = set(
            range(
                1,
                len(
                    output.allocations
                )
                + 1,
            )
        )

        if set(ranks) != expected_ranks:
            raise AIOutputInvalidError(
                "planning_priority_rank "
                "must be unique 1..N"
            )

        total_optional = 0

        for allocation in (
            output.allocations
        ):
            bound = bounds_by_target[
                allocation.study_target_id
            ]

            minutes = (
                allocation
                .optional_extra_minutes
            )

            if minutes < 0:
                raise AIOutputInvalidError(
                    "optional_extra_minutes "
                    "must be non-negative"
                )

            if minutes % 5 != 0:
                raise AIOutputInvalidError(
                    "optional_extra_minutes "
                    "must be a multiple of 5"
                )

            if (
                minutes
                > bound
                .maximum_optional_minutes
            ):
                raise AIOutputInvalidError(
                    "optional_extra_minutes "
                    "exceeds target maximum "
                    f"for StudyTarget "
                    f"{allocation.study_target_id}"
                )

            if (
                minutes > 0
                and minutes
                < bound
                .minimum_optional_increment_minutes
            ):
                raise AIOutputInvalidError(
                    "positive optional allocation "
                    "is below minimum increment "
                    f"for StudyTarget "
                    f"{allocation.study_target_id}"
                )

            total_optional += (
                minutes
            )

        if (
            total_optional
            > context
            .total_soft_capacity_minutes
        ):
            raise AIOutputInvalidError(
                "sum(optional_extra_minutes) "
                "exceeds total_soft_capacity"
            )