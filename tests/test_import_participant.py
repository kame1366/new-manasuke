import json
from datetime import datetime

import pytest

from db.connection import connect
from domain.errors import DomainValidationError
from domain.time_rules import JST
from repositories.participant_repository import (
    ParticipantRepository,
)
from scripts.import_participant import (
    import_participant,
)
from scripts.migrate import run_migrations


def make_valid_payload() -> dict:
    return {
        "participant_id": "participant-import-test",

        "study_targets": [
            {
                "key": "math",
                "kind": "MATERIAL",
                "title": "数学問題集",
                "unit_type": "PAGE",
                "next_position": 1,
                "estimated_minutes_per_unit": 5.0,
                "ranges": [
                    {
                        "sequence_no": 0,
                        "start_position": 1,
                        "end_position": 100,
                    }
                ],
            },
            {
                "key": "writing",
                "kind": "THEME",
                "title": "英作文練習",
            },
        ],

        "goals": [
            {
                "study_target_key": "math",
                "goal_type": "TEST",
                "title": "数学テスト",
                "deadline_at": (
                    "2026-10-20T18:00:00+09:00"
                ),
                "importance": "HIGH",
                "ranges": [
                    {
                        "start_position": 1,
                        "end_position": 80,
                    }
                ],
            }
        ],

        "available_times": [
            {
                "weekday": 0,
                "start_minute_of_day": 1080,
                "end_minute_of_day": 1200,
            }
        ],

        "busy_events": [
            {
                "start_at": (
                    "2026-10-06T19:00:00+09:00"
                ),
                "end_at": (
                    "2026-10-06T20:00:00+09:00"
                ),
            }
        ],

        "extra_available_times": [
            {
                "start_at": (
                    "2026-10-10T09:00:00+09:00"
                ),
                "end_at": (
                    "2026-10-10T11:00:00+09:00"
                ),
            }
        ],
    }


def write_payload(
    tmp_path,
    payload: dict,
):
    path = (
        tmp_path
        / "participant.json"
    )

    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return path


def test_participant_json_can_be_imported(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    json_path = write_payload(
        tmp_path,
        make_valid_payload(),
    )

    participant_id = import_participant(
        json_path,
        db_path,
        created_at=datetime(
            2026,
            10,
            5,
            9,
            0,
            tzinfo=JST,
        ),
    )

    assert (
        participant_id
        == "participant-import-test"
    )

    participant_repository = (
        ParticipantRepository(
            db_path
        )
    )

    assert participant_repository.exists(
        participant_id
    )

    # import全体でversionは1回だけ増える
    assert (
        participant_repository
        .get_planning_data_version(
            participant_id
        )
        == 1
    )


def test_import_creates_expected_rows(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    json_path = write_payload(
        tmp_path,
        make_valid_payload(),
    )

    import_participant(
        json_path,
        db_path,
        created_at=datetime(
            2026,
            10,
            5,
            9,
            0,
            tzinfo=JST,
        ),
    )

    connection = connect(
        db_path
    )

    try:
        assert (
            connection.execute(
                """
                SELECT COUNT(*)
                FROM study_targets
                """
            ).fetchone()[0]
            == 2
        )

        assert (
            connection.execute(
                """
                SELECT COUNT(*)
                FROM goals
                """
            ).fetchone()[0]
            == 1
        )

        assert (
            connection.execute(
                """
                SELECT COUNT(*)
                FROM available_times
                """
            ).fetchone()[0]
            == 1
        )

        assert (
            connection.execute(
                """
                SELECT COUNT(*)
                FROM busy_events
                """
            ).fetchone()[0]
            == 1
        )

        assert (
            connection.execute(
                """
                SELECT COUNT(*)
                FROM extra_available_times
                """
            ).fetchone()[0]
            == 1
        )

    finally:
        connection.close()


def test_goal_is_linked_to_imported_target(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    json_path = write_payload(
        tmp_path,
        make_valid_payload(),
    )

    import_participant(
        json_path,
        db_path,
        created_at=datetime(
            2026,
            10,
            5,
            9,
            0,
            tzinfo=JST,
        ),
    )

    connection = connect(
        db_path
    )

    try:
        row = connection.execute(
            """
            SELECT
                goals.study_target_id,
                study_targets.title
            FROM goals
            JOIN study_targets
              ON study_targets.id =
                 goals.study_target_id
            LIMIT 1
            """
        ).fetchone()

        assert row is not None
        assert (
            row["title"]
            == "数学問題集"
        )

    finally:
        connection.close()


def test_import_is_rolled_back_on_invalid_goal_target(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    payload = make_valid_payload()

    payload["goals"][0][
        "study_target_key"
    ] = "does-not-exist"

    json_path = write_payload(
        tmp_path,
        payload,
    )

    with pytest.raises(
        DomainValidationError,
        match=(
            "unknown study_target_key"
        ),
    ):
        import_participant(
            json_path,
            db_path,
            created_at=datetime(
                2026,
                10,
                5,
                9,
                0,
                tzinfo=JST,
            ),
        )

    # transaction全体がrollbackされるので
    # participantも残らない
    repository = ParticipantRepository(
        db_path
    )

    assert (
        repository.exists(
            "participant-import-test"
        )
        is False
    )


def test_duplicate_study_target_key_rolls_back(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    payload = make_valid_payload()

    payload["study_targets"][1][
        "key"
    ] = "math"

    json_path = write_payload(
        tmp_path,
        payload,
    )

    with pytest.raises(
        DomainValidationError,
        match="duplicate StudyTarget key",
    ):
        import_participant(
            json_path,
            db_path,
            created_at=datetime(
                2026,
                10,
                5,
                9,
                0,
                tzinfo=JST,
            ),
        )

    repository = ParticipantRepository(
        db_path
    )

    assert (
        repository.exists(
            "participant-import-test"
        )
        is False
    )