from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from ai.errors import (
    PlanningDataChangedError,
)
from db.connection import transaction
from domain.enums import (
    AttemptStage,
    GoalMode,
)
from domain.time_rules import (
    to_db_utc,
)
from planning.attempt_errors import (
    DeadlineSelectionInfeasibleError,
)
from planning.feasibility_analyzer import (
    FeasibilityResult,
    GoalFeasibilityResult,
)
from repositories.ai_interaction_repository import (
    AIInteractionRepository,
)
from repositories.plan_generation_attempt_repository import (
    PlanGenerationAttemptRepository,
)


PHASE_BASELINE_ALL_STRICT = (
    "BASELINE_ALL_STRICT"
)

PHASE_FINAL_SELECTION = (
    "FINAL_SELECTION"
)

DECISION_SOURCE_AUTO_ALL_STRICT = (
    "AUTO_ALL_STRICT"
)

DECISION_SOURCE_USER_CONFIRMED = (
    "USER_CONFIRMED"
)


class PlanGenerationCheckpointRepository:
    def __init__(
        self,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(
            db_path
        )

    def record_baseline(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        result: FeasibilityResult,
        now: datetime,
    ) -> AttemptStage:
        """
        FEASIBILITY checkpoint。

        all STRICT feasibleなら:
            BASELINE snapshot
            + AUTO decisions
            + FINAL snapshot
            + AI_PLANNING

        infeasibleなら:
            BASELINE snapshot
            + AWAITING_GOAL_DECISION
        """
        with transaction(
            self._db_path
        ) as connection:
            attempt = (
                PlanGenerationAttemptRepository
                .assert_in_progress_in_transaction(
                    connection,
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    expected_stage=(
                        AttemptStage
                        .FEASIBILITY
                    ),
                )
            )

            (
                PlanGenerationAttemptRepository
                .assert_source_version_in_transaction(
                    connection,
                    participant_id=(
                        participant_id
                    ),
                    attempt=attempt,
                )
            )

            self._insert_snapshot(
                connection,
                attempt_id=attempt_id,
                phase=(
                    PHASE_BASELINE_ALL_STRICT
                ),
                result=result,
                now=now,
            )

            if result.strict_set_feasible:
                self._insert_goal_decisions(
                    connection,
                    attempt_id=(
                        attempt_id
                    ),
                    goal_results=(
                        result.goal_results
                    ),
                    goal_modes={
                        item.goal_id:
                        GoalMode.STRICT
                        for item
                        in result.goal_results
                    },
                    decision_source=(
                        DECISION_SOURCE_AUTO_ALL_STRICT
                    ),
                    now=now,
                )

                self._insert_snapshot(
                    connection,
                    attempt_id=(
                        attempt_id
                    ),
                    phase=(
                        PHASE_FINAL_SELECTION
                    ),
                    result=result,
                    now=now,
                )

                next_stage = (
                    AttemptStage
                    .AI_PLANNING
                )

            else:
                next_stage = (
                    AttemptStage
                    .AWAITING_GOAL_DECISION
                )

            (
                PlanGenerationAttemptRepository
                .advance_stage_in_transaction(
                    connection,
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    next_stage=(
                        next_stage
                    ),
                    now=now,
                )
            )

        return next_stage

    def record_user_selection(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        baseline_goal_results: Sequence[
            GoalFeasibilityResult
        ],
        goal_modes: Mapping[
            int,
            GoalMode,
        ],
        final_result: FeasibilityResult,
        now: datetime,
    ) -> None:
        """
        AWAITING_GOAL_DECISION
        -> AI_PLANNING
        """
        if not final_result.strict_set_feasible:
            raise (
                DeadlineSelectionInfeasibleError(
                    "selected STRICT Goal set "
                    "is still infeasible"
                )
            )

        expected_goal_ids = {
            item.goal_id
            for item
            in baseline_goal_results
        }

        actual_goal_ids = set(
            goal_modes
        )

        if (
            expected_goal_ids
            != actual_goal_ids
        ):
            raise ValueError(
                "goal_modes must contain "
                "exactly all Goal IDs"
            )

        with transaction(
            self._db_path
        ) as connection:
            attempt = (
                PlanGenerationAttemptRepository
                .assert_in_progress_in_transaction(
                    connection,
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    expected_stage=(
                        AttemptStage
                        .AWAITING_GOAL_DECISION
                    ),
                )
            )

            (
                PlanGenerationAttemptRepository
                .assert_source_version_in_transaction(
                    connection,
                    participant_id=(
                        participant_id
                    ),
                    attempt=attempt,
                )
            )

            self._insert_goal_decisions(
                connection,
                attempt_id=attempt_id,
                goal_results=(
                    baseline_goal_results
                ),
                goal_modes=goal_modes,
                decision_source=(
                    DECISION_SOURCE_USER_CONFIRMED
                ),
                now=now,
            )

            self._insert_snapshot(
                connection,
                attempt_id=attempt_id,
                phase=(
                    PHASE_FINAL_SELECTION
                ),
                result=final_result,
                now=now,
            )

            (
                PlanGenerationAttemptRepository
                .advance_stage_in_transaction(
                    connection,
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    next_stage=(
                        AttemptStage
                        .AI_PLANNING
                    ),
                    now=now,
                )
            )

    def record_planning_ai_success(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        interaction_id: int,
        structured_output_json: str,
        now: datetime,
    ) -> None:
        """
        validated AI② output
        +
        AI_PLANNING -> SCHEDULING

        を同じTransactionで行う。
        """
        with transaction(
            self._db_path
        ) as connection:
            attempt = (
                PlanGenerationAttemptRepository
                .assert_in_progress_in_transaction(
                    connection,
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    expected_stage=(
                        AttemptStage
                        .AI_PLANNING
                    ),
                )
            )

            (
                PlanGenerationAttemptRepository
                .assert_source_version_in_transaction(
                    connection,
                    participant_id=(
                        participant_id
                    ),
                    attempt=attempt,
                )
            )

            (
                AIInteractionRepository
                .mark_succeeded_for_attempt_in_transaction(
                    connection,
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    interaction_id=(
                        interaction_id
                    ),
                    structured_output_json=(
                        structured_output_json
                    ),
                )
            )

            (
                PlanGenerationAttemptRepository
                .advance_stage_in_transaction(
                    connection,
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    next_stage=(
                        AttemptStage
                        .SCHEDULING
                    ),
                    now=now,
                )
            )

    @staticmethod
    def _insert_snapshot(
        connection: sqlite3.Connection,
        *,
        attempt_id: int,
        phase: str,
        result: FeasibilityResult,
        now: datetime,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO plan_feasibility_snapshots (
                attempt_id,
                phase,
                total_projected_capacity_minutes,
                normalized_required_minutes,
                aggregate_shortage_minutes,
                strict_set_feasible,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                phase,
                (
                    result
                    .total_projected_capacity_minutes
                ),
                (
                    result
                    .normalized_required_minutes
                ),
                (
                    result
                    .aggregate_shortage_minutes
                ),
                (
                    1
                    if result.strict_set_feasible
                    else 0
                ),
                to_db_utc(
                    now
                ),
            ),
        )

        snapshot_id = (
            cursor.lastrowid
        )

        if snapshot_id is None:
            raise RuntimeError(
                "failed to insert "
                "FeasibilitySnapshot"
            )

        for deadline in (
            result.deadline_snapshots
        ):
            connection.execute(
                """
                INSERT INTO
                    plan_feasibility_deadline_snapshots (
                        snapshot_id,
                        deadline_at,
                        cumulative_required_minutes,
                        cumulative_available_minutes,
                        cumulative_shortage_minutes,
                        feasible
                    )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    to_db_utc(
                        deadline
                        .deadline_at
                    ),
                    (
                        deadline
                        .cumulative_required_minutes
                    ),
                    (
                        deadline
                        .cumulative_available_minutes
                    ),
                    (
                        deadline
                        .cumulative_shortage_minutes
                    ),
                    (
                        1
                        if deadline.feasible
                        else 0
                    ),
                ),
            )

        return int(
            snapshot_id
        )

    @staticmethod
    def _insert_goal_decisions(
        connection: sqlite3.Connection,
        *,
        attempt_id: int,
        goal_results: Sequence[
            GoalFeasibilityResult
        ],
        goal_modes: Mapping[
            int,
            GoalMode,
        ],
        decision_source: str,
        now: datetime,
    ) -> None:
        for goal_result in (
            goal_results
        ):
            mode = goal_modes[
                goal_result.goal_id
            ]

            connection.execute(
                """
                INSERT INTO plan_goal_decisions (
                    attempt_id,
                    goal_id,
                    mode,
                    decision_source,
                    individually_feasible,
                    estimated_required_minutes,
                    individual_shortage_minutes,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    goal_result.goal_id,
                    mode.value,
                    decision_source,
                    (
                        1
                        if (
                            goal_result
                            .individually_feasible
                        )
                        else 0
                    ),
                    (
                        goal_result
                        .estimated_required_minutes
                    ),
                    (
                        goal_result
                        .individual_shortage_minutes
                    ),
                    to_db_utc(
                        now
                    ),
                ),
            )