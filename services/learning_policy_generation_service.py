from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ai.errors import (
    AIGenerationError,
    AIOutputInvalidError,
    PlanningDataChangedError,
)
from ai.learning_policy_models import (
    LearningPolicyOutput,
)
from db.connection import transaction
from domain.errors import (
    DomainValidationError,
)
from domain.models import (
    AvailableTime,
    Goal,
    LearningPolicy,
    StudyTarget,
)
from domain.time_rules import (
    now_jst,
)
from repositories.ai_interaction_repository import (
    AI_OPERATION_LEARNING_POLICY,
    AIInteractionRepository,
)
from repositories.availability_repository import (
    AvailabilityRepository,
)
from repositories.goal_repository import (
    GoalRepository,
)
from repositories.learning_policy_repository import (
    LearningPolicyRepository,
)
from repositories.participant_repository import (
    ParticipantRepository,
)
from repositories.study_target_repository import (
    StudyTargetRepository,
)


logger = logging.getLogger(
    __name__
)


class LearningPolicyGeneratorProtocol(
    Protocol
):
    @property
    def model_name(
        self,
    ) -> str:
        ...

    @property
    def prompt_version(
        self,
    ) -> str:
        ...

    def generate(
        self,
        *,
        study_targets: list[
            StudyTarget
        ],
        goals: list[
            Goal
        ],
        available_times: list[
            AvailableTime
        ],
        reference_time: datetime,
    ) -> LearningPolicyOutput:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class LearningPolicyGenerationResult:
    interaction_id: int

    policies: tuple[
        LearningPolicy,
        ...,
    ]

    source_planning_data_version: int

    resulting_planning_data_version: int


class LearningPolicyGenerationService:
    """
    AI①全体を管理するApplication Service。

    OpenAI呼び出し中は
    DB transactionを保持しない。
    """

    def __init__(
        self,
        *,
        db_path: str | Path,
        generator: (
            LearningPolicyGeneratorProtocol
        ),
    ) -> None:
        self._db_path = Path(
            db_path
        )

        self._generator = (
            generator
        )

        self._participant_repository = (
            ParticipantRepository(
                self._db_path
            )
        )

        self._study_target_repository = (
            StudyTargetRepository(
                self._db_path
            )
        )

        self._goal_repository = (
            GoalRepository(
                self._db_path
            )
        )

        self._availability_repository = (
            AvailabilityRepository(
                self._db_path
            )
        )

        self._learning_policy_repository = (
            LearningPolicyRepository(
                self._db_path
            )
        )

        self._ai_interaction_repository = (
            AIInteractionRepository(
                self._db_path
            )
        )

    def generate_for_participant(
        self,
        participant_id: str,
        *,
        reference_time: (
            datetime | None
        ) = None,
    ) -> LearningPolicyGenerationResult:
        normalized_participant_id = (
            participant_id.strip()
        )

        if not normalized_participant_id:
            raise DomainValidationError(
                "participant_id "
                "must not be empty"
            )

        effective_reference_time = (
            reference_time
            if reference_time
            is not None
            else now_jst()
        )

        source_version_before = (
            self._participant_repository
            .get_planning_data_version(
                normalized_participant_id
            )
        )

        if (
            source_version_before
            is None
        ):
            raise DomainValidationError(
                "participant not found: "
                f"{normalized_participant_id}"
            )

        study_targets = (
            self._study_target_repository
            .list_by_participant(
                normalized_participant_id
            )
        )

        if not study_targets:
            raise DomainValidationError(
                "participant has no "
                "StudyTargets"
            )

        goals = (
            self._goal_repository
            .list_by_participant(
                normalized_participant_id
            )
        )

        available_times = (
            self._availability_repository
            .list_available_times(
                normalized_participant_id
            )
        )

        # 複数Repository read中に
        # Source Dataが変わっていないか確認。
        source_version_after_read = (
            self._participant_repository
            .get_planning_data_version(
                normalized_participant_id
            )
        )

        if (
            source_version_after_read
            != source_version_before
        ):
            raise PlanningDataChangedError(
                "planning data changed "
                "while loading AI input"
            )

        interaction_id = (
            self._ai_interaction_repository
            .start(
                participant_id=(
                    normalized_participant_id
                ),
                operation_type=(
                    AI_OPERATION_LEARNING_POLICY
                ),
                prompt_version=(
                    self._generator
                    .prompt_version
                ),
                model_name=(
                    self._generator
                    .model_name
                ),
            )
        )

        try:
            output = (
                self._generator.generate(
                    study_targets=(
                        study_targets
                    ),
                    goals=goals,
                    available_times=(
                        available_times
                    ),
                    reference_time=(
                        effective_reference_time
                    ),
                )
            )

            policies = (
                self._convert_to_domain_policies(
                    output=output,
                    study_targets=(
                        study_targets
                    ),
                )
            )

            structured_json = (
                output.model_dump_json()
            )

            with transaction(
                self._db_path
            ) as connection:
                current_version = (
                    ParticipantRepository
                    .get_planning_data_version_in_transaction(
                        connection,
                        normalized_participant_id,
                    )
                )

                if (
                    current_version
                    != source_version_before
                ):
                    raise (
                        PlanningDataChangedError(
                            "planning data changed "
                            "while AI was running"
                        )
                    )

                for policy in policies:
                    (
                        self
                        ._learning_policy_repository
                        .upsert(
                            connection,
                            normalized_participant_id,
                            policy,
                        )
                    )

                ParticipantRepository.increment_planning_data_version(
                    connection,
                    normalized_participant_id,
                )

                (
                    AIInteractionRepository
                    .mark_succeeded_in_transaction(
                        connection,
                        participant_id=(
                            normalized_participant_id
                        ),
                        interaction_id=(
                            interaction_id
                        ),
                        structured_output_json=(
                            structured_json
                        ),
                    )
                )

            return (
                LearningPolicyGenerationResult(
                    interaction_id=(
                        interaction_id
                    ),
                    policies=tuple(
                        policies
                    ),
                    source_planning_data_version=(
                        source_version_before
                    ),
                    resulting_planning_data_version=(
                        source_version_before
                        + 1
                    ),
                )
            )

        except Exception as exc:
            error_type = (
                self._classify_error(
                    exc
                )
            )

            try:
                (
                    self
                    ._ai_interaction_repository
                    .mark_failed(
                        participant_id=(
                            normalized_participant_id
                        ),
                        interaction_id=(
                            interaction_id
                        ),
                        error_type=(
                            error_type
                        ),
                    )
                )

            except Exception:
                # 元のfailureを隠さない。
                logger.exception(
                    "failed to mark "
                    "AIInteraction as FAILED",
                    extra={
                        "participant_id": (
                            normalized_participant_id
                        ),
                        "operation": (
                            AI_OPERATION_LEARNING_POLICY
                        ),
                        "interaction_id": (
                            interaction_id
                        ),
                    },
                )

            raise

    @staticmethod
    def _convert_to_domain_policies(
        *,
        output: LearningPolicyOutput,
        study_targets: list[
            StudyTarget
        ],
    ) -> list[
        LearningPolicy
    ]:
        expected_ids = {
            target.id
            for target
            in study_targets
        }

        output_ids = [
            proposal.study_target_id
            for proposal
            in output.policies
        ]

        if len(
            output_ids
        ) != len(
            set(
                output_ids
            )
        ):
            raise AIOutputInvalidError(
                "AI output contains "
                "duplicate study_target_id"
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
                "AI output StudyTarget IDs "
                "do not match input; "
                f"missing={missing}, "
                f"unknown={unknown}"
            )

        policies: list[
            LearningPolicy
        ] = []

        try:
            for proposal in (
                output.policies
            ):
                policies.append(
                    LearningPolicy(
                        study_target_id=(
                            proposal
                            .study_target_id
                        ),
                        purpose=(
                            proposal
                            .purpose
                        ),
                        policy_priority=(
                            proposal
                            .policy_priority
                        ),
                        normal_sessions_per_week=(
                            proposal
                            .normal_sessions_per_week
                        ),
                        normal_minutes=(
                            proposal
                            .normal_minutes
                        ),
                        minimum_sessions_per_week=(
                            proposal
                            .minimum_sessions_per_week
                        ),
                        minimum_minutes=(
                            proposal
                            .minimum_minutes
                        ),
                    )
                )

        except DomainValidationError as exc:
            raise AIOutputInvalidError(
                "AI output failed "
                "LearningPolicy "
                "domain validation"
            ) from exc

        policies.sort(
            key=lambda policy: (
                policy.study_target_id
            )
        )

        return policies

    @staticmethod
    def _classify_error(
        exc: Exception,
    ) -> str:
        if isinstance(
            exc,
            PlanningDataChangedError,
        ):
            return (
                "PLANNING_DATA_CHANGED"
            )

        if isinstance(
            exc,
            AIOutputInvalidError,
        ):
            return (
                "AI_OUTPUT_INVALID"
            )

        if isinstance(
            exc,
            AIGenerationError,
        ):
            return "AI_FAILED"

        return "AI_FAILED"