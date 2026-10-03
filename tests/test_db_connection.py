from db.connection import connect


def test_connection_enables_foreign_keys(
    tmp_path,
):
    db_path = tmp_path / "test.db"

    connection = connect(db_path)

    try:
        result = connection.execute(
            "PRAGMA foreign_keys"
        ).fetchone()

        assert result[0] == 1

    finally:
        connection.close()


def test_connection_sets_busy_timeout(
    tmp_path,
):
    db_path = tmp_path / "test.db"

    connection = connect(db_path)

    try:
        result = connection.execute(
            "PRAGMA busy_timeout"
        ).fetchone()

        assert result[0] == 5000

    finally:
        connection.close()


def test_connection_uses_wal_mode(
    tmp_path,
):
    db_path = tmp_path / "test.db"

    connection = connect(db_path)

    try:
        result = connection.execute(
            "PRAGMA journal_mode"
        ).fetchone()

        assert result[0].lower() == "wal"

    finally:
        connection.close()