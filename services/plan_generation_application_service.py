from __future__ import annotations

from datetime import datetime
from pathlib import Path

from domain.enums import (
    PlanOperationType,
)
from domain.time_rules import (
    ensure_aware,
)
from services.plan_generation_logging import (
    get_plan_generation_logger,
)
from services.study_result_service import (
    StudyResultService,
)

from typing import Mapping

from domain.enums import GoalMode
from repositories.plan_generation_attempt_repository import (
    PlanGenerationAttemptRepository,
)
from repositories.goal_repository import GoalRepository


class PlanGenerationApplicationService:
    """
    Streamlitから見えるPlan生成の唯一の入口。

    UIはFreeSlotBuilder / Scheduler /
    AttemptRepository等を直接呼ばない。
    """

    def __init__(
        self,
        *,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(
            db_path
        )

        self._logger = (
            get_plan_generation_logger(
                self._db_path
            )
        )

        self._study_result_service = (
            StudyResultService(
                db_path=self._db_path
            )
        )

    def generate(
        self,
        *,
        participant_id: str,
        operation_type: PlanOperationType,
        now: datetime,
    ):
        ensure_aware(
            now
        )

        self._logger.info(
            "plan_generation_started "
            "participant_id=%s operation_type=%s",
            participant_id,
            operation_type.value,
        )

        try:
            if operation_type in {
                PlanOperationType.REPLAN_NOW,
                PlanOperationType.REPLAN_TOMORROW,
            }:
                self._study_result_service.assert_replan_ready(
                    participant_id=(
                        participant_id
                    ),
                    now=now,
                )

            result = self._generate_impl(
                participant_id=(
                    participant_id
                ),
                operation_type=(
                    operation_type
                ),
                now=now,
            )
        except Exception:
            self._logger.exception(
                "plan_generation_failed "
                "participant_id=%s operation_type=%s",
                participant_id,
                operation_type.value,
            )
            raise

        if result.succeeded:
            plan = result.plan
            self._logger.info(
                "plan_created "
                "participant_id=%s operation_type=%s "
                "attempt_id=%s plan_id=%s version_no=%s "
                "effective_from=%s horizon_end=%s",
                participant_id,
                operation_type.value,
                result.attempt_id,
                plan.id if plan is not None else None,
                plan.version_no if plan is not None else None,
                plan.effective_from.isoformat()
                if plan is not None
                else None,
                plan.horizon_end.isoformat()
                if plan is not None
                else None,
            )
        elif result.awaiting_goal_decision:
            self._logger.info(
                "plan_generation_waiting_for_goal_decision "
                "participant_id=%s operation_type=%s "
                "attempt_id=%s",
                participant_id,
                operation_type.value,
                result.attempt_id,
            )
        else:
            self._logger.warning(
                "plan_generation_finished_without_plan "
                "participant_id=%s operation_type=%s "
                "attempt_id=%s stage=%s",
                participant_id,
                operation_type.value,
                result.attempt_id,
                result.stage.value,
            )

        return result

    def _generate_impl(
        self,
        *,
        participant_id: str,
        operation_type: PlanOperationType,
        now: datetime,
    ):
        """
        ここには10/12までに作成した
        Plan generation pipeline本体を接続する。

        UIからこの下の構成要素を
        直接呼び出してはいけない。

        すでに別Serviceにpipeline本体がある場合は、
        このメソッドをそのServiceへのdelegateにする。
        """

        from services.plan_generation_pipeline_service import (
            PlanGenerationPipelineService,
        )

        pipeline = (
            PlanGenerationPipelineService(
                db_path=self._db_path
            )
        )

        return pipeline.generate(
            participant_id=(
                participant_id
            ),
            operation_type=(
                operation_type
            ),
            now=now,
        )

    def get_active_attempt(
        self,
        *,
        participant_id: str,
    ):
        """現在進行中のPlan生成Attemptを取得する。"""
        repository = PlanGenerationAttemptRepository(
            self._db_path
        )
        return repository.get_current_in_progress(
            participant_id
        )

    def list_goals_for_decision(
        self,
        *,
        participant_id: str,
    ):
        """ユーザーが保証レベルを選択するGoal一覧。"""
        repository = GoalRepository(
            self._db_path
        )
        return repository.list_active_by_participant(
            participant_id
        )

    def continue_after_goal_decision(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        goal_modes: Mapping[int, GoalMode],
        now: datetime,
    ):
        """既存Attemptから計画生成を再開する。"""
        ensure_aware(now)

        from services.plan_generation_pipeline_service import (
            PlanGenerationPipelineService,
        )

        pipeline = PlanGenerationPipelineService(
            db_path=self._db_path
        )

        try:
            return pipeline.continue_after_goal_decision(
                participant_id=participant_id,
                attempt_id=attempt_id,
                goal_modes=goal_modes,
                now=now,
            )
        except Exception:
            self._logger.exception(
                "plan_generation_resume_failed "
                "participant_id=%s attempt_id=%s",
                participant_id,
                attempt_id,
            )
            raise