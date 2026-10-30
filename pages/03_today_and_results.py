from __future__ import annotations

import streamlit as st

from domain.enums import (
    StudyResultStatus,
    StudyTargetKind,
)
from domain.time_rules import (
    now_jst,
    to_jst,
)
from repositories.plan_repository import (
    PlanRepository,
)
from repositories.study_result_repository import (
    StudyResultRepository,
)
from repositories.study_target_repository import (
    StudyTargetRepository,
)
from services.study_result_service import (
    StudyResultService,
)
from ui.formatters import (
    format_plan_item_work,
    format_time,
)
from ui.messages import (
    user_message_for_exception,
)
from ui.runtime import get_db_path
from ui.session import require_participant


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
    page_title="今日の学習・実績 | Manasuke",
    page_icon="✅",
    layout="wide",
)


participant_id = require_participant()
db_path = get_db_path()
now = now_jst()
today = now.date()


plan_repository = PlanRepository(
    db_path
)

study_target_repository = (
    StudyTargetRepository(
        db_path
    )
)

result_repository = (
    StudyResultRepository(
        db_path
    )
)

result_service = (
    StudyResultService(
        db_path=db_path
    )
)


STATUS_LABELS = {
    "完了":
        StudyResultStatus.COMPLETED,

    "途中まで":
        StudyResultStatus.PARTIAL,

    "やらなかった":
        StudyResultStatus.NOT_DONE,
}


def resolve_current_plan():
    plans = (
        plan_repository
        .list_by_participant(
            participant_id
        )
    )

    candidates = [
        plan
        for plan in plans
        if plan.effective_from <= now
    ]

    if not candidates:
        return None

    selected = max(
        candidates,
        key=lambda plan: (
            plan.version_no
        ),
    )

    if now >= selected.horizon_end:
        return None

    return selected


def get_existing_result(
    plan_item_id: int,
):
    return (
        result_repository
        .get_by_plan_item(
            participant_id=(
                participant_id
            ),
            plan_item_id=(
                plan_item_id
            ),
        )
    )


def show_material_form(
    *,
    item,
    target,
    existing,
) -> None:
    form_key = (
        f"material-result-{item.id}"
    )

    with st.form(
        form_key
    ):
        default_index = 0

        if existing is not None:
            if (
                existing.status
                == StudyResultStatus
                .COMPLETED
            ):
                default_index = 0

            elif (
                existing.status
                == StudyResultStatus
                .PARTIAL
            ):
                default_index = 1

            else:
                default_index = 2

        label = st.radio(
            "結果",
            options=tuple(
                STATUS_LABELS.keys()
            ),
            index=default_index,
            horizontal=True,
            key=(
                f"material-status-"
                f"{item.id}"
            ),
        )

        status = (
            STATUS_LABELS[
                label
            ]
        )

        actual_end_position = None

        if (
            status
            == StudyResultStatus.PARTIAL
        ):
            if (
                item.range_start is None
                or item.range_end is None
            ):
                st.error(
                    "この予定には教材範囲が"
                    "設定されていません。"
                )

            else:
                max_partial = (
                    item.range_end - 1
                )

                default_value = (
                    item.range_start
                )

                if (
                    existing is not None
                    and existing
                    .actual_end_position
                    is not None
                ):
                    default_value = (
                        existing
                        .actual_end_position
                    )

                actual_end_position = (
                    st.number_input(
                        "最後に完了した位置",
                        min_value=(
                            item.range_start
                        ),
                        max_value=(
                            max_partial
                        ),
                        value=(
                            min(
                                max(
                                    default_value,
                                    item.range_start,
                                ),
                                max_partial,
                            )
                        ),
                        step=1,
                        key=(
                            "material-partial-"
                            f"{item.id}"
                        ),
                    )
                )

        elif (
            status
            == StudyResultStatus.COMPLETED
        ):
            default_completed = (
                item.range_end
                if (
                    item.range_end
                    is not None
                )
                else 1
            )

            if (
                existing is not None
                and existing
                .actual_end_position
                is not None
            ):
                default_completed = (
                    existing
                    .actual_end_position
                )

            advanced = st.checkbox(
                "予定より先まで進んだ",
                value=(
                    existing is not None
                    and item.range_end
                    is not None
                    and existing
                    .actual_end_position
                    is not None
                    and existing
                    .actual_end_position
                    > item.range_end
                ),
                key=(
                    "material-advanced-"
                    f"{item.id}"
                ),
            )

            if advanced:
                actual_end_position = (
                    st.number_input(
                        "実際に完了した最後の位置",
                        min_value=(
                            item.range_end
                            if (
                                item.range_end
                                is not None
                            )
                            else 1
                        ),
                        value=(
                            default_completed
                        ),
                        step=1,
                        key=(
                            "material-completed-"
                            f"{item.id}"
                        ),
                    )
                )

        button_label = (
            "実績を修正"
            if existing is not None
            else "実績を保存"
        )

        submitted = (
            st.form_submit_button(
                button_label,
                type="primary",
            )
        )

    if not submitted:
        return

    try:
        if existing is None:
            result_service.record(
                participant_id=(
                    participant_id
                ),
                plan_item_id=(
                    item.id
                ),
                status=status,
                actual_end_position=(
                    int(
                        actual_end_position
                    )
                    if (
                        actual_end_position
                        is not None
                    )
                    else None
                ),
                now=now_jst(),
            )

            st.success(
                "実績を保存しました。"
            )

        else:
            result_service.correct(
                participant_id=(
                    participant_id
                ),
                plan_item_id=(
                    item.id
                ),
                status=status,
                actual_end_position=(
                    int(
                        actual_end_position
                    )
                    if (
                        actual_end_position
                        is not None
                    )
                    else None
                ),
                now=now_jst(),
            )

            st.success(
                "実績を修正しました。"
            )

        st.rerun()

    except Exception as exc:
        st.error(
            user_message_for_exception(
                exc
            )
        )


def show_theme_form(
    *,
    item,
    target,
    existing,
) -> None:
    form_key = (
        f"theme-result-{item.id}"
    )

    with st.form(
        form_key
    ):
        default_index = 0

        if existing is not None:
            if (
                existing.status
                == StudyResultStatus
                .COMPLETED
            ):
                default_index = 0

            elif (
                existing.status
                == StudyResultStatus
                .PARTIAL
            ):
                default_index = 1

            else:
                default_index = 2

        label = st.radio(
            "結果",
            options=tuple(
                STATUS_LABELS.keys()
            ),
            index=default_index,
            horizontal=True,
            key=(
                f"theme-status-{item.id}"
            ),
        )

        status = (
            STATUS_LABELS[
                label
            ]
        )

        actual_minutes_default = (
            item.planned_minutes
        )

        if (
            existing is not None
            and existing.actual_minutes
            is not None
        ):
            actual_minutes_default = (
                existing.actual_minutes
            )

        actual_minutes = (
            st.number_input(
                "実際に取り組んだ時間（分）",
                min_value=0,
                value=int(
                    actual_minutes_default
                ),
                step=5,
                key=(
                    "theme-minutes-"
                    f"{item.id}"
                ),
            )
        )

        feeling_options = (
            "",
            "短く感じた",
            "ちょうどよかった",
            "長く感じた",
        )

        feeling_index = 0

        if (
            existing is not None
            and existing.time_feeling
            in feeling_options
        ):
            feeling_index = (
                feeling_options.index(
                    existing.time_feeling
                )
            )

        time_feeling = (
            st.selectbox(
                "時間の感覚",
                options=(
                    feeling_options
                ),
                index=feeling_index,
                key=(
                    "theme-feeling-"
                    f"{item.id}"
                ),
            )
        )

        memo = st.text_area(
            "メモ（任意）",
            value=(
                existing.memo
                if (
                    existing is not None
                    and existing.memo
                    is not None
                )
                else ""
            ),
            key=(
                "theme-memo-"
                f"{item.id}"
            ),
        )

        button_label = (
            "実績を修正"
            if existing is not None
            else "実績を保存"
        )

        submitted = (
            st.form_submit_button(
                button_label,
                type="primary",
            )
        )

    if not submitted:
        return

    try:
        kwargs = {
            "participant_id":
                participant_id,

            "plan_item_id":
                item.id,

            "status":
                status,

            "actual_minutes":
                int(
                    actual_minutes
                ),

            "time_feeling":
                (
                    time_feeling
                    if time_feeling
                    else None
                ),

            "memo":
                (
                    memo.strip()
                    if memo.strip()
                    else None
                ),

            "now":
                now_jst(),
        }

        if existing is None:
            result_service.record(
                **kwargs
            )

            st.success(
                "実績を保存しました。"
            )

        else:
            result_service.correct(
                **kwargs
            )

            st.success(
                "実績を修正しました。"
            )

        st.rerun()

    except Exception as exc:
        st.error(
            user_message_for_exception(
                exc
            )
        )


st.title(
    "今日の学習・実績"
)

st.caption(
    today.strftime(
        "%Y年%m月%d日"
    )
)

with st.container(key="manasuke_nav"):
    col1, col2 = st.columns(2, gap="medium")

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
        


plan = resolve_current_plan()

if plan is None:
    st.info(
        "現在利用できる学習計画はありません。"
    )

    st.stop()


try:
    plan_items = (
        plan_repository.list_items(
            participant_id=(
                participant_id
            ),
            plan_id=(
                plan.id
            ),
        )
    )

    study_targets = (
        study_target_repository
        .list_by_participant(
            participant_id
        )
    )

except Exception:
    st.error(
        "今日の予定を読み込めませんでした。"
    )

    st.stop()


targets_by_id = {
    target.id: target
    for target in study_targets
}


today_items = [
    item
    for item in plan_items
    if (
        to_jst(
            item.start_at
        ).date()
        == today
    )
]


today_items.sort(
    key=lambda item: (
        item.start_at,
        item.id,
    )
)


if not today_items:
    st.info(
        "今日の予定はありません。"
    )

    st.stop()


for item in today_items:
    target = targets_by_id.get(
        item.study_target_id
    )

    if target is None:
        continue

    with st.container(
        border=True
    ):
        st.markdown(
            f"### "
            f"{format_time(item.start_at)}"
            "〜"
            f"{format_time(item.end_at)}"
        )

        st.write(
            format_plan_item_work(
                item=item,
                target=target,
            )
        )

        st.caption(
            f"予定時間: "
            f"{item.planned_minutes}分"
        )

        if item.is_cancelled:
            st.warning(
                "この予定はキャンセルされています。"
            )

            continue

        existing = (
            get_existing_result(
                item.id
            )
        )

        if existing is None:
            st.info(
                "実績: 未入力"
            )

        else:
            st.success(
                "実績: "
                f"{existing.status.value}"
            )

        if (
            target.kind
            == StudyTargetKind.MATERIAL
        ):
            show_material_form(
                item=item,
                target=target,
                existing=existing,
            )

        elif (
            target.kind
            == StudyTargetKind.THEME
        ):
            show_theme_form(
                item=item,
                target=target,
                existing=existing,
            )