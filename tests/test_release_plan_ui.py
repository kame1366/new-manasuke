"""Static safety regression for the plan page's generation entrypoints."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_plan_generation_invoked_only_inside_helper():
    source = (ROOT / "pages" / "02_plan.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "generate"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "generation_service"
    ]
    assert len(calls) == 1, "No button should independently generate twice"
    assert "traceback.format_exc" not in source
    assert '"DEBUG: "' not in source


def test_settings_are_grouped_into_tabs():
    source = (ROOT / "pages" / "01_learning_settings.py").read_text(encoding="utf-8")
    assert "tab_targets, tab_goals, tab_time, tab_archive = st.tabs(" in source
    for section in ("with tab_targets:", "with tab_goals:",
                    "with tab_time:", "with tab_archive:"):
        assert section in source


def test_goal_decision_list_excludes_archived_goals():
    source = (ROOT / "services" / "plan_generation_application_service.py").read_text(encoding="utf-8")
    start = source.index("    def list_goals_for_decision(")
    end = source.index("    def continue_after_goal_decision(", start)
    assert "list_active_by_participant(" in source[start:end]
