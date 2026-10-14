from __future__ import annotations

import streamlit as st

from ui.session import (
    authenticate,
    current_participant_id,
    is_authenticated,
    logout,
)


st.set_page_config(
    page_title="Manasuke",
    page_icon="📚",
    layout="wide",
)


st.title("Manasuke")

st.caption(
    "学習計画の作成と修正を支援します。"
)


if is_authenticated():
    participant_id = (
        current_participant_id()
    )

    st.success(
        "ログインしています。"
    )

    st.write(
        f"参加者ID: `{participant_id}`"
    )

    st.subheader(
        "メニュー"
    )

    col1, col2, col3 = (
        st.columns(3)
    )

    with col1:
        st.page_link(
            "pages/01_learning_settings.py",
            label="学習設定",
            icon="⚙️",
        )

    with col2:
        st.page_link(
            "pages/02_plan.py",
            label="学習計画",
            icon="📅",
        )

    with col3:
        st.page_link(
            "pages/03_today_and_results.py",
            label="今日の学習・実績",
            icon="✅",
        )

    st.divider()

    if st.button(
        "ログアウト",
        type="secondary",
    ):
        logout()
        st.rerun()

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
        if authenticate(
            access_key=access_key,
            participant_id=(
                participant_id
            ),
        ):
            st.rerun()

        else:
            st.error(
                "アクセスキーまたは参加者IDを"
                "確認してください。"
            )