from datetime import datetime

import pytest

from domain.plan_state import PlanState
from domain.errors import DomainValidationError
from domain.models import Plan
from domain.time_rules import JST
from planning.plan_resolver import (
    PlanResolver,
)
from planning.plan_validator import (
    PlanValidationIssue,
    PlanValidationResult,
)


def dt(
    day: int,
    hour: int = 0,
    minute: int = 0,
) -> datetime:
    return datetime(
        2026,
        10,
        day,
        hour,
        minute,
        tzinfo=JST,
    )


def make_plan(
    *,
    version: int,
    effective_day: int,
    horizon_day: int,
    source_version: int = 1,
    participant_id: str = "participant-a",
) -> Plan:
    return Plan(
        id=version,
        participant_id=participant_id,
        version_no=version,
        created_at=dt(
            effective_day,
            0,
        ),
        effective_from=dt(
            effective_day,
            0,
        ),
        horizon_end=dt(
            horizon_day,
            0,
        ),
        source_planning_data_version=(
            source_version
        ),
    )


def valid_result() -> PlanValidationResult:
    return PlanValidationResult(
        issues=()
    )


def invalid_result() -> PlanValidationResult:
    return PlanValidationResult(
        issues=(
            PlanValidationIssue(
                code="TEST_INVALID",
                message="invalid",
            ),
        )
    )


def test_resolve_returns_current_highest_version():
    resolver = PlanResolver()

    version_1 = make_plan(
        version=1,
        effective_day=7,
        horizon_day=14,
    )

    version_2 = make_plan(
        version=2,
        effective_day=8,
        horizon_day=15,
    )

    resolved = resolver.resolve(
        participant_id="participant-a",
        plans=[
            version_1,
            version_2,
        ],
        at=dt(
            9,
            12,
        ),
    )

    assert resolved is not None
    assert resolved.version_no == 2


def test_future_plan_does_not_shadow_current_plan_yet():
    resolver = PlanResolver()

    current = make_plan(
        version=1,
        effective_day=7,
        horizon_day=14,
    )

    future = make_plan(
        version=2,
        effective_day=10,
        horizon_day=17,
    )

    resolved = resolver.resolve(
        participant_id="participant-a",
        plans=[
            current,
            future,
        ],
        at=dt(
            9,
            12,
        ),
    )

    assert resolved is not None
    assert resolved.version_no == 1


def test_future_plan_becomes_selected_at_effective_from():
    resolver = PlanResolver()

    version_1 = make_plan(
        version=1,
        effective_day=7,
        horizon_day=14,
    )

    version_2 = make_plan(
        version=2,
        effective_day=10,
        horizon_day=17,
    )

    resolved = resolver.resolve(
        participant_id="participant-a",
        plans=[
            version_1,
            version_2,
        ],
        at=dt(
            10,
            0,
        ),
    )

    assert resolved is not None
    assert resolved.version_no == 2


def test_expired_selected_plan_returns_none():
    resolver = PlanResolver()

    expired = make_plan(
        version=1,
        effective_day=1,
        horizon_day=8,
    )

    resolved = resolver.resolve(
        participant_id="participant-a",
        plans=[
            expired
        ],
        at=dt(
            8,
            0,
        ),
    )

    assert resolved is None


def test_resolver_never_falls_back_to_older_plan():
    resolver = PlanResolver()

    # このテストではno-fallbackルールそのものを
    # 独立して確認するため、
    # older Planを意図的に長いhorizonにしている。
    #
    # Resolverの責務はhorizon構築ではなく、
    # 「最大versionを選んでからexpiry判定」
    # すること。
    older = make_plan(
        version=1,
        effective_day=1,
        horizon_day=20,
    )

    newer = make_plan(
        version=2,
        effective_day=5,
        horizon_day=10,
    )

    resolved = resolver.resolve(
        participant_id="participant-a",
        plans=[
            older,
            newer,
        ],
        at=dt(
            11,
            0,
        ),
    )

    # v2が最大version。
    # v2はexpired。
    #
    # v1がまだ期間内でも
    # v1へfallbackしてはいけない。
    assert resolved is None


def test_no_plan_before_first_effective_from():
    resolver = PlanResolver()

    future = make_plan(
        version=1,
        effective_day=10,
        horizon_day=17,
    )

    resolved = resolver.resolve(
        participant_id="participant-a",
        plans=[
            future
        ],
        at=dt(
            9,
            0,
        ),
    )

    assert resolved is None


def test_other_participant_plan_is_ignored():
    resolver = PlanResolver()

    plan_a = make_plan(
        version=1,
        effective_day=7,
        horizon_day=14,
        participant_id=(
            "participant-a"
        ),
    )

    plan_b = make_plan(
        version=99,
        effective_day=7,
        horizon_day=14,
        participant_id=(
            "participant-b"
        ),
    )

    resolved = resolver.resolve(
        participant_id="participant-a",
        plans=[
            plan_a,
            plan_b,
        ],
        at=dt(
            9,
        ),
    )

    assert resolved is not None
    assert resolved.version_no == 1
    assert (
        resolved.participant_id
        == "participant-a"
    )


def test_current_state():
    resolver = PlanResolver()

    current = make_plan(
        version=1,
        effective_day=7,
        horizon_day=14,
        source_version=5,
    )

    states = resolver.derive_states(
        participant_id="participant-a",
        plans=[
            current
        ],
        at=dt(
            9,
        ),
        current_planning_data_version=5,
        validation_results_by_version={
            1: valid_result()
        },
    )

    assert (
        states[1]
        == PlanState.CURRENT
    )


def test_outdated_valid_state():
    resolver = PlanResolver()

    plan_value = make_plan(
        version=1,
        effective_day=7,
        horizon_day=14,
        source_version=4,
    )

    states = resolver.derive_states(
        participant_id="participant-a",
        plans=[
            plan_value
        ],
        at=dt(
            9,
        ),
        current_planning_data_version=5,
        validation_results_by_version={
            1: valid_result()
        },
    )

    assert (
        states[1]
        == PlanState.OUTDATED_VALID
    )


def test_outdated_invalid_state():
    resolver = PlanResolver()

    plan_value = make_plan(
        version=1,
        effective_day=7,
        horizon_day=14,
        source_version=4,
    )

    states = resolver.derive_states(
        participant_id="participant-a",
        plans=[
            plan_value
        ],
        at=dt(
            9,
        ),
        current_planning_data_version=5,
        validation_results_by_version={
            1: invalid_result()
        },
    )

    assert (
        states[1]
        == PlanState.OUTDATED_INVALID
    )


def test_invalid_selected_plan_fails_closed_even_if_version_matches():
    resolver = PlanResolver()

    plan_value = make_plan(
        version=1,
        effective_day=7,
        horizon_day=14,
        source_version=5,
    )

    states = resolver.derive_states(
        participant_id="participant-a",
        plans=[
            plan_value
        ],
        at=dt(
            9,
        ),
        current_planning_data_version=5,
        validation_results_by_version={
            1: invalid_result()
        },
    )

    # 保存済みPlanは本来validation済みなので
    # このケースは通常起きない。
    #
    # それでもHard violationを検出した場合は
    # CURRENTとして実行せずfail closedする。
    assert (
        states[1]
        == PlanState.OUTDATED_INVALID
    )


def test_future_and_shadowed_states():
    resolver = PlanResolver()

    old = make_plan(
        version=1,
        effective_day=7,
        horizon_day=14,
        source_version=1,
    )

    current = make_plan(
        version=2,
        effective_day=8,
        horizon_day=15,
        source_version=1,
    )

    future = make_plan(
        version=3,
        effective_day=12,
        horizon_day=19,
        source_version=1,
    )

    states = resolver.derive_states(
        participant_id="participant-a",
        plans=[
            old,
            current,
            future,
        ],
        at=dt(
            9,
        ),
        current_planning_data_version=1,
        validation_results_by_version={
            2: valid_result()
        },
    )

    assert (
        states[1]
        == PlanState.SHADOWED
    )

    assert (
        states[2]
        == PlanState.CURRENT
    )

    assert (
        states[3]
        == PlanState.FUTURE_APPLICABLE
    )


def test_selected_expired_plan_is_expired_and_old_plan_stays_shadowed():
    resolver = PlanResolver()

    older = make_plan(
        version=1,
        effective_day=1,
        horizon_day=20,
    )

    newer = make_plan(
        version=2,
        effective_day=5,
        horizon_day=10,
    )

    states = resolver.derive_states(
        participant_id="participant-a",
        plans=[
            older,
            newer,
        ],
        at=dt(
            11,
        ),
        current_planning_data_version=1,
        validation_results_by_version={},
    )

    assert (
        states[1]
        == PlanState.SHADOWED
    )

    assert (
        states[2]
        == PlanState.EXPIRED
    )


def test_duplicate_version_is_rejected():
    resolver = PlanResolver()

    first = make_plan(
        version=1,
        effective_day=7,
        horizon_day=14,
    )

    duplicate = make_plan(
        version=1,
        effective_day=8,
        horizon_day=15,
    )

    with pytest.raises(
        DomainValidationError,
        match=(
            "duplicate Plan version_no"
        ),
    ):
        resolver.resolve(
            participant_id="participant-a",
            plans=[
                first,
                duplicate,
            ],
            at=dt(
                9,
            ),
        )


def test_plan_source_version_cannot_be_newer_than_current_version():
    resolver = PlanResolver()

    plan_value = make_plan(
        version=1,
        effective_day=7,
        horizon_day=14,
        source_version=6,
    )

    with pytest.raises(
        DomainValidationError,
        match=(
            "cannot be newer than current"
        ),
    ):
        resolver.derive_states(
            participant_id="participant-a",
            plans=[
                plan_value
            ],
            at=dt(
                9,
            ),
            current_planning_data_version=5,
            validation_results_by_version={
                1: valid_result()
            },
        )