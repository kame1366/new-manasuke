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
        selected=(
            current_page
            if current_page in PAGE_TARGETS
            else None
        ),
        styles={
            "nav": {
                "background-color": "#ffffff",
                "box-shadow": "0 1px 3px rgba(32, 48, 56, 0.12)",
            },
            "div": {
                "max-width": "64rem",
            },
            "span": {
                "color": "#34434a",
                "font-family": "'Noto Sans JP', 'Yu Gothic', sans-serif",
                "font-size": "1.0rem",
                "font-weight": "500",
                "padding": "0.5rem 5rem",
            },
            "active": {
                "background-color": "#e8f2f0",
            },
            "hover": {
                "background-color": "#f2f6f5",
            },
        },
        adjust=False,
    )
    st.html(
        """
        <style>
        header[data-testid="stHeader"] {
            display: none;
        }
        div[data-testid="stMainBlockContainer"] {
            padding-top: 0 !important;
        }
        </style>
        """
    )

    target = PAGE_TARGETS.get(selected_page)
    if target is not None and selected_page != current_page:
        st.switch_page(target)