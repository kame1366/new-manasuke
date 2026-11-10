"""Create an empty participant in the same SQLite DB the app uses.

Run from project root:
    python -m scripts.create_participant student001
Or interactively:
    python -m scripts.create_participant

Initialize the database first with: python -m scripts.migrate
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

from domain.time_rules import UTC
from repositories.participant_repository import ParticipantRepository
from ui.runtime import get_db_path


def create_participant(
    participant_id: str, db_path: str | Path | None = None
) -> str:
    """Insert only the participants row; study settings start empty.

    The function never creates a new database or overwrites a participant.
    """
    normalized_id = participant_id.strip()
    if not normalized_id or len(normalized_id) > 128 or not normalized_id.isprintable():
        raise ValueError("参加者IDは1〜128文字の印字可能な文字列にしてください。")

    db_path = Path(db_path) if db_path is not None else get_db_path()
    if not db_path.is_file():
        raise FileNotFoundError(
            f"DBが見つかりません: {db_path}。"
            "まず python -m scripts.migrate を実行してください。"
        )

    # Reuse the project's timestamp conversion, transaction, and DB schema.
    ParticipantRepository(db_path).create(normalized_id, datetime.now(UTC))
    return normalized_id


def create_empty_participant(
    participant_id: str, db_path: str | Path | None = None
) -> str:
    """Backward-compatible name for the same participant creation operation."""
    return create_participant(participant_id, db_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manasukeに空の参加者データを登録する管理者用コマンド"
    )
    parser.add_argument(
        "participant_id", nargs="?", help="新しい参加者ID（省略時は入力）"
    )
    parser.add_argument(
        "--db", type=Path, default=None, help="SQLiteファイル（省略時はMANASUKE_DB_PATH）"
    )
    args = parser.parse_args()
    participant_id = args.participant_id
    if participant_id is None:
        participant_id = input("登録する参加者ID: ")

    db_path = args.db if args.db is not None else get_db_path()
    try:
        result = create_participant(participant_id, db_path)
    except ValueError as exc:
        print(f"入力エラー: {exc}")
        return 1
    except FileNotFoundError as exc:
        print(f"設定エラー: {exc}")
        return 1
    except sqlite3.IntegrityError:
        print("登録失敗: 同じ参加者IDが既に存在します（上書きしません）。")
        return 1
    except sqlite3.Error as exc:
        print(f"DBエラー: {exc}。DBパスとマイグレーションを確認してください。")
        return 1

    print(f"登録成功: {result} (DB: {db_path})")
    print("StudyTarget、Goal、学習可能時間は未登録の初期状態です。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
