import sqlite3
from datetime import datetime

import pytest

from db.connection import connect
from domain.time_rules import JST
from scripts.seed_dummy_data import (
    build_dummy_payload,
    seed_dummy_data,
)


def test_seed_dummy_data_inserts_requested_participants(
    tmp_path,
):
    db_path = tmp_path / "test.db"

    participant_ids = seed_dummy_data(
        db_path,
        count=2,
        prefix="demo",
        reference_date=datetime(
            2026,
            10,
            16,
            12,
            0,
            tzinfo=JST,
        ),
    )

    assert participant_ids == ["demo-001", "demo-002"]

    connection = connect(db_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM participants"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM study_targets"
        ).fetchone()[0] == 4
        assert connection.execute(
            "SELECT COUNT(*) FROM goals"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM available_times"
        ).fetchone()[0] == 10
    finally:
        connection.close()


def test_seed_dummy_data_rejects_duplicate_ids(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    seed_dummy_data(
        db_path,
        count=1,
        prefix="demo",
    )

    with pytest.raises(sqlite3.IntegrityError):
        seed_dummy_data(
            db_path,
            count=1,
            prefix="demo",
        )


def test_build_dummy_payload_uses_reference_date():
    payload = build_dummy_payload(
        "demo-001",
        datetime(
            2026,
            10,
            16,
            12,
            0,
            tzinfo=JST,
        ),
    )

    assert payload["participant_id"] == "demo-001"
    assert payload["goals"][0]["deadline_at"] == (
        "2026-10-30T12:00:00+09:00"
    )
