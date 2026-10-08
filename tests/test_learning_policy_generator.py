import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from ai.errors import (
    AIOutputInvalidError,
)
from ai.learning_policy_generator import (
    LEARNING_POLICY_INSTRUCTIONS,
    LearningPolicyGenerator,
)
from ai.learning_policy_models import (
    LearningPolicyOutput,
    LearningPolicyProposal,
)
from domain.enums import (
    Importance,
    StudyTargetKind,
)
from domain.models import (
    AvailableTime,
    StudyTarget,
)
from domain.time_rules import JST


class FakeResponses:
    def __init__(
        self,
        output_parsed,
    ):
        self.output_parsed = (
            output_parsed
        )

        self.last_kwargs = None

    def parse(
        self,
        **kwargs,
    ):
        self.last_kwargs = kwargs

        return SimpleNamespace(
            output_parsed=(
                self.output_parsed
            ),
            status="completed",
        )


class FakeClient:
    def __init__(
        self,
        output_parsed,
    ):
        self.responses = FakeResponses(
            output_parsed
        )


def target() -> StudyTarget:
    return StudyTarget(
        id=1,
        participant_id="participant-a",
        kind=StudyTargetKind.THEME,
        title="英作文",
    )


def output() -> LearningPolicyOutput:
    return LearningPolicyOutput(
        policies=[
            LearningPolicyProposal(
                study_target_id=1,
                purpose=(
                    "英作文の練習を続ける"
                ),
                policy_priority=(
                    Importance.HIGH
                ),
                normal_sessions_per_week=4,
                normal_minutes=30,
                minimum_sessions_per_week=2,
                minimum_minutes=15,
            )
        ]
    )


def test_generator_uses_responses_parse():
    fake_client = FakeClient(
        output()
    )

    generator = LearningPolicyGenerator(
        client=fake_client,
        model_name="test-model",
    )

    result = generator.generate(
        study_targets=[
            target()
        ],
        goals=[],
        available_times=[
            AvailableTime(
                weekday=0,
                start_minute_of_day=1080,
                end_minute_of_day=1200,
            )
        ],
        reference_time=datetime(
            2026,
            10,
            10,
            12,
            0,
            tzinfo=JST,
        ),
    )

    assert result == output()

    kwargs = (
        fake_client
        .responses
        .last_kwargs
    )

    assert kwargs is not None

    assert (
        kwargs["model"]
        == "test-model"
    )

    assert (
        kwargs["text_format"]
        is LearningPolicyOutput
    )

    assert (
        kwargs["store"]
        is False
    )


def test_generator_input_contains_source_data():
    fake_client = FakeClient(
        output()
    )

    generator = LearningPolicyGenerator(
        client=fake_client,
        model_name="test-model",
    )

    generator.generate(
        study_targets=[
            target()
        ],
        goals=[],
        available_times=[
            AvailableTime(
                weekday=0,
                start_minute_of_day=1080,
                end_minute_of_day=1200,
            )
        ],
        reference_time=datetime(
            2026,
            10,
            10,
            12,
            0,
            tzinfo=JST,
        ),
    )

    kwargs = (
        fake_client
        .responses
        .last_kwargs
    )

    payload = json.loads(
        kwargs["input"]
    )

    assert (
        payload[
            "study_targets"
        ][0]["id"]
        == 1
    )

    assert (
        payload[
            "study_targets"
        ][0]["title"]
        == "英作文"
    )

    assert (
        payload[
            "weekly_available_minutes"
        ]
        == 120
    )


def test_generator_instructions_protect_source_data():
    assert (
        "Never invent"
        in LEARNING_POLICY_INSTRUCTIONS
    )

    assert (
        "untrusted data"
        in LEARNING_POLICY_INSTRUCTIONS
    )

    assert (
        "exact dates or clock times"
        in LEARNING_POLICY_INSTRUCTIONS
    )


def test_generator_rejects_missing_parsed_output():
    fake_client = FakeClient(
        None
    )

    generator = LearningPolicyGenerator(
        client=fake_client,
        model_name="test-model",
    )

    with pytest.raises(
        AIOutputInvalidError,
        match=(
            "did not contain "
            "parsed output"
        ),
    ):
        generator.generate(
            study_targets=[
                target()
            ],
            goals=[],
            available_times=[],
            reference_time=datetime(
                2026,
                10,
                10,
                12,
                0,
                tzinfo=JST,
            ),
        )


def test_generator_rejects_empty_targets():
    fake_client = FakeClient(
        output()
    )

    generator = LearningPolicyGenerator(
        client=fake_client,
        model_name="test-model",
    )

    with pytest.raises(
        AIOutputInvalidError,
        match="at least one StudyTarget",
    ):
        generator.generate(
            study_targets=[],
            goals=[],
            available_times=[],
            reference_time=datetime(
                2026,
                10,
                10,
                12,
                0,
                tzinfo=JST,
            ),
        )