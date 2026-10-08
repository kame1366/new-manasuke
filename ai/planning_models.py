from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class PlanningAllocation(
    BaseModel
):
    """
    AI②が返すStudyTarget単位の
    Soft allocation。
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    study_target_id: int = Field(
        gt=0,
    )

    optional_extra_minutes: int = Field(
        ge=0,
        multiple_of=5,
    )

    planning_priority_rank: int = Field(
        ge=1,
    )

    reason: str = Field(
        min_length=1,
        max_length=240,
    )


class PlanningOutput(
    BaseModel
):
    model_config = ConfigDict(
        extra="forbid",
    )

    allocations: list[
        PlanningAllocation
    ] = Field(
        default_factory=list,
    )