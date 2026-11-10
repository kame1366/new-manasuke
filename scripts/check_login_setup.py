"""Verify login configuration without revealing any access keys."""
from __future__ import annotations

import argparse
import sqlite3

from repositories.participant_repository import ParticipantRepository
from ui.runtime import (
    get_auth_mode,
    get_db_path,
    get_participant_invite_keys,
    get_shared_experiment_access_key,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manasukeログイン設定の診断")
    parser.add_argument("participant_id", nargs="?", help="ログインしたい参加者ID")
    args = parser.parse_args()

    try:
        mode = get_auth_mode()
        if mode == "shared":
            get_shared_experiment_access_key()  # Validate; never print the key.
        else:
            invite_keys = get_participant_invite_keys()
    except RuntimeError as exc:
        print(f"認証設定エラー: {exc}")
        return 1

    print(f"認証設定: OK ({mode})")
    db_path = get_db_path()
    print(f"参照DB: {db_path.resolve()}")
    if not db_path.is_file():
        print("DBエラー: ファイルがありません。MANASUKE_DB_PATHを確認してください。")
        return 1

    try:
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0]
        print(f"登録済み参加者数: {count}")
        if args.participant_id:
            exists = ParticipantRepository(db_path).exists(args.participant_id.strip())
            if not exists:
                print("参加者IDエラー: DBに登録されていません。")
                return 1
            if mode == "individual" and args.participant_id.strip() not in invite_keys:
                print("招待キー設定エラー: この参加者IDのキーがありません。")
                return 1
            print("指定した参加者ID: ログイン対象として設定されています。")
    except sqlite3.Error as exc:
        print(f"DBエラー: {exc}。マイグレーションを確認してください。")
        return 1

    print("診断OK: 認証設定とDBの基本条件を確認しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
