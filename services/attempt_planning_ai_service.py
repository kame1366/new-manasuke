from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from ai.errors import (
    AIGenerationError,
    AIOutputInvalidError,
    PlanningDataChangedError,
)
from ai.planning_models import (
    PlanningOutput,
)
from domain.models import (
    Goal,
    LearningPolicy,
    StudyTarget,
)
from planning.optional_allocation import (
    PlanningAIContext,
)
from repositories.ai_interaction_repository import (
    AIInteractionRepository,
)
from repositories.plan_generation_attempt_repository import (
    PlanGenerationAttemptRepository,
)
from repositories.plan_generation_checkpoint_repository import (
    PlanGenerationCheckpointRepository,
)
from services.planning_ai_service import (
    PlanningAIService,
)


ERROR_AI_FAILED = "AI_FAILED"
ERROR_AI_OUTPUT_INVALID = (
    "AI_OUTPUT_INVALID"
)
ERROR_PLANNING_DATA_CHANGED = (
    "PLANNING_DATA_CHANGED"
)


class AttemptPlanningAIService:
    """
    AttemptのAI_PLANNING stageで
    AI②を実行する。

    OpenAI呼び出し中に
    DB Transactionを保持しない。
    """

    def __init__(
        self,
        *,
        db_path: str | Path,
        planning_ai_service: (
            PlanningAIService
        ),
        prompt_version: str,
        model_name: str,
    ) -> None:
        self._db_path = Path(
            db_path
        )

        self._planning_ai_service = (
            planning_ai_service
        )

        self._prompt_version = (
            prompt_version
        )

        self._model_name = (
            model_name
        )

        self._ai_repository = (
            AIInteractionRepository(
                self._db_path
            )
        )

        self._attempt_repository = (
            PlanGenerationAttemptRepository(
                self._db_path
            )
        )

        self._checkpoint_repository = (
            PlanGenerationCheckpointRepository(
                self._db_path
            )
        )

    def execute(
        self,
        *,
        participant_id: str,
        attempt_id: int,
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
        now: datetime,
    ) -> PlanningOutput:
        interaction_id = (
            self._ai_repository
            .start_for_attempt(
                participant_id=(
                    participant_id
                ),
                attempt_id=(
                    attempt_id
                ),
                prompt_version=(
                    self._prompt_version
                ),
                model_name=(
                    self._model_name
                ),
                now=now,
            )
        )

        try:
            # ------------------------------------------------
            # OpenAI call
            #
            # DB Transactionを保持していない。
            # semantic correction最大1回も
            # PlanningAIService内部。
            # ------------------------------------------------

            output = (
                self
                ._planning_ai_service
                .generate_validated_output(
                    context=context,
                    study_targets=(
                        study_targets
                    ),
                    goals=goals,
                    learning_policies=(
                        learning_policies
                    ),
                )
            )

            # ------------------------------------------------
            # validated output保存
            # +
            # stage -> SCHEDULING
            #
            # 同じ短Transaction。
            # ------------------------------------------------

            (
                self
                ._checkpoint_repository
                .record_planning_ai_success(
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    interaction_id=(
                        interaction_id
                    ),
                    structured_output_json=(
                        output.model_dump_json()
                    ),
                    now=now,
                )
            )

            return output

        except Exception as exc:
            if isinstance(
                exc,
                PlanningDataChangedError,
            ):
                error_type = (
                    ERROR_PLANNING_DATA_CHANGED
                )

            elif isinstance(
                exc,
                AIOutputInvalidError,
            ):
                error_type = (
                    ERROR_AI_OUTPUT_INVALID
                )

            elif isinstance(
                exc,
                AIGenerationError,
            ):
                error_type = (
                    ERROR_AI_FAILED
                )

            else:
                error_type = (
                    ERROR_AI_FAILED
                )

            try:
                self._ai_repository.mark_failed(
                    participant_id=(
                        participant_id
                    ),
                    interaction_id=(
                        interaction_id
                    ),
                    error_type=(
                        error_type
                    ),
                )

            except RuntimeError:
                # checkpoint成功後など、
                # すでにterminalなら上書きしない。
                pass

            try:
                self._attempt_repository.mark_failed(
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    error_type=(
                        error_type
                    ),
                    now=now,
                )

            except Exception:
                # stale ABANDONED等を
                # FAILEDへ上書きしない。
                pass

            raise