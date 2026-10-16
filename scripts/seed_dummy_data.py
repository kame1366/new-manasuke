from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from domain.time_rules import JST
from scripts.import_participant import import_participant
from scripts.migrate import DEFAULT_DB_PATH, run_migrations


def build_dummy_payload(
    participant_id: str,
    reference_date: datetime,
) -> dict[str, Any]:
    """Build a representative participant payload for local development."""

    deadline = reference_date + timedelta(days=14)
    busy_start = reference_date + timedelta(days=1)
    busy_end = busy_start + timedelta(hours=1)
    extra_start = reference_date + timedelta(days=2, hours=9)
    extra_end = extra_start + timedelta(hours=2)

    return {
        "participant_id": participant_id,
        "study_targets": [
            {
                "key": "math_book",
                "kind": "MATERIAL",
                "title": "数学問題集",
                "unit_type": "PAGE",
                "next_position": 1,
                "estimated_minutes_per_unit": 5.0,
                "ranges": [
                    {
                        "sequence_no": 0,
                        "start_position": 1,
                        "end_position": 120,
                    }
                ],
            },
            {
                "key": "english_writing",
                "kind": "THEME",
                "title": "英作文練習",
                "note": "自由英作文の練習",
            },
        ],
        "goals": [
            {
                "study_target_key": "math_book",
                "goal_type": "TEST",
                "title": "数学テスト",
                "deadline_at": deadline.isoformat(),
                "importance": "HIGH",
                "target_minutes": 600,
                "ranges": [
                    {
                        "start_position": 1,
                        "end_position": 80,
                    }
                ],
            }
        ],
        "available_times": [
            {
                "weekday": weekday,
                "start_minute_of_day": 1080,
                "end_minute_of_day": 1200,
            }
            for weekday in range(5)
        ],
        "busy_events": [
            {
                "start_at": busy_start.isoformat(),
                "end_at": busy_end.isoformat(),
                "note": "予定",
            }
        ],
        "extra_available_times": [
            {
                "start_at": extra_start.isoformat(),
                "end_at": extra_end.isoformat(),
                "note": "追加学習可能時間",
            }
        ],
    }


def seed_dummy_data(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    count: int = 3,
    prefix: str = "dummy-user",
    reference_date: datetime | None = None,
) -> list[str]:
    """Insert deterministic, representative dummy participants."""

    if count < 1:
        raise ValueError("count must be at least 1")

    normalized_prefix = prefix.strip()
    if not normalized_prefix:
        raise ValueError("prefix must not be empty")

    timestamp = reference_date or datetime.now(JST)
    if timestamp.tzinfo is None:
        raise ValueError("reference_date must be timezone-aware")

    database_path = Path(db_path)
    run_migrations(database_path)

    participant_ids: list[str] = []
    with tempfile.TemporaryDirectory() as temporary_directory:
        for number in range(1, count + 1):
            participant_id = f"{normalized_prefix}-{number:03d}"
            payload = build_dummy_payload(
                participant_id,
                timestamp,
            )
            json_path = (
                Path(temporary_directory)
                / f"{participant_id}.json"
            )
            json_path.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            participant_ids.append(
                import_participant(
                    json_path,
                    database_path,
                    created_at=timestamp,
                )
            )

    return participant_ids


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Insert representative dummy participants into a Manasuke database."
        )
    )
    parser.add_argument(
        "db_path",
        nargs="?",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite DB path (defaults to data/manasuke.db)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="Number of participants to insert (defaults to 3)",
    )
    parser.add_argument(
        "--prefix",
        default="dummy-user",
        help="Participant ID prefix (defaults to dummy-user)",
    )
    args = parser.parse_args()

    participant_ids = seed_dummy_data(
        args.db_path,
        count=args.count,
        prefix=args.prefix,
    )

    for participant_id in participant_ids:
        print(f"Inserted dummy participant: {participant_id}")


if __name__ == "__main__":
    main()
