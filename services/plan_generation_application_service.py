from __future__ import annotations

from datetime import datetime
from pathlib import Path

from domain.enums import (
    PlanOperationType,
)
from domain.time_rules import (
    ensure_aware,
)
from services.study_result_service import (
    StudyResultService,
)


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

        return self._generate_impl(
            participant_id=(
                participant_id
            ),
            operation_type=(
                operation_type
            ),
            now=now,
        )

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