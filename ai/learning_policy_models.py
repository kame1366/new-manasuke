from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from domain.enums import Importance


class LearningPolicyProposal(
    BaseModel
):
    """
    OpenAI Structured Outputの
    StudyTarget 1件分。

    これはAI transport schemaであり、
    最終Domain Modelではない。
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    study_target_id: int = Field(
        gt=0,
    )

    purpose: str = Field(
        min_length=1,
        max_length=240,
    )

    policy_priority: Importance

    normal_sessions_per_week: int = Field(
        ge=0,
        le=7,
    )

    normal_minutes: int = Field(
        ge=0,
        multiple_of=5,
    )

    minimum_sessions_per_week: int = Field(
        ge=0,
        le=7,
    )

    minimum_minutes: int = Field(
        ge=0,
        multiple_of=5,
    )


class LearningPolicyOutput(
    BaseModel
):
    """
    AI①全体のStructured Output。
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    policies: list[
        LearningPolicyProposal
    ] = Field(
        min_length=1,
    )