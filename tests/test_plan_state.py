from domain.plan_state import PlanState


def test_plan_state_contains_all_defined_states():
    assert {
        state.value
        for state in PlanState
    } == {
        "CURRENT",
        "OUTDATED_VALID",
        "OUTDATED_INVALID",
        "FUTURE_APPLICABLE",
        "SHADOWED",
        "EXPIRED",
    }


def test_plan_state_does_not_store_active_state():
    values = {
        state.value
        for state in PlanState
    }

    assert "ACTIVE" not in values


def test_plan_state_does_not_store_superseded_state():
    values = {
        state.value
        for state in PlanState
    }

    assert "SUPERSEDED" not in values