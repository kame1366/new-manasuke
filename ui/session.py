from __future__ import annotations

import hmac

import streamlit as st

from repositories.participant_repository import (
    ParticipantRepository,
)
from ui.runtime import (
    get_db_path,
    get_participant_invite_keys,
)


SESSION_AUTHENTICATED = (
    "manasuke_authenticated"
)

SESSION_PARTICIPANT_ID = (
    "manasuke_participant_id"
)


def is_authenticated() -> bool:
    return bool(
        st.session_state.get(
            SESSION_AUTHENTICATED,
            False,
        )
    )


def current_participant_id() -> str | None:
    value = st.session_state.get(
        SESSION_PARTICIPANT_ID
    )

    if not isinstance(
        value,
        str,
    ):
        return None

    value = value.strip()

    return value or None


def authenticate(
    *,
    access_key: str,
    participant_id: str,
) -> bool:
    normalized_participant_id = participant_id.strip()
    if not normalized_participant_id:
        return False

    # Authorization is bound to the selected participant ID.
    # Never fall back to a shared project-wide key.
    expected = get_participant_invite_keys().get(normalized_participant_id)
    if expected is None or not hmac.compare_digest(access_key, expected):
        return False

    repository = (
        ParticipantRepository(
            get_db_path()
        )
    )

    if not repository.exists(
        normalized_participant_id
    ):
        return False

    st.session_state[
        SESSION_AUTHENTICATED
    ] = True

    st.session_state[
        SESSION_PARTICIPANT_ID
    ] = normalized_participant_id

    return True


def logout() -> None:
    st.session_state.pop(
        SESSION_AUTHENTICATED,
        None,
    )

    st.session_state.pop(
        SESSION_PARTICIPANT_ID,
        None,
    )


def require_participant() -> str:
    if not is_authenticated():
        st.error(
            "このページを利用するには、"
            "最初に参加者IDでログインしてください。"
        )

        st.page_link(
            "app.py",
            label="ログイン画面へ",
        )

        st.stop()

    participant_id = (
        current_participant_id()
    )

    if participant_id is None:
        logout()

        st.error(
            "参加者情報を確認できませんでした。"
        )

        st.stop()

    repository = (
        ParticipantRepository(
            get_db_path()
        )
    )

    if not repository.exists(
        participant_id
    ):
        logout()

        st.error(
            "この参加者IDは現在利用できません。"
        )

        st.stop()

    return participant_id