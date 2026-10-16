from __future__ import annotations

import os
import json
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


DEFAULT_DB_PATH = Path(
    "data/manasuke.db"
)


def get_db_path() -> Path:
    raw = os.getenv(
        "MANASUKE_DB_PATH"
    )

    if raw is None:
        return DEFAULT_DB_PATH

    value = raw.strip()

    if not value:
        return DEFAULT_DB_PATH

    return Path(value)


def get_participant_invite_keys() -> dict[str, str]:
    """Return private, per-participant invite keys from server environment.

    Example: MANASUKE_INVITE_KEYS_JSON='{"participant-01":"<random-key>"}'
    Misconfiguration fails closed (the shared experiment key is not accepted).
    """
    raw = os.getenv("MANASUKE_INVITE_KEYS_JSON", "")
    if not raw.strip():
        raise RuntimeError("MANASUKE_INVITE_KEYS_JSON is not configured")

    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid MANASUKE_INVITE_KEYS_JSON") from exc

    if not isinstance(mapping, dict) or not mapping:
        raise RuntimeError("Invite key mapping must be a nonempty object")

    parsed: dict[str, str] = {}
    for participant_id, key in mapping.items():
        if (
            not isinstance(participant_id, str)
            or not participant_id.strip()
            or participant_id != participant_id.strip()
            or not isinstance(key, str)
            or len(key) < 16
            or key != key.strip()
            or "REPLACE" in key.upper()
            or "CHANGE-ME" in key.upper()
        ):
            raise RuntimeError("Invalid participant invite key configuration")
        parsed[participant_id] = key

    if len(set(parsed.values())) != len(parsed):
        raise RuntimeError("Invite keys must be unique for each participant")
    return parsed
