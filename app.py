from __future__ import annotations

import streamlit as st

from ui.session import (
    authenticate,
    current_participant_id,
    is_authenticated,
    logout,
)
from ui.navigation import render_navigation


st.set_page_config(
    page_title="Manasuke",
    page_icon="📚",
    layout="wide",
)

if is_authenticated():
    render_navigation("ホーム")

st.title("Manasuke")

if is_authenticated():
    participant_id = current_participant_id()
    st.success("ログインしています。")
    st.write(f"参加者ID: `{participant_id}`")

else:
    st.subheader(
        "実験参加"
    )

    with st.form(
        "participant-login",
        clear_on_submit=False,
    ):
        access_key = st.text_input(
            "実験アクセスキー",
            type="password",
        )

        participant_id = st.text_input(
            "参加者ID",
        )

        submitted = st.form_submit_button(
            "ログイン",
            type="primary",
        )

    if submitted:
        try:
            success = authenticate(
                access_key=access_key,
                participant_id=participant_id,
            )
        except RuntimeError:
            # Do not expose credential configuration to participants.
            st.error("ログイン設定を確認できません。運営者に連絡してください。")
        else:
            if success:
                st.rerun()
            else:
                st.error("アクセスキーまたは参加者IDを確認してください。")