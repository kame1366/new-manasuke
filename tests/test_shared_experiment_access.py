"""Regression tests for explicitly selected shared experiment access."""
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.create_participant import create_empty_participant, create_participant
from scripts.migrate import run_migrations
from ui.runtime import get_auth_mode, get_shared_experiment_access_key


def test_shared_auth_requires_explicit_mode_and_key(monkeypatch):
    monkeypatch.delenv("MANASUKE_AUTH_MODE", raising=False)
    assert get_auth_mode() == "individual"
    monkeypatch.setenv("MANASUKE_AUTH_MODE", "shared")
    assert get_auth_mode() == "shared"
    monkeypatch.delenv("MANASUKE_EXPERIMENT_ACCESS_KEY", raising=False)
    with pytest.raises(RuntimeError):
        get_shared_experiment_access_key()
    monkeypatch.setenv("MANASUKE_EXPERIMENT_ACCESS_KEY", "participant")
    assert get_shared_experiment_access_key() == "participant"
    monkeypatch.setenv("MANASUKE_AUTH_MODE", "unsupported")
    with pytest.raises(RuntimeError):
        get_auth_mode()


def test_register_initial_empty_participant_and_prevent_duplicate(tmp_path):
    db_path = tmp_path / "manasuke.db"
    with pytest.raises(FileNotFoundError):
        create_participant("student001", db_path)
    assert not db_path.exists()

    run_migrations(db_path)
    assert create_participant(" student001 ", db_path) == "student001"

    with sqlite3.connect(db_path) as conn:
        record = conn.execute(
            "SELECT id, planning_data_version, created_at FROM participants"
        ).fetchone()
        assert record[0] == "student001"
        assert record[1] == 0
        assert record[2].endswith("Z")
        assert conn.execute("SELECT COUNT(*) FROM study_targets").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 0

    with pytest.raises(sqlite3.IntegrityError):
        create_empty_participant("student001", db_path)

    with pytest.raises(ValueError):
        create_empty_participant("    ", db_path)


def test_explicit_shared_key_auth_checks_participant_exists(monkeypatch, tmp_path):
    db_path = tmp_path / "app.db"
    run_migrations(db_path)
    create_participant("student001", db_path)

    monkeypatch.setenv("MANASUKE_AUTH_MODE", "shared")
    monkeypatch.setenv("MANASUKE_EXPERIMENT_ACCESS_KEY", "participant")
    monkeypatch.delenv("MANASUKE_INVITE_KEYS_JSON", raising=False)

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    sys.modules.pop("ui.session", None)
    try:
        from ui import session
        monkeypatch.setattr(session, "st", fake_st)
        monkeypatch.setattr(session, "get_db_path", lambda: db_path)

        assert not session.authenticate(access_key="wrong", participant_id="student001")
        assert not session.is_authenticated()
        assert not session.authenticate(access_key="participant", participant_id="missing")
        assert not session.is_authenticated()
        assert session.authenticate(access_key="participant", participant_id="student001")
        assert session.current_participant_id() == "student001"
    finally:
        sys.modules.pop("ui.session", None)


def test_create_participant_supports_default_path_and_legacy_name(monkeypatch, tmp_path):
    db_path = tmp_path / "manasuke.db"
    run_migrations(db_path)
    monkeypatch.setenv("MANASUKE_DB_PATH", str(db_path))

    # Old single-argument command/API remains valid.
    assert create_participant("student002") == "student002"
    # Two-argument API also works under the legacy function name.
    assert create_empty_participant("student003", db_path) == "student003"

    with sqlite3.connect(db_path) as conn:
        participants = conn.execute(
            "SELECT id, planning_data_version FROM participants ORDER BY id"
        ).fetchall()
        assert participants == [("student002", 0), ("student003", 0)]