from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


DEFAULT_BUSY_TIMEOUT_MS = 5000


def connect(
    db_path: str | Path,
) -> sqlite3.Connection:
    """Open a configured SQLite connection."""

    connection = sqlite3.connect(
        str(db_path),
        timeout=DEFAULT_BUSY_TIMEOUT_MS / 1000,
    )

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )
    connection.execute(
        f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}"
    )

    # WAL is persistent for a file-backed SQLite DB.
    connection.execute(
        "PRAGMA journal_mode = WAL"
    )

    return connection


@contextmanager
def transaction(
    db_path: str | Path,
) -> Generator[sqlite3.Connection, None, None]:
    """Open a short-lived transaction."""

    connection = connect(db_path)

    try:
        connection.execute("BEGIN")
        yield connection
        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()