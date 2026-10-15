
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from domain.models import Plan
from domain.time_rules import ensure_aware
from repositories.participant_repository import (
    ParticipantRepository,
)
from repositories.plan_repository import PlanRepository


@dataclass(frozen=True)
class PlanVersionStatus:
    current_version: int
    active_plan: Plan | None
    next_plan: Plan | None

    @property
    def active_has_changes(self) -> bool:
        return (
            self.active_plan is not None
            and self.active_plan.source_planning_data_version
            != self.current_version
        )

    @property
    def next_has_changes(self) -> bool:
        return (
            self.next_plan is not None
            and self.next_plan.source_planning_data_version
            != self.current_version
        )


class PlanVersionStatusService:
    def __init__(self, db_path: str | Path) -> None:
        self._participants = ParticipantRepository(db_path)
        self._plans = PlanRepository(db_path)

    def get_status(
        self,
        *,
        participant_id: str,
        now: datetime,
    ) -> PlanVersionStatus:
        ensure_aware(now)

        current_version = (
            self._participants.get_planning_data_version(
                participant_id
            )
        )

        if current_version is None:
            raise ValueError(
                "参加者情報が見つかりません。"
            )

        plans = self._plans.list_by_participant(
            participant_id
        )

        # PlanResolverの選択規則に合わせる。
        # 開始済みPlanのうち、最大version_noを選ぶ。
        started = [
            plan
            for plan in plans
            if plan.effective_from <= now
        ]

        latest_started = max(
            started,
            key=lambda plan: plan.version_no,
            default=None,
        )

        # 期限切れの場合、古いPlanへ戻らない。
        active_plan = (
            latest_started
            if (
                latest_started is not None
                and now < latest_started.horizon_end
            )
            else None
        )

        # 次に有効となり得る未来Planも確認する。
        latest_started_version = (
            latest_started.version_no
            if latest_started is not None
            else 0
        )

        future_candidates = [
            plan
            for plan in plans
            if (
                plan.effective_from > now
                and plan.version_no > latest_started_version
            )
        ]

        next_plan = min(
            future_candidates,
            key=lambda plan: (
                plan.effective_from,
                -plan.version_no,
            ),
            default=None,
        )

        return PlanVersionStatus(
            current_version=current_version,
            active_plan=active_plan,
            next_plan=next_plan,
        )
