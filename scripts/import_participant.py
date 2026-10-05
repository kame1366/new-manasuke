from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from db.connection import transaction
from domain.enums import (
    GoalType,
    Importance,
    StudyTargetKind,
    UnitType,
)
from domain.errors import DomainValidationError
from domain.models import (
    AvailableTime,
    BusyEvent,
    ExtraAvailableTime,
    Goal,
    GoalRange,
    StudyTarget,
    StudyTargetRange,
)
from domain.time_rules import (
    UTC,
    ensure_aware,
)
from repositories.availability_repository import (
    AvailabilityRepository,
)
from repositories.goal_repository import (
    GoalRepository,
)
from repositories.participant_repository import (
    ParticipantRepository,
)
from repositories.study_target_repository import (
    StudyTargetRepository,
)
from scripts.migrate import run_migrations


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "manasuke.db"
)


def parse_datetime(
    value: str,
) -> datetime:
    normalized = value.strip()

    if normalized.endswith("Z"):
        normalized = (
            normalized[:-1]
            + "+00:00"
        )

    try:
        result = datetime.fromisoformat(
            normalized
        )

    except ValueError as exc:
        raise DomainValidationError(
            f"invalid datetime: {value}"
        ) from exc

    ensure_aware(result)

    return result


def require_object(
    value: Any,
    name: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DomainValidationError(
            f"{name} must be an object"
        )

    return value


def require_list(
    value: Any,
    name: str,
) -> list[Any]:
    if not isinstance(value, list):
        raise DomainValidationError(
            f"{name} must be a list"
        )

    return value


def import_participant(
    json_path: str | Path,
    db_path: str | Path,
    *,
    created_at: datetime | None = None,
) -> str:
    json_path = Path(json_path)
    db_path = Path(db_path)

    try:
        raw_payload = json.loads(
            json_path.read_text(
                encoding="utf-8"
            )
        )

    except json.JSONDecodeError as exc:
        raise DomainValidationError(
            "participant JSON is invalid"
        ) from exc

    payload = require_object(
        raw_payload,
        "root",
    )

    participant_id_raw = payload.get(
        "participant_id"
    )

    if not isinstance(
        participant_id_raw,
        str,
    ):
        raise DomainValidationError(
            "participant_id must be a string"
        )

    participant_id = (
        participant_id_raw.strip()
    )

    if not participant_id:
        raise DomainValidationError(
            "participant_id must not be empty"
        )

    study_targets_raw = require_list(
        payload.get(
            "study_targets",
            [],
        ),
        "study_targets",
    )

    goals_raw = require_list(
        payload.get(
            "goals",
            [],
        ),
        "goals",
    )

    available_times_raw = require_list(
        payload.get(
            "available_times",
            [],
        ),
        "available_times",
    )

    busy_events_raw = require_list(
        payload.get(
            "busy_events",
            [],
        ),
        "busy_events",
    )

    extra_available_times_raw = require_list(
        payload.get(
            "extra_available_times",
            [],
        ),
        "extra_available_times",
    )

    timestamp = (
        created_at
        if created_at is not None
        else datetime.now(UTC)
    )

    ensure_aware(timestamp)

    participant_repository = (
        ParticipantRepository(
            db_path
        )
    )

    study_target_repository = (
        StudyTargetRepository(
            db_path
        )
    )

    goal_repository = GoalRepository(
        db_path
    )

    availability_repository = (
        AvailabilityRepository(
            db_path
        )
    )

    with transaction(
        db_path
    ) as connection:
        participant_repository.insert(
            connection,
            participant_id,
            timestamp,
        )

        key_to_target_id: dict[
            str,
            int,
        ] = {}

        # -----------------------------------------
        # StudyTargets
        # -----------------------------------------

        for index, raw in enumerate(
            study_targets_raw
        ):
            item = require_object(
                raw,
                f"study_targets[{index}]",
            )

            key_raw = item.get("key")

            if not isinstance(
                key_raw,
                str,
            ):
                raise DomainValidationError(
                    "StudyTarget key must be a string"
                )

            key = key_raw.strip()

            if not key:
                raise DomainValidationError(
                    "StudyTarget key must not be empty"
                )

            if key in key_to_target_id:
                raise DomainValidationError(
                    f"duplicate StudyTarget key: {key}"
                )

            try:
                kind = StudyTargetKind(
                    item["kind"]
                )

            except (
                KeyError,
                ValueError,
            ) as exc:
                raise DomainValidationError(
                    f"invalid StudyTarget kind for {key}"
                ) from exc

            unit_type_raw = item.get(
                "unit_type"
            )

            unit_type = (
                UnitType(unit_type_raw)
                if unit_type_raw is not None
                else None
            )

            ranges_raw = require_list(
                item.get(
                    "ranges",
                    [],
                ),
                f"ranges for {key}",
            )

            ranges = [
                StudyTargetRange(
                    sequence_no=int(
                        require_object(
                            raw_range,
                            "StudyTargetRange",
                        )["sequence_no"]
                    ),
                    start_position=int(
                        require_object(
                            raw_range,
                            "StudyTargetRange",
                        )["start_position"]
                    ),
                    end_position=int(
                        require_object(
                            raw_range,
                            "StudyTargetRange",
                        )["end_position"]
                    ),
                )
                for raw_range in ranges_raw
            ]

            target = StudyTarget(
                id=0,
                participant_id=participant_id,
                kind=kind,
                title=str(
                    item["title"]
                ),
                unit_type=unit_type,
                next_position=(
                    int(item["next_position"])
                    if item.get(
                        "next_position"
                    ) is not None
                    else None
                ),
                estimated_minutes_per_unit=(
                    float(
                        item[
                            "estimated_minutes_per_unit"
                        ]
                    )
                    if item.get(
                        "estimated_minutes_per_unit"
                    )
                    is not None
                    else None
                ),
                note=item.get("note"),
                ranges=ranges,
            )

            target_id = (
                study_target_repository.insert(
                    connection,
                    participant_id,
                    target,
                )
            )

            key_to_target_id[
                key
            ] = target_id

        # -----------------------------------------
        # Goals
        # -----------------------------------------

        for index, raw in enumerate(
            goals_raw
        ):
            item = require_object(
                raw,
                f"goals[{index}]",
            )

            target_key_raw = item.get(
                "study_target_key"
            )

            if not isinstance(
                target_key_raw,
                str,
            ):
                raise DomainValidationError(
                    "study_target_key "
                    "must be a string"
                )

            target_key = (
                target_key_raw.strip()
            )

            if (
                target_key
                not in key_to_target_id
            ):
                raise DomainValidationError(
                    "unknown study_target_key: "
                    f"{target_key}"
                )

            try:
                goal_type = GoalType(
                    item["goal_type"]
                )
                importance = Importance(
                    item["importance"]
                )

            except (
                KeyError,
                ValueError,
            ) as exc:
                raise DomainValidationError(
                    "invalid Goal enum value"
                ) from exc

            ranges_raw = require_list(
                item.get(
                    "ranges",
                    [],
                ),
                "Goal ranges",
            )

            goal_ranges = [
                GoalRange(
                    start_position=int(
                        require_object(
                            raw_range,
                            "GoalRange",
                        )["start_position"]
                    ),
                    end_position=int(
                        require_object(
                            raw_range,
                            "GoalRange",
                        )["end_position"]
                    ),
                )
                for raw_range in ranges_raw
            ]

            goal = Goal(
                id=0,
                participant_id=participant_id,
                study_target_id=(
                    key_to_target_id[
                        target_key
                    ]
                ),
                goal_type=goal_type,
                title=str(
                    item["title"]
                ),
                deadline_at=parse_datetime(
                    str(
                        item[
                            "deadline_at"
                        ]
                    )
                ),
                importance=importance,
                target_minutes=(
                    int(
                        item[
                            "target_minutes"
                        ]
                    )
                    if item.get(
                        "target_minutes"
                    )
                    is not None
                    else None
                ),
                note=item.get("note"),
                ranges=goal_ranges,
            )

            goal_repository.insert(
                connection,
                participant_id,
                goal,
            )

        # -----------------------------------------
        # Weekly AvailableTime
        # -----------------------------------------

        available_times: list[
            AvailableTime
        ] = []

        for index, raw in enumerate(
            available_times_raw
        ):
            item = require_object(
                raw,
                f"available_times[{index}]",
            )

            available_times.append(
                AvailableTime(
                    weekday=int(
                        item["weekday"]
                    ),
                    start_minute_of_day=int(
                        item[
                            "start_minute_of_day"
                        ]
                    ),
                    end_minute_of_day=int(
                        item[
                            "end_minute_of_day"
                        ]
                    ),
                )
            )

        availability_repository.insert_available_times(
            connection,
            participant_id,
            available_times,
        )

        # -----------------------------------------
        # BusyEvent
        # -----------------------------------------

        for index, raw in enumerate(
            busy_events_raw
        ):
            item = require_object(
                raw,
                f"busy_events[{index}]",
            )

            event = BusyEvent(
                start_at=parse_datetime(
                    str(item["start_at"])
                ),
                end_at=parse_datetime(
                    str(item["end_at"])
                ),
            )

            availability_repository.insert_busy_event(
                connection,
                participant_id,
                event,
                note=item.get("note"),
            )

        # -----------------------------------------
        # ExtraAvailableTime
        # -----------------------------------------

        for index, raw in enumerate(
            extra_available_times_raw
        ):
            item = require_object(
                raw,
                f"extra_available_times[{index}]",
            )

            event = ExtraAvailableTime(
                start_at=parse_datetime(
                    str(item["start_at"])
                ),
                end_at=parse_datetime(
                    str(item["end_at"])
                ),
            )

            availability_repository.insert_extra_available_time(
                connection,
                participant_id,
                event,
                note=item.get("note"),
            )

        # initial setup全体を1回のSource Data変更とみなす
        ParticipantRepository.increment_planning_data_version(
            connection,
            participant_id,
        )

    return participant_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Import a Manasuke experiment participant."
        )
    )

    parser.add_argument(
        "json_path",
        type=Path,
        help="Participant JSON file",
    )

    parser.add_argument(
        "db_path",
        nargs="?",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=(
            "SQLite DB path. "
            "Defaults to data/manasuke.db"
        ),
    )

    args = parser.parse_args()

    run_migrations(
        args.db_path
    )

    participant_id = import_participant(
        args.json_path,
        args.db_path,
    )

    print(
        f"Imported participant: {participant_id}"
    )


if __name__ == "__main__":
    main()