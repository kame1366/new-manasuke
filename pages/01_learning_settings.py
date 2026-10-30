from __future__ import annotations

from datetime import datetime, time, timedelta

import streamlit as st

from domain.enums import StudyTargetKind
from repositories.availability_repository import (
    AvailabilityRepository,
    EventKind,
)
from repositories.goal_repository import GoalRepository
from repositories.learning_policy_repository import (
    LearningPolicyRepository,
)
from repositories.study_target_repository import (
    StudyTargetRepository,
)
from ui.formatters import (
    format_datetime,
    format_goal_deadline,
    format_importance,
    format_unit_type,
)
from ui.runtime import get_db_path
from ui.session import require_participant

import logging

from repositories.participant_repository import (
    ParticipantRepository,
)
from repositories.availability_repository import (
    AvailabilityConflictError,
)
from services.weekly_availability_service import (
    WeeklyAvailabilityService,
)

from domain.time_rules import JST, now_jst

from repositories.participant_repository import (
    ParticipantRepository,
)
from repositories.availability_repository import (
    AvailabilityConflictError,
    AvailabilityRecordNotFoundError,
)
from services.dated_availability_service import (
    DatedAvailabilityService,
)

import logging

from domain.enums import Importance, UnitType
from domain.errors import DomainValidationError
from domain.models import (
    StudyTarget,
    StudyTargetRange,
    LearningPolicy,
)
from services.study_target_settings_service import (
    StudyTargetSettingsService,
    StudyTargetSettingsConflictError,
)

from services.study_target_archive_service import (
    StudyTargetArchiveService,
    ArchiveConflictError,
    ArchiveOperationError,
)

from datetime import datetime, time, timedelta

from domain.enums import GoalType, Importance
from domain.time_rules import JST, now_jst

from repositories.participant_repository import (
    ParticipantRepository,
)

from services.goal_settings_service import (
    GoalSettingsService,
    GoalSettingsConflictError,
)

from domain.time_rules import now_jst

from services.plan_version_status_service import (
    PlanVersionStatusService,
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
    "利用可能時間を確認/編集できます。"
)
st.caption("登録した内容を確認できます。追加・編集が必要なときだけフォームを開いてください。")


# =====================================================
# Plan Version Notice
# =====================================================

try:
    plan_status = PlanVersionStatusService(
        db_path
    ).get_status(
        participant_id=participant_id,
        now=now_jst(),
    )

except Exception:
    logging.getLogger(__name__).exception(
        "Failed to load plan version status"
    )
    st.error(
        "学習計画の状態を確認できませんでした。"
    )

else:
    needs_review = False

    if plan_status.active_has_changes:
        needs_review = True

        st.warning(
            "学習設定が変更されています。\n\n"
            "現在の学習計画は変更前の設定から"
            "作成されています。"
            "新しい条件で実行可能かどうかは"
            "まだ確認できていません。"
        )

    if plan_status.next_has_changes:
        needs_review = True

        st.warning(
            "これから適用される学習計画も、"
            "以前の設定から作成されています。"
        )

    if (
        plan_status.active_plan is None
        and plan_status.next_plan is None
    ):
        st.info(
            "現在適用中、または適用予定の"
            "学習計画はありません。"
            "設定が終わったら計画を作成できます。"
        )

    if needs_review:
        st.info(
            "変更した設定を反映するには、"
            "学習計画ページで再計画してください。"
        )

    with st.container(key = "manasuke_nav"):
        col1, col2 = st.columns(2, gap="medium")

        with col1:
            if st.button(
                "学習計画",
                icon=":material/calendar_month:",
                width="stretch"
            ):
                st.switch_page("pages/02_plan.py")

        with col2:
            if st.button(
                "学習記録",
                icon=":material/edit_note:",
                width="stretch"
            ):
                st.switch_page("pages/03_today_and_results.py")


st.divider()


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

active_study_targets = [
    target
    for target in study_targets
    if target.archived_at is None
]

archived_study_targets = [
    target
    for target in study_targets
    if target.archived_at is not None
]

active_goals = [
    goal
    for goal in goals
    if (
        goal.archived_at is None
        and goal.study_target_id in targets_by_id
        and targets_by_id[
            goal.study_target_id
        ].archived_at is None
    )
]

archived_goals = [
    goal
    for goal in goals
    if goal.archived_at is not None
]

policies_by_target = {
    policy.study_target_id: policy
    for policy in policies
}


tab_targets, tab_goals, tab_time, tab_archive = st.tabs(
    ["📚 学習対象", "🎯 目標", "🕒 学習時間", "🗃️ アーカイブ"]
)

with tab_targets:
    # =====================================================
    # StudyTarget Creation
    # =====================================================

    target_settings_service = StudyTargetSettingsService(
        db_path
    )

    create_prefix = f"study_target_create_{participant_id}"
    revision_key = f"{create_prefix}_revision"
    version_key = f"{create_prefix}_version"
    flash_key = f"{create_prefix}_flash"

    if revision_key not in st.session_state:
        st.session_state[revision_key] = 0

    if version_key not in st.session_state:
        current_version = ParticipantRepository(
            db_path
        ).get_planning_data_version(participant_id)

        if current_version is None:
            st.error("参加者情報が見つかりません。")
            st.stop()

        st.session_state[version_key] = current_version


    def reset_target_create_draft() -> None:
        st.session_state[revision_key] += 1
        st.session_state.pop(version_key, None)
        st.rerun()


    flash = st.session_state.pop(flash_key, None)
    if flash:
        st.success(flash)


    with st.expander("＋ 学習対象を新規登録"):
        revision = st.session_state[revision_key]
        prefix = f"{create_prefix}_{revision}"

        kind = st.radio(
            "学習対象の種類",
            options=[
                StudyTargetKind.MATERIAL,
                StudyTargetKind.THEME,
            ],
            format_func=lambda value: (
                "教材" if value == StudyTargetKind.MATERIAL
                else "テーマ"
            ),
            horizontal=True,
            key=f"{prefix}_kind",
        )

        title = st.text_input(
            "学習対象名",
            placeholder="例：数学Ⅰ 問題集",
            max_chars=200,
            key=f"{prefix}_title",
        )

        note = st.text_area(
            "説明・メモ（任意）",
            key=f"{prefix}_note",
        )

        unit_type = None
        next_position = None
        estimated_minutes_per_unit = None
        ranges = []

        if kind == StudyTargetKind.MATERIAL:
            st.markdown("### 教材の設定")

            unit_labels = {
                "PAGE": "ページ",
                "PROBLEM": "問題",
                "WORD": "単語",
                "SECTION": "セクション",
                "OTHER": "その他",
            }

            unit_type = st.selectbox(
                "学習単位",
                options=list(UnitType),
                format_func=lambda value: str(
                    unit_labels.get(
                        value.name,
                        value.value,
                    )
                ),
                key=f"{prefix}_unit_type",
            )

            col_start, col_end = st.columns(2)

            with col_start:
                base_start = st.number_input(
                    "開始位置",
                    min_value=1,
                    value=1,
                    step=1,
                    key=f"{prefix}_base_start",
                )

            with col_end:
                base_end = st.number_input(
                    "終了位置",
                    min_value=1,
                    value=100,
                    step=1,
                    key=f"{prefix}_base_end",
                )

            ranges.append((int(base_start), int(base_end)))

            advanced = st.checkbox(
                "詳細設定：複数の学習範囲を指定する",
                key=f"{prefix}_advanced",
            )

            ids_key = f"{prefix}_extra_range_ids"
            next_id_key = f"{prefix}_next_range_id"

            if ids_key not in st.session_state:
                st.session_state[ids_key] = []

            if next_id_key not in st.session_state:
                st.session_state[next_id_key] = 1

            if advanced:
                st.caption(
                    "学習する順番に、重複しない範囲を"
                    "追加してください。"
                )

                for range_id in list(st.session_state[ids_key]):
                    col1, col2, col3 = st.columns([4, 4, 2])

                    with col1:
                        extra_start = st.number_input(
                            "開始位置",
                            min_value=1,
                            value=101,
                            step=1,
                            key=f"{prefix}_extra_{range_id}_start",
                        )

                    with col2:
                        extra_end = st.number_input(
                            "終了位置",
                            min_value=1,
                            value=120,
                            step=1,
                            key=f"{prefix}_extra_{range_id}_end",
                        )

                    with col3:
                        if st.button(
                            "削除",
                            key=f"{prefix}_remove_{range_id}",
                        ):
                            st.session_state[ids_key].remove(
                                range_id
                            )
                            st.rerun()

                    ranges.append((int(extra_start), int(extra_end)))

                if st.button(
                    "＋ 学習範囲を追加",
                    key=f"{prefix}_add_range",
                ):
                    new_id = st.session_state[next_id_key]
                    st.session_state[next_id_key] += 1
                    st.session_state[ids_key].append(new_id)
                    st.rerun()

            next_position = int(
                st.number_input(
                    "現在位置（次に取り組む単位）",
                    min_value=1,
                    value=1,
                    step=1,
                    key=f"{prefix}_next_position",
                )
            )

            estimated_minutes_per_unit = float(
                st.number_input(
                    "1単位あたりの予想所要時間（分）",
                    min_value=0.1,
                    value=3.0,
                    step=0.5,
                    key=f"{prefix}_minutes_per_unit",
                )
            )

        st.divider()

        # =================================================
        # LearningPolicy
        # =================================================

        st.markdown("### 学習方針")
        st.caption(
            "初期値を用意しています。"
            "必要に応じて自由に変更できます。"
        )

        purpose = st.text_area(
            "学習する目的",
            value="学習を継続し、理解を深めるため",
            key=f"{prefix}_purpose",
        )

        priority = st.selectbox(
            "学習の優先度",
            options=list(Importance),
            index=list(Importance).index(
                Importance.MEDIUM
            ),
            format_func=lambda value: str(
                {
                    "HIGH": "高",
                    "MEDIUM": "中",
                    "LOW": "低",
                }.get(value.name, value.value)
            ),
            key=f"{prefix}_priority",
        )

        st.markdown("**通常の学習**")

        c1, c2 = st.columns(2)

        with c1:
            normal_days = st.number_input(
                "通常：週あたりの日数",
                min_value=1,
                max_value=7,
                value=3,
                step=1,
                key=f"{prefix}_normal_days",
            )

        with c2:
            normal_minutes = st.number_input(
                "通常：1日あたりの時間（分）",
                min_value=5,
                value=30,
                step=5,
                key=f"{prefix}_normal_minutes",
            )

        st.markdown("**最低ライン**")

        c3, c4 = st.columns(2)

        with c3:
            minimum_days = st.number_input(
                "最低：週あたりの日数",
                min_value=1,
                max_value=7,
                value=1,
                step=1,
                key=f"{prefix}_minimum_days",
            )

        with c4:
            minimum_minutes = st.number_input(
                "最低：1日あたりの時間（分）",
                min_value=5,
                value=15,
                step=5,
                key=f"{prefix}_minimum_minutes",
            )

        st.info(
            "最低ラインは計画生成時の必須条件です。"
            "利用可能時間が不足すると、"
            "計画を生成できない場合があります。"
        )

        if st.button(
            "学習対象と学習方針を登録",
            type="primary",
            key=f"{prefix}_submit",
        ):
            try:
                validated_ranges = [
                    StudyTargetRange(
                        sequence_no=index,
                        start_position=start,
                        end_position=end,
                    )
                    for index, (start, end) in enumerate(ranges)
                ]

                target = StudyTarget(
                    id=0,
                    participant_id=participant_id,
                    kind=kind,
                    title=title.strip(),
                    unit_type=unit_type,
                    next_position=next_position,
                    estimated_minutes_per_unit=(
                        estimated_minutes_per_unit
                    ),
                    note=note.strip() or None,
                    ranges=validated_ranges,
                )

                policy = LearningPolicy(
                    study_target_id=0,
                    purpose=purpose.strip(),
                    policy_priority=priority,
                    normal_sessions_per_week=int(normal_days),
                    normal_minutes=int(normal_minutes),
                    minimum_sessions_per_week=int(minimum_days),
                    minimum_minutes=int(minimum_minutes),
                )

                new_id = (
                    target_settings_service.create_with_policy(
                        target=target,
                        policy=policy,
                        expected_version=st.session_state[
                            version_key
                        ],
                    )
                )

            except (
                ValueError,
                DomainValidationError,
                StudyTargetSettingsConflictError,
            ) as exc:
                st.error(str(exc))

            except Exception:
                logging.getLogger(__name__).exception(
                    "StudyTarget creation failed"
                )
                st.error(
                    "学習対象の登録に失敗しました。"
                    "開発ログを確認してください。"
                )

            else:
                st.session_state[flash_key] = (
                    f"学習対象（ID: {new_id}）を登録しました。"
                )
                reset_target_create_draft()

        if st.button(
            "入力内容を破棄して再読み込み",
            key=f"{prefix}_reset",
        ):
            reset_target_create_draft()


    st.subheader("学習対象")

    if not active_study_targets:
        st.info("有効な学習対象がありません。上の登録フォームから追加できます。")

    for target in active_study_targets:
        policy = policies_by_target.get(target.id)

        with st.container(border=True):
            st.markdown(f"#### {target.title}")

            if target.kind == StudyTargetKind.MATERIAL:
                unit = format_unit_type(target.unit_type)
                overview = ["教材"]
                if target.next_position is not None:
                    overview.append(f"次に取り組む位置：{unit}{target.next_position}")
                if target.estimated_minutes_per_unit is not None:
                    overview.append(
                        f"1{unit or '単位'}あたり約"
                        f"{target.estimated_minutes_per_unit:g}分"
                    )
                st.caption("  ｜  ".join(overview))
                if target.ranges:
                    ranges_text = "、".join(
                        f"{r.start_position}〜{r.end_position}"
                        for r in sorted(target.ranges, key=lambda r: r.sequence_no)
                    )
                    st.write(f"学習範囲：{ranges_text}")
            else:
                st.caption("テーマ")

            if target.note:
                st.caption(target.note)

            if policy is not None:
                st.write(f"**学ぶ目的：** {policy.purpose}")
                st.caption(
                    f"通常：週{policy.normal_sessions_per_week}日 × "
                    f"{policy.normal_minutes}分  ｜  "
                    f"最低ライン：週{policy.minimum_sessions_per_week}日 × "
                    f"{policy.minimum_minutes}分"
                )


with tab_goals:
    st.divider()

    st.subheader(
        "目標"
    )

    # =====================================================
    # Goal Creation
    # =====================================================

    goal_settings_service = GoalSettingsService(db_path)

    goal_prefix = f"goal_create_{participant_id}"
    goal_revision_key = f"{goal_prefix}_revision"
    goal_version_key = f"{goal_prefix}_version"
    goal_flash_key = f"{goal_prefix}_flash"

    if goal_revision_key not in st.session_state:
        st.session_state[goal_revision_key] = 0


    def reset_goal_create_form() -> None:
        st.session_state[goal_revision_key] += 1
        st.session_state.pop(goal_version_key, None)
        st.rerun()


    goal_flash = st.session_state.pop(goal_flash_key, None)

    if goal_flash:
        st.success(goal_flash)


    with st.expander("＋ 新しい目標を登録"):
        if not active_study_targets:
            st.info(
                "目標を作るには、先に学習対象を"
                "登録してください。"
            )

        else:
            if goal_version_key not in st.session_state:
                version = ParticipantRepository(
                    db_path
                ).get_planning_data_version(
                    participant_id
                )

                if version is None:
                    st.error("参加者情報が見つかりません。")
                    st.stop()

                st.session_state[goal_version_key] = version

            revision = st.session_state[goal_revision_key]
            prefix = f"{goal_prefix}_{revision}"

            active_targets_by_id = {
                target.id: target
                for target in active_study_targets
            }

            selected_target_id = st.selectbox(
                "学習対象",
                options=list(active_targets_by_id),
                format_func=lambda target_id: (
                    active_targets_by_id[target_id].title
                ),
                key=f"{prefix}_target",
            )

            selected_target = active_targets_by_id[
                selected_target_id
            ]

            title = st.text_input(
                "目標名",
                placeholder=(
                    "例：中間テストまでに問題50まで解く"
                ),
                max_chars=200,
                key=f"{prefix}_title",
            )

            goal_type_labels = {
                "TEST": "テスト",
                "ASSIGNMENT": "課題",
                "CERTIFICATION": "資格試験",
                "PERSONAL": "個人的な目標",
                "OTHER": "その他",
            }

            goal_type = st.selectbox(
                "目標の種類",
                options=list(GoalType),
                format_func=lambda value: str(
                    goal_type_labels.get(
                        value.name,
                        value.value,
                    )
                ),
                key=f"{prefix}_type",
            )

            range_start = None
            range_end = None
            target_minutes = None

            if selected_target.kind == StudyTargetKind.MATERIAL:
                st.markdown("**目標にする教材の範囲**")

                ordered_ranges = sorted(
                    selected_target.ranges,
                    key=lambda item: item.sequence_no,
                )

                if ordered_ranges:
                    st.caption(
                        "登録済みの学習範囲："
                        + "、".join(
                            f"{item.start_position}"
                            f"〜{item.end_position}"
                            for item in ordered_ranges
                        )
                    )

                    current = selected_target.next_position

                    default_start = (
                        current
                        if current is not None
                        and any(
                            item.start_position
                            <= current
                            <= item.end_position
                            for item in ordered_ranges
                        )
                        else ordered_ranges[0].start_position
                    )

                    default_end = ordered_ranges[-1].end_position

                    col1, col2 = st.columns(2)

                    with col1:
                        range_start = int(
                            st.number_input(
                                "開始位置",
                                min_value=1,
                                value=default_start,
                                step=1,
                                key=(
                                    f"{prefix}_start_"
                                    f"{selected_target_id}"
                                ),
                            )
                        )

                    with col2:
                        range_end = int(
                            st.number_input(
                                "終了位置",
                                min_value=1,
                                value=default_end,
                                step=1,
                                key=(
                                    f"{prefix}_end_"
                                    f"{selected_target_id}"
                                ),
                            )
                        )

                    st.caption(
                        "教材の学習範囲に空白がある場合は、"
                        "登録時にその部分を除外します。"
                    )

                else:
                    st.error(
                        "この教材には学習範囲がありません。"
                    )

            else:
                st.markdown("**目標学習時間**")

                target_minutes = int(
                    st.number_input(
                        "期限までに学習する合計時間（分）",
                        min_value=5,
                        value=180,
                        step=5,
                        key=f"{prefix}_target_minutes",
                    )
                )

            st.divider()
            st.markdown("**達成期限**")

            deadline_date = st.date_input(
                "期限の日付",
                value=(
                    now_jst().date()
                    + timedelta(days=7)
                ),
                key=f"{prefix}_deadline_date",
            )

            has_exact_time = st.checkbox(
                "締切時刻を指定する",
                value=False,
                key=f"{prefix}_exact_time",
            )

            deadline_clock = None

            if has_exact_time:
                deadline_clock = st.time_input(
                    "締切時刻",
                    value=time(18, 0),
                    step=300,
                    key=f"{prefix}_deadline_time",
                )

            importance_labels = {
                "HIGH": "高",
                "MEDIUM": "中",
                "LOW": "低",
            }

            importance = st.selectbox(
                "重要度",
                options=list(Importance),
                index=list(Importance).index(
                    Importance.MEDIUM
                ),
                format_func=lambda value: str(
                    importance_labels.get(
                        value.name,
                        value.value,
                    )
                ),
                key=f"{prefix}_importance",
            )

            note = st.text_area(
                "メモ（任意）",
                max_chars=500,
                key=f"{prefix}_note",
            )

            if st.button(
                "目標を登録",
                type="primary",
                key=f"{prefix}_submit",
            ):
                try:
                    # 日付のみなら、翌日00:00を終了境界にする
                    if has_exact_time:
                        if deadline_clock is None:
                            raise ValueError(
                                "期限時刻を入力してください。"
                            )
                        deadline_at = datetime.combine(
                            deadline_date,
                            deadline_clock,
                            tzinfo=JST,
                        )
                    else:
                        deadline_at = datetime.combine(
                            deadline_date + timedelta(days=1),
                            time(0, 0),
                            tzinfo=JST,
                        )

                    new_goal_id = (
                        goal_settings_service.create(
                            participant_id=participant_id,
                            study_target_id=selected_target_id,
                            goal_type=goal_type,
                            title=title,
                            deadline_at=deadline_at,
                            importance=importance,
                            range_start=range_start,
                            range_end=range_end,
                            target_minutes=target_minutes,
                            note=note,
                            expected_version=st.session_state[
                                goal_version_key
                            ],
                            deadline_is_date_only=not has_exact_time,
                        )
                    )

                except (
                    ValueError,
                    DomainValidationError,
                    GoalSettingsConflictError,
                ) as exc:
                    st.error(str(exc))

                except Exception:
                    logging.getLogger(__name__).exception(
                        "Goal creation failed"
                    )
                    st.error(
                        "目標の登録に失敗しました。"
                        "開発ログを確認してください。"
                    )

                else:
                    st.session_state[goal_flash_key] = (
                        f"目標（ID: {new_goal_id}）を"
                        "登録しました。"
                    )
                    reset_goal_create_form()

            if st.button(
                "入力内容を破棄して再読み込み",
                key=f"{prefix}_reset",
            ):
                reset_goal_create_form()

    if not active_goals:
        st.info("有効な目標がありません。上の登録フォームから追加できます。")

    for goal in active_goals:
        target = targets_by_id.get(goal.study_target_id)
        target_name = target.title if target is not None else "学習対象が不明"

        with st.container(border=True):
            st.markdown(f"#### {goal.title}")
            st.caption(
                f"{target_name}  ｜  期限：{format_goal_deadline(goal)}"
                f"  ｜  重要度：{format_importance(goal.importance)}"
            )
            if goal.target_minutes is not None:
                st.write(f"目標学習時間：{goal.target_minutes}分")
            if goal.ranges:
                ranges_text = "、".join(
                    f"{r.start_position}〜{r.end_position}"
                    for r in goal.ranges
                )
                st.write(f"目標範囲：{ranges_text}")
            if goal.note:
                st.caption(goal.note)


st.divider()


with tab_targets:
    with st.expander("✏️ 登録済みの学習対象を編集", expanded=False):
        # =====================================================
        # StudyTarget Settings Editor
        # =====================================================

        st.subheader("登録済み学習対象の編集")

        edit_prefix = f"study_target_edit_{participant_id}"
        edit_revision_key = f"{edit_prefix}_revision"
        edit_version_key = f"{edit_prefix}_version"
        edit_flash_key = f"{edit_prefix}_flash"

        if edit_revision_key not in st.session_state:
            st.session_state[edit_revision_key] = 0


        def reset_target_editor() -> None:
            st.session_state[edit_revision_key] += 1
            st.session_state.pop(edit_version_key, None)
            st.rerun()


        edit_flash = st.session_state.pop(
            edit_flash_key,
            None,
        )

        if edit_flash:
            st.success(edit_flash)

        if not active_study_targets:
            st.info(
                "編集できる学習対象がありません。"
                "先に学習対象を登録してください。"
            )

        else:
            selected_target_id = st.selectbox(
                "編集する学習対象",
                options=[target.id for target in active_study_targets],
                format_func=lambda target_id: (
                    targets_by_id[target_id].title
                ),
                key=f"{edit_prefix}_selected_target",
            )

            selected_target = targets_by_id[selected_target_id]
            selected_policy = policies_by_target.get(
                selected_target_id
            )

            if selected_policy is None:
                st.error(
                    "この学習対象にはLearningPolicyがありません。"
                    "編集を続ける前にデータを確認してください。"
                )

            else:
                if edit_version_key not in st.session_state:
                    current_version = ParticipantRepository(
                        db_path
                    ).get_planning_data_version(participant_id)

                    if current_version is None:
                        st.error(
                            "参加者情報が見つかりません。"
                        )
                        st.stop()

                    st.session_state[edit_version_key] = (
                        current_version
                    )

                revision = st.session_state[edit_revision_key]
                form_prefix = (
                    f"{edit_prefix}_{revision}_"
                    f"{selected_target_id}"
                )

                with st.form(key=f"{form_prefix}_form"):
                    st.markdown("### 基本情報")

                    new_title = st.text_input(
                        "学習対象名",
                        value=selected_target.title,
                        max_chars=200,
                        key=f"{form_prefix}_title",
                    )

                    new_note = st.text_area(
                        "説明・メモ",
                        value=selected_target.note or "",
                        key=f"{form_prefix}_note",
                    )

                    if (
                        selected_target.kind
                        == StudyTargetKind.MATERIAL
                    ):
                        new_estimate = float(
                            st.number_input(
                                "1単位の予想所要時間（分）",
                                value=float(
                                    selected_target
                                    .estimated_minutes_per_unit
                                    or 1.0
                                ),
                                step=0.5,
                                format="%.2f",
                                key=f"{form_prefix}_estimate",
                            )
                        )

                        st.caption(
                            "現在位置："
                            f"{selected_target.next_position}"
                            "（今回は変更できません）"
                        )

                    else:
                        new_estimate = None

                    st.divider()
                    st.markdown("### 学習方針")

                    new_purpose = st.text_area(
                        "学習する目的",
                        value=selected_policy.purpose,
                        key=f"{form_prefix}_purpose",
                    )

                    priorities = list(Importance)

                    new_priority = st.selectbox(
                        "学習の優先度",
                        options=priorities,
                        index=priorities.index(
                            selected_policy.policy_priority
                        ),
                        format_func=lambda value: str(
                            {
                                "HIGH": "高",
                                "MEDIUM": "中",
                                "LOW": "低",
                            }.get(value.name, value.value)
                        ),
                        key=f"{form_prefix}_priority",
                    )

                    st.markdown("**通常の学習**")

                    col1, col2 = st.columns(2)

                    with col1:
                        new_normal_days = st.number_input(
                            "通常：週あたりの日数",
                            min_value=0,
                            max_value=7,
                            value=selected_policy
                            .normal_sessions_per_week,
                            step=1,
                            key=f"{form_prefix}_normal_days",
                        )

                    with col2:
                        new_normal_minutes = st.number_input(
                            "通常：1日あたりの時間（分）",
                            min_value=0,
                            value=selected_policy.normal_minutes,
                            step=5,
                            key=f"{form_prefix}_normal_minutes",
                        )

                    st.markdown("**最低ライン**")

                    col3, col4 = st.columns(2)

                    with col3:
                        new_minimum_days = st.number_input(
                            "最低：週あたりの日数",
                            min_value=0,
                            max_value=7,
                            value=selected_policy
                            .minimum_sessions_per_week,
                            step=1,
                            key=f"{form_prefix}_minimum_days",
                        )

                    with col4:
                        new_minimum_minutes = st.number_input(
                            "最低：1日あたりの時間（分）",
                            min_value=0,
                            value=selected_policy.minimum_minutes,
                            step=5,
                            key=f"{form_prefix}_minimum_minutes",
                        )

                    submitted = st.form_submit_button(
                        "変更を保存",
                        type="primary",
                    )

                if submitted:
                    try:
                        updated_policy = LearningPolicy(
                            study_target_id=selected_target_id,
                            purpose=new_purpose.strip(),
                            policy_priority=new_priority,
                            normal_sessions_per_week=int(
                                new_normal_days
                            ),
                            normal_minutes=int(
                                new_normal_minutes
                            ),
                            minimum_sessions_per_week=int(
                                new_minimum_days
                            ),
                            minimum_minutes=int(
                                new_minimum_minutes
                            ),
                        )

                        target_settings_service.update_settings(
                            participant_id=participant_id,
                            study_target_id=selected_target_id,
                            title=new_title,
                            note=new_note,
                            estimated_minutes_per_unit=new_estimate,
                            policy=updated_policy,
                            expected_version=st.session_state[
                                edit_version_key
                            ],
                        )

                    except (
                        ValueError,
                        DomainValidationError,
                        StudyTargetSettingsConflictError,
                    ) as exc:
                        st.error(str(exc))

                    except Exception:
                        logging.getLogger(__name__).exception(
                            "StudyTarget update failed"
                        )
                        st.error(
                            "学習対象の編集に失敗しました。"
                            "開発ログを確認してください。"
                        )

                    else:
                        st.session_state[edit_flash_key] = (
                            "学習対象と学習方針を更新しました。"
                        )
                        reset_target_editor()

                if st.button(
                    "変更を破棄して最新情報を読み込む",
                    key=f"{edit_prefix}_reload",
                ):
                    reset_target_editor()



with tab_goals:
    with st.expander("✏️ 登録済みの目標を編集", expanded=False):
        # =====================================================
        # Goal Editor
        # =====================================================

        st.subheader("登録済み目標の編集")

        goal_edit_prefix = f"goal_edit_{participant_id}"
        goal_edit_version_key = f"{goal_edit_prefix}_version"
        goal_edit_revision_key = f"{goal_edit_prefix}_revision"
        goal_edit_flash_key = f"{goal_edit_prefix}_flash"

        if goal_edit_revision_key not in st.session_state:
            st.session_state[goal_edit_revision_key] = 0


        def reset_goal_editor(message: str | None = None) -> None:
            st.session_state[goal_edit_revision_key] += 1
            st.session_state.pop(goal_edit_version_key, None)

            if message:
                st.session_state[goal_edit_flash_key] = message

            st.rerun()


        edit_flash = st.session_state.pop(
            goal_edit_flash_key, None
        )

        if edit_flash:
            st.success(edit_flash)


        if not active_goals:
            st.info("編集可能な目標はありません。")

        else:
            if goal_edit_version_key not in st.session_state:
                version = ParticipantRepository(
                    db_path
                ).get_planning_data_version(participant_id)

                if version is None:
                    st.error("参加者情報が見つかりません。")
                    st.stop()

                st.session_state[goal_edit_version_key] = version

            goals_by_id_for_edit = {
                goal.id: goal
                for goal in active_goals
            }

            selected_goal_id = st.selectbox(
                "編集する目標",
                options=list(goals_by_id_for_edit),
                format_func=lambda goal_id: (
                    goals_by_id_for_edit[goal_id].title
                ),
                key=f"{goal_edit_prefix}_selected",
            )

            selected_goal = goals_by_id_for_edit[
                selected_goal_id
            ]

            selected_target = targets_by_id[
                selected_goal.study_target_id
            ]

            revision = st.session_state[
                goal_edit_revision_key
            ]

            prefix = (
                f"{goal_edit_prefix}_{revision}_"
                f"{selected_goal_id}"
            )

            with st.expander(
                "目標の内容を編集",
                expanded=True,
            ):
                st.caption(
                    f"学習対象：{selected_target.title}"
                    "（変更不可）"
                )

                new_title = st.text_input(
                    "目標名",
                    value=selected_goal.title,
                    max_chars=200,
                    key=f"{prefix}_title",
                )

                goal_types = list(GoalType)

                new_goal_type = st.selectbox(
                    "目標の種類",
                    options=goal_types,
                    index=goal_types.index(
                        selected_goal.goal_type
                    ),
                    format_func=lambda value: str(
                        {
                            "TEST": "テスト",
                            "ASSIGNMENT": "課題",
                            "CERTIFICATION": "資格試験",
                            "PERSONAL": "個人的な目標",
                            "OTHER": "その他",
                        }.get(value.name, value.value)
                    ),
                    key=f"{prefix}_type",
                )

                requested_ranges = []
                edited_rows = []
                new_target_minutes = None

                if (
                    selected_target.kind
                    == StudyTargetKind.MATERIAL
                ):
                    st.markdown("**目標範囲**")

                    st.caption(
                        "行を追加・削除して目標範囲を"
                        "編集できます。教材の学習経路に"
                        "含まれる範囲を指定してください。"
                    )

                    initial_ranges = [
                        {
                            "開始位置": r.start_position,
                            "終了位置": r.end_position,
                        }
                        for r in selected_goal.ranges
                    ]

                    edited_rows = st.data_editor(
                        initial_ranges,
                        num_rows="dynamic",
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "開始位置": st.column_config.NumberColumn(
                                "開始位置",
                                min_value=1,
                                step=1,
                                required=True,
                            ),
                            "終了位置": st.column_config.NumberColumn(
                                "終了位置",
                                min_value=1,
                                step=1,
                                required=True,
                            ),
                        },
                        key=f"{prefix}_ranges",
                    )

                    st.caption(
                        "教材の登録範囲："
                        + "、".join(
                            f"{r.start_position}〜{r.end_position}"
                            for r in sorted(
                                selected_target.ranges,
                                key=lambda x: x.sequence_no,
                            )
                        )
                    )

                else:
                    new_target_minutes = int(
                        st.number_input(
                            "目標学習時間（分）",
                            min_value=5,
                            value=int(
                                selected_goal.target_minutes or 180
                            ),
                            step=5,
                            key=f"{prefix}_minutes",
                        )
                    )

                st.divider()
                st.markdown("**達成期限**")

                deadline_local = (
                    selected_goal.deadline_at.astimezone(JST)
                )

                if selected_goal.deadline_is_date_only:
                    initial_date = (
                        deadline_local - timedelta(days=1)
                    ).date()
                else:
                    initial_date = deadline_local.date()

                new_deadline_date = st.date_input(
                    "期限の日付",
                    value=initial_date,
                    key=f"{prefix}_deadline_date",
                )

                new_has_exact_time = st.checkbox(
                    "締切時刻を指定する",
                    value=not selected_goal.deadline_is_date_only,
                    key=f"{prefix}_exact_time",
                )

                new_deadline_clock = None

                if new_has_exact_time:
                    new_deadline_clock = st.time_input(
                        "締切時刻",
                        value=deadline_local.time(),
                        step=300,
                        key=f"{prefix}_deadline_time",
                    )

                st.divider()

                priorities = list(Importance)

                new_importance = st.selectbox(
                    "重要度",
                    options=priorities,
                    index=priorities.index(
                        selected_goal.importance
                    ),
                    format_func=lambda value: str(
                        {
                            "HIGH": "高",
                            "MEDIUM": "中",
                            "LOW": "低",
                        }.get(value.name, value.value)
                    ),
                    key=f"{prefix}_importance",
                )

                new_note = st.text_area(
                    "メモ",
                    value=selected_goal.note or "",
                    max_chars=500,
                    key=f"{prefix}_note",
                )

                if st.button(
                    "目標の変更を保存",
                    type="primary",
                    key=f"{prefix}_save",
                ):
                    try:
                        if (
                            selected_target.kind
                            == StudyTargetKind.MATERIAL
                        ):
                            for row in edited_rows:
                                start = row.get("開始位置")
                                end = row.get("終了位置")

                                if start is None or end is None:
                                    raise ValueError(
                                        "目標範囲の開始・終了を"
                                        "両方入力してください。"
                                    )

                                requested_ranges.append(
                                    (int(start), int(end))
                                )

                        if new_has_exact_time:
                            if new_deadline_clock is None:
                                raise ValueError(
                                    "期限時刻を入力してください。"
                                )
                            deadline_at = datetime.combine(
                                new_deadline_date,
                                new_deadline_clock,
                                tzinfo=JST,
                            )
                        else:
                            deadline_at = datetime.combine(
                                new_deadline_date
                                + timedelta(days=1),
                                time(0, 0),
                                tzinfo=JST,
                            )

                        goal_settings_service.update(
                            participant_id=participant_id,
                            goal_id=selected_goal_id,
                            goal_type=new_goal_type,
                            title=new_title,
                            deadline_at=deadline_at,
                            deadline_is_date_only=(
                                not new_has_exact_time
                            ),
                            importance=new_importance,
                            requested_ranges=requested_ranges,
                            target_minutes=new_target_minutes,
                            note=new_note,
                            expected_version=st.session_state[
                                goal_edit_version_key
                            ],
                        )

                    except (
                        ValueError,
                        DomainValidationError,
                        GoalSettingsConflictError,
                    ) as exc:
                        st.error(str(exc))

                    except Exception:
                        logging.getLogger(__name__).exception(
                            "Goal update failed"
                        )
                        st.error(
                            "目標の更新に失敗しました。"
                            "開発ログを確認してください。"
                        )

                    else:
                        reset_goal_editor(
                            "目標を更新しました。"
                        )

            if st.button(
                "目標の最新情報を再読み込み",
                key=f"{goal_edit_prefix}_reload",
            ):
                reset_goal_editor()


with tab_archive:
    # =====================================================
    # StudyTarget / Goal Archive Editor
    # =====================================================

    archive_service = StudyTargetArchiveService(db_path)

    archive_prefix = f"archive_settings_{participant_id}"
    archive_version_key = f"{archive_prefix}_version"
    archive_revision_key = f"{archive_prefix}_revision"
    archive_flash_key = f"{archive_prefix}_flash"

    if archive_revision_key not in st.session_state:
        st.session_state[archive_revision_key] = 0

    if archive_version_key not in st.session_state:
        current_version = ParticipantRepository(
            db_path
        ).get_planning_data_version(participant_id)

        if current_version is None:
            st.error("参加者情報が見つかりません。")
            st.stop()

        st.session_state[archive_version_key] = current_version


    def reset_archive_editor(
        message: str | None = None,
    ) -> None:
        st.session_state[archive_revision_key] += 1
        st.session_state.pop(archive_version_key, None)

        if message:
            st.session_state[archive_flash_key] = message

        st.rerun()


    def run_archive_operation(
        operation,
        success_message,
    ) -> None:
        try:
            result = operation()

        except (
            ArchiveConflictError,
            ArchiveOperationError,
            ValueError,
        ) as exc:
            st.error(str(exc))

        except Exception:
            logging.getLogger(__name__).exception(
                "Archive operation failed"
            )
            st.error(
                "アーカイブ・復元処理に失敗しました。"
                "開発ログを確認してください。"
            )

        else:
            reset_archive_editor(
                success_message(result)
            )


    def render_archive_form(
        *,
        action_key: str,
        title: str,
        options: list[int],
        format_option,
        confirm_label: str,
        submit_label: str,
        operation,
        success_message,
    ) -> None:
        st.markdown(f"**{title}**")

        if not options:
            st.caption("対象となるデータはありません。")
            return

        revision = st.session_state[archive_revision_key]
        form_prefix = (
            f"{archive_prefix}_{revision}_{action_key}"
        )

        with st.form(key=f"{form_prefix}_form"):
            selected_id = st.selectbox(
                "対象を選択",
                options=options,
                format_func=format_option,
                key=f"{form_prefix}_selected",
            )

            confirmed = st.checkbox(
                confirm_label,
                key=f"{form_prefix}_confirmed",
            )

            submitted = st.form_submit_button(
                submit_label,
            )

        if submitted:
            if not confirmed:
                st.error(
                    "操作内容を確認し、チェックを"
                    "入れてください。"
                )
            else:
                run_archive_operation(
                    operation=lambda: operation(
                        selected_id,
                        st.session_state[archive_version_key],
                    ),
                    success_message=success_message,
                )


    flash = st.session_state.pop(
        archive_flash_key,
        None,
    )

    if flash:
        st.success(flash)

    st.divider()

    st.subheader("アーカイブ・復元")
    st.caption(
        "今後の計画から除外したり、"
        "再び学習対象として利用したりできます。"
    )

    st.info(
        "アーカイブしても、"
        "過去の学習計画や学習実績は削除されません。"
    )

    with st.expander("アーカイブ・復元の管理"):
        target_tab, goal_tab = st.tabs(
            ["学習対象", "目標"]
        )

        # =============================================
        # StudyTarget
        # =============================================

        with target_tab:
            st.markdown("### 学習対象の管理")

            render_archive_form(
                action_key="archive_target",
                title="学習対象をアーカイブ",
                options=[
                    target.id
                    for target in active_study_targets
                ],
                format_option=lambda target_id: (
                    targets_by_id[target_id].title
                    + "（関連する有効目標："
                    + str(
                        sum(
                            goal.study_target_id == target_id
                            for goal in active_goals
                        )
                    )
                    + "件）"
                ),
                confirm_label=(
                    "関連する有効なGoalも同時に"
                    "アーカイブされることを確認しました"
                ),
                submit_label="学習対象をアーカイブ",
                operation=lambda target_id, version: (
                    archive_service.archive_study_target(
                        participant_id=participant_id,
                        study_target_id=target_id,
                        expected_version=version,
                    )
                ),
                success_message=lambda count: (
                    "学習対象をアーカイブしました。"
                    f"関連するGoal：{count}件"
                ),
            )

            st.divider()

            render_archive_form(
                action_key="restore_target",
                title="学習対象を復元",
                options=[
                    target.id
                    for target in archived_study_targets
                ],
                format_option=lambda target_id: (
                    targets_by_id[target_id].title
                ),
                confirm_label=(
                    "Goalは自動復元されないことを"
                    "確認しました"
                ),
                submit_label="学習対象を復元",
                operation=lambda target_id, version: (
                    archive_service.restore_study_target(
                        participant_id=participant_id,
                        study_target_id=target_id,
                        expected_version=version,
                    )
                ),
                success_message=lambda _: (
                    "学習対象を復元しました。"
                    "必要なGoalは別途復元してください。"
                ),
            )

        # =============================================
        # Goal
        # =============================================

        with goal_tab:
            st.markdown("### 目標の管理")

            goals_by_id = {
                goal.id: goal
                for goal in goals
            }

            render_archive_form(
                action_key="archive_goal",
                title="目標をアーカイブ",
                options=[
                    goal.id
                    for goal in active_goals
                ],
                format_option=lambda goal_id: (
                    goals_by_id[goal_id].title
                ),
                confirm_label=(
                    "この目標を今後の計画から"
                    "除外することを確認しました"
                ),
                submit_label="目標をアーカイブ",
                operation=lambda goal_id, version: (
                    archive_service.archive_goal(
                        participant_id=participant_id,
                        goal_id=goal_id,
                        expected_version=version,
                    )
                ),
                success_message=lambda _: (
                    "目標をアーカイブしました。"
                ),
            )

            st.divider()

            restorable_goals = [
                goal
                for goal in archived_goals
                if (
                    goal.study_target_id in targets_by_id
                    and targets_by_id[
                        goal.study_target_id
                    ].archived_at is None
                )
            ]

            blocked_goal_count = (
                len(archived_goals)
                - len(restorable_goals)
            )

            if blocked_goal_count:
                st.info(
                    f"{blocked_goal_count}件の目標は、"
                    "学習対象がアーカイブ中のため"
                    "復元できません。"
                    "先に学習対象を復元してください。"
                )

            render_archive_form(
                action_key="restore_goal",
                title="目標を復元",
                options=[
                    goal.id
                    for goal in restorable_goals
                ],
                format_option=lambda goal_id: (
                    goals_by_id[goal_id].title
                ),
                confirm_label=(
                    "この目標を再び有効にすることを"
                    "確認しました"
                ),
                submit_label="目標を復元",
                operation=lambda goal_id, version: (
                    archive_service.restore_goal(
                        participant_id=participant_id,
                        goal_id=goal_id,
                        expected_version=version,
                    )
                ),
                success_message=lambda _: (
                    "目標を復元しました。"
                ),
            )

    if st.button(
        "アーカイブ情報を再読み込み",
        key=f"{archive_prefix}_reload",
    ):
        reset_archive_editor()


