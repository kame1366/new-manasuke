from enum import Enum


class StudyTargetKind(str, Enum):
    MATERIAL = "MATERIAL"
    THEME = "THEME"


class UnitType(str, Enum):
    PAGE = "PAGE"
    PROBLEM = "PROBLEM"
    WORD = "WORD"
    SECTION = "SECTION"
    OTHER = "OTHER"


class GoalType(str, Enum):
    TEST = "TEST"
    ASSIGNMENT = "ASSIGNMENT"
    CERTIFICATION = "CERTIFICATION"
    PERSONAL = "PERSONAL"
    OTHER = "OTHER"


class Importance(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PlanItemOrigin(str, Enum):
    SYSTEM_GENERATED = "SYSTEM_GENERATED"
    USER_MODIFIED = "USER_MODIFIED"
    USER_CREATED = "USER_CREATED"


class StudyResultStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    NOT_DONE = "NOT_DONE"


class PlanOperationType(str, Enum):
    INITIAL = "INITIAL"
    REPLAN_NOW = "REPLAN_NOW"
    REPLAN_TOMORROW = "REPLAN_TOMORROW"


class AttemptStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class AttemptStage(str, Enum):
    FEASIBILITY = "FEASIBILITY"
    AWAITING_GOAL_DECISION = "AWAITING_GOAL_DECISION"
    AI_PLANNING = "AI_PLANNING"
    SCHEDULING = "SCHEDULING"


class GoalMode(str, Enum):
    STRICT = "STRICT"
    BEST_EFFORT = "BEST_EFFORT"