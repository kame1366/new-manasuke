"""Public-facing Japanese labels and date-only deadline rendering."""

from datetime import datetime, timedelta

from domain.enums import (
    GoalType, Importance, PlanItemOrigin, StudyTargetKind, UnitType,
)
from domain.models import Goal, PlanItem, StudyTarget
from domain.time_rules import JST
from ui.formatters import (
    format_goal_deadline,
    format_importance,
    format_plan_item_work,
)


def _target(unit_type: UnitType) -> StudyTarget:
    return StudyTarget(
        id=1, participant_id="test", kind=StudyTargetKind.MATERIAL,
        title="数学 基礎問題集", unit_type=unit_type,
        next_position=1, estimated_minutes_per_unit=4,
    )


def _item() -> PlanItem:
    return PlanItem(
        id=1, plan_id=1, study_target_id=1,
        start_at=datetime(2026, 10, 16, 18, 0, tzinfo=JST),
        end_at=datetime(2026, 10, 16, 18, 30, tzinfo=JST),
        origin=PlanItemOrigin.SYSTEM_GENERATED, planned_minutes=30,
        range_start=6, range_end=12,
    )


def test_plan_item_unit_types_are_japanese():
    item = _item()
    assert format_plan_item_work(item=item, target=_target(UnitType.PROBLEM)) == (
        "数学 基礎問題集 問題6〜12"
    )
    assert format_plan_item_work(item=item, target=_target(UnitType.WORD)) == (
        "数学 基礎問題集 単語6〜12"
    )


def _goal(deadline: datetime, date_only: bool) -> Goal:
    return Goal(
        id=1, participant_id="test", study_target_id=1,
        goal_type=GoalType.TEST, title="テスト", deadline_at=deadline,
        importance=Importance.HIGH, deadline_is_date_only=date_only,
    )


def test_goal_deadline_date_only_shows_original_date():
    deadline = datetime(2026, 10, 26, 0, 0, tzinfo=JST)
    assert format_goal_deadline(_goal(deadline, True)) == "10/25まで"
    assert format_goal_deadline(_goal(deadline, False)) == "10/26 00:00"


def test_importance_labels():
    assert format_importance(Importance.HIGH) == "高"
    assert format_importance(Importance.MEDIUM) == "中"
    assert format_importance(Importance.LOW) == "低"


def test_settings_archive_is_not_in_normal_lists():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "pages" / "01_learning_settings.py").read_text(encoding="utf-8")
    assert "for target in active_study_targets:" in source
    assert "for goal in active_goals:" in source
    assert "options=[target.id for target in active_study_targets]" in source


def test_plan_displays_entire_horizon():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "pages" / "02_plan.py").read_text(encoding="utf-8")
    assert "end_date = to_jst(plan.horizon_end - timedelta(microseconds=1)).date()" in source
    assert "if not day_items:" in source
    assert "PlanItemOrigin.USER_CREATED" in source
