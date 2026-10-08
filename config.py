from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """
    必須environment configurationが
    不正・不足している場合のエラー。
    """


@dataclass(
    frozen=True,
    slots=True,
)
class Settings:
    openai_api_key: str
    openai_model: str

    openai_max_retries: int
    openai_timeout_seconds: float


def _require_env(
    name: str,
) -> str:
    value = os.getenv(
        name
    )

    if value is None:
        raise ConfigurationError(
            f"{name} is not set"
        )

    normalized = value.strip()

    if not normalized:
        raise ConfigurationError(
            f"{name} must not be empty"
        )

    return normalized


def _read_max_retries() -> int:
    raw = os.getenv(
        "OPENAI_MAX_RETRIES",
        "1",
    )

    try:
        value = int(
            raw
        )

    except ValueError as exc:
        raise ConfigurationError(
            "OPENAI_MAX_RETRIES must "
            "be an integer"
        ) from exc

    if value not in {
        1,
        2,
    }:
        raise ConfigurationError(
            "OPENAI_MAX_RETRIES must "
            "be 1 or 2"
        )

    return value


def _read_timeout_seconds() -> float:
    raw = os.getenv(
        "OPENAI_TIMEOUT_SECONDS",
        "120",
    )

    try:
        value = float(
            raw
        )

    except ValueError as exc:
        raise ConfigurationError(
            "OPENAI_TIMEOUT_SECONDS "
            "must be numeric"
        ) from exc

    if value <= 0:
        raise ConfigurationError(
            "OPENAI_TIMEOUT_SECONDS "
            "must be positive"
        )

    return value


@lru_cache
def get_settings() -> Settings:
    """
    Environmentから設定を一度だけ読み込む。

    API keyやmodel名をコードへ
    hard-codeしない。
    """
    load_dotenv()

    return Settings(
        openai_api_key=(
            _require_env(
                "OPENAI_API_KEY"
            )
        ),
        openai_model=(
            _require_env(
                "OPENAI_MODEL"
            )
        ),
        openai_max_retries=(
            _read_max_retries()
        ),
        openai_timeout_seconds=(
            _read_timeout_seconds()
        ),
    )