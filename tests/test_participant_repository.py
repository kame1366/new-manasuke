import sqlite3
from datetime import datetime

import pytest

from db.connection import connect
from domain.errors import DomainValidationError
from domain.time_rules import JST
from repositories.participant_repository import (
    ParticipantRepository,
)
from scripts.migrate import run_migrations


@pytest.fixture
def migrated_db(tmp_path):
    db_path = tmp_path / "test.db"

    run_migrations(
        db_path
    )

    return db_path


def test_participant_does_not_exist_initially(
    migrated_db,
):
    repository = ParticipantRepository(
        migrated_db
    )

    assert (
        repository.exists(
            "participant-001"
        )
        is False
    )


def test_participant_can_be_created(
    migrated_db,
):
    repository = ParticipantRepository(
        migrated_db
    )

    repository.create(
        participant_id="participant-001",
        created_at=datetime(
            2026,
            10,
            3,
            12,
            0,
            tzinfo=JST,
        ),
    )

    assert repository.exists(
        "participant-001"
    )


def test_new_participant_has_zero_planning_data_version(
    migrated_db,
):
    repository = ParticipantRepository(
        migrated_db
    )

    repository.create(
        participant_id="participant-001",
        created_at=datetime(
            2026,
            10,
            3,
            12,
            0,
            tzinfo=JST,
        ),
    )

    assert (
        repository.get_planning_data_version(
            "participant-001"
        )
        == 0
    )


def test_created_at_is_stored_as_utc(
    migrated_db,
):
    repository = ParticipantRepository(
        migrated_db
    )

    repository.create(
        participant_id="participant-001",
        created_at=datetime(
            2026,
            10,
            3,
            12,
            0,
            tzinfo=JST,
        ),
    )

    connection = connect(
        migrated_db
    )

    try:
        row = connection.execute(
            """
            SELECT created_at
            FROM participants
            WHERE id = ?
            """,
            (
                "participant-001",
            ),
        ).fetchone()

        assert (
            row["created_at"]
            == "2026-10-03T03:00:00Z"
        )

    finally:
        connection.close()


def test_duplicate_participant_is_rejected(
    migrated_db,
):
    repository = ParticipantRepository(
        migrated_db
    )

    created_at = datetime(
        2026,
        10,
        3,
        12,
        0,
        tzinfo=JST,
    )

    repository.create(
        "participant-001",
        created_at,
    )

    with pytest.raises(
        sqlite3.IntegrityError
    ):
        repository.create(
            "participant-001",
            created_at,
        )


def test_blank_participant_id_is_rejected(
    migrated_db,
):
    repository = ParticipantRepository(
        migrated_db
    )

    with pytest.raises(
        DomainValidationError,
        match="participant_id must not be empty",
    ):
        repository.create(
            participant_id="   ",
            created_at=datetime(
                2026,
                10,
                3,
                12,
                0,
                tzinfo=JST,
            ),
        )