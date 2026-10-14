from datetime import datetime

from domain.models import (
    AvailableTime,
    BusyEvent,
    ExtraAvailableTime,
)
from domain.time_rules import (
    JST,
    to_utc,
)
from repositories.availability_repository import (
    AvailabilityRepository,
)
from repositories.participant_repository import (
    ParticipantRepository,
)
from scripts.migrate import run_migrations


def setup_participant(
    db_path,
) -> ParticipantRepository:
    repository = ParticipantRepository(
        db_path
    )

    repository.create(
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

    return repository


def test_available_times_can_be_replaced(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    setup_participant(
        db_path
    )

    repository = AvailabilityRepository(
        db_path
    )

    repository.replace_available_times(
        "participant-a",
        [
            AvailableTime(
                weekday=0,
                start_minute_of_day=1080,
                end_minute_of_day=1200,
            ),
            AvailableTime(
                weekday=2,
                start_minute_of_day=900,
                end_minute_of_day=1050,
            ),
        ],
    )

    loaded = repository.list_available_times(
        "participant-a"
    )

    assert len(loaded) == 2
    assert loaded[0].weekday == 0
    assert loaded[1].weekday == 2


def test_replace_available_times_replaces_old_rows(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    setup_participant(
        db_path
    )

    repository = AvailabilityRepository(
        db_path
    )

    repository.replace_available_times(
        "participant-a",
        [
            AvailableTime(
                weekday=0,
                start_minute_of_day=600,
                end_minute_of_day=720,
            )
        ],
    )

    repository.replace_available_times(
        "participant-a",
        [
            AvailableTime(
                weekday=4,
                start_minute_of_day=1080,
                end_minute_of_day=1200,
            )
        ],
    )

    loaded = repository.list_available_times(
        "participant-a"
    )

    assert len(loaded) == 1
    assert loaded[0].weekday == 4


def test_busy_event_can_be_saved(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    setup_participant(
        db_path
    )

    repository = AvailabilityRepository(
        db_path
    )

    original = BusyEvent(
        start_at=datetime(
            2026,
            10,
            6,
            23,
            0,
            tzinfo=JST,
        ),
        note="通院",
        end_at=datetime(
            2026,
            10,
            7,
            1,
            0,
            tzinfo=JST,
        ),
    )

    repository.add_busy_event(
        "participant-a",
        original,
    )

    loaded = repository.list_busy_events(
        "participant-a"
    )

    assert len(loaded) == 1
    assert (
        loaded[0].start_at
        == to_utc(original.start_at)
    )
    assert (
        loaded[0].end_at
        == to_utc(original.end_at)
    )
    assert loaded[0].note == original.note


def test_extra_available_time_can_be_saved(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    setup_participant(
        db_path
    )

    repository = AvailabilityRepository(
        db_path
    )

    original = ExtraAvailableTime(
        start_at=datetime(
            2026,
            10,
            10,
            9,
            0,
            tzinfo=JST,
        ),
        note="臨時枠",
        end_at=datetime(
            2026,
            10,
            10,
            11,
            0,
            tzinfo=JST,
        ),
    )

    repository.add_extra_available_time(
        "participant-a",
        original,
    )

    loaded = (
        repository.list_extra_available_times(
            "participant-a"
        )
    )

    assert len(loaded) == 1
    assert (
        loaded[0].start_at
        == to_utc(original.start_at)
    )
    assert loaded[0].note == original.note


def test_availability_changes_increment_version(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    participant_repository = (
        setup_participant(
            db_path
        )
    )

    repository = AvailabilityRepository(
        db_path
    )

    assert (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
        == 0
    )

    repository.replace_available_times(
        "participant-a",
        [
            AvailableTime(
                weekday=0,
                start_minute_of_day=1080,
                end_minute_of_day=1200,
            )
        ],
    )

    assert (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
        == 1
    )

    repository.add_busy_event(
        "participant-a",
        BusyEvent(
            start_at=datetime(
                2026,
                10,
                6,
                18,
                0,
                tzinfo=JST,
            ),
            end_at=datetime(
                2026,
                10,
                6,
                19,
                0,
                tzinfo=JST,
            ),
        ),
    )

    assert (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
        == 2
    )

    repository.add_extra_available_time(
        "participant-a",
        ExtraAvailableTime(
            start_at=datetime(
                2026,
                10,
                7,
                20,
                0,
                tzinfo=JST,
            ),
            end_at=datetime(
                2026,
                10,
                7,
                21,
                0,
                tzinfo=JST,
            ),
        ),
    )

    assert (
        participant_repository
        .get_planning_data_version(
            "participant-a"
        )
        == 3
    )