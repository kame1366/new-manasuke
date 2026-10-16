"""Release-gate regression tests for participant-scoped invite keys."""
import json
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest

from domain.time_rules import JST
from repositories.participant_repository import ParticipantRepository
from scripts.migrate import run_migrations
from ui.runtime import get_participant_invite_keys


def test_invite_keys_are_required(monkeypatch):
    monkeypatch.delenv("MANASUKE_INVITE_KEYS_JSON", raising=False)
    with pytest.raises(RuntimeError):
        get_participant_invite_keys()


def test_invite_keys_must_be_unique_and_long(monkeypatch):
    monkeypatch.setenv("MANASUKE_INVITE_KEYS_JSON", json.dumps({"a":"short"}))
    with pytest.raises(RuntimeError):
        get_participant_invite_keys()
    monkeypatch.setenv("MANASUKE_INVITE_KEYS_JSON", json.dumps({
        "a":"a-key-long-enough-111", "b":"a-key-long-enough-111"
    }))
    with pytest.raises(RuntimeError):
        get_participant_invite_keys()


def test_participant_specific_invite_prevents_cross_login(monkeypatch, tmp_path):
    db_path = tmp_path / "app.db"
    run_migrations(db_path)
    for participant in ("student-a", "student-b"):
        ParticipantRepository(db_path).create(
            participant,
            datetime(2026, 10, 15, 10, 0, tzinfo=JST),
        )

    a_key = "random-example-key-a-000001"
    b_key = "random-example-key-b-000002"
    monkeypatch.setenv("MANASUKE_INVITE_KEYS_JSON", json.dumps({
        "student-a": a_key,
        "student-b": b_key,
    }))

    # Isolate Streamlit's session state; the authentication function
    # otherwise only needs the private server-side repository.
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    sys.modules.pop("ui.session", None)
    try:
        from ui import session
        monkeypatch.setattr(session, "get_db_path", lambda: db_path)

        assert session.authenticate(access_key=a_key, participant_id="student-b") is False
        assert not session.is_authenticated()
        assert session.authenticate(access_key=b_key, participant_id="student-b") is True
        assert session.current_participant_id() == "student-b"
        session.logout()
        assert session.authenticate(access_key=a_key, participant_id="student-a") is True
        assert session.current_participant_id() == "student-a"
    finally:
        sys.modules.pop("ui.session", None)


def test_example_placeholder_key_cannot_be_used(monkeypatch):
    monkeypatch.setenv("MANASUKE_INVITE_KEYS_JSON", json.dumps({
        "student-a": "REPLACE_WITH_A_RANDOM_SECRET_001",
    }))
    with pytest.raises(RuntimeError):
        get_participant_invite_keys()