with tab_time:
    # =====================================================
    # Weekly Availability Editor
    # =====================================================

    st.subheader("週の利用可能時間")
    st.caption(
        "曜日ごとに学習できる時間を設定します。"
        "変更は保存ボタンを押すまで反映されません。"
    )

    weekly_service = WeeklyAvailabilityService(db_path)

    # Streamlit Session Stateを参加者単位で管理する
    prefix = f"weekly_{participant_id}"
    draft_key = f"{prefix}_draft"
    version_key = f"{prefix}_version"
    uid_key = f"{prefix}_next_uid"


    def new_slot_id() -> int:
        st.session_state[uid_key] = (
            st.session_state.get(uid_key, 0) + 1
        )
        return st.session_state[uid_key]


    # 初回だけDBの設定を編集用データへコピー
    if draft_key not in st.session_state:
        version = ParticipantRepository(
            db_path
        ).get_planning_data_version(participant_id)

        if version is None:
            st.error("参加者情報が見つかりません。")
            st.stop()

        draft = {day: [] for day in range(7)}

        for item in available_times:
            draft[item.weekday].append({
                "id": new_slot_id(),
                "start": format_minute_of_day(
                    item.start_minute_of_day
                ),
                "end": format_minute_of_day(
                    item.end_minute_of_day
                ),
            })

        st.session_state[draft_key] = draft
        st.session_state[version_key] = version


    def update_slot(
        day: int,
        slot_id: int,
        field: str,
        widget_key: str,
    ) -> None:
        """UIの変更を編集用データへ反映する。"""

        new_value = st.session_state[widget_key]

        for slot in st.session_state[draft_key][day]:
            if slot["id"] == slot_id:
                slot[field] = new_value
                break


    # 5分単位の時刻選択肢
    START_TIMES = [
        f"{minute // 60:02d}:{minute % 60:02d}"
        for minute in range(0, 1440, 5)
    ]

    END_TIMES = START_TIMES + ["24:00"]


    day = st.selectbox(
        "編集する曜日",
        options=list(range(7)),
        format_func=lambda value: WEEKDAY_LABELS[value],
        key=f"{prefix}_selected_day",
    )

    st.markdown(
        f"**{WEEKDAY_LABELS[day]}曜日の時間帯**"
    )

    slots = st.session_state[draft_key][day]

    if not slots:
        st.info("この曜日に時間帯はありません。")

    for slot in slots:
        col_start, col_end, col_delete = st.columns(
            [4, 4, 1]
        )

        start_key = f"{prefix}_start_{slot['id']}"
        end_key = f"{prefix}_end_{slot['id']}"

        with col_start:
            st.selectbox(
                "開始",
                options=START_TIMES,
                index=START_TIMES.index(slot["start"]),
                key=start_key,
                on_change=update_slot,
                args=(day, slot["id"], "start", start_key),
            )

        with col_end:
            st.selectbox(
                "終了",
                options=END_TIMES,
                index=END_TIMES.index(slot["end"]),
                key=end_key,
                on_change=update_slot,
                args=(day, slot["id"], "end", end_key),
            )

        with col_delete:
            st.write("")
            st.write("")

            if st.button(
                "削除",
                key=f"{prefix}_delete_{slot['id']}",
            ):
                st.session_state[draft_key][day] = [
                    item
                    for item in slots
                    if item["id"] != slot["id"]
                ]
                st.rerun()


    if st.button(
        "＋ 時間帯を追加",
        key=f"{prefix}_add",
    ):
        st.session_state[draft_key][day].append({
            "id": new_slot_id(),
            "start": "18:00",
            "end": "19:00",
        })
        st.rerun()


    # =====================================================
    # Copy to other weekdays
    # =====================================================

    st.divider()
    st.markdown("**他の曜日へコピー**")

    copy_targets = st.multiselect(
        "コピー先の曜日",
        options=[
            value for value in range(7)
            if value != day
        ],
        format_func=lambda value: WEEKDAY_LABELS[value],
        key=f"{prefix}_copy_to_{day}",
    )

    st.caption(
        "コピー先に現在設定されている時間帯は"
        "置き換えられます。"
    )

    if st.button(
        "選択した曜日にコピー",
        disabled=not copy_targets,
        key=f"{prefix}_copy",
    ):
        source_slots = st.session_state[draft_key][day]

        for target_day in copy_targets:
            st.session_state[draft_key][target_day] = [
                {
                    "id": new_slot_id(),
                    "start": slot["start"],
                    "end": slot["end"],
                }
                for slot in source_slots
            ]

        st.rerun()


    # =====================================================
    # Save all weekdays
    # =====================================================

    st.divider()
    st.markdown("**変更の保存**")

    st.caption(
        "7曜日分の設定をまとめて保存します。"
        "深夜またぎは保存時に曜日単位へ分割されます。"
    )

    if st.button(
        "変更を保存",
        type="primary",
        key=f"{prefix}_save",
    ):
        weekly_slots = {
            current_day: [
                (slot["start"], slot["end"])
                for slot in st.session_state[draft_key][current_day]
            ]
            for current_day in range(7)
        }

        try:
            weekly_service.save(
                participant_id=participant_id,
                weekly_slots=weekly_slots,
                expected_version=st.session_state[version_key],
            )

            # 保存成功後、DBの正規化済みデータを再読込
            st.session_state.pop(draft_key, None)
            st.session_state[f"{prefix}_saved"] = True
            st.rerun()

        except AvailabilityConflictError as exc:
            st.error(str(exc))

        except ValueError as exc:
            st.error(str(exc))

        except Exception:
            logging.getLogger(__name__).exception(
                "Weekly availability save failed"
            )
            st.error(
                "設定の保存に失敗しました。"
                "開発ログを確認してください。"
            )


    if st.session_state.pop(f"{prefix}_saved", False):
        st.success("学習可能時間を保存しました。")


    if st.button(
        "変更を破棄して再読み込み",
        key=f"{prefix}_reload",
    ):
        st.session_state.pop(draft_key, None)
        st.rerun()

    st.divider()


    # =====================================================
    # BusyEvent / ExtraAvailableTime Editor
    # =====================================================

    dated_service = DatedAvailabilityService(db_path)

    event_prefix = f"dated_events_{participant_id}"
    event_version_key = f"{event_prefix}_version"
    event_revision_key = f"{event_prefix}_revision"
    event_flash_key = f"{event_prefix}_flash"

    if event_revision_key not in st.session_state:
        st.session_state[event_revision_key] = 0

    if event_version_key not in st.session_state:
        version = ParticipantRepository(
            db_path
        ).get_planning_data_version(participant_id)

        if version is None:
            st.error("参加者情報が見つかりません。")
            st.stop()

        st.session_state[event_version_key] = version


    def refresh_dated_editor(message: str | None = None):
        # 古いフォームのWidget Stateを使い回さない
        st.session_state[event_revision_key] += 1
        st.session_state.pop(event_version_key, None)

        if message is not None:
            st.session_state[event_flash_key] = message

        st.rerun()


    def render_datetime_fields(
        *,
        key_prefix: str,
        default_start: datetime,
        default_end: datetime,
        default_note: str = "",
    ):
        start_local = default_start.astimezone(JST)
        end_local = default_end.astimezone(JST)

        col_start, col_end = st.columns(2)

        with col_start:
            st.markdown("**開始日時**")

            start_date = st.date_input(
                "開始日",
                value=start_local.date(),
                key=f"{key_prefix}_start_date",
            )

            start_time = st.time_input(
                "開始時刻",
                value=start_local.time().replace(tzinfo=None),
                step=300,
                key=f"{key_prefix}_start_time",
            )

        with col_end:
            st.markdown("**終了日時**")

            end_date = st.date_input(
                "終了日",
                value=end_local.date(),
                key=f"{key_prefix}_end_date",
            )

            end_time = st.time_input(
                "終了時刻",
                value=end_local.time().replace(tzinfo=None),
                step=300,
                key=f"{key_prefix}_end_time",
            )

        note = st.text_input(
            "予定名・メモ（任意）",
            value=default_note,
            max_chars=500,
            key=f"{key_prefix}_note",
        )

        return (
            datetime.combine(
                start_date, start_time, tzinfo=JST
            ),
            datetime.combine(
                end_date, end_time, tzinfo=JST
            ),
            note,
        )


    def execute_dated_action(action, success_message: str):
        try:
            action()

        except AvailabilityConflictError as exc:
            st.error(str(exc))
            st.info(
                "ほかの設定が更新されています。"
                "下の再読み込みボタンを押してください。"
            )

        except (ValueError, AvailabilityRecordNotFoundError) as exc:
            st.error(str(exc))

        except Exception:
            logging.getLogger(__name__).exception(
                "Dated availability operation failed"
            )
            st.error(
                "予定の保存・削除に失敗しました。"
                "開発ログを確認してください。"
            )

        else:
            refresh_dated_editor(success_message)


    def render_dated_event_section(
        *,
        kind: EventKind,
        title: str,
        description: str,
    ):
        st.subheader(title)
        st.caption(description)

        records = dated_service.list_events(
            participant_id=participant_id,
            kind=kind,
        )

        revision = st.session_state[event_revision_key]

        # -----------------------------------------
        # Add
        # -----------------------------------------

        with st.expander(
            "＋ 新しい予定を追加",
            expanded=not bool(records),
        ):
            with st.form(
                key=f"{event_prefix}_{revision}_{kind}_add"
            ):
                default_day = (
                    now_jst().date() + timedelta(days=1)
                )

                default_start = datetime.combine(
                    default_day,
                    time(18, 0),
                    tzinfo=JST,
                )

                default_end = datetime.combine(
                    default_day,
                    time(19, 0),
                    tzinfo=JST,
                )

                start_at, end_at, note = render_datetime_fields(
                    key_prefix=(
                        f"{event_prefix}_{revision}_{kind}_new"
                    ),
                    default_start=default_start,
                    default_end=default_end,
                )

                submitted = st.form_submit_button(
                    "予定を追加",
                    type="primary",
                )

            if submitted:
                execute_dated_action(
                    lambda: dated_service.save(
                        participant_id=participant_id,
                        kind=kind,
                        event_id=None,
                        start_at=start_at,
                        end_at=end_at,
                        note=note,
                        expected_version=st.session_state[
                            event_version_key
                        ],
                    ),
                    "予定を追加しました。",
                )

        # -----------------------------------------
        # List / Edit / Delete
        # -----------------------------------------

        st.markdown("**登録済みの予定**")

        if not records:
            st.info("登録済みの予定はありません。")

        for record in records:
            label = record.note or "名称なし"

            heading = (
                f"{label}："
                f"{format_datetime(record.start_at)}"
                " 〜 "
                f"{format_datetime(record.end_at)}"
            )

            with st.expander(heading):
                with st.form(
                    key=(
                        f"{event_prefix}_{revision}_"
                        f"{kind}_edit_{record.id}"
                    )
                ):
                    start_at, end_at, note = (
                        render_datetime_fields(
                            key_prefix=(
                                f"{event_prefix}_{revision}_"
                                f"{kind}_{record.id}"
                            ),
                            default_start=record.start_at,
                            default_end=record.end_at,
                            default_note=record.note or "",
                        )
                    )

                    confirm_delete = st.checkbox(
                        "この予定の削除を確認しました",
                        key=(
                            f"{event_prefix}_{revision}_"
                            f"{kind}_{record.id}_confirm"
                        ),
                    )

                    col_save, col_delete = st.columns(2)

                    with col_save:
                        save_clicked = st.form_submit_button(
                            "変更を保存",
                            type="primary",
                        )

                    with col_delete:
                        delete_clicked = st.form_submit_button(
                            "予定を削除",
                        )

                if save_clicked:
                    execute_dated_action(
                        lambda: dated_service.save(
                            participant_id=participant_id,
                            kind=kind,
                            event_id=record.id,
                            start_at=start_at,
                            end_at=end_at,
                            note=note,
                            expected_version=st.session_state[
                                event_version_key
                            ],
                        ),
                        "予定を更新しました。",
                    )

                elif delete_clicked:
                    if not confirm_delete:
                        st.error(
                            "削除する場合は確認欄に"
                            "チェックを入れてください。"
                        )
                    else:
                        execute_dated_action(
                            lambda: dated_service.delete(
                                participant_id=participant_id,
                                kind=kind,
                                event_id=record.id,
                                expected_version=st.session_state[
                                    event_version_key
                                ],
                            ),
                            "予定を削除しました。",
                        )


    # =====================================================
    # Render sections
    # =====================================================

    flash = st.session_state.pop(event_flash_key, None)
    if flash:
        st.success(flash)

    st.divider()

    render_dated_event_section(
        kind="busy",
        title="学習できない予定",
        description=(
            "普段の学習可能時間から除外する"
            "日時を登録します。"
        ),
    )

    st.divider()

    render_dated_event_section(
        kind="extra",
        title="追加で使える時間",
        description=(
            "普段の設定にない、"
            "特別に学習できる日時を登録します。"
        ),
    )

    st.divider()

    if st.button(
        "予定の最新情報を再読み込み",
        key=f"{event_prefix}_reload",
    ):
        refresh_dated_editor()