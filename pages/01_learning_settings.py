from __future__ import annotations

from datetime import time

import streamlit as st

from domain.enums import StudyTargetKind
from repositories.availability_repository import (
    AvailabilityRepository,
)
from repositories.goal_repository import GoalRepository
from repositories.learning_policy_repository import (
    LearningPolicyRepository,
)
from repositories.study_target_repository import (
    StudyTargetRepository,
)
from ui.formatters import format_datetime
from ui.runtime import get_db_path
from ui.session import require_participant


st.set_page_config(
    page_title="学習設定 | Manasuke",
    page_icon="⚙️",
    layout="wide",
)


participant_id = require_participant()
db_path = get_db_path()


study_target_repository = StudyTargetRepository(
    db_path
)

goal_repository = GoalRepository(
    db_path
)

learning_policy_repository = (
    LearningPolicyRepository(
        db_path
    )
)

availability_repository = (
    AvailabilityRepository(
        db_path
    )
)


def minute_to_time(
    minute_of_day: int,
) -> time:
    hour = minute_of_day // 60
    minute = minute_of_day % 60

    if hour == 24:
        return time(
            23,
            59,
        )

    return time(
        hour=hour,
        minute=minute,
    )


def format_minute_of_day(
    minute_of_day: int,
) -> str:
    if minute_of_day == 1440:
        return "24:00"

    hour = minute_of_day // 60
    minute = minute_of_day % 60

    return (
        f"{hour:02d}:"
        f"{minute:02d}"
    )


WEEKDAY_LABELS = (
    "月",
    "火",
    "水",
    "木",
    "金",
    "土",
    "日",
)


st.title(
    "学習設定"
)

st.caption(
    "学習対象・目標・学習方針・"
    "利用可能時間を確認できます。"
)


try:
    study_targets = (
        study_target_repository
        .list_by_participant(
            participant_id
        )
    )

    goals = (
        goal_repository
        .list_by_participant(
            participant_id
        )
    )

    policies = (
        learning_policy_repository
        .list_by_participant(
            participant_id
        )
    )

    available_times = (
        availability_repository
        .list_available_times(
            participant_id
        )
    )

    busy_events = (
        availability_repository
        .list_busy_events(
            participant_id
        )
    )

    extra_available_times = (
        availability_repository
        .list_extra_available_times(
            participant_id
        )
    )

except Exception:
    st.error(
        "学習設定を読み込めませんでした。"
    )

    st.stop()


targets_by_id = {
    target.id: target
    for target in study_targets
}

policies_by_target = {
    policy.study_target_id: policy
    for policy in policies
}


st.subheader(
    "学習対象"
)

if not study_targets:
    st.info(
        "学習対象が登録されていません。"
    )

for target in study_targets:
    with st.container(
        border=True
    ):
        st.markdown(
            f"### {target.title}"
        )

        if (
            target.kind
            == StudyTargetKind.MATERIAL
        ):
            col1, col2, col3 = (
                st.columns(3)
            )

            with col1:
                st.metric(
                    "種類",
                    "教材",
                )

            with col2:
                st.metric(
                    "現在位置",
                    (
                        target.next_position
                        if (
                            target.next_position
                            is not None
                        )
                        else "-"
                    ),
                )

            with col3:
                if (
                    target
                    .estimated_minutes_per_unit
                    is not None
                ):
                    st.metric(
                        "1単位の目安",
                        (
                            f"{target.estimated_minutes_per_unit:g}"
                            "分"
                        ),
                    )

            if target.ranges:
                st.write(
                    "学習範囲"
                )

                for target_range in sorted(
                    target.ranges,
                    key=lambda value: (
                        value.sequence_no
                    ),
                ):
                    st.write(
                        "・"
                        f"{target_range.start_position}"
                        "〜"
                        f"{target_range.end_position}"
                    )

        else:
            st.metric(
                "種類",
                "テーマ",
            )

        if target.note:
            st.caption(
                target.note
            )

        policy = policies_by_target.get(
            target.id
        )

        if policy is not None:
            st.divider()

            st.markdown(
                "**学習方針**"
            )

            st.write(
                policy.purpose
            )

            col1, col2, col3 = (
                st.columns(3)
            )

            with col1:
                st.metric(
                    "通常",
                    (
                        f"週"
                        f"{policy.normal_sessions_per_week}"
                        "日"
                    ),
                )

            with col2:
                st.metric(
                    "通常時間",
                    (
                        f"{policy.normal_minutes}"
                        "分"
                    ),
                )

            with col3:
                st.metric(
                    "最低ライン",
                    (
                        f"週"
                        f"{policy.minimum_sessions_per_week}"
                        "日 / "
                        f"{policy.minimum_minutes}"
                        "分"
                    ),
                )


st.divider()

st.subheader(
    "目標"
)

if not goals:
    st.info(
        "目標が登録されていません。"
    )

for goal in goals:
    target = targets_by_id.get(
        goal.study_target_id
    )

    with st.container(
        border=True
    ):
        st.markdown(
            f"### {goal.title}"
        )

        col1, col2, col3 = (
            st.columns(3)
        )

        with col1:
            st.write(
                "**学習対象**"
            )

            st.write(
                (
                    target.title
                    if target is not None
                    else "不明"
                )
            )

        with col2:
            st.write(
                "**期限**"
            )

            st.write(
                format_datetime(
                    goal.deadline_at
                )
            )

        with col3:
            st.write(
                "**重要度**"
            )

            st.write(
                goal.importance.value
            )

        if goal.target_minutes is not None:
            st.write(
                "目標時間: "
                f"{goal.target_minutes}分"
            )

        if goal.ranges:
            st.write(
                "対象範囲:"
            )

            for goal_range in goal.ranges:
                st.write(
                    "・"
                    f"{goal_range.start_position}"
                    "〜"
                    f"{goal_range.end_position}"
                )

        if goal.note:
            st.caption(
                goal.note
            )


st.divider()

st.subheader(
    "週の利用可能時間"
)

if not available_times:
    st.info(
        "利用可能時間が登録されていません。"
    )

else:
    rows = []

    for item in sorted(
        available_times,
        key=lambda value: (
            value.weekday,
            value.start_minute_of_day,
        ),
    ):
        rows.append(
            {
                "曜日": (
                    WEEKDAY_LABELS[
                        item.weekday
                    ]
                ),
                "開始": (
                    format_minute_of_day(
                        item.start_minute_of_day
                    )
                ),
                "終了": (
                    format_minute_of_day(
                        item.end_minute_of_day
                    )
                ),
            }
        )

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
    )


st.divider()

st.subheader(
    "予定あり"
)

if not busy_events:
    st.info(
        "予定あり時間はありません。"
    )

for event in busy_events:
    with st.container(
        border=True
    ):
        st.write(
            f"{format_datetime(event.start_at)}"
            " 〜 "
            f"{format_datetime(event.end_at)}"
        )

        if event.note:
            st.caption(
                event.note
            )


st.divider()

st.subheader(
    "追加で使える時間"
)

if not extra_available_times:
    st.info(
        "追加時間はありません。"
    )

for extra in extra_available_times:
    with st.container(
        border=True
    ):
        st.write(
            f"{format_datetime(extra.start_at)}"
            " 〜 "
            f"{format_datetime(extra.end_at)}"
        )

        if extra.note:
            st.caption(
                extra.note
            )


st.divider()

st.page_link(
    "app.py",
    label="ホームへ戻る",
    icon="🏠",
)