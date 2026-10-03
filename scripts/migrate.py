from __future__ import annotations

import argparse
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from db.connection import connect
from domain.time_rules import UTC, to_db_utc


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_MIGRATIONS_DIR = (
    PROJECT_ROOT
    / "db"
    / "migrations"
)

DEFAULT_DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "manasuke.db"
)

MIGRATION_FILENAME_PATTERN = re.compile(
    r"^(?P<version>\d{3})_[a-z0-9_]+\.sql$"
)


@dataclass(frozen=True)
class Migration:
    version: int
    path: Path

    @property
    def filename(self) -> str:
        return self.path.name


def ensure_schema_migrations_table(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """
    )

    connection.commit()


def discover_migrations(
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
) -> list[Migration]:
    migrations: list[Migration] = []

    for path in migrations_dir.glob("*.sql"):
        match = MIGRATION_FILENAME_PATTERN.fullmatch(
            path.name
        )

        if match is None:
            raise ValueError(
                f"invalid migration filename: {path.name}"
            )

        migrations.append(
            Migration(
                version=int(
                    match.group("version")
                ),
                path=path,
            )
        )

    migrations.sort(
        key=lambda migration: migration.version
    )

    versions = [
        migration.version
        for migration in migrations
    ]

    if len(versions) != len(set(versions)):
        raise ValueError(
            "duplicate migration version detected"
        )

    return migrations


def load_applied_versions(
    connection: sqlite3.Connection,
) -> set[int]:
    rows = connection.execute(
        """
        SELECT version
        FROM schema_migrations
        ORDER BY version
        """
    ).fetchall()

    return {
        int(row["version"])
        for row in rows
    }


def sql_string_literal(
    value: str,
) -> str:
    escaped = value.replace(
        "'",
        "''",
    )

    return f"'{escaped}'"


def apply_migration(
    connection: sqlite3.Connection,
    migration: Migration,
) -> None:
    sql = migration.path.read_text(
        encoding="utf-8"
    )

    applied_at = to_db_utc(
        datetime.now(UTC)
    )

    migration_record_sql = f"""
        INSERT INTO schema_migrations (
            version,
            filename,
            applied_at
        )
        VALUES (
            {migration.version},
            {sql_string_literal(migration.filename)},
            {sql_string_literal(applied_at)}
        );
    """

    script = f"""
        BEGIN IMMEDIATE;

        {sql}

        {migration_record_sql}

        COMMIT;
    """

    try:
        connection.executescript(script)

    except Exception:
        if connection.in_transaction:
            connection.rollback()

        raise


def run_migrations(
    db_path: str | Path,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
) -> list[int]:
    database_path = Path(db_path)

    database_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    migrations = discover_migrations(
        migrations_dir
    )

    connection = connect(
        database_path
    )

    applied_now: list[int] = []

    try:
        ensure_schema_migrations_table(
            connection
        )

        already_applied = (
            load_applied_versions(
                connection
            )
        )

        for migration in migrations:
            if migration.version in already_applied:
                continue

            apply_migration(
                connection,
                migration,
            )

            applied_now.append(
                migration.version
            )

    finally:
        connection.close()

    return applied_now


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Apply Manasuke SQLite migrations."
        )
    )

    parser.add_argument(
        "db_path",
        nargs="?",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=(
            "SQLite database path. "
            "Defaults to data/manasuke.db"
        ),
    )

    args = parser.parse_args()

    applied = run_migrations(
        args.db_path
    )

    if applied:
        versions = ", ".join(
            f"{version:03d}"
            for version in applied
        )

        print(
            f"Applied migrations: {versions}"
        )

    else:
        print(
            "Database is already up to date."
        )


if __name__ == "__main__":
    main()