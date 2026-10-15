
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from domain.models import AvailableTime
from repositories.availability_repository import (
    AvailabilityRepository,
)


def parse_clock(value: str, *, allow_24: bool = False) -> int:
    """HH:MMを0〜1440の分数へ変換する。"""

    if (
        len(value) != 5
        or value[2] != ":"
        or not value[:2].isdigit()
        or not value[3:].isdigit()
    ):
        raise ValueError(f"時刻の形式が正しくありません: {value}")

    hour = int(value[:2])
    minute = int(value[3:])

    if hour == 24 and minute == 0 and allow_24:
        return 1440

    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"無効な時刻です: {value}")

    if minute % 5 != 0:
        raise ValueError("時刻は5分単位で指定してください。")

    return hour * 60 + minute


class WeeklyAvailabilityService:
    def __init__(self, db_path: str | Path):
        self._repository = AvailabilityRepository(db_path)

    def save(
        self,
        *,
        participant_id: str,
        weekly_slots: Mapping[
            int, Sequence[tuple[str, str]]
        ],
        expected_version: int,
    ) -> int:
        """
        7曜日の時間帯を検証・正規化して一括保存。

        深夜またぎは翌曜日へ分割する。
        重複・隣接区間は統合する。
        """

        if set(weekly_slots) != set(range(7)):
            raise ValueError("7曜日すべての設定が必要です。")

        by_day: dict[int, list[tuple[int, int]]] = {
            day: [] for day in range(7)
        }

        for day, slots in weekly_slots.items():
            for start_text, end_text in slots:
                start = parse_clock(start_text)
                end = parse_clock(end_text, allow_24=True)

                if start == end:
                    raise ValueError(
                        "開始時刻と終了時刻を同じにはできません。"
                    )

                if end > start:
                    by_day[day].append((start, end))
                else:
                    # 当日の残り
                    by_day[day].append((start, 1440))

                    # 翌日の開始部分
                    if end > 0:
                        next_day = (day + 1) % 7
                        by_day[next_day].append((0, end))

        normalized: list[AvailableTime] = []

        for day in range(7):
            intervals = sorted(by_day[day])
            merged: list[list[int]] = []

            for start, end in intervals:
                if merged and start <= merged[-1][1]:
                    merged[-1][1] = max(
                        merged[-1][1], end
                    )
                else:
                    merged.append([start, end])

            for start, end in merged:
                normalized.append(
                    AvailableTime(
                        weekday=day,
                        start_minute_of_day=start,
                        end_minute_of_day=end,
                    )
                )

        self._repository.replace_available_times_if_version(
            participant_id=participant_id,
            available_times=normalized,
            expected_version=expected_version,
        )

        return len(normalized)
