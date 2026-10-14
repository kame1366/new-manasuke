# services/plan_generation_pipeline_service.py

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path

from openai import OpenAI

from ai.errors import (
    AIGenerationError,
    AIOutputInvalidError,
    PlanningDataChangedError,
)
from ai.planning_generator import PlanningGenerator
from ai.planning_models import (
    PlanningAllocation,
    PlanningOutput,
)
from ai.planning_output_validator import (
    PlanningOutputValidator,
)
from config import get_settings
from domain.enums import (
    AttemptStage,
    GoalMode,
    PlanOperationType,
    StudyTargetKind,
)
from domain.errors import DomainValidationError
from domain.models import (
    AvailableTime,
    BusyEvent,
    ExtraAvailableTime,
    Goal,
    LearningPolicy,
    Plan,
    PlanGenerationAttempt,
    PlanItem,
    StudyTarget,
)
from domain.time_rules import (
    JST,
    ensure_aware,
    to_jst,
)
from planning.attempt_errors import (
    AttemptNotActiveError,
    AttemptStageError,
    DeadlineSelectionInfeasibleError,
    PlanValidationFailedError,
)
from planning.feasibility_analyzer import (
    DeadlineFeasibilityAnalyzer,
    FeasibilityResult,
    MinimumReservation,
)
from planning.free_slot_builder import (
    FreeSlot,
    FreeSlotBuilder,
)
from planning.greedy_scheduler import (
    GreedyScheduler,
    ScheduleResult,
)
from planning.optional_allocation import (
    OptionalAllocationContextBuilder,
    PlanningAIContext,
)
from planning.optional_work_chunk_builder import (
    OptionalWorkChunkBuilder,
)
from planning.placement_engine import (
    PlacementEngine,
    ScheduledChunk,
)
from planning.plan_validator import (
    MinimumPolicyRequirement,
)
from planning.replan_rules import (
    CarryForwardPlanItem,
    ReplanRules,
    UserModifiedConflictError,
)
from planning.work_chunk_builder import (
    WorkChunk,
    WorkChunkBuilder,
    scheduled_duration_minutes,
)
from planning.work_segment_builder import (
    WorkSegment,
    WorkSegmentBuilder,
)
from repositories.ai_interaction_repository import (
    AIInteractionRepository,
)
from repositories.availability_repository import (
    AvailabilityRepository,
)
from repositories.goal_repository import GoalRepository
from repositories.learning_policy_repository import (
    LearningPolicyRepository,
)
from repositories.plan_generation_attempt_repository import (
    PlanGenerationAttemptRepository,
)
from repositories.plan_generation_checkpoint_repository import (
    PlanGenerationCheckpointRepository,
)
from repositories.plan_repository import PlanRepository
from repositories.study_result_repository import (
    StudyResultRepository,
)
from repositories.study_target_repository import (
    StudyTargetRepository,
)
from services.plan_generation_attempt_service import (
    PlanGenerationAttemptService,
)
from services.planning_ai_service import (
    PlanningAIService,
)
from services.study_result_service import (
    StudyResultService,
)


ERROR_MINIMUM_POLICY_INFEASIBLE = (
    "MINIMUM_POLICY_INFEASIBLE"
)

ERROR_SCHEDULING_FAILED = (
    "SCHEDULING_FAILED"
)

ERROR_SOURCE_DATA_INCOMPLETE = (
    "SOURCE_DATA_INCOMPLETE"
)

ERROR_USER_MODIFIED_CONFLICT = (
    "USER_MODIFIED_CONFLICT"
)

ERROR_AI_FAILED = (
    "AI_FAILED"
)

ERROR_AI_OUTPUT_INVALID = (
    "AI_OUTPUT_INVALID"
)

ERROR_SCHEDULING_RETRY = (
    "SCHEDULING_RETRY"
)


class MinimumPolicyInfeasibleError(
    RuntimeError
):
    pass


class SchedulingFailedError(
    RuntimeError
):
    pass


class SourceDataIncompleteError(
    RuntimeError
):
    pass


@dataclass(
    frozen=True,
    slots=True,
)
class PlanGenerationPipelineResult:
    """
    generate() の結果。

    全STRICTが不可能な場合はPlanを生成せず、
    AWAITING_GOAL_DECISIONを返す。
    """

    attempt_id: int
    stage: AttemptStage

    plan: Plan | None = None

    feasibility: (
        FeasibilityResult | None
    ) = None

    @property
    def awaiting_goal_decision(
        self,
    ) -> bool:
        return (
            self.stage
            == AttemptStage
            .AWAITING_GOAL_DECISION
        )

    @property
    def succeeded(
        self,
    ) -> bool:
        return self.plan is not None


@dataclass(
    frozen=True,
    slots=True,
)
class _SourceData:
    study_targets: tuple[
        StudyTarget,
        ...,
    ]

    goals: tuple[
        Goal,
        ...,
    ]

    learning_policies: tuple[
        LearningPolicy,
        ...,
    ]

    weekly_available_times: tuple[
        AvailableTime,
        ...,
    ]

    busy_events: tuple[
        BusyEvent,
        ...,
    ]

    extra_available_times: tuple[
        ExtraAvailableTime,
        ...,
    ]

    theme_completed_minutes_by_target: Mapping[
        int,
        int,
    ]


@dataclass(
    frozen=True,
    slots=True,
)
class _PreparedContext:
    source: _SourceData

    effective_from: datetime
    horizon_end: datetime

    carried_items: tuple[
        CarryForwardPlanItem,
        ...,
    ]

    fixed_plan_items: tuple[
        PlanItem,
        ...,
    ]

    free_slots: tuple[
        FreeSlot,
        ...,
    ]

    work_segments: tuple[
        WorkSegment,
        ...,
    ]


class PlanGenerationPipelineService:
    """
    Manasuke Plan生成pipelineのApplication Service。

    UIから呼び出すPlan生成処理は、
    原則このServiceへ集約する。

    Pipeline:

    1. Attempt start
    2. Source Data load
    3. carry-forward USER_MODIFIED
    4. FreeSlot
    5. WorkSegment
    6. baseline feasibility
    7. STRICT/BEST_EFFORT decision
    8. mandatory WorkChunk
    9. mandatory placement
    10. minimum policy preflight
    11. optional allocation context
    12. AI②
    13. optional WorkChunk
    14. Scheduler
    15. PlanValidator
    16. atomic final save
    """

    def __init__(
        self,
        *,
        db_path: str | Path,
        stale_after: timedelta = timedelta(
            minutes=30
        ),
        planning_generator: (
            PlanningGenerator | None
        ) = None,
        planning_ai_service: (
            PlanningAIService | None
        ) = None,
        planning_output_validator: (
            PlanningOutputValidator | None
        ) = None,
    ) -> None:
        if (
            stale_after.total_seconds()
            <= 0
        ):
            raise ValueError(
                "stale_after must be positive"
            )

        self._db_path = Path(
            db_path
        )

        self._stale_after = (
            stale_after
        )

        # ==========================================
        # Repositories
        # ==========================================

        self._study_target_repository = (
            StudyTargetRepository(
                self._db_path
            )
        )

        self._goal_repository = (
            GoalRepository(
                self._db_path
            )
        )

        self._learning_policy_repository = (
            LearningPolicyRepository(
                self._db_path
            )
        )

        self._availability_repository = (
            AvailabilityRepository(
                self._db_path
            )
        )

        self._plan_repository = (
            PlanRepository(
                self._db_path
            )
        )

        self._study_result_repository = (
            StudyResultRepository(
                self._db_path
            )
        )

        self._attempt_repository = (
            PlanGenerationAttemptRepository(
                self._db_path
            )
        )

        self._checkpoint_repository = (
            PlanGenerationCheckpointRepository(
                self._db_path
            )
        )

        self._ai_interaction_repository = (
            AIInteractionRepository(
                self._db_path
            )
        )

        # ==========================================
        # Services
        # ==========================================

        self._attempt_service = (
            PlanGenerationAttemptService(
                db_path=self._db_path
            )
        )

        self._study_result_service = (
            StudyResultService(
                db_path=self._db_path
            )
        )

        # ==========================================
        # Pure planning components
        # ==========================================

        self._replan_rules = (
            ReplanRules()
        )

        self._free_slot_builder = (
            FreeSlotBuilder()
        )

        self._work_segment_builder = (
            WorkSegmentBuilder()
        )

        self._feasibility_analyzer = (
            DeadlineFeasibilityAnalyzer(
                free_slot_builder=(
                    self
                    ._free_slot_builder
                )
            )
        )

        self._work_chunk_builder = (
            WorkChunkBuilder()
        )

        self._placement_engine = (
            PlacementEngine()
        )

        self._scheduler = (
            GreedyScheduler()
        )

        self._optional_context_builder = (
            OptionalAllocationContextBuilder()
        )

        self._optional_work_chunk_builder = (
            OptionalWorkChunkBuilder()
        )

        # ==========================================
        # AI②
        # ==========================================

        self._planning_output_validator = (
            planning_output_validator
            or PlanningOutputValidator()
        )

        if planning_generator is None:
            settings = (
                get_settings()
            )

            client = OpenAI(
                api_key=(
                    settings
                    .openai_api_key
                ),
                max_retries=(
                    settings
                    .openai_max_retries
                ),
                timeout=(
                    settings
                    .openai_timeout_seconds
                ),
            )

            planning_generator = (
                PlanningGenerator(
                    client=client,
                    model_name=(
                        settings
                        .openai_model
                    ),
                )
            )

        self._planning_generator = (
            planning_generator
        )

        self._planning_ai_service = (
            planning_ai_service
            or PlanningAIService(
                generator=(
                    self
                    ._planning_generator
                ),
                validator=(
                    self
                    ._planning_output_validator
                ),
            )
        )

    # =====================================================
    # Public API
    # =====================================================

    def generate(
        self,
        *,
        participant_id: str,
        operation_type: PlanOperationType,
        now: datetime,
    ) -> PlanGenerationPipelineResult:
        """
        Plan生成を開始する。

        全GoalをSTRICTにして可能なら、
        そのまま最後まで生成する。

        不可能なら、
        AWAITING_GOAL_DECISIONで止める。
        """

        ensure_aware(
            now
        )

        participant_id = (
            participant_id.strip()
        )

        if not participant_id:
            raise DomainValidationError(
                "participant_id "
                "must not be empty"
            )

        # ------------------------------------------
        # replan前のMaterial UNRECORDED block
        # ------------------------------------------

        if operation_type in {
            PlanOperationType.REPLAN_NOW,
            PlanOperationType
            .REPLAN_TOMORROW,
        }:
            (
                self
                ._study_result_service
                .assert_replan_ready(
                    participant_id=(
                        participant_id
                    ),
                    now=now,
                )
            )

        # LearningPolicyはAttempt開始前に
        # 完成している必要がある。
        #
        # AI①を呼ぶなら、Attempt開始前。
        self._assert_learning_policies_complete(
            participant_id
        )

        effective_from = (
            self._replan_rules
            .effective_from(
                operation_type=(
                    operation_type
                ),
                now=now,
            )
        )

        attempt = (
            self
            ._attempt_service
            .start(
                participant_id=(
                    participant_id
                ),
                operation_type=(
                    operation_type
                ),
                now=now,
                stale_after=(
                    self._stale_after
                ),
            )
        )

        try:
            prepared = (
                self._prepare_context(
                    participant_id=(
                        participant_id
                    ),
                    operation_type=(
                        operation_type
                    ),
                    effective_from=(
                        effective_from
                    ),
                    reference_time=now,
                )
            )

            all_goal_ids = {
                goal.id
                for goal
                in prepared.source.goals
            }

            # --------------------------------------
            # Baseline:
            # 全Goal STRICT
            # --------------------------------------

            baseline = (
                self._analyze_feasibility(
                    prepared=prepared,
                    strict_goal_ids=(
                        all_goal_ids
                    ),
                )
            )

            next_stage = (
                self
                ._attempt_service
                .record_baseline(
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt.id
                    ),
                    result=baseline,
                    now=now,
                )
            )

            # --------------------------------------
            # ユーザー判断が必要
            # --------------------------------------

            if (
                next_stage
                == AttemptStage
                .AWAITING_GOAL_DECISION
            ):
                return (
                    PlanGenerationPipelineResult(
                        attempt_id=(
                            attempt.id
                        ),
                        stage=(
                            AttemptStage
                            .AWAITING_GOAL_DECISION
                        ),
                        feasibility=(
                            baseline
                        ),
                    )
                )

            # --------------------------------------
            # all STRICT
            # --------------------------------------

            return (
                self
                ._run_after_goal_decision(
                    participant_id=(
                        participant_id
                    ),
                    attempt=attempt,
                    prepared=prepared,
                    strict_goal_ids=(
                        all_goal_ids
                    ),
                    best_effort_goal_ids=set(),
                    final_feasibility=(
                        baseline
                    ),
                    now=now,
                )
            )

        except Exception as exc:
            self._safe_fail_attempt(
                participant_id=(
                    participant_id
                ),
                attempt_id=(
                    attempt.id
                ),
                error_type=(
                    self._error_type(
                        exc
                    )
                ),
                now=now,
            )

            raise

    def continue_after_goal_decision(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        goal_modes: Mapping[
            int,
            GoalMode,
        ],
        now: datetime,
    ) -> PlanGenerationPipelineResult:
        """
        AWAITING_GOAL_DECISIONから再開する。

        goal_modes例:

        {
            1: GoalMode.STRICT,
            2: GoalMode.BEST_EFFORT,
        }
        """

        ensure_aware(
            now
        )

        attempt = (
            self
            ._attempt_repository
            .get_by_id(
                participant_id,
                attempt_id,
            )
        )

        if attempt is None:
            raise AttemptNotActiveError(
                "Attempt not found"
            )

        if (
            attempt.stage
            != AttemptStage
            .AWAITING_GOAL_DECISION
        ):
            raise AttemptStageError(
                "continue_after_goal_decision "
                "requires "
                "AWAITING_GOAL_DECISION"
            )

        # REPLAN_NOWのeffective_fromを
        # ユーザー回答時刻から再計算すると
        # 計画開始時刻がズレる。
        #
        # Attempt.started_atを基準にする。
        effective_from = (
            self._replan_rules
            .effective_from(
                operation_type=(
                    attempt.operation_type
                ),
                now=(
                    attempt.started_at
                ),
            )
        )

        prepared = (
            self._prepare_context(
                participant_id=(
                    participant_id
                ),
                operation_type=(
                    attempt.operation_type
                ),
                effective_from=(
                    effective_from
                ),
                reference_time=now,
            )
        )

        expected_goal_ids = {
            goal.id
            for goal
            in prepared.source.goals
        }

        actual_goal_ids = set(
            goal_modes
        )

        if (
            expected_goal_ids
            != actual_goal_ids
        ):
            raise DomainValidationError(
                "goal_modes must contain "
                "exactly all Goal IDs"
            )

        strict_goal_ids = {
            goal_id
            for goal_id, mode
            in goal_modes.items()
            if mode == GoalMode.STRICT
        }

        best_effort_goal_ids = (
            expected_goal_ids
            - strict_goal_ids
        )

        # baselineを再計算。
        # Source Dataが変わっていれば
        # checkpoint時にversion checkで止まる。
        baseline = (
            self._analyze_feasibility(
                prepared=prepared,
                strict_goal_ids=(
                    expected_goal_ids
                ),
            )
        )

        final_feasibility = (
            self._analyze_feasibility(
                prepared=prepared,
                strict_goal_ids=(
                    strict_goal_ids
                ),
            )
        )

        if not (
            final_feasibility
            .strict_set_feasible
        ):
            # 選び直せるよう、
            # AttemptをFAILEDにしない。
            raise (
                DeadlineSelectionInfeasibleError(
                    "selected STRICT Goal set "
                    "is still infeasible"
                )
            )

        try:
            (
                self
                ._attempt_service
                .record_user_selection(
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    baseline_goal_results=(
                        baseline.goal_results
                    ),
                    goal_modes=(
                        goal_modes
                    ),
                    final_result=(
                        final_feasibility
                    ),
                    now=now,
                )
            )

            return (
                self
                ._run_after_goal_decision(
                    participant_id=(
                        participant_id
                    ),
                    attempt=attempt,
                    prepared=prepared,
                    strict_goal_ids=(
                        strict_goal_ids
                    ),
                    best_effort_goal_ids=(
                        best_effort_goal_ids
                    ),
                    final_feasibility=(
                        final_feasibility
                    ),
                    now=now,
                )
            )

        except (
            DeadlineSelectionInfeasibleError
        ):
            raise

        except Exception as exc:
            self._safe_fail_attempt(
                participant_id=(
                    participant_id
                ),
                attempt_id=(
                    attempt_id
                ),
                error_type=(
                    self._error_type(
                        exc
                    )
                ),
                now=now,
            )

            raise

    # =====================================================
    # Main pipeline after Goal decision
    # =====================================================

    def _run_after_goal_decision(
        self,
        *,
        participant_id: str,
        attempt: PlanGenerationAttempt,
        prepared: _PreparedContext,
        strict_goal_ids: set[int],
        best_effort_goal_ids: set[int],
        final_feasibility: FeasibilityResult,
        now: datetime,
    ) -> PlanGenerationPipelineResult:

        policies_by_target = {
            policy.study_target_id:
            policy

            for policy
            in prepared
            .source
            .learning_policies
        }

        preferred_chunk_minutes = {
            target_id:
            policy.normal_minutes

            for target_id, policy
            in policies_by_target.items()
        }

        # ------------------------------------------
        # carried USER_MODIFIEDを
        # WorkChunk側のreserved workとして表現
        # ------------------------------------------

        reserved_chunks = (
            self
            ._reserved_chunks_from_carry_forward(
                carried_items=(
                    prepared.carried_items
                ),
                study_targets=(
                    prepared
                    .source
                    .study_targets
                ),
                theme_completed_minutes_by_target=(
                    prepared
                    .source
                    .theme_completed_minutes_by_target
                ),
            )
        )

        # ------------------------------------------
        # STRICT deadline mandatory work
        # ------------------------------------------

        mandatory_chunks = (
            self
            ._work_chunk_builder
            .build_mandatory_deadline_chunks(
                study_targets=(
                    prepared
                    .source
                    .study_targets
                ),
                goals=(
                    prepared
                    .source
                    .goals
                ),
                work_segments=(
                    prepared
                    .work_segments
                ),
                strict_goal_ids=(
                    strict_goal_ids
                ),
                preferred_chunk_minutes_by_target=(
                    preferred_chunk_minutes
                ),
                not_before=(
                    prepared
                    .effective_from
                ),
            )
        )

        # reserved USER_MODIFIEDと
        # duplicateしないように除去。
        mandatory_chunks = (
            self
            ._subtract_reserved_material_work(
                chunks=(
                    mandatory_chunks
                ),
                carried_items=(
                    prepared.carried_items
                ),
                study_targets=(
                    prepared
                    .source
                    .study_targets
                ),
            )
        )

        # Material precedence barrier。
        mandatory_chunks = (
            self
            ._apply_reserved_precedence(
                chunks=(
                    mandatory_chunks
                ),
                carried_items=(
                    prepared.carried_items
                ),
            )
        )

        # ------------------------------------------
        # Mandatory Placement preflight
        # ------------------------------------------

        (
            mandatory_chunks,
            mandatory_schedule,
        ) = (
            self
            ._schedule_mandatory_with_repair(
                chunks=(
                    mandatory_chunks
                ),
                free_slots=(
                    prepared.free_slots
                ),
                study_targets=(
                    prepared
                    .source
                    .study_targets
                ),
            )
        )

        if not mandatory_schedule.success:
            diagnostic = (
                self
                ._build_mandatory_failure_diagnostic(
                    chunks=(
                        mandatory_chunks
                    ),
                    free_slots=(
                        prepared.free_slots
                    ),
                    effective_from=(
                        prepared.effective_from
                    ),
                    horizon_end=(
                        prepared.horizon_end
                    ),
                )
            )

            raise SchedulingFailedError(
                diagnostic
            )

        # ------------------------------------------
        # LearningPolicy minimum
        # ------------------------------------------

        minimum_requirements = (
            self
            ._build_minimum_requirements(
                learning_policies=(
                    prepared
                    .source
                    .learning_policies
                ),
                free_slots=(
                    prepared.free_slots
                ),
                carried_items=(
                    prepared.carried_items
                ),
            )
        )

        (
            minimum_chunks,
            minimum_placements,
            remaining_slots,
        ) = (
            self
            ._place_minimum_policy_chunks(
                source=(
                    prepared.source
                ),
                strict_goal_ids=(
                    strict_goal_ids
                ),
                work_segments=(
                    prepared.work_segments
                ),
                carried_items=(
                    prepared.carried_items
                ),
                reserved_chunks=(
                    reserved_chunks
                ),
                existing_mandatory_chunks=(
                    tuple(
                        mandatory_chunks
                    )
                ),
                existing_placements=(
                    mandatory_schedule
                    .placements
                ),
                free_slots=(
                    mandatory_schedule
                    .remaining_slots
                ),
                minimum_requirements=(
                    minimum_requirements
                ),
                effective_from=(
                    prepared
                    .effective_from
                ),
            )
        )

        all_mandatory_chunks = (
            tuple(
                reserved_chunks
            )
            + tuple(
                mandatory_chunks
            )
            + tuple(
                minimum_chunks
            )
        )

        # ------------------------------------------
        # AI②前 Soft allocation context
        # ------------------------------------------

        optional_context = (
            self
            ._optional_context_builder
            .build(
                study_targets=(
                    prepared
                    .source
                    .study_targets
                ),
                goals=(
                    prepared
                    .source
                    .goals
                ),
                learning_policies=(
                    prepared
                    .source
                    .learning_policies
                ),
                work_segments=(
                    prepared
                    .work_segments
                ),
                strict_goal_ids=(
                    strict_goal_ids
                ),
                best_effort_goal_ids=(
                    best_effort_goal_ids
                ),
                mandatory_chunks=(
                    all_mandatory_chunks
                ),
                remaining_free_slots=(
                    remaining_slots
                ),
                theme_completed_minutes_by_target=(
                    prepared
                    .source
                    .theme_completed_minutes_by_target
                ),
            )
        )

        # ------------------------------------------
        # AI② + optional scheduling
        # ------------------------------------------

        optional_placements = (
            self
            ._generate_and_place_optional_work(
                participant_id=(
                    participant_id
                ),
                attempt_id=(
                    attempt.id
                ),
                context=(
                    optional_context
                ),
                source=(
                    prepared.source
                ),
                work_segments=(
                    prepared
                    .work_segments
                ),
                strict_goal_ids=(
                    strict_goal_ids
                ),
                best_effort_goal_ids=(
                    best_effort_goal_ids
                ),
                mandatory_chunks=(
                    all_mandatory_chunks
                ),
                carried_items=(
                    prepared.carried_items
                ),
                free_slots=(
                    remaining_slots
                ),
                effective_from=(
                    prepared
                    .effective_from
                ),
                now=now,
            )
        )

        # ------------------------------------------
        # Final schedule
        # ------------------------------------------

        scheduled_chunks = tuple(
            sorted(
                (
                    tuple(
                        mandatory_schedule
                        .placements
                    )
                    + tuple(
                        minimum_placements
                    )
                    + tuple(
                        optional_placements
                    )
                ),
                key=lambda placement: (
                    placement.start_at,
                    placement.end_at,
                    placement
                    .chunk
                    .chunk_id,
                ),
            )
        )

        # ------------------------------------------
        # PlanValidator + atomic save
        # ------------------------------------------

        plan = (
            self
            ._attempt_service
            .finalize(
                participant_id=(
                    participant_id
                ),
                attempt_id=(
                    attempt.id
                ),
                effective_from=(
                    prepared
                    .effective_from
                ),
                scheduled_chunks=(
                    scheduled_chunks
                ),
                study_targets=(
                    prepared
                    .source
                    .study_targets
                ),
                goals=(
                    prepared
                    .source
                    .goals
                ),
                strict_goal_ids=(
                    strict_goal_ids
                ),
                weekly_available_times=(
                    prepared
                    .source
                    .weekly_available_times
                ),
                extra_available_times=(
                    prepared
                    .source
                    .extra_available_times
                ),
                busy_events=(
                    prepared
                    .source
                    .busy_events
                ),
                carried_items=(
                    prepared
                    .carried_items
                ),
                minimum_requirements=(
                    minimum_requirements
                ),
                theme_completed_minutes_by_target=(
                    prepared
                    .source
                    .theme_completed_minutes_by_target
                ),
                now=now,
            )
        )

        return (
            PlanGenerationPipelineResult(
                attempt_id=(
                    attempt.id
                ),
                stage=(
                    AttemptStage.SCHEDULING
                ),
                plan=plan,
                feasibility=(
                    final_feasibility
                ),
            )
        )

    # =====================================================
    # Context
    # =====================================================

    def _prepare_context(
        self,
        *,
        participant_id: str,
        operation_type: PlanOperationType,
        effective_from: datetime,
        reference_time: datetime,
    ) -> _PreparedContext:

        source = (
            self._load_source_data(
                participant_id
            )
        )

        horizon_end = (
            self._horizon_end(
                effective_from
            )
        )

        carried_items = (
            self._collect_carry_forward(
                participant_id=(
                    participant_id
                ),
                operation_type=(
                    operation_type
                ),
                source=source,
                reference_time=(
                    reference_time
                ),
                effective_from=(
                    effective_from
                ),
                horizon_end=(
                    horizon_end
                ),
            )
        )

        fixed_plan_items = tuple(
            item.to_plan_item(
                plan_id=1,
                temporary_id=index,
            )
            for index, item
            in enumerate(
                carried_items,
                start=1,
            )
        )

        free_slots = tuple(
            self
            ._free_slot_builder
            .build(
                window_start=(
                    effective_from
                ),
                window_end=(
                    horizon_end
                ),
                weekly_available_times=(
                    source
                    .weekly_available_times
                ),
                extra_available_times=(
                    source
                    .extra_available_times
                ),
                busy_events=(
                    source.busy_events
                ),
                fixed_plan_items=(
                    fixed_plan_items
                ),
            )
        )

        work_segments = tuple(
            self
            ._work_segment_builder
            .build(
                study_targets=(
                    source.study_targets
                ),
                goals=source.goals,
                theme_completed_minutes_by_target=(
                    source
                    .theme_completed_minutes_by_target
                ),
            )
        )

        return _PreparedContext(
            source=source,
            effective_from=(
                effective_from
            ),
            horizon_end=(
                horizon_end
            ),
            carried_items=(
                carried_items
            ),
            fixed_plan_items=(
                fixed_plan_items
            ),
            free_slots=(
                free_slots
            ),
            work_segments=(
                work_segments
            ),
        )

    def _load_source_data(
        self,
        participant_id: str,
    ) -> _SourceData:

        study_targets = tuple(
            self
            ._study_target_repository
            .list_by_participant(
                participant_id
            )
        )

        goals = tuple(
            self
            ._goal_repository
            .list_by_participant(
                participant_id
            )
        )

        learning_policies = tuple(
            self
            ._learning_policy_repository
            .list_by_participant(
                participant_id
            )
        )

        weekly_available_times = tuple(
            self
            ._availability_repository
            .list_available_times(
                participant_id
            )
        )

        busy_events = tuple(
            self
            ._availability_repository
            .list_busy_events(
                participant_id
            )
        )

        extra_available_times = tuple(
            self
            ._availability_repository
            .list_extra_available_times(
                participant_id
            )
        )

        theme_completed = (
            self
            ._study_result_repository
            .sum_theme_actual_minutes_by_target(
                participant_id=(
                    participant_id
                )
            )
        )

        target_ids = {
            target.id
            for target
            in study_targets
        }

        policy_ids = {
            policy.study_target_id
            for policy
            in learning_policies
        }

        if target_ids != policy_ids:
            missing = sorted(
                target_ids
                - policy_ids
            )

            extra = sorted(
                policy_ids
                - target_ids
            )

            raise (
                SourceDataIncompleteError(
                    "LearningPolicy mismatch; "
                    f"missing={missing}, "
                    f"extra={extra}"
                )
            )

        return _SourceData(
            study_targets=(
                study_targets
            ),
            goals=goals,
            learning_policies=(
                learning_policies
            ),
            weekly_available_times=(
                weekly_available_times
            ),
            busy_events=(
                busy_events
            ),
            extra_available_times=(
                extra_available_times
            ),
            theme_completed_minutes_by_target=(
                theme_completed
            ),
        )

    # =====================================================
    # Feasibility
    # =====================================================

    def _analyze_feasibility(
        self,
        *,
        prepared: _PreparedContext,
        strict_goal_ids: set[int],
    ) -> FeasibilityResult:

        minimum_reservations = (
            self
            ._build_minimum_reservations(
                learning_policies=(
                    prepared
                    .source
                    .learning_policies
                ),
                work_segments=(
                    prepared
                    .work_segments
                ),
                strict_goal_ids=(
                    strict_goal_ids
                ),
                free_slots=(
                    prepared.free_slots
                ),
                carried_items=(
                    prepared.carried_items
                ),
                horizon_end=(
                    prepared.horizon_end
                ),
            )
        )

        return (
            self
            ._feasibility_analyzer
            .analyze(
                effective_from=(
                    prepared
                    .effective_from
                ),
                goals=(
                    prepared
                    .source
                    .goals
                ),
                work_segments=(
                    prepared
                    .work_segments
                ),
                weekly_available_times=(
                    prepared
                    .source
                    .weekly_available_times
                ),
                extra_available_times=(
                    prepared
                    .source
                    .extra_available_times
                ),
                busy_events=(
                    prepared
                    .source
                    .busy_events
                ),
                fixed_plan_items=(
                    prepared
                    .fixed_plan_items
                ),
                strict_goal_ids=(
                    strict_goal_ids
                ),
                minimum_reservations=(
                    minimum_reservations
                ),
            )
        )

    # =====================================================
    # Replan / carry-forward
    # =====================================================

    def _collect_carry_forward(
        self,
        *,
        participant_id: str,
        operation_type: PlanOperationType,
        source: _SourceData,
        reference_time: datetime,
        effective_from: datetime,
        horizon_end: datetime,
    ) -> tuple[
        CarryForwardPlanItem,
        ...,
    ]:

        if (
            operation_type
            == PlanOperationType.INITIAL
        ):
            return ()

        source_plan = (
            self._resolve_plan_at(
                participant_id=(
                    participant_id
                ),
                at=effective_from,
            )
        )

        if source_plan is None:
            return ()

        plan_items = (
            self
            ._plan_repository
            .list_items(
                participant_id=(
                    participant_id
                ),
                plan_id=(
                    source_plan.id
                ),
            )
        )

        return (
            self
            ._replan_rules
            .collect_carry_forward(
                plan_items=(
                    plan_items
                ),
                study_targets=list(
                    source.study_targets
                ),
                now=reference_time,
                effective_from=(
                    effective_from
                ),
                horizon_end=(
                    horizon_end
                ),
            )
        )

    def _resolve_plan_at(
        self,
        *,
        participant_id: str,
        at: datetime,
    ) -> Plan | None:

        plans = (
            self
            ._plan_repository
            .list_by_participant(
                participant_id
            )
        )

        candidates = [
            plan
            for plan in plans
            if plan.effective_from <= at
        ]

        if not candidates:
            return None

        selected = max(
            candidates,
            key=lambda plan: (
                plan.version_no
            ),
        )

        # expired selected Planから
        # older Planへfallbackしない。
        if at >= selected.horizon_end:
            return None

        return selected

    @staticmethod
    def _horizon_end(
        effective_from: datetime,
    ) -> datetime:

        local = to_jst(
            effective_from
        )

        return datetime.combine(
            local.date()
            + timedelta(
                days=7
            ),
            time.min,
            tzinfo=JST,
        )

    # =====================================================
    # LearningPolicy minimum
    # =====================================================

    def _build_minimum_reservations(
        self,
        *,
        learning_policies: Sequence[
            LearningPolicy
        ],
        work_segments: Sequence[
            WorkSegment
        ],
        strict_goal_ids: set[int],
        free_slots: Sequence[
            FreeSlot
        ],
        carried_items: Sequence[
            CarryForwardPlanItem
        ],
        horizon_end: datetime,
    ) -> tuple[
        MinimumReservation,
        ...,
    ]:

        eligible_days = (
            self._eligible_days(
                free_slots=free_slots,
                carried_items=(
                    carried_items
                ),
            )
        )

        if eligible_days == 0:
            return ()

        strict_minutes_by_target: dict[
            int,
            float,
        ] = {}

        for segment in work_segments:
            if (
                set(
                    segment
                    .required_by_goal_ids
                )
                & strict_goal_ids
            ):
                strict_minutes_by_target[
                    segment.study_target_id
                ] = (
                    strict_minutes_by_target
                    .get(
                        segment
                        .study_target_id,
                        0.0,
                    )
                    + segment
                    .estimated_minutes
                )

        carried_minutes_by_target: dict[
            int,
            int,
        ] = {}

        for item in carried_items:
            carried_minutes_by_target[
                item.study_target_id
            ] = (
                carried_minutes_by_target
                .get(
                    item.study_target_id,
                    0,
                )
                + item.planned_minutes
            )

        additional_minutes = 0

        for policy in learning_policies:
            required_days = (
                self
                ._effective_minimum_days(
                    sessions_per_week=(
                        policy
                        .minimum_sessions_per_week
                    ),
                    eligible_days=(
                        eligible_days
                    ),
                )
            )

            required_minutes = (
                required_days
                * policy.minimum_minutes
            )

            strict_minutes = (
                math.ceil(
                    strict_minutes_by_target
                    .get(
                        policy
                        .study_target_id,
                        0.0,
                    )
                    - 1e-9
                )
            )

            carried_minutes = (
                carried_minutes_by_target
                .get(
                    policy
                    .study_target_id,
                    0,
                )
            )

            additional_minutes += max(
                0,
                required_minutes
                - strict_minutes
                - carried_minutes,
            )

        if additional_minutes <= 0:
            return ()

        return (
            MinimumReservation(
                deadline_at=(
                    horizon_end
                ),
                minutes=(
                    additional_minutes
                ),
            ),
        )

    def _build_minimum_requirements(
        self,
        *,
        learning_policies: Sequence[
            LearningPolicy
        ],
        free_slots: Sequence[
            FreeSlot
        ],
        carried_items: Sequence[
            CarryForwardPlanItem
        ],
    ) -> tuple[
        MinimumPolicyRequirement,
        ...,
    ]:

        eligible_days = (
            self._eligible_days(
                free_slots=free_slots,
                carried_items=(
                    carried_items
                ),
            )
        )

        result: list[
            MinimumPolicyRequirement
        ] = []

        for policy in sorted(
            learning_policies,
            key=lambda value: (
                value.study_target_id
            ),
        ):
            required_days = (
                self
                ._effective_minimum_days(
                    sessions_per_week=(
                        policy
                        .minimum_sessions_per_week
                    ),
                    eligible_days=(
                        eligible_days
                    ),
                )
            )

            if (
                required_days <= 0
                or policy.minimum_minutes
                <= 0
            ):
                continue

            result.append(
                MinimumPolicyRequirement(
                    study_target_id=(
                        policy
                        .study_target_id
                    ),
                    required_distinct_days=(
                        required_days
                    ),
                    minimum_minutes_per_day=(
                        policy
                        .minimum_minutes
                    ),
                )
            )

        return tuple(
            result
        )

    @staticmethod
    def _eligible_days(
        *,
        free_slots: Sequence[
            FreeSlot
        ],
        carried_items: Sequence[
            CarryForwardPlanItem
        ],
    ) -> int:

        days = {
            to_jst(
                slot.start_at
            ).date()
            for slot in free_slots
        }

        days.update(
            to_jst(
                item.start_at
            ).date()
            for item
            in carried_items
        )

        return min(
            7,
            len(days),
        )

    @staticmethod
    def _effective_minimum_days(
        *,
        sessions_per_week: int,
        eligible_days: int,
    ) -> int:
        """
        ceil(
            minimum_sessions_per_week
            * eligible_days
            / 7
        )
        """

        if (
            sessions_per_week <= 0
            or eligible_days <= 0
        ):
            return 0

        value = math.ceil(
            sessions_per_week
            * eligible_days
            / 7
        )

        return min(
            eligible_days,
            value,
        )

    # =====================================================
    # Minimum placement preflight
    # =====================================================

    def _place_minimum_policy_chunks(
        self,
        *,
        source: _SourceData,
        strict_goal_ids: set[int],
        work_segments: Sequence[
            WorkSegment
        ],
        carried_items: Sequence[
            CarryForwardPlanItem
        ],
        reserved_chunks: Sequence[
            WorkChunk
        ],
        existing_mandatory_chunks: Sequence[
            WorkChunk
        ],
        existing_placements: Sequence[
            ScheduledChunk
        ],
        free_slots: Sequence[
            FreeSlot
        ],
        minimum_requirements: Sequence[
            MinimumPolicyRequirement
        ],
        effective_from: datetime,
    ) -> tuple[
        tuple[
            WorkChunk,
            ...,
        ],
        tuple[
            ScheduledChunk,
            ...,
        ],
        tuple[
            FreeSlot,
            ...,
        ],
    ]:

        targets_by_id = {
            target.id: target
            for target
            in source.study_targets
        }

        policies_by_target = {
            policy.study_target_id:
            policy

            for policy
            in source.learning_policies
        }

        minutes_by_target_day: dict[
            tuple[
                int,
                date,
            ],
            int,
        ] = {}

        # すでにSTRICT workで
        # minimumを満たす日を数える。
        for placement in (
            existing_placements
        ):
            key = (
                placement
                .chunk
                .study_target_id,
                to_jst(
                    placement.start_at
                ).date(),
            )

            minutes_by_target_day[
                key
            ] = (
                minutes_by_target_day
                .get(
                    key,
                    0,
                )
                + placement
                .chunk
                .scheduled_duration_minutes
            )

        # USER_MODIFIED固定予定も
        # minimumへ寄与できる。
        for item in carried_items:
            key = (
                item.study_target_id,
                to_jst(
                    item.start_at
                ).date(),
            )

            minutes_by_target_day[
                key
            ] = (
                minutes_by_target_day
                .get(
                    key,
                    0,
                )
                + item.planned_minutes
            )

        remaining_slots = tuple(
            free_slots
        )

        built_chunks: list[
            WorkChunk
        ] = []

        placements: list[
            ScheduledChunk
        ] = []

        exclusion_chunks: list[
            WorkChunk
        ] = [
            *reserved_chunks,
            *existing_mandatory_chunks,
        ]

        for requirement in sorted(
            minimum_requirements,
            key=lambda value: (
                value.study_target_id
            ),
        ):
            target = targets_by_id.get(
                requirement
                .study_target_id
            )

            policy = policies_by_target.get(
                requirement
                .study_target_id
            )

            if (
                target is None
                or policy is None
            ):
                raise (
                    SourceDataIncompleteError(
                        "minimum policy "
                        "references unknown target"
                    )
                )

            qualifying_days = {
                day

                for (
                    target_id,
                    day,
                ), minutes
                in (
                    minutes_by_target_day
                    .items()
                )

                if (
                    target_id
                    == requirement
                    .study_target_id

                    and minutes
                    >= requirement
                    .minimum_minutes_per_day
                )
            }

            while (
                len(
                    qualifying_days
                )
                < requirement
                .required_distinct_days
            ):
                chunk = (
                    self
                    ._build_one_minimum_chunk(
                        target=target,
                        policy=policy,
                        source=source,
                        strict_goal_ids=(
                            strict_goal_ids
                        ),
                        work_segments=(
                            work_segments
                        ),
                        mandatory_chunks=(
                            tuple(
                                exclusion_chunks
                            )
                        ),
                        effective_from=(
                            effective_from
                        ),
                        ordinal=(
                            len(
                                built_chunks
                            )
                        ),
                    )
                )

                chunk = (
                    self
                    ._apply_reserved_precedence(
                        chunks=[
                            chunk
                        ],
                        carried_items=(
                            carried_items
                        ),
                    )[0]
                )

                outcome = (
                    self
                    ._placement_engine
                    .place_chunk(
                        chunk=chunk,
                        free_slots=(
                            remaining_slots
                        ),
                        used_study_days=(
                            frozenset(
                                qualifying_days
                            )
                        ),
                        additional_not_before=None,
                        prefer_new_study_day=True,
                    )
                )

                if (
                    outcome.placement
                    is None
                ):
                    raise (
                        MinimumPolicyInfeasibleError(
                            "LearningPolicy "
                            "minimum cannot "
                            "be placed"
                        )
                    )

                placement_day = (
                    to_jst(
                        outcome
                        .placement
                        .start_at
                    ).date()
                )

                # PlacementEngineが
                # unused dayを見つけられず
                # used dayへfallbackした場合。
                if (
                    placement_day
                    in qualifying_days
                ):
                    raise (
                        MinimumPolicyInfeasibleError(
                            "LearningPolicy "
                            "requires another "
                            "distinct study day"
                        )
                    )

                built_chunks.append(
                    chunk
                )

                exclusion_chunks.append(
                    chunk
                )

                placements.append(
                    outcome.placement
                )

                remaining_slots = (
                    outcome
                    .remaining_slots
                )

                key = (
                    requirement
                    .study_target_id,
                    placement_day,
                )

                minutes_by_target_day[
                    key
                ] = (
                    minutes_by_target_day
                    .get(
                        key,
                        0,
                    )
                    + chunk
                    .scheduled_duration_minutes
                )

                if (
                    minutes_by_target_day[
                        key
                    ]
                    >= requirement
                    .minimum_minutes_per_day
                ):
                    qualifying_days.add(
                        placement_day
                    )

        return (
            tuple(
                built_chunks
            ),
            tuple(
                placements
            ),
            tuple(
                remaining_slots
            ),
        )

    def _build_one_minimum_chunk(
        self,
        *,
        target: StudyTarget,
        policy: LearningPolicy,
        source: _SourceData,
        strict_goal_ids: set[int],
        work_segments: Sequence[
            WorkSegment
        ],
        mandatory_chunks: Sequence[
            WorkChunk
        ],
        effective_from: datetime,
        ordinal: int,
    ) -> WorkChunk:

        minimum_increment = 10

        if (
            target.kind
            == StudyTargetKind.MATERIAL
        ):
            unit_minutes = (
                target
                .estimated_minutes_per_unit
            )

            if (
                unit_minutes is None
                or unit_minutes <= 0
            ):
                raise (
                    SourceDataIncompleteError(
                        "Material StudyTarget "
                        "requires "
                        "estimated_minutes_per_unit"
                    )
                )

            minimum_increment = (
                scheduled_duration_minutes(
                    unit_minutes
                )
            )

        budget = max(
            policy.minimum_minutes,
            minimum_increment,
        )

        budget = (
            int(
                math.ceil(
                    budget / 5
                )
            )
            * 5
        )

        # OptionalWorkChunkBuilderの
        # ordered-work生成ロジックを
        # Hard minimumにも再利用する。
        synthetic_output = (
            PlanningOutput(
                allocations=[
                    PlanningAllocation(
                        study_target_id=(
                            target.id
                        ),
                        optional_extra_minutes=(
                            budget
                        ),
                        planning_priority_rank=1,
                        reason=(
                            "minimum policy "
                            "hard requirement"
                        ),
                    )
                ]
            )
        )

        chunks = (
            self
            ._optional_work_chunk_builder
            .build(
                output=(
                    synthetic_output
                ),
                study_targets=(
                    source.study_targets
                ),
                learning_policies=(
                    source
                    .learning_policies
                ),
                work_segments=(
                    work_segments
                ),
                strict_goal_ids=(
                    strict_goal_ids
                ),
                best_effort_goal_ids=set(),
                mandatory_chunks=(
                    mandatory_chunks
                ),
                not_before=(
                    effective_from
                ),
                theme_completed_minutes_by_target=(
                    source
                    .theme_completed_minutes_by_target
                ),
            )
        )

        if not chunks:
            raise (
                MinimumPolicyInfeasibleError(
                    "no physical work remains "
                    f"for StudyTarget "
                    f"{target.id}"
                )
            )

        # minimum sessionは
        # 1 study-dayに載せる必要がある。
        #
        # MVPでは1 chunkにできないケースは
        # preflight失敗とする。
        if len(chunks) != 1:
            raise (
                MinimumPolicyInfeasibleError(
                    "minimum policy session "
                    "was split into multiple "
                    "WorkChunks"
                )
            )

        return replace(
            chunks[0],
            chunk_id=(
                f"{target.id}:"
                f"MIN:"
                f"{ordinal:04d}"
            ),
            mandatory=True,
            planning_priority_rank=None,
        )

    # =====================================================
    # AI② + optional Scheduler
    # =====================================================

    def _generate_and_place_optional_work(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        context: PlanningAIContext,
        source: _SourceData,
        work_segments: Sequence[
            WorkSegment
        ],
        strict_goal_ids: set[int],
        best_effort_goal_ids: set[int],
        mandatory_chunks: Sequence[
            WorkChunk
        ],
        carried_items: Sequence[
            CarryForwardPlanItem
        ],
        free_slots: Sequence[
            FreeSlot
        ],
        effective_from: datetime,
        now: datetime,
    ) -> tuple[
        ScheduledChunk,
        ...,
    ]:

        # ------------------------------------------
        # optionalなしでも
        # SCHEDULING checkpointを作る。
        # ------------------------------------------

        if (
            not context.bounds
            or (
                context
                .total_soft_capacity_minutes
                <= 0
            )
        ):
            output = (
                PlanningOutput(
                    allocations=[]
                )
            )

            interaction_id = (
                self
                ._ai_interaction_repository
                .start_for_attempt(
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    prompt_version=(
                        self
                        ._planning_generator
                        .prompt_version
                    ),
                    model_name=(
                        self
                        ._planning_generator
                        .model_name
                    ),
                    now=now,
                )
            )

            (
                self
                ._checkpoint_repository
                .record_planning_ai_success(
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
                        output
                        .model_dump_json()
                    ),
                    now=now,
                )
            )

            return ()

        # ------------------------------------------
        # Initial AI②
        # ------------------------------------------

        first_interaction_id = (
            self
            ._ai_interaction_repository
            .start_for_attempt(
                participant_id=(
                    participant_id
                ),
                attempt_id=(
                    attempt_id
                ),
                prompt_version=(
                    self
                    ._planning_generator
                    .prompt_version
                ),
                model_name=(
                    self
                    ._planning_generator
                    .model_name
                ),
                now=now,
            )
        )

        try:
            output = (
                self
                ._planning_ai_service
                .generate_validated_output(
                    context=context,
                    study_targets=(
                        source.study_targets
                    ),
                    goals=source.goals,
                    learning_policies=(
                        source
                        .learning_policies
                    ),
                )
            )

        except Exception:
            self._safe_fail_ai_interaction(
                participant_id=(
                    participant_id
                ),
                interaction_id=(
                    first_interaction_id
                ),
                error_type=(
                    ERROR_AI_FAILED
                ),
            )

            raise

        schedule = (
            self
            ._schedule_optional_output(
                output=output,
                source=source,
                work_segments=(
                    work_segments
                ),
                strict_goal_ids=(
                    strict_goal_ids
                ),
                best_effort_goal_ids=(
                    best_effort_goal_ids
                ),
                mandatory_chunks=(
                    mandatory_chunks
                ),
                carried_items=(
                    carried_items
                ),
                free_slots=(
                    free_slots
                ),
                effective_from=(
                    effective_from
                ),
            )
        )

        if schedule.success:
            (
                self
                ._checkpoint_repository
                .record_planning_ai_success(
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    interaction_id=(
                        first_interaction_id
                    ),
                    structured_output_json=(
                        output
                        .model_dump_json()
                    ),
                    now=now,
                )
            )

            return (
                schedule.placements
            )

        # ------------------------------------------
        # scheduling corrective reallocation
        # 最大1回
        # ------------------------------------------

        (
            self
            ._ai_interaction_repository
            .mark_failed(
                participant_id=(
                    participant_id
                ),
                interaction_id=(
                    first_interaction_id
                ),
                error_type=(
                    ERROR_SCHEDULING_RETRY
                ),
            )
        )

        second_interaction_id = (
            self
            ._ai_interaction_repository
            .start_for_attempt(
                participant_id=(
                    participant_id
                ),
                attempt_id=(
                    attempt_id
                ),
                prompt_version=(
                    self
                    ._planning_generator
                    .prompt_version
                ),
                model_name=(
                    self
                    ._planning_generator
                    .model_name
                ),
                now=now,
            )
        )

        feedback = (
            "The previous optional allocation "
            "passed semantic validation, but "
            "its generated optional WorkChunks "
            "could not all be placed in the "
            "remaining FreeSlots. "
            "Reallocate optional_extra_minutes "
            "within exactly the same hard bounds. "
            "Do not change source data, deadlines, "
            "STRICT/BEST_EFFORT decisions, "
            "or total_soft_capacity."
        )

        try:
            corrected_output = (
                self
                ._planning_generator
                .generate(
                    context=context,
                    study_targets=(
                        source.study_targets
                    ),
                    goals=source.goals,
                    learning_policies=(
                        source
                        .learning_policies
                    ),
                    correction_feedback=(
                        feedback
                    ),
                )
            )

            (
                self
                ._planning_output_validator
                .validate(
                    context=context,
                    output=(
                        corrected_output
                    ),
                )
            )

        except Exception:
            self._safe_fail_ai_interaction(
                participant_id=(
                    participant_id
                ),
                interaction_id=(
                    second_interaction_id
                ),
                error_type=(
                    ERROR_AI_OUTPUT_INVALID
                ),
            )

            raise

        corrected_schedule = (
            self
            ._schedule_optional_output(
                output=(
                    corrected_output
                ),
                source=source,
                work_segments=(
                    work_segments
                ),
                strict_goal_ids=(
                    strict_goal_ids
                ),
                best_effort_goal_ids=(
                    best_effort_goal_ids
                ),
                mandatory_chunks=(
                    mandatory_chunks
                ),
                carried_items=(
                    carried_items
                ),
                free_slots=(
                    free_slots
                ),
                effective_from=(
                    effective_from
                ),
            )
        )

        if not corrected_schedule.success:
            (
                self
                ._ai_interaction_repository
                .mark_failed(
                    participant_id=(
                        participant_id
                    ),
                    interaction_id=(
                        second_interaction_id
                    ),
                    error_type=(
                        ERROR_SCHEDULING_FAILED
                    ),
                )
            )

            raise SchedulingFailedError(
                "optional WorkChunks could "
                "not be placed after "
                "one AI reallocation"
            )

        (
            self
            ._checkpoint_repository
            .record_planning_ai_success(
                participant_id=(
                    participant_id
                ),
                attempt_id=(
                    attempt_id
                ),
                interaction_id=(
                    second_interaction_id
                ),
                structured_output_json=(
                    corrected_output
                    .model_dump_json()
                ),
                now=now,
            )
        )

        return (
            corrected_schedule
            .placements
        )

    def _schedule_optional_output(
        self,
        *,
        output: PlanningOutput,
        source: _SourceData,
        work_segments: Sequence[
            WorkSegment
        ],
        strict_goal_ids: set[int],
        best_effort_goal_ids: set[int],
        mandatory_chunks: Sequence[
            WorkChunk
        ],
        carried_items: Sequence[
            CarryForwardPlanItem
        ],
        free_slots: Sequence[
            FreeSlot
        ],
        effective_from: datetime,
    ) -> ScheduleResult:

        chunks = (
            self
            ._optional_work_chunk_builder
            .build(
                output=output,
                study_targets=(
                    source.study_targets
                ),
                learning_policies=(
                    source
                    .learning_policies
                ),
                work_segments=(
                    work_segments
                ),
                strict_goal_ids=(
                    strict_goal_ids
                ),
                best_effort_goal_ids=(
                    best_effort_goal_ids
                ),
                mandatory_chunks=(
                    mandatory_chunks
                ),
                not_before=(
                    effective_from
                ),
                theme_completed_minutes_by_target=(
                    source
                    .theme_completed_minutes_by_target
                ),
            )
        )

        chunks = (
            self
            ._apply_reserved_precedence(
                chunks=chunks,
                carried_items=(
                    carried_items
                ),
            )
        )

        return (
            self._scheduler.schedule(
                chunks=chunks,
                free_slots=(
                    free_slots
                ),
            )
        )

    # =====================================================
    # USER_MODIFIED reserved work
    # =====================================================

    def _reserved_chunks_from_carry_forward(
        self,
        *,
        carried_items: Sequence[
            CarryForwardPlanItem
        ],
        study_targets: Sequence[
            StudyTarget
        ],
        theme_completed_minutes_by_target: Mapping[
            int,
            int,
        ],
    ) -> tuple[
        WorkChunk,
        ...,
    ]:

        targets_by_id = {
            target.id: target
            for target
            in study_targets
        }

        theme_offsets = dict(
            theme_completed_minutes_by_target
        )

        result: list[
            WorkChunk
        ] = []

        ordered = sorted(
            carried_items,
            key=lambda item: (
                item.start_at,
                item.end_at,
                item
                .source_plan_item_id,
            ),
        )

        for sequence_no, item in enumerate(
            ordered
        ):
            target = targets_by_id[
                item.study_target_id
            ]

            theme_start = None
            theme_end = None

            if (
                target.kind
                == StudyTargetKind.THEME
            ):
                theme_start = (
                    theme_offsets.get(
                        target.id,
                        0,
                    )
                )

                theme_end = (
                    theme_start
                    + item.planned_minutes
                )

                theme_offsets[
                    target.id
                ] = theme_end

            result.append(
                WorkChunk(
                    chunk_id=(
                        f"{item.study_target_id}:"
                        "RESERVED:"
                        f"{item.source_plan_item_id}"
                    ),
                    study_target_id=(
                        item.study_target_id
                    ),
                    kind=target.kind,
                    estimated_minutes=float(
                        item.planned_minutes
                    ),
                    scheduled_duration_minutes=(
                        item.planned_minutes
                    ),
                    sequence_no=(
                        sequence_no
                    ),
                    mandatory=True,
                    required_by_goal_ids=(),
                    must_finish_before=None,
                    not_before=(
                        item.start_at
                    ),
                    planning_priority_rank=None,
                    range_start=(
                        item.range_start
                    ),
                    range_end=(
                        item.range_end
                    ),
                    theme_minute_start=(
                        theme_start
                    ),
                    theme_minute_end=(
                        theme_end
                    ),
                )
            )

        return tuple(
            result
        )

    def _subtract_reserved_material_work(
        self,
        *,
        chunks: Sequence[
            WorkChunk
        ],
        carried_items: Sequence[
            CarryForwardPlanItem
        ],
        study_targets: Sequence[
            StudyTarget
        ],
    ) -> list[
        WorkChunk
    ]:

        targets_by_id = {
            target.id: target
            for target
            in study_targets
        }

        reserved_by_target: dict[
            int,
            list[
                CarryForwardPlanItem
            ],
        ] = {}

        for item in carried_items:
            if (
                item.range_start
                is None
                or item.range_end
                is None
            ):
                continue

            reserved_by_target.setdefault(
                item.study_target_id,
                [],
            ).append(
                item
            )

        result: list[
            WorkChunk
        ] = []

        for chunk in chunks:
            if (
                chunk.kind
                != StudyTargetKind.MATERIAL
            ):
                result.append(
                    chunk
                )

                continue

            if (
                chunk.range_start is None
                or chunk.range_end is None
            ):
                raise DomainValidationError(
                    "mandatory Material "
                    "WorkChunk requires range"
                )

            intervals = [
                (
                    chunk.range_start,
                    chunk.range_end,
                )
            ]

            for reserved in (
                reserved_by_target.get(
                    chunk.study_target_id,
                    [],
                )
            ):
                assert (
                    reserved.range_start
                    is not None
                )

                assert (
                    reserved.range_end
                    is not None
                )

                intervals = (
                    self
                    ._subtract_interval_list(
                        intervals=(
                            intervals
                        ),
                        remove_start=(
                            reserved
                            .range_start
                        ),
                        remove_end=(
                            reserved
                            .range_end
                        ),
                    )
                )

            target = targets_by_id[
                chunk.study_target_id
            ]

            unit_minutes = (
                target
                .estimated_minutes_per_unit
            )

            if (
                unit_minutes is None
                or unit_minutes <= 0
            ):
                raise (
                    SourceDataIncompleteError(
                        "Material StudyTarget "
                        "requires "
                        "estimated_minutes_per_unit"
                    )
                )

            for index, (
                start,
                end,
            ) in enumerate(
                intervals
            ):
                estimated = (
                    (
                        end
                        - start
                        + 1
                    )
                    * unit_minutes
                )

                result.append(
                    replace(
                        chunk,
                        chunk_id=(
                            f"{chunk.chunk_id}:"
                            f"R{index}"
                        ),
                        estimated_minutes=(
                            estimated
                        ),
                        scheduled_duration_minutes=(
                            scheduled_duration_minutes(
                                estimated
                            )
                        ),
                        range_start=(
                            start
                        ),
                        range_end=(
                            end
                        ),
                    )
                )

        return (
            self
            ._resequence_material_chunks(
                result
            )
        )

    @staticmethod
    def _subtract_interval_list(
        *,
        intervals: Sequence[
            tuple[
                int,
                int,
            ]
        ],
        remove_start: int,
        remove_end: int,
    ) -> list[
        tuple[
            int,
            int,
        ]
    ]:

        result: list[
            tuple[
                int,
                int,
            ]
        ] = []

        for start, end in intervals:
            if (
                remove_end < start
                or remove_start > end
            ):
                result.append(
                    (
                        start,
                        end,
                    )
                )

                continue

            if start < remove_start:
                result.append(
                    (
                        start,
                        remove_start - 1,
                    )
                )

            if remove_end < end:
                result.append(
                    (
                        remove_end + 1,
                        end,
                    )
                )

        return result

    @staticmethod
    def _resequence_material_chunks(
        chunks: Sequence[
            WorkChunk
        ],
    ) -> list[
        WorkChunk
    ]:

        material_by_target: dict[
            int,
            list[
                WorkChunk
            ],
        ] = {}

        result: list[
            WorkChunk
        ] = []

        for chunk in chunks:
            if (
                chunk.kind
                == StudyTargetKind.MATERIAL
            ):
                material_by_target.setdefault(
                    chunk.study_target_id,
                    [],
                ).append(
                    chunk
                )

            else:
                result.append(
                    chunk
                )

        for target_chunks in (
            material_by_target.values()
        ):
            ordered = sorted(
                target_chunks,
                key=lambda chunk: (
                    (
                        chunk.range_start
                        if (
                            chunk.range_start
                            is not None
                        )
                        else -1
                    ),
                    (
                        chunk.range_end
                        if (
                            chunk.range_end
                            is not None
                        )
                        else -1
                    ),
                    chunk.chunk_id,
                ),
            )

            for sequence_no, chunk in enumerate(
                ordered
            ):
                result.append(
                    replace(
                        chunk,
                        sequence_no=(
                            sequence_no
                        ),
                    )
                )

        return result

    def _apply_reserved_precedence(
        self,
        *,
        chunks: Sequence[
            WorkChunk
        ],
        carried_items: Sequence[
            CarryForwardPlanItem
        ],
    ) -> list[
        WorkChunk
    ]:
        """
        Material USER_MODIFIEDを
        precedence barrierとして扱う。

        例:
        current p.10
        fixed p.20-25 at 18:00

        p.10-19
        -> must_finish_before = 18:00

        p.26+
        -> not_before = fixed end
        """

        reserved_by_target: dict[
            int,
            list[
                CarryForwardPlanItem
            ],
        ] = {}

        for item in carried_items:
            if (
                item.range_start
                is None
                or item.range_end
                is None
            ):
                continue

            reserved_by_target.setdefault(
                item.study_target_id,
                [],
            ).append(
                item
            )

        for values in (
            reserved_by_target.values()
        ):
            values.sort(
                key=lambda item: (
                    item.range_start
                    if (
                        item.range_start
                        is not None
                    )
                    else -1
                )
            )

        result: list[
            WorkChunk
        ] = []

        for chunk in chunks:
            if (
                chunk.kind
                != StudyTargetKind.MATERIAL
                or chunk.range_start
                is None
                or chunk.range_end
                is None
            ):
                result.append(
                    chunk
                )

                continue

            previous_reserved = None
            next_reserved = None

            for reserved in (
                reserved_by_target.get(
                    chunk.study_target_id,
                    [],
                )
            ):
                assert (
                    reserved.range_start
                    is not None
                )

                assert (
                    reserved.range_end
                    is not None
                )

                if (
                    reserved.range_end
                    < chunk.range_start
                ):
                    previous_reserved = (
                        reserved
                    )

                    continue

                if (
                    reserved.range_start
                    > chunk.range_end
                ):
                    next_reserved = (
                        reserved
                    )

                    break

            not_before = (
                chunk.not_before
            )

            if (
                previous_reserved
                is not None
            ):
                if (
                    not_before is None
                    or (
                        previous_reserved
                        .end_at
                        > not_before
                    )
                ):
                    not_before = (
                        previous_reserved
                        .end_at
                    )

            must_finish_before = (
                chunk
                .must_finish_before
            )

            if next_reserved is not None:
                if (
                    must_finish_before
                    is None
                    or (
                        next_reserved
                        .start_at
                        < must_finish_before
                    )
                ):
                    must_finish_before = (
                        next_reserved
                        .start_at
                    )

            if (
                not_before is not None
                and (
                    must_finish_before
                    is not None
                )
                and (
                    not_before
                    >= must_finish_before
                )
            ):
                raise (
                    UserModifiedConflictError(
                        "reserved Material work "
                        "creates an impossible "
                        "precedence window"
                    )
                )

            result.append(
                replace(
                    chunk,
                    not_before=(
                        not_before
                    ),
                    must_finish_before=(
                        must_finish_before
                    ),
                )
            )

        return result

    # =====================================================
    # Helpers
    # =====================================================

    def _assert_learning_policies_complete(
        self,
        participant_id: str,
    ) -> None:

        study_targets = (
            self
            ._study_target_repository
            .list_by_participant(
                participant_id
            )
        )

        policies = (
            self
            ._learning_policy_repository
            .list_by_participant(
                participant_id
            )
        )

        target_ids = {
            target.id
            for target
            in study_targets
        }

        policy_ids = {
            policy.study_target_id
            for policy
            in policies
        }

        if target_ids != policy_ids:
            missing = sorted(
                target_ids
                - policy_ids
            )

            extra = sorted(
                policy_ids
                - target_ids
            )

            raise (
                SourceDataIncompleteError(
                    "LearningPolicy must "
                    "exist before Plan "
                    "generation; "
                    f"missing={missing}, "
                    f"extra={extra}"
                )
            )

    def _safe_fail_attempt(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        error_type: str,
        now: datetime,
    ) -> None:

        try:
            (
                self
                ._attempt_service
                .fail(
                    participant_id=(
                        participant_id
                    ),
                    attempt_id=(
                        attempt_id
                    ),
                    error_type=(
                        error_type
                    ),
                    now=now,
                )
            )

        except (
            AttemptNotActiveError
        ):
            # ABANDONED / FAILED /
            # SUCCEEDEDを上書きしない。
            pass

    def _safe_fail_ai_interaction(
        self,
        *,
        participant_id: str,
        interaction_id: int,
        error_type: str,
    ) -> None:

        try:
            (
                self
                ._ai_interaction_repository
                .mark_failed(
                    participant_id=(
                        participant_id
                    ),
                    interaction_id=(
                        interaction_id
                    ),
                    error_type=(
                        error_type
                    ),
                )
            )

        except RuntimeError:
            pass

    @staticmethod
    def _error_type(
        exc: Exception,
    ) -> str:

        if isinstance(
            exc,
            MinimumPolicyInfeasibleError,
        ):
            return (
                ERROR_MINIMUM_POLICY_INFEASIBLE
            )

        if isinstance(
            exc,
            SchedulingFailedError,
        ):
            return (
                ERROR_SCHEDULING_FAILED
            )

        if isinstance(
            exc,
            SourceDataIncompleteError,
        ):
            return (
                ERROR_SOURCE_DATA_INCOMPLETE
            )

        if isinstance(
            exc,
            UserModifiedConflictError,
        ):
            return (
                ERROR_USER_MODIFIED_CONFLICT
            )

        if isinstance(
            exc,
            PlanningDataChangedError,
        ):
            return (
                "PLANNING_DATA_CHANGED"
            )

        if isinstance(
            exc,
            PlanValidationFailedError,
        ):
            return (
                "PLAN_VALIDATION_FAILED"
            )

        if isinstance(
            exc,
            AIOutputInvalidError,
        ):
            return (
                ERROR_AI_OUTPUT_INVALID
            )

        if isinstance(
            exc,
            AIGenerationError,
        ):
            return (
                ERROR_AI_FAILED
            )

        return (
            "PLAN_GENERATION_FAILED"
        )

    def _build_mandatory_failure_diagnostic(
        self,
        *,
        chunks: Sequence[
            WorkChunk
        ],
        free_slots: Sequence[
            FreeSlot
        ],
        effective_from: datetime,
        horizon_end: datetime,
    ) -> str:
        total_mandatory_minutes = sum(
            chunk.scheduled_duration_minutes
            for chunk in chunks
        )

        total_free_minutes = sum(
            int(
                (
                    slot.end_at
                    - slot.start_at
                ).total_seconds()
                // 60
            )
            for slot in free_slots
        )

        lines: list[str] = [
            (
                "mandatory WorkChunks "
                "could not be placed"
            ),
            "",
            (
                "Plan horizon: "
                f"{effective_from.isoformat()}"
                " -> "
                f"{horizon_end.isoformat()}"
            ),
            (
                "Mandatory minutes: "
                f"{total_mandatory_minutes}"
            ),
            (
                "FreeSlot minutes: "
                f"{total_free_minutes}"
            ),
            (
                "Mandatory chunk count: "
                f"{len(chunks)}"
            ),
            (
                "FreeSlot count: "
                f"{len(free_slots)}"
            ),
            "",
            "MANDATORY CHUNKS:",
        ]

        for chunk in sorted(
            chunks,
            key=lambda value: (
                (
                    value.must_finish_before
                    if (
                        value.must_finish_before
                        is not None
                    )
                    else datetime.max.replace(
                        tzinfo=JST
                    )
                ),
                value.study_target_id,
                value.sequence_no,
                value.chunk_id,
            ),
        ):
            lines.append(
                (
                    f"- id={chunk.chunk_id}"
                    f", target="
                    f"{chunk.study_target_id}"
                    f", kind={chunk.kind.value}"
                    f", duration="
                    f"{chunk.scheduled_duration_minutes}"
                    f", mandatory="
                    f"{chunk.mandatory}"
                    f", not_before="
                    f"{chunk.not_before}"
                    f", must_finish_before="
                    f"{chunk.must_finish_before}"
                    f", range="
                    f"{chunk.range_start}"
                    "-"
                    f"{chunk.range_end}"
                    f", required_by_goals="
                    f"{chunk.required_by_goal_ids}"
                )
            )

        lines.append(
            ""
        )

        lines.append(
            "FREE SLOTS:"
        )

        for slot in sorted(
            free_slots,
            key=lambda value: (
                value.start_at,
                value.end_at,
            ),
        ):
            duration = int(
                (
                    slot.end_at
                    - slot.start_at
                ).total_seconds()
                // 60
            )

            lines.append(
                (
                    f"- {slot.start_at.isoformat()}"
                    " -> "
                    f"{slot.end_at.isoformat()}"
                    f" ({duration} min)"
                )
            )

        if (
            total_mandatory_minutes
            > total_free_minutes
        ):
            lines.extend(
                [
                    "",
                    "DIAGNOSIS:",
                    (
                        "Total mandatory minutes "
                        "exceed total 7-day "
                        "FreeSlot capacity."
                    ),
                ]
            )

        else:
            largest_chunk = max(
                (
                    chunk
                    .scheduled_duration_minutes
                    for chunk in chunks
                ),
                default=0,
            )

            largest_slot = max(
                (
                    int(
                        (
                            slot.end_at
                            - slot.start_at
                        ).total_seconds()
                        // 60
                    )
                    for slot in free_slots
                ),
                default=0,
            )

            lines.extend(
                [
                    "",
                    "DIAGNOSIS:",
                    (
                        "Total capacity is enough, "
                        "so placement failed because "
                        "of slot fragmentation, "
                        "deadline/not_before constraints, "
                        "Material precedence, "
                        "or missing deterministic repair."
                    ),
                    (
                        "Largest chunk: "
                        f"{largest_chunk} min"
                    ),
                    (
                        "Largest slot: "
                        f"{largest_slot} min"
                    ),
                ]
            )

            if (
                largest_chunk
                > largest_slot
            ):
                lines.append(
                    (
                        "At least one mandatory "
                        "WorkChunk is larger than "
                        "every available FreeSlot. "
                        "WorkChunk splitting is required."
                    )
                )

        return "\n".join(
            lines
        )

    def _schedule_mandatory_with_repair(
        self,
        *,
        chunks: Sequence[
            WorkChunk
        ],
        free_slots: Sequence[
            FreeSlot
        ],
        study_targets: Sequence[
            StudyTarget
        ],
    ) -> tuple[
        list[
            WorkChunk
        ],
        ScheduleResult,
    ]:
        """
        Mandatory WorkChunkのdeterministic repair。

        優先順位:

        1. 通常greedy
        distributed practiceあり

        2. WorkChunk split

        3. split後も失敗したら
        distributed practiceを弱め、
        同日複数sessionを許可

        Hard constraints:
        - deadline
        - not_before
        - Material ordering
        - FreeSlot

        は常に維持する。
        """

        targets_by_id = {
            target.id: target
            for target
            in study_targets
        }

        current_chunks = list(
            chunks
        )

        # ==========================================
        # STEP 1
        # standard greedy
        # ==========================================

        schedule = (
            self._scheduler.schedule(
                chunks=current_chunks,
                free_slots=free_slots,
                prefer_distributed_practice=True,
            )
        )

        if schedule.success:
            return (
                current_chunks,
                schedule,
            )

        # ==========================================
        # STEP 2
        # deterministic split repair
        # ==========================================

        for _round in range(6):
            repaired: list[
                WorkChunk
            ] = []

            changed = False

            for chunk in current_chunks:
                target = (
                    targets_by_id.get(
                        chunk.study_target_id
                    )
                )

                if target is None:
                    raise (
                        SourceDataIncompleteError(
                            "WorkChunk references "
                            "unknown StudyTarget: "
                            f"{chunk.study_target_id}"
                        )
                    )

                split_chunks = (
                    self
                    ._split_mandatory_chunk_once(
                        chunk=chunk,
                        target=target,
                    )
                )

                if len(split_chunks) > 1:
                    changed = True

                repaired.extend(
                    split_chunks
                )

            if not changed:
                break

            current_chunks = (
                self
                ._resequence_material_chunks(
                    repaired
                )
            )

            # --------------------------------------
            # 2-A
            # distributed practiceあり
            # --------------------------------------

            schedule = (
                self._scheduler.schedule(
                    chunks=current_chunks,
                    free_slots=free_slots,
                    prefer_distributed_practice=True,
                )
            )

            if schedule.success:
                return (
                    current_chunks,
                    schedule,
                )

            # --------------------------------------
            # 2-B
            # 同日複数sessionを積極的に許可
            #
            # Hard constraintではない
            # distributed practiceを外す。
            # --------------------------------------

            schedule = (
                self._scheduler.schedule(
                    chunks=current_chunks,
                    free_slots=free_slots,
                    prefer_distributed_practice=False,
                )
            )

            if schedule.success:
                return (
                    current_chunks,
                    schedule,
                )

        # ==========================================
        # STEP 3
        # split不能になった後も最後に
        # compact schedulingを試す
        # ==========================================

        schedule = (
            self._scheduler.schedule(
                chunks=current_chunks,
                free_slots=free_slots,
                prefer_distributed_practice=False,
            )
        )

        return (
            current_chunks,
            schedule,
        )

    def _split_mandatory_chunk_once(
        self,
        *,
        chunk: WorkChunk,
        target: StudyTarget,
    ) -> list[
        WorkChunk
    ]:
        """
        Mandatory WorkChunkを
        deterministicに1段階splitする。

        現時点ではMaterialを対象とする。

        Materialでは、
        rangeをordered sequence上で
        前半/後半へ分割する。

        splitによってcalendar minutesが
        増えてしまう場合はsplitしない。
        """

        if (
            chunk.kind
            != StudyTargetKind.MATERIAL
        ):
            return [
                chunk
            ]

        if (
            chunk.range_start is None
            or chunk.range_end is None
        ):
            raise DomainValidationError(
                "Material WorkChunk "
                "requires range"
            )

        if (
            target.kind
            != StudyTargetKind.MATERIAL
        ):
            raise DomainValidationError(
                "Material WorkChunk target "
                "must be MATERIAL"
            )

        unit_minutes = (
            target
            .estimated_minutes_per_unit
        )

        if (
            unit_minutes is None
            or unit_minutes <= 0
        ):
            raise (
                SourceDataIncompleteError(
                    "Material StudyTarget "
                    "requires positive "
                    "estimated_minutes_per_unit"
                )
            )

        unit_count = (
            chunk.range_end
            - chunk.range_start
            + 1
        )

        # 1 unitならsplit不能。
        if unit_count <= 1:
            return [
                chunk
            ]

        left_unit_count = (
            unit_count // 2
        )

        right_unit_count = (
            unit_count
            - left_unit_count
        )

        if (
            left_unit_count <= 0
            or right_unit_count <= 0
        ):
            return [
                chunk
            ]

        left_start = (
            chunk.range_start
        )

        left_end = (
            left_start
            + left_unit_count
            - 1
        )

        right_start = (
            left_end + 1
        )

        right_end = (
            chunk.range_end
        )

        left_estimated = (
            left_unit_count
            * unit_minutes
        )

        right_estimated = (
            right_unit_count
            * unit_minutes
        )

        left_scheduled = (
            scheduled_duration_minutes(
                left_estimated
            )
        )

        right_scheduled = (
            scheduled_duration_minutes(
                right_estimated
            )
        )

        # splitによってcalendar capacityが
        # 増えるなら、むやみに細分化しない。
        #
        # 例:
        # original 10分
        # ↓
        # 10分 + 10分
        #
        # はcapacityを倍消費するので禁止。
        if (
            left_scheduled
            + right_scheduled
            > chunk
            .scheduled_duration_minutes
        ):
            return [
                chunk
            ]

        left = replace(
            chunk,
            chunk_id=(
                f"{chunk.chunk_id}:S0"
            ),
            estimated_minutes=(
                left_estimated
            ),
            scheduled_duration_minutes=(
                left_scheduled
            ),
            range_start=(
                left_start
            ),
            range_end=(
                left_end
            ),
        )

        right = replace(
            chunk,
            chunk_id=(
                f"{chunk.chunk_id}:S1"
            ),
            estimated_minutes=(
                right_estimated
            ),
            scheduled_duration_minutes=(
                right_scheduled
            ),
            range_start=(
                right_start
            ),
            range_end=(
                right_end
            ),
        )

        return [
            left,
            right,
        ]