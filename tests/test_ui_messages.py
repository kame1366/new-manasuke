from services.plan_generation_pipeline_service import (
    SourceDataIncompleteError,
)
from ui.messages import (
    user_message_for_exception,
)


def test_missing_learning_policy_has_actionable_message():
    message = user_message_for_exception(
        SourceDataIncompleteError(
            "LearningPolicy must exist before "
            "Plan generation; missing=[1, 2], extra=[]"
        )
    )

    assert "学習方針が未生成です" in message
    assert (
        "generate_learning_policies.py"
        in message
    )
