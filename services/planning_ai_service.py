from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ai.errors import (
    AIOutputInvalidError,
)
from ai.planning_models import (
    PlanningOutput,
)
from ai.planning_output_validator import (
    PlanningOutputValidator,
)
from domain.models import (
    Goal,
    LearningPolicy,
    StudyTarget,
)
from planning.optional_allocation import (
    PlanningAIContext,
)


class PlanningGeneratorProtocol(
    Protocol
):
    def generate(
        self,
        *,
        context: PlanningAIContext,
        study_targets: Sequence[
            StudyTarget
        ],
        goals: Sequence[
            Goal
        ],
        learning_policies: Sequence[
            LearningPolicy
        ],
        correction_feedback: str
        | None = None,
    ) -> PlanningOutput:
        ...


class PlanningAIService:
    """
    AI②のsemantic validationと
    corrective generationを管理する。

    DB / Attempt lifecycleへの接続は
    10/12側の責務。
    """

    def __init__(
        self,
        *,
        generator: (
            PlanningGeneratorProtocol
        ),
        validator: (
            PlanningOutputValidator
            | None
        ) = None,
    ) -> None:
        self._generator = generator

        self._validator = (
            validator
            or PlanningOutputValidator()
        )

    def generate_validated_output(
        self,
        *,
        context: PlanningAIContext,
        study_targets: Sequence[
            StudyTarget
        ],
        goals: Sequence[
            Goal
        ],
        learning_policies: Sequence[
            LearningPolicy
        ],
    ) -> PlanningOutput:
        if not context.bounds:
            return PlanningOutput(
                allocations=[]
            )

        correction_feedback = None
        last_error = None

        for attempt_index in range(
            2
        ):
            output = (
                self._generator.generate(
                    context=context,
                    study_targets=(
                        study_targets
                    ),
                    goals=goals,
                    learning_policies=(
                        learning_policies
                    ),
                    correction_feedback=(
                        correction_feedback
                    ),
                )
            )

            try:
                self._validator.validate(
                    context=context,
                    output=output,
                )

                return output

            except (
                AIOutputInvalidError
            ) as exc:
                last_error = exc

                if attempt_index == 1:
                    break

                correction_feedback = (
                    "The previous output was "
                    "semantically invalid. "
                    "Correct it without changing "
                    "the supplied hard bounds. "
                    f"Validation error: {exc}"
                )

        assert (
            last_error is not None
        )

        raise AIOutputInvalidError(
            "planning output remained "
            "invalid after one "
            "corrective generation"
        ) from last_error