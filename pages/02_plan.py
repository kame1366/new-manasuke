from __future__ import annotations

from datetime import date

import streamlit as st

from domain.enums import (
    PlanItemOrigin,
    PlanOperationType,
)
from domain.plan_state import (
    PlanState,
)
from domain.time_rules import now_jst
from repositories.participant_repository import (
    ParticipantRepository,
)
from repositories.plan_repository import (
    PlanRepository,
)
from repositories.study_target_repository import (
    StudyTargetRepository,
)
from services.plan_generation_application_service import (
    PlanGenerationApplicationService,
)
from ui.formatters import (
    format_datetime,
    format_plan_item_work,
    format_time,
)
from ui.messages import (
    user_message_for_exception,
)
from ui.runtime import get_db_path
from ui.session import require_participant

import traceback
import logging

logger = logging.getLogger(
    __name__
)


st.set_page_config(
    page_title="学習計画 | Manasuke",
    page_icon="📅",
    layout="wide",
)


participant_id = require_participant()
db_path = get_db_path()
now = now_jst()


plan_repository = PlanRepository(
    db_path
)

participant_repository = (
    ParticipantRepository(
        db_path
    )
)

study_target_repository = (
    StudyTargetRepository(
        db_path
    )
)

generation_service = (
    PlanGenerationApplicationService(
        db_path=db_path
    )
)


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


def derive_simple_plan_state(
    plan,
) -> PlanState:
    current_version = (
        participant_repository
        .get_planning_data_version(
            participant_id
        )
    )

    if current_version is None:
        return PlanState.EXPIRED

    if (
        plan.source_planning_data_version
        == current_version
    ):
        return PlanState.CURRENT

    # UI側ではversion mismatchのみから
    # INVALIDを推測しない。
    #
    # 完全なOUTDATED_VALID / INVALID判定を
    # 既存PlanResolverで実装済みなら、
    # この関数をそのresolver呼び出しへ置換する。
    return PlanState.OUTDATED_VALID


def show_plan_state(
    state: PlanState,
) -> None:
    if state == PlanState.CURRENT:
        st.success(
            "この計画は最新です。"
        )

    elif (
        state
        == PlanState.OUTDATED_VALID
    ):
        st.warning(
            "学習設定または進捗が変更されています。"
            "この計画は以前の情報から作られています。"
            "再計画をおすすめします。"
        )

    elif (
        state
        == PlanState.OUTDATED_INVALID
    ):
        st.error(
            "現在の条件では、この計画を"
            "そのまま実行できません。"
            "再計画または予定の修正が必要です。"
        )

    elif (
        state
        == PlanState.FUTURE_APPLICABLE
    ):
        st.info(
            "この計画はこれから有効になります。"
        )

    elif state == PlanState.SHADOWED:
        st.info(
            "この計画は新しい計画に"
            "置き換えられています。"
        )

    elif state == PlanState.EXPIRED:
        st.info(
            "この計画の有効期間は終了しています。"
        )


st.title(
    "学習計画"
)

st.caption(
    "7日間の学習計画を確認・更新できます。"
)


st.subheader(
    "計画を更新"
)

col1, col2 = st.columns(2)

with col1:
    if st.button(
        "今から再計画",
        type="primary",
        use_container_width=True,
    ):
        try:
            with st.spinner(
                "学習計画を作っています..."
            ):
                generation_service.generate(
                    participant_id=(
                        participant_id
                    ),
                    operation_type=(
                        PlanOperationType
                        .REPLAN_NOW
                    ),
                    now=now_jst(),
                )

            st.success(
                "学習計画を更新しました。"
            )

            st.rerun()

        except Exception as exc:
            st.error(
                user_message_for_exception(
                    exc
                )
            )


with col2:
    if st.button(
        "明日から再計画",
        use_container_width=True,
    ):
        try:
            with st.spinner(
                "明日からの学習計画を"
                "作っています..."
            ):
                generation_service.generate(
                    participant_id=(
                        participant_id
                    ),
                    operation_type=(
                        PlanOperationType
                        .REPLAN_TOMORROW
                    ),
                    now=now_jst(),
                )

            st.success(
                "明日からの計画を作成しました。"
            )

            st.rerun()

        except Exception as exc:
            st.error(
                user_message_for_exception(
                    exc
                )
            )


st.divider()


plan = resolve_current_plan()

if plan is None:
    st.info(
        "現在利用できる学習計画はありません。"
    )

    if st.button(
        "最初の学習計画を作る",
        type="primary",
    ):
        try:
            with st.spinner(
                "学習計画を作っています..."
            ):
                generation_service.generate(
                    participant_id=(
                        participant_id
                    ),
                    operation_type=(
                        PlanOperationType
                        .INITIAL
                    ),
                    now=now_jst(),
                )

            st.success(
                "学習計画を作成しました。"
            )

            st.rerun()


        #except Exception as exc:
        #    st.error(
        #        user_message_for_exception(
        #            exc
        #        )
        #    )

        except Exception as exc:
            logger.exception(
                "Plan generation failed"
            )

            st.error(
                user_message_for_exception(
                    exc
                )
            )

            st.error(
                "DEBUG: "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

            with st.expander(
                "開発用エラー詳細",
                expanded=True,
            ):
                st.code(
                    traceback.format_exc(),
                    language="text",
                )

    st.stop()


state = derive_simple_plan_state(
    plan
)

show_plan_state(
    state
)


st.write(
    "Plan version: "
    f"**{plan.version_no}**"
)

st.write(
    "有効期間: "
    f"{format_datetime(plan.effective_from)}"
    " 〜 "
    f"{format_datetime(plan.horizon_end)}"
)


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
        "計画を読み込めませんでした。"
    )

    st.stop()


targets_by_id = {
    target.id: target
    for target in study_targets
}


items_by_date: dict[
    date,
    list,
] = {}

for item in plan_items:
    local_date = (
        item.start_at
        .astimezone(
            now.tzinfo
        )
        .date()
    )

    items_by_date.setdefault(
        local_date,
        [],
    ).append(
        item
    )


st.divider()

st.subheader(
    "7日間の予定"
)


for study_date in sorted(
    items_by_date
):
    st.markdown(
        "### "
        f"{study_date.strftime('%m/%d')}"
    )

    day_items = sorted(
        items_by_date[
            study_date
        ],
        key=lambda item: (
            item.start_at,
            item.id,
        ),
    )

    for item in day_items:
        target = targets_by_id.get(
            item.study_target_id
        )

        if target is None:
            continue

        with st.container(
            border=True
        ):
            col_time, col_work, col_state = (
                st.columns(
                    [
                        1,
                        3,
                        1,
                    ]
                )
            )

            with col_time:
                st.write(
                    f"**{format_time(item.start_at)}**"
                )

                st.caption(
                    "〜 "
                    f"{format_time(item.end_at)}"
                )

            with col_work:
                st.write(
                    format_plan_item_work(
                        item=item,
                        target=target,
                    )
                )

                st.caption(
                    f"{item.planned_minutes}分"
                )

            with col_state:
                if item.is_cancelled:
                    st.warning(
                        "キャンセル"
                    )

                elif (
                    item.origin
                    == PlanItemOrigin
                    .USER_MODIFIED
                ):
                    st.info(
                        "変更済み"
                    )

                else:
                    st.caption(
                        "自動生成"
                    )


if not plan_items:
    st.info(
        "この計画には予定がありません。"
    )


st.divider()

st.page_link(
    "pages/03_today_and_results.py",
    label="今日の学習・実績へ",
    icon="✅",
)

st.page_link(
    "app.py",
    label="ホームへ戻る",
    icon="🏠",
)