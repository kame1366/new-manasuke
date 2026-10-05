from datetime import datetime
import sqlite3

import pytest

from domain.enums import (
    Importance,
    StudyTargetKind,
)
from domain.models import (
    LearningPolicy,
    StudyTarget,
)
from domain.time_rules import JST
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


def setup_target(
    db_path,
) -> int:
    ParticipantRepository(
        db_path
    ).create(
        "participant-a",
        datetime(
            2026,
            10,
            5,
            9,
            0,
            tzinfo=JST,
        ),
    )

    return StudyTargetRepository(
        db_path
    ).create(
        StudyTarget(
            id=0,
            participant_id="participant-a",
            kind=StudyTargetKind.THEME,
            title="英作文",
        )
    )


def make_policy(
    target_id: int,
    *,
    normal_minutes: int = 30,
) -> LearningPolicy:
    return LearningPolicy(
        study_target_id=target_id,
        purpose="英作文の練習",
        policy_priority=Importance.HIGH,
        normal_sessions_per_week=4,
        normal_minutes=normal_minutes,
        minimum_sessions_per_week=2,
        minimum_minutes=15,
    )


def test_policy_can_be_created_and_loaded(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    target_id = setup_target(
        db_path
    )

    repository = LearningPolicyRepository(
        db_path
    )

    repository.create(
        "participant-a",
        make_policy(target_id),
    )

    loaded = repository.get_by_study_target(
        "participant-a",
        target_id,
    )

    assert loaded is not None
    assert loaded.normal_minutes == 30
    assert loaded.minimum_minutes == 15
    assert loaded.policy_priority == Importance.HIGH


def test_policy_can_be_updated(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    target_id = setup_target(
        db_path
    )

    repository = LearningPolicyRepository(
        db_path
    )

    repository.create(
        "participant-a",
        make_policy(target_id),
    )

    repository.update(
        "participant-a",
        make_policy(
            target_id,
            normal_minutes=45,
        ),
    )

    loaded = repository.get_by_study_target(
        "participant-a",
        target_id,
    )

    assert loaded is not None
    assert loaded.normal_minutes == 45


def test_duplicate_policy_is_rejected(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    target_id = setup_target(
        db_path
    )

    repository = LearningPolicyRepository(
        db_path
    )

    repository.create(
        "participant-a",
        make_policy(target_id),
    )

    with pytest.raises(
        sqlite3.IntegrityError
    ):
        repository.create(
            "participant-a",
            make_policy(target_id),
        )


def test_policy_changes_increment_version(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    target_id = setup_target(
        db_path
    )

    participant_repository = (
        ParticipantRepository(
            db_path
        )
    )

    repository = LearningPolicyRepository(
        db_path
    )

    # StudyTarget作成済みなので1
    assert (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
        == 1
    )

    repository.create(
        "participant-a",
        make_policy(target_id),
    )

    assert (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
        == 2
    )

    repository.update(
        "participant-a",
        make_policy(
            target_id,
            normal_minutes=45,
        ),
    )

    assert (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
        == 3
    )