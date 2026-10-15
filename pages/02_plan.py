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

from domain.enums import (
    AttemptStage,
    GoalMode,
)

from services.plan_version_status_service import (
    PlanVersionStatusService,
)

logger = logging.getLogger(
    __name__
)


def request_plan_generation(operation_type):
    try:
        with st.spinner(
            "学習計画を作っています..."
        ):
            result = generation_service.generate(
                participant_id=participant_id,
                operation_type=operation_type,
                now=now_jst(),
            )

        if result.succeeded:
            st.rerun()

        elif result.awaiting_goal_decision:
            # 判断待ち画面を表示するため再実行
            st.rerun()

        else:
            st.error(
                "計画を完成できませんでした。"
                f" 処理段階: {result.stage.value}"
            )

    except Exception as exc:
        logger.exception(
            "Plan generation failed"
        )
        st.error(
            user_message_for_exception(exc)
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

# =========================================
# 進行中Attemptの復元
# =========================================

active_attempt = generation_service.get_active_attempt(
    participant_id=participant_id,
)

if active_attempt is not None:

    if (
        active_attempt.stage
        == AttemptStage.AWAITING_GOAL_DECISION
    ):
        st.warning(
            "すべての目標を期限内に達成することが"
            "難しいため、目標ごとに保証レベルを"
            "選択してください。"
        )

        st.info(
            f"計画生成 Attempt ID: {active_attempt.id}"
        )

        goals = generation_service.list_goals_for_decision(
            participant_id=participant_id,
        )

        if not goals:
            st.error(
                "選択対象のGoalが見つかりません。"
                "設定と生成状態を確認してください。"
            )

        else:
            with st.form(
                key=f"goal_decision_{active_attempt.id}"
            ):
                goal_modes = {}

                for goal in goals:
                    selected = st.radio(
                        f"{goal.title} (ID: {goal.id})",
                        options=[
                            "STRICT",
                            "BEST_EFFORT",
                        ],
                        horizontal=True,
                        key=(
                            f"goal_mode_"
                            f"{active_attempt.id}_"
                            f"{goal.id}"
                        ),
                        help=(
                            "STRICT: 期限内達成を必須条件とする。"
                            "BEST_EFFORT: 期限内達成を目指すが"
                            "保証しない。"
                        ),
                    )

                    goal_modes[goal.id] = GoalMode(
                        selected
                    )

                submitted = st.form_submit_button(
                    "この条件で計画生成を続行",
                    type="primary",
                )

            if submitted:
                try:
                    with st.spinner(
                        "選択内容を検証し、"
                        "計画生成を再開しています..."
                    ):
                        result = (
                            generation_service
                            .continue_after_goal_decision(
                                participant_id=participant_id,
                                attempt_id=active_attempt.id,
                                goal_modes=goal_modes,
                                now=now_jst(),
                            )
                        )

                    if result.succeeded:
                        st.success(
                            "学習計画を作成しました。"
                        )
                        st.rerun()

                    else:
                        st.error(
                            "計画を完成できませんでした。"
                        )

                except Exception as exc:
                    logger.exception(
                        "Plan generation resume failed"
                    )
                    st.error(
                        user_message_for_exception(exc)
                    )

                    # ローカル開発中だけ表示
                    with st.expander(
                        "開発用エラー詳細"
                    ):
                        st.code(
                            traceback.format_exc(),
                            language="text",
                        )

    else:
        st.info(
            "現在、計画生成処理が進行中です。"
            f" 処理段階: {active_attempt.stage.value}"
        )

st.subheader(
    "計画を更新"
)

col1, col2 = st.columns(2)

with col1:
    if st.button(
        "今すぐ再計画",
        type="primary",
        disabled=(active_attempt is not None),
    ):
        request_plan_generation(
            PlanOperationType.INITIAL
        )
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
        type="primary",
        disabled=(active_attempt is not None),
    ):
        request_plan_generation(
            PlanOperationType.REPLAN_TOMORROW
        )
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


try:
    version_status = PlanVersionStatusService(
        db_path
    ).get_status(
        participant_id=participant_id,
        now=now_jst(),
    )

except Exception:
    logger.exception(
        "Failed to resolve plan version status"
    )
    st.error(
        "学習計画の状態を確認できませんでした。"
    )
    st.stop()

plan = version_status.active_plan

if plan is None:
    if version_status.next_plan is not None:
        st.info(
            "これから適用される学習計画があります。"
        )

        if version_status.next_has_changes:
            st.warning(
                "適用予定の計画は古い設定で"
                "作成されています。"
                "再計画をおすすめします。"
            )
    else:
        st.info(
            "現在利用できる学習計画はありません。"
        )

    if st.button(
        "最初の学習計画を作る",
        type="primary",
        disabled=(version_status.next_plan is not None),
    ):
        request_plan_generation(
            PlanOperationType.INITIAL
        )
        try:
            with st.spinner(
                "学習計画を作っています..."
            ):
                result = generation_service.generate(
                    participant_id=participant_id,
                    operation_type=PlanOperationType.INITIAL,
                    now=now_jst(),
                )

                if result.succeeded:
                    st.success("学習計画を作成しました。")
                    st.rerun()

                elif result.awaiting_goal_decision:
                    st.warning(
                        "目標をすべて期限内に達成できないため、"
                        "STRICT / BEST_EFFORTの選択が必要です。"
                    )
                    st.info(
                        f"計画生成Attempt ID: {result.attempt_id}"
                    )

                else:
                    st.error(
                        "計画を完成できませんでした。"
                        f"現在の処理段階: {result.stage.value}"
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


if (
    plan.source_planning_data_version
    != version_status.current_version
):
    st.warning(
        "学習設定が変更されています。\n\n"
        "この計画は以前の設定をもとに"
        "作成されています。"
        "現在の条件で有効かどうかは"
        "まだ検証されていません。"
        "再計画をおすすめします。"
    )

else:
    st.caption(
        "計画作成時の設定バージョンと"
        "現在の設定バージョンは一致しています。"
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