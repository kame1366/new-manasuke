from __future__ import annotations

import streamlit as st

from ui.session import (
    authenticate,
    current_participant_id,
    is_authenticated,
    logout,
)


st.markdown("""
<style>
.st-key-manasuke_nav button {
    width: 100%;
    min-height: 90px;
    border-radius: 16px;
    border: 1px solid #dbeafe;
    background: #f8fbff;
    color: #1e3a5f;
    font-size: 16px;
    font-weight: 600;
    transition: all 0.2s ease;
}

/* マウスを乗せたとき */
.st-key-manasuke_nav button:hover {
    background: #eff6ff;
    border-color: #3b82f6;
    color: #1d4ed8;
    transform: translateY(-3px);
    box-shadow: 0 6px 18px rgba(59, 130, 246, 0.12);
}

/* キーボード操作時 */
.st-key-manasuke_nav button:focus-visible {
    outline: 3px solid #93c5fd;
    outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
    .st-key-manasuke_nav button {
        transition: none;
    }
    .st-key-manasuke_nav button:hover {
        transform: none;
    }
}
</style>
""", unsafe_allow_html=True)


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
    participant_id = current_participant_id()
    st.success("ログインしています。")
    st.write(f"参加者ID: `{participant_id}`")

    with st.container(key="manasuke_nav"):
        col1, col2, col3 = st.columns(3, gap="medium")

        with col1:
            if st.button(
                "学習設定",
                icon=":material/menu_book:",
                width="stretch"
            ):
                st.switch_page("pages/01_learning_settings.py")

        with col2:
            if st.button(
                "学習計画",
                icon=":material/calendar_month:",
                width="stretch"
            ):
                st.switch_page("pages/02_plan.py")

        with col3:
            if st.button(
                "学習記録",
                icon=":material/edit_note:",
                width="stretch"
            ):
                st.switch_page("pages/03_today_and_results.py")
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