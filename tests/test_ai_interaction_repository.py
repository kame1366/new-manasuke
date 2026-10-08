from datetime import datetime

import pytest

from ai.errors import (
    AIInteractionAlreadyRunningError,
)
from domain.time_rules import JST
from repositories.ai_interaction_repository import (
    AI_OPERATION_LEARNING_POLICY,
    AI_STATUS_FAILED,
    AI_STATUS_RUNNING,
    AI_STATUS_SUCCEEDED,
    AIInteractionRepository,
)
from repositories.participant_repository import (
    ParticipantRepository,
)
from scripts.migrate import run_migrations


def setup_participant(
    db_path,
):
    ParticipantRepository(
        db_path
    ).create(
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


def test_running_ai_interaction_can_be_created(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    setup_participant(
        db_path
    )

    repository = (
        AIInteractionRepository(
            db_path
        )
    )

    interaction_id = (
        repository.start(
            participant_id=(
                "participant-a"
            ),
            operation_type=(
                AI_OPERATION_LEARNING_POLICY
            ),
            prompt_version=(
                "learning-policy-v1"
            ),
            model_name="test-model",
        )
    )

    record = repository.get_by_id(
        participant_id=(
            "participant-a"
        ),
        interaction_id=(
            interaction_id
        ),
    )

    assert record is not None

    assert (
        record.status
        == AI_STATUS_RUNNING
    )

    assert record.attempt_id is None


def test_second_running_interaction_is_rejected(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    setup_participant(
        db_path
    )

    repository = (
        AIInteractionRepository(
            db_path
        )
    )

    repository.start(
        participant_id=(
            "participant-a"
        ),
        operation_type=(
            AI_OPERATION_LEARNING_POLICY
        ),
        prompt_version=(
            "learning-policy-v1"
        ),
        model_name="test-model",
    )

    with pytest.raises(
        AIInteractionAlreadyRunningError
    ):
        repository.start(
            participant_id=(
                "participant-a"
            ),
            operation_type=(
                AI_OPERATION_LEARNING_POLICY
            ),
            prompt_version=(
                "learning-policy-v1"
            ),
            model_name="test-model",
        )


def test_interaction_can_be_marked_succeeded(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    setup_participant(
        db_path
    )

    repository = (
        AIInteractionRepository(
            db_path
        )
    )

    interaction_id = (
        repository.start(
            participant_id=(
                "participant-a"
            ),
            operation_type=(
                AI_OPERATION_LEARNING_POLICY
            ),
            prompt_version=(
                "learning-policy-v1"
            ),
            model_name="test-model",
        )
    )

    repository.mark_succeeded(
        participant_id=(
            "participant-a"
        ),
        interaction_id=(
            interaction_id
        ),
        structured_output_json=(
            '{"policies":[]}'
        ),
    )

    record = repository.get_by_id(
        participant_id=(
            "participant-a"
        ),
        interaction_id=(
            interaction_id
        ),
    )

    assert record is not None

    assert (
        record.status
        == AI_STATUS_SUCCEEDED
    )

    assert (
        record.structured_output_json
        == '{"policies":[]}'
    )


def test_failed_interaction_allows_new_run(
    tmp_path,
):
    db_path = (
        tmp_path
        / "test.db"
    )

    run_migrations(
        db_path
    )

    setup_participant(
        db_path
    )

    repository = (
        AIInteractionRepository(
            db_path
        )
    )

    interaction_id = (
        repository.start(
            participant_id=(
                "participant-a"
            ),
            operation_type=(
                AI_OPERATION_LEARNING_POLICY
            ),
            prompt_version=(
                "learning-policy-v1"
            ),
            model_name="test-model",
        )
    )

    repository.mark_failed(
        participant_id=(
            "participant-a"
        ),
        interaction_id=(
            interaction_id
        ),
        error_type="AI_FAILED",
    )

    record = repository.get_by_id(
        participant_id=(
            "participant-a"
        ),
        interaction_id=(
            interaction_id
        ),
    )

    assert record is not None

    assert (
        record.status
        == AI_STATUS_FAILED
    )

    second_id = repository.start(
        participant_id=(
            "participant-a"
        ),
        operation_type=(
            AI_OPERATION_LEARNING_POLICY
        ),
        prompt_version=(
            "learning-policy-v1"
        ),
        model_name="test-model",
    )

    assert (
        second_id
        != interaction_id
    )