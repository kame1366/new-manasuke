import streamlit as st
from streamlit_navigation_bar import st_navbar

PAGE_TARGETS = {
    "ホーム": "app.py",
    "学習設定": "pages/01_learning_settings.py",
    "学習計画": "pages/02_plan.py",
    "学習記録": "pages/03_today_and_results.py",
}


def render_navigation(current_page: str) -> None:
    selected_page = st_navbar(
        list(PAGE_TARGETS),
        selected=current_page,
        styles={
            "div": {
                "max-width": "64rem",
            },
        },
        adjust=False,
    )

    target = PAGE_TARGETS.get(selected_page)
    if target is not None and selected_page != current_page:
        st.switch_page(target)