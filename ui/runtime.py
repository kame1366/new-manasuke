from __future__ import annotations

import os
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


def get_experiment_access_key() -> str:
    value = os.getenv(
        "MANASUKE_EXPERIMENT_ACCESS_KEY"
    )

    if value is None:
        raise RuntimeError(
            "MANASUKE_EXPERIMENT_ACCESS_KEY "
            "is not configured"
        )

    value = value.strip()

    if not value:
        raise RuntimeError(
            "MANASUKE_EXPERIMENT_ACCESS_KEY "
            "must not be empty"
        )

    return value