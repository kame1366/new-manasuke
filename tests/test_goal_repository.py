from datetime import datetime

import pytest

from domain.enums import (
    GoalType,
    Importance,
    StudyTargetKind,
    UnitType,
)
from domain.errors import DomainValidationError
from domain.models import (
    Goal,
    GoalRange,
    StudyTarget,
    StudyTargetRange,
)
from domain.time_rules import JST
from repositories.goal_repository import (
    GoalRepository,
)
from repositories.participant_repository import (
    ParticipantRepository,
)
from repositories.study_target_repository import (
    StudyTargetRepository,
)
from scripts.migrate import run_migrations


def create_participant(
    db_path,
    participant_id: str,
) -> None:
    ParticipantRepository(
        db_path
    ).create(
        participant_id,
        datetime(
            2026,
            10,
            5,
            9,
            0,
            tzinfo=JST,
        ),
    )


def create_material_target(
    db_path,
    participant_id: str,
) -> int:
    return StudyTargetRepository(
        db_path
    ).create(
        StudyTarget(
            id=0,
            participant_id=participant_id,
            kind=StudyTargetKind.MATERIAL,
            title="数学問題集",
            unit_type=UnitType.PAGE,
            next_position=1,
            estimated_minutes_per_unit=5.0,
            ranges=[
                StudyTargetRange(
                    sequence_no=0,
                    start_position=1,
                    end_position=100,
                )
            ],
        )
    )


def test_goal_can_be_saved_and_loaded(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    create_participant(
        db_path,
        "participant-a",
    )

    target_id = create_material_target(
        db_path,
        "participant-a",
    )

    repository = GoalRepository(
        db_path
    )

    goal_id = repository.create(
        Goal(
            id=0,
            participant_id="participant-a",
            study_target_id=target_id,
            goal_type=GoalType.TEST,
            title="数学テスト",
            deadline_at=datetime(
                2026,
                10,
                20,
                18,
                0,
                tzinfo=JST,
            ),
            importance=Importance.HIGH,
            ranges=[
                GoalRange(
                    start_position=1,
                    end_position=80,
                )
            ],
        )
    )

    loaded = repository.get_by_id(
        "participant-a",
        goal_id,
    )

    assert loaded is not None
    assert loaded.title == "数学テスト"
    assert loaded.study_target_id == target_id
    assert loaded.importance == Importance.HIGH

    assert len(loaded.ranges) == 1
    assert loaded.ranges[0].start_position == 1
    assert loaded.ranges[0].end_position == 80


def test_goal_is_participant_scoped(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    create_participant(
        db_path,
        "participant-a",
    )
    create_participant(
        db_path,
        "participant-b",
    )

    target_id = create_material_target(
        db_path,
        "participant-a",
    )

    repository = GoalRepository(
        db_path
    )

    goal_id = repository.create(
        Goal(
            id=0,
            participant_id="participant-a",
            study_target_id=target_id,
            goal_type=GoalType.TEST,
            title="数学テスト",
            deadline_at=datetime(
                2026,
                10,
                20,
                18,
                0,
                tzinfo=JST,
            ),
            importance=Importance.HIGH,
        )
    )

    assert (
        repository.get_by_id(
            "participant-b",
            goal_id,
        )
        is None
    )


def test_goal_cannot_use_other_participant_target(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    create_participant(
        db_path,
        "participant-a",
    )
    create_participant(
        db_path,
        "participant-b",
    )

    target_id = create_material_target(
        db_path,
        "participant-a",
    )

    repository = GoalRepository(
        db_path
    )

    with pytest.raises(
        DomainValidationError,
        match=(
            "Goal StudyTarget does not belong "
            "to participant"
        ),
    ):
        repository.create(
            Goal(
                id=0,
                participant_id="participant-b",
                study_target_id=target_id,
                goal_type=GoalType.TEST,
                title="不正Goal",
                deadline_at=datetime(
                    2026,
                    10,
                    20,
                    18,
                    0,
                    tzinfo=JST,
                ),
                importance=Importance.HIGH,
            )
        )


def test_creating_goal_increments_version(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    create_participant(
        db_path,
        "participant-a",
    )

    target_id = create_material_target(
        db_path,
        "participant-a",
    )

    participant_repository = (
        ParticipantRepository(
            db_path
        )
    )

    assert (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
        == 1
    )

    GoalRepository(
        db_path
    ).create(
        Goal(
            id=0,
            participant_id="participant-a",
            study_target_id=target_id,
            goal_type=GoalType.TEST,
            title="数学テスト",
            deadline_at=datetime(
                2026,
                10,
                20,
                18,
                0,
                tzinfo=JST,
            ),
            importance=Importance.HIGH,
        )
    )

    assert (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
        == 2
    )