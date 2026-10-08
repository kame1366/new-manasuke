from __future__ import annotations

import argparse
from pathlib import Path

from openai import OpenAI

from ai.learning_policy_generator import (
    LearningPolicyGenerator,
)
from config import get_settings
from services.learning_policy_generation_service import (
    LearningPolicyGenerationService,
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

DEFAULT_DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "manasuke.db"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate LearningPolicies "
            "for a Manasuke participant."
        )
    )

    parser.add_argument(
        "participant_id",
        type=str,
        help="Participant ID",
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

    settings = (
        get_settings()
    )

    client = OpenAI(
        api_key=(
            settings.openai_api_key
        ),
        max_retries=(
            settings.openai_max_retries
        ),
        timeout=(
            settings
            .openai_timeout_seconds
        ),
    )

    generator = (
        LearningPolicyGenerator(
            client=client,
            model_name=(
                settings.openai_model
            ),
        )
    )

    service = (
        LearningPolicyGenerationService(
            db_path=args.db_path,
            generator=generator,
        )
    )

    result = (
        service
        .generate_for_participant(
            args.participant_id
        )
    )

    print(
        "LearningPolicy generation succeeded."
    )

    print(
        "interaction_id:",
        result.interaction_id,
    )

    print(
        "planning_data_version:",
        (
            result
            .source_planning_data_version
        ),
        "->",
        (
            result
            .resulting_planning_data_version
        ),
    )

    print(
        "policies:"
    )

    for policy in result.policies:
        print(
            "-",
            policy.study_target_id,
            policy.policy_priority.value,
            (
                f"normal="
                f"{policy.normal_sessions_per_week}"
                f"x{policy.normal_minutes}min"
            ),
            (
                f"minimum="
                f"{policy.minimum_sessions_per_week}"
                f"x{policy.minimum_minutes}min"
            ),
            policy.purpose,
        )


if __name__ == "__main__":
    main()