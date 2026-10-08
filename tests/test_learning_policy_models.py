import pytest

from pydantic import ValidationError

from domain.enums import Importance
from ai.learning_policy_models import (
    LearningPolicyOutput,
    LearningPolicyProposal,
)


def valid_policy():
    return {
        "study_target_id": 1,
        "purpose": "数学の理解を進める",
        "policy_priority": (
            Importance.HIGH
        ),
        "normal_sessions_per_week": 4,
        "normal_minutes": 30,
        "minimum_sessions_per_week": 2,
        "minimum_minutes": 15,
    }


def test_valid_learning_policy_proposal():
    proposal = (
        LearningPolicyProposal(
            **valid_policy()
        )
    )

    assert (
        proposal.study_target_id
        == 1
    )

    assert (
        proposal.policy_priority
        == Importance.HIGH
    )

    assert (
        proposal.normal_minutes
        == 30
    )


def test_minutes_must_be_multiple_of_five():
    payload = valid_policy()

    payload[
        "normal_minutes"
    ] = 13

    with pytest.raises(
        ValidationError
    ):
        LearningPolicyProposal(
            **payload
        )


def test_session_count_cannot_exceed_seven():
    payload = valid_policy()

    payload[
        "normal_sessions_per_week"
    ] = 8

    with pytest.raises(
        ValidationError
    ):
        LearningPolicyProposal(
            **payload
        )


def test_unknown_fields_are_rejected():
    payload = valid_policy()

    payload[
        "unexpected"
    ] = "value"

    with pytest.raises(
        ValidationError
    ):
        LearningPolicyProposal(
            **payload
        )


def test_output_requires_at_least_one_policy():
    with pytest.raises(
        ValidationError
    ):
        LearningPolicyOutput(
            policies=[]
        )


def test_output_accepts_policy_list():
    output = LearningPolicyOutput(
        policies=[
            LearningPolicyProposal(
                **valid_policy()
            )
        ]
    )

    assert len(
        output.policies
    ) == 1