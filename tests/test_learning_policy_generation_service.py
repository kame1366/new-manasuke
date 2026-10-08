from datetime import datetime

import pytest

from ai.errors import (
    AIGenerationError,
    AIOutputInvalidError,
    PlanningDataChangedError,
)
from ai.learning_policy_models import (
    LearningPolicyOutput,
    LearningPolicyProposal,
)
from db.connection import transaction
from domain.enums import (
    Importance,
    StudyTargetKind,
)
from domain.models import (
    StudyTarget,
)
from domain.time_rules import JST
from repositories.ai_interaction_repository import (
    AI_OPERATION_LEARNING_POLICY,
    AI_STATUS_FAILED,
    AI_STATUS_SUCCEEDED,
    AIInteractionRepository,
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
from scripts.migrate import run_migrations
from services.learning_policy_generation_service import (
    LearningPolicyGenerationService,
)


class FakeGenerator:
    model_name = "test-model"

    prompt_version = (
        "learning-policy-test-v1"
    )

    def __init__(
        self,
        *,
        output=None,
        error=None,
        on_generate=None,
    ):
        self._output = output
        self._error = error
        self._on_generate = (
            on_generate
        )

        self.calls = 0

    def generate(
        self,
        *,
        study_targets,
        goals,
        available_times,
        reference_time,
    ):
        self.calls += 1

        if (
            self._on_generate
            is not None
        ):
            self._on_generate()

        if self._error is not None:
            raise self._error

        return self._output


def setup_participant_with_targets(
    db_path,
):
    participant_repository = (
        ParticipantRepository(
            db_path
        )
    )

    participant_repository.create(
        "participant-a",
        datetime(
            2026,
            10,
            10,
            9,
            0,
            tzinfo=JST,
        ),
    )

    target_repository = (
        StudyTargetRepository(
            db_path
        )
    )

    first_id = (
        target_repository.create(
            StudyTarget(
                id=0,
                participant_id=(
                    "participant-a"
                ),
                kind=(
                    StudyTargetKind.THEME
                ),
                title="英作文",
            )
        )
    )

    second_id = (
        target_repository.create(
            StudyTarget(
                id=0,
                participant_id=(
                    "participant-a"
                ),
                kind=(
                    StudyTargetKind.THEME
                ),
                title="歴史の復習",
            )
        )
    )

    return (
        first_id,
        second_id,
    )


def make_output(
    first_id: int,
    second_id: int,
):
    return LearningPolicyOutput(
        policies=[
            LearningPolicyProposal(
                study_target_id=(
                    first_id
                ),
                purpose=(
                    "英作文の練習を続ける"
                ),
                policy_priority=(
                    Importance.HIGH
                ),
                normal_sessions_per_week=4,
                normal_minutes=30,
                minimum_sessions_per_week=2,
                minimum_minutes=15,
            ),
            LearningPolicyProposal(
                study_target_id=(
                    second_id
                ),
                purpose=(
                    "歴史の内容を復習する"
                ),
                policy_priority=(
                    Importance.MEDIUM
                ),
                normal_sessions_per_week=3,
                normal_minutes=30,
                minimum_sessions_per_week=1,
                minimum_minutes=15,
            ),
        ]
    )


def test_service_saves_all_policies_atomically(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    (
        first_id,
        second_id,
    ) = setup_participant_with_targets(
        db_path
    )

    participant_repository = (
        ParticipantRepository(
            db_path
        )
    )

    before_version = (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
    )

    assert before_version == 2

    generator = FakeGenerator(
        output=make_output(
            first_id,
            second_id,
        )
    )

    service = (
        LearningPolicyGenerationService(
            db_path=db_path,
            generator=generator,
        )
    )

    result = (
        service
        .generate_for_participant(
            "participant-a",
            reference_time=datetime(
                2026,
                10,
                10,
                12,
                0,
                tzinfo=JST,
            ),
        )
    )

    policy_repository = (
        LearningPolicyRepository(
            db_path
        )
    )

    policies = (
        policy_repository
        .list_by_participant(
            "participant-a"
        )
    )

    assert len(policies) == 2

    # 2 policyを書いたが、
    # AI① operation全体で
    # planning_data_versionは1回だけ増える。
    assert (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
        == 3
    )

    assert (
        result
        .source_planning_data_version
        == 2
    )

    assert (
        result
        .resulting_planning_data_version
        == 3
    )


def test_successful_service_marks_interaction_succeeded(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    (
        first_id,
        second_id,
    ) = setup_participant_with_targets(
        db_path
    )

    service = (
        LearningPolicyGenerationService(
            db_path=db_path,
            generator=FakeGenerator(
                output=make_output(
                    first_id,
                    second_id,
                )
            ),
        )
    )

    result = (
        service
        .generate_for_participant(
            "participant-a",
            reference_time=datetime(
                2026,
                10,
                10,
                12,
                0,
                tzinfo=JST,
            ),
        )
    )

    repository = (
        AIInteractionRepository(
            db_path
        )
    )

    record = repository.get_by_id(
        participant_id=(
            "participant-a"
        ),
        interaction_id=(
            result.interaction_id
        ),
    )

    assert record is not None

    assert (
        record.status
        == AI_STATUS_SUCCEEDED
    )

    assert (
        record
        .structured_output_json
        is not None
    )


def test_missing_policy_is_rejected_and_nothing_is_saved(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    (
        first_id,
        _second_id,
    ) = setup_participant_with_targets(
        db_path
    )

    participant_repository = (
        ParticipantRepository(
            db_path
        )
    )

    before_version = (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
    )

    bad_output = (
        LearningPolicyOutput(
            policies=[
                LearningPolicyProposal(
                    study_target_id=(
                        first_id
                    ),
                    purpose="英作文",
                    policy_priority=(
                        Importance.HIGH
                    ),
                    normal_sessions_per_week=4,
                    normal_minutes=30,
                    minimum_sessions_per_week=2,
                    minimum_minutes=15,
                )
            ]
        )
    )

    service = (
        LearningPolicyGenerationService(
            db_path=db_path,
            generator=FakeGenerator(
                output=bad_output
            ),
        )
    )

    with pytest.raises(
        AIOutputInvalidError,
        match=(
            "StudyTarget IDs "
            "do not match"
        ),
    ):
        (
            service
            .generate_for_participant(
                "participant-a",
                reference_time=datetime(
                    2026,
                    10,
                    10,
                    12,
                    0,
                    tzinfo=JST,
                ),
            )
        )

    policies = (
        LearningPolicyRepository(
            db_path
        ).list_by_participant(
            "participant-a"
        )
    )

    assert policies == []

    assert (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
        == before_version
    )

    interaction = (
        AIInteractionRepository(
            db_path
        )
        .get_latest_for_operation(
            participant_id=(
                "participant-a"
            ),
            operation_type=(
                AI_OPERATION_LEARNING_POLICY
            ),
        )
    )

    assert interaction is not None

    assert (
        interaction.status
        == AI_STATUS_FAILED
    )

    assert (
        interaction.error_type
        == "AI_OUTPUT_INVALID"
    )


def test_api_failure_marks_interaction_failed(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    setup_participant_with_targets(
        db_path
    )

    service = (
        LearningPolicyGenerationService(
            db_path=db_path,
            generator=FakeGenerator(
                error=AIGenerationError(
                    "simulated API failure"
                )
            ),
        )
    )

    with pytest.raises(
        AIGenerationError
    ):
        (
            service
            .generate_for_participant(
                "participant-a",
                reference_time=datetime(
                    2026,
                    10,
                    10,
                    12,
                    0,
                    tzinfo=JST,
                ),
            )
        )

    interaction = (
        AIInteractionRepository(
            db_path
        )
        .get_latest_for_operation(
            participant_id=(
                "participant-a"
            ),
            operation_type=(
                AI_OPERATION_LEARNING_POLICY
            ),
        )
    )

    assert interaction is not None

    assert (
        interaction.status
        == AI_STATUS_FAILED
    )

    assert (
        interaction.error_type
        == "AI_FAILED"
    )


def test_source_data_change_during_ai_call_blocks_stale_save(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    (
        first_id,
        second_id,
    ) = setup_participant_with_targets(
        db_path
    )

    def change_source_data():
        with transaction(
            db_path
        ) as connection:
            ParticipantRepository.increment_planning_data_version(
                connection,
                "participant-a",
            )

    generator = FakeGenerator(
        output=make_output(
            first_id,
            second_id,
        ),
        on_generate=(
            change_source_data
        ),
    )

    service = (
        LearningPolicyGenerationService(
            db_path=db_path,
            generator=generator,
        )
    )

    with pytest.raises(
        PlanningDataChangedError,
        match=(
            "planning data changed "
            "while AI was running"
        ),
    ):
        (
            service
            .generate_for_participant(
                "participant-a",
                reference_time=datetime(
                    2026,
                    10,
                    10,
                    12,
                    0,
                    tzinfo=JST,
                ),
            )
        )

    policies = (
        LearningPolicyRepository(
            db_path
        )
        .list_by_participant(
            "participant-a"
        )
    )

    assert policies == []

    interaction = (
        AIInteractionRepository(
            db_path
        )
        .get_latest_for_operation(
            participant_id=(
                "participant-a"
            ),
            operation_type=(
                AI_OPERATION_LEARNING_POLICY
            ),
        )
    )

    assert interaction is not None

    assert (
        interaction.status
        == AI_STATUS_FAILED
    )

    assert (
        interaction.error_type
        == "PLANNING_DATA_CHANGED"
    )