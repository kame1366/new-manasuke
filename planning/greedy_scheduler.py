from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from domain.enums import (
    StudyTargetKind,
)
from domain.errors import (
    DomainValidationError,
)
from domain.time_rules import to_jst
from planning.free_slot_builder import (
    FreeSlot,
)
from planning.placement_engine import (
    PlacementEngine,
    ScheduledChunk,
)
from planning.work_chunk_builder import (
    WorkChunk,
)


@dataclass(
    frozen=True,
    slots=True,
)
class ScheduleResult:
    success: bool

    placements: tuple[
        ScheduledChunk,
        ...,
    ]

    unplaced_chunks: tuple[
        WorkChunk,
        ...,
    ]

    remaining_slots: tuple[
        FreeSlot,
        ...,
    ]


class GreedyScheduler:
    """
    Manasuke MVPの決定論的Greedy Scheduler。

    優先:
        1. mandatory
        2. deadline work
        3. earlier deadline
        4. planning_priority_rank
        5. deterministic tie-break

    PlacementEngine側で、
    distributed practiceをSoft preferenceとして扱う。

    MATERIALはsequence_noによって
    ordered precedenceをHard保証する。
    """

    def __init__(
        self,
        placement_engine: PlacementEngine
        | None = None,
    ) -> None:
        self._placement_engine = (
            placement_engine
            or PlacementEngine()
        )

    def schedule(
        self,
        *,
        chunks: Sequence[
            WorkChunk
        ],
        free_slots: Sequence[
            FreeSlot
        ],
        prefer_distributed_practice: bool = True,
    ) -> ScheduleResult:
        self._validate_chunks(
            chunks
        )

        remaining_chunks = list(
            chunks
        )

        remaining_slots = tuple(
            sorted(
                free_slots,
                key=lambda slot: (
                    slot.start_at,
                    slot.end_at,
                ),
            )
        )

        placements: list[
            ScheduledChunk
        ] = []

        used_days: dict[int, set[date]] = defaultdict(set)

        last_material_end_by_target = {}

        while remaining_chunks:
            ready_chunks = (
                self._get_ready_chunks(
                    remaining_chunks
                )
            )

            if not ready_chunks:
                raise DomainValidationError(
                    "no schedulable WorkChunk "
                    "because Material precedence "
                    "is inconsistent"
                )

            selected = min(
                ready_chunks,
                key=self._priority_key,
            )

            additional_not_before = None

            if (
                selected.kind
                == StudyTargetKind.MATERIAL
            ):
                additional_not_before = (
                    last_material_end_by_target.get(
                        selected.study_target_id
                    )
                )

            outcome = (
                self._placement_engine
                .place_chunk(
                    chunk=selected,
                    free_slots=(
                        remaining_slots
                    ),
                    used_study_days=frozenset(
                        used_days[selected.study_target_id]
                    ),
                    additional_not_before=(
                        additional_not_before
                    ),
                    prefer_new_study_day=prefer_distributed_practice,
                )
            )

            if outcome.placement is None:
                ordered_unplaced = tuple(
                    sorted(
                        [
                            *remaining_chunks,
                        ],
                        key=self._priority_key,
                    )
                )

                return ScheduleResult(
                    success=False,
                    placements=tuple(
                        placements
                    ),
                    unplaced_chunks=(
                        ordered_unplaced
                    ),
                    remaining_slots=(
                        remaining_slots
                    ),
                )

            placement = (
                outcome.placement
            )

            placements.append(
                placement
            )

            remaining_slots = (
                outcome.remaining_slots
            )

            study_day = to_jst(
                placement.start_at
            ).date()

            used_days[selected.study_target_id].add(
                study_day
            )

            if (
                selected.kind
                == StudyTargetKind.MATERIAL
            ):
                last_material_end_by_target[
                    selected.study_target_id
                ] = placement.end_at

            remaining_chunks.remove(
                selected
            )

        return ScheduleResult(
            success=True,
            placements=tuple(
                placements
            ),
            unplaced_chunks=(),
            remaining_slots=(
                remaining_slots
            ),
        )

    @staticmethod
    def _validate_chunks(
        chunks: Sequence[
            WorkChunk
        ],
    ) -> None:
        chunk_ids = [
            chunk.chunk_id
            for chunk in chunks
        ]

        if len(chunk_ids) != len(
            set(chunk_ids)
        ):
            raise DomainValidationError(
                "duplicate WorkChunk chunk_id"
            )

        material_sequences: dict[
            int,
            set[int],
        ] = {}

        for chunk in chunks:
            if (
                chunk.kind
                != StudyTargetKind.MATERIAL
            ):
                continue

            sequences = (
                material_sequences
                .setdefault(
                    chunk.study_target_id,
                    set(),
                )
            )

            if (
                chunk.sequence_no
                in sequences
            ):
                raise DomainValidationError(
                    "duplicate MATERIAL sequence_no "
                    "within StudyTarget"
                )

            sequences.add(
                chunk.sequence_no
            )

    @staticmethod
    def _get_ready_chunks(
        remaining_chunks: Sequence[
            WorkChunk
        ],
    ) -> list[WorkChunk]:
        lowest_material_sequence: dict[
            int,
            int,
        ] = {}

        for chunk in remaining_chunks:
            if (
                chunk.kind
                != StudyTargetKind.MATERIAL
            ):
                continue

            current = (
                lowest_material_sequence.get(
                    chunk.study_target_id
                )
            )

            if (
                current is None
                or chunk.sequence_no
                < current
            ):
                lowest_material_sequence[
                    chunk.study_target_id
                ] = chunk.sequence_no

        ready: list[
            WorkChunk
        ] = []

        for chunk in remaining_chunks:
            if (
                chunk.kind
                == StudyTargetKind.MATERIAL
                and (
                    chunk.sequence_no
                    != lowest_material_sequence[
                        chunk.study_target_id
                    ]
                )
            ):
                continue

            ready.append(
                chunk
            )

        return ready

    @staticmethod
    def _priority_key(
        chunk: WorkChunk,
    ) -> tuple:
        mandatory_rank = (
            0
            if chunk.mandatory
            else 1
        )

        has_deadline_rank = (
            0
            if (
                chunk.must_finish_before
                is not None
            )
            else 1
        )

        deadline_value = (
            chunk.must_finish_before.timestamp()
            if (
                chunk.must_finish_before
                is not None
            )
            else math.inf
        )

        planning_rank = (
            chunk.planning_priority_rank
            if (
                chunk.planning_priority_rank
                is not None
            )
            else math.inf
        )

        return (
            mandatory_rank,
            has_deadline_rank,
            deadline_value,
            planning_rank,
            chunk.study_target_id,
            chunk.sequence_no,
            chunk.chunk_id,
        )