import sqlite3

import pytest

from db.connection import connect
from scripts.migrate import run_migrations


EXPECTED_TABLES = {
    "schema_migrations",
    "participants",
    "study_targets",
    "study_target_ranges",
    "goals",
    "goal_ranges",
    "learning_policies",
    "available_times",
    "busy_events",
    "extra_available_times",
    "plans",
    "plan_items",
    "plan_item_adjustments",
    "study_results",
    "study_result_revisions",
    "plan_generation_attempts",
    "plan_goal_decisions",
    "plan_feasibility_snapshots",
    "plan_feasibility_deadline_snapshots",
    "ai_interactions",
}


def test_initial_migration_creates_all_tables(
    tmp_path,
):
    db_path = tmp_path / "test.db"

    applied = run_migrations(
        db_path
    )

    assert applied == [1, 2, 3]

    connection = connect(
        db_path
    )

    try:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()

        actual_tables = {
            row["name"]
            for row in rows
        }

        assert EXPECTED_TABLES <= actual_tables

    finally:
        connection.close()


def test_migrations_are_idempotent(
    tmp_path,
):
    db_path = tmp_path / "test.db"

    first = run_migrations(
        db_path
    )

    second = run_migrations(
        db_path
    )

    assert first == [1, 2, 3]
    assert second == []

    connection = connect(
        db_path
    )

    try:
        count = connection.execute(
            """
            SELECT COUNT(*)
            FROM schema_migrations
            """
        ).fetchone()[0]

        assert count == 3

    finally:
        connection.close()


def test_foreign_key_rejects_unknown_participant(
    tmp_path,
):
    db_path = tmp_path / "test.db"

    run_migrations(
        db_path
    )

    connection = connect(
        db_path
    )

    try:
        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                INSERT INTO study_targets (
                    participant_id,
                    kind,
                    title,
                    unit_type,
                    next_position,
                    estimated_minutes_per_unit,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?
                )
                """,
                (
                    "does-not-exist",
                    "MATERIAL",
                    "数学",
                    "PAGE",
                    1,
                    5.0,
                    "2026-10-03T00:00:00Z",
                    "2026-10-03T00:00:00Z",
                ),
            )

    finally:
        connection.close()


def test_only_one_in_progress_attempt_per_participant(
    tmp_path,
):
    db_path = tmp_path / "test.db"

    run_migrations(
        db_path
    )

    connection = connect(
        db_path
    )

    try:
        connection.execute(
            """
            INSERT INTO participants (
                id,
                planning_data_version,
                created_at
            )
            VALUES (?, 0, ?)
            """,
            (
                "participant-001",
                "2026-10-03T00:00:00Z",
            ),
        )

        connection.execute(
            """
            INSERT INTO plan_generation_attempts (
                participant_id,
                operation_type,
                source_planning_data_version,
                status,
                stage,
                started_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "participant-001",
                "INITIAL",
                0,
                "IN_PROGRESS",
                "FEASIBILITY",
                "2026-10-03T00:00:00Z",
                "2026-10-03T00:00:00Z",
            ),
        )

        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                INSERT INTO plan_generation_attempts (
                    participant_id,
                    operation_type,
                    source_planning_data_version,
                    status,
                    stage,
                    started_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "participant-001",
                    "REPLAN_NOW",
                    0,
                    "IN_PROGRESS",
                    "FEASIBILITY",
                    "2026-10-03T01:00:00Z",
                    "2026-10-03T01:00:00Z",
                ),
            )

    finally:
        connection.close()