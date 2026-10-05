from datetime import datetime

from domain.enums import (
    StudyTargetKind,
    UnitType,
)
from domain.models import (
    StudyTarget,
    StudyTargetRange,
)
from domain.time_rules import JST
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
    repository = ParticipantRepository(
        db_path
    )

    repository.create(
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


def test_material_study_target_can_be_saved_and_loaded(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    create_participant(
        db_path,
        "participant-a",
    )

    repository = StudyTargetRepository(
        db_path
    )

    target = StudyTarget(
        id=0,
        participant_id="participant-a",
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

    target_id = repository.create(
        target
    )

    loaded = repository.get_by_id(
        "participant-a",
        target_id,
    )

    assert loaded is not None
    assert loaded.id == target_id
    assert loaded.title == "数学問題集"
    assert loaded.kind == StudyTargetKind.MATERIAL
    assert loaded.unit_type == UnitType.PAGE
    assert loaded.next_position == 1
    assert loaded.estimated_minutes_per_unit == 5.0

    assert len(loaded.ranges) == 1
    assert loaded.ranges[0].start_position == 1
    assert loaded.ranges[0].end_position == 100


def test_theme_study_target_can_be_saved_and_loaded(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    create_participant(
        db_path,
        "participant-a",
    )

    repository = StudyTargetRepository(
        db_path
    )

    target = StudyTarget(
        id=0,
        participant_id="participant-a",
        kind=StudyTargetKind.THEME,
        title="英作文練習",
        note="自由英作文",
    )

    target_id = repository.create(
        target
    )

    loaded = repository.get_by_id(
        "participant-a",
        target_id,
    )

    assert loaded is not None
    assert loaded.kind == StudyTargetKind.THEME
    assert loaded.unit_type is None
    assert loaded.next_position is None
    assert loaded.estimated_minutes_per_unit is None


def test_study_target_is_participant_scoped(
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

    repository = StudyTargetRepository(
        db_path
    )

    target = StudyTarget(
        id=0,
        participant_id="participant-a",
        kind=StudyTargetKind.THEME,
        title="復習",
    )

    target_id = repository.create(
        target
    )

    assert (
        repository.get_by_id(
            "participant-b",
            target_id,
        )
        is None
    )


def test_creating_study_target_increments_version(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    create_participant(
        db_path,
        "participant-a",
    )

    participant_repository = (
        ParticipantRepository(
            db_path
        )
    )

    repository = StudyTargetRepository(
        db_path
    )

    assert (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
        == 0
    )

    repository.create(
        StudyTarget(
            id=0,
            participant_id="participant-a",
            kind=StudyTargetKind.THEME,
            title="復習",
        )
    )

    assert (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
        == 1
    )