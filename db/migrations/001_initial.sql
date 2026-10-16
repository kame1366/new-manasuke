CREATE TABLE participants (
    id TEXT PRIMARY KEY,
    planning_data_version INTEGER NOT NULL DEFAULT 0
        CHECK (planning_data_version >= 0),
    created_at TEXT NOT NULL
);


CREATE TABLE study_targets (
    id INTEGER PRIMARY KEY,
    participant_id TEXT NOT NULL,

    kind TEXT NOT NULL
        CHECK (kind IN ('MATERIAL', 'THEME')),

    title TEXT NOT NULL
        CHECK (length(trim(title)) > 0),

    unit_type TEXT
        CHECK (
            unit_type IS NULL
            OR unit_type IN (
                'PAGE',
                'PROBLEM',
                'WORD',
                'SECTION',
                'OTHER'
            )
        ),

    next_position INTEGER
        CHECK (
            next_position IS NULL
            OR next_position >= 0
        ),

    estimated_minutes_per_unit REAL
        CHECK (
            estimated_minutes_per_unit IS NULL
            OR estimated_minutes_per_unit > 0
        ),

    note TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    CHECK (
        (
            kind = 'MATERIAL'
            AND unit_type IS NOT NULL
            AND next_position IS NOT NULL
            AND estimated_minutes_per_unit IS NOT NULL
        )
        OR
        (
            kind = 'THEME'
            AND unit_type IS NULL
            AND next_position IS NULL
            AND estimated_minutes_per_unit IS NULL
        )
    ),

    FOREIGN KEY (participant_id)
        REFERENCES participants(id)
        ON DELETE CASCADE
);


CREATE TABLE study_target_ranges (
    id INTEGER PRIMARY KEY,
    study_target_id INTEGER NOT NULL,

    sequence_no INTEGER NOT NULL
        CHECK (sequence_no >= 0),

    start_position INTEGER NOT NULL,
    end_position INTEGER NOT NULL,

    CHECK (start_position <= end_position),

    UNIQUE (
        study_target_id,
        sequence_no
    ),

    FOREIGN KEY (study_target_id)
        REFERENCES study_targets(id)
        ON DELETE CASCADE
);


CREATE TABLE goals (
    id INTEGER PRIMARY KEY,

    participant_id TEXT NOT NULL,
    study_target_id INTEGER NOT NULL,

    goal_type TEXT NOT NULL
        CHECK (
            goal_type IN (
                'TEST',
                'ASSIGNMENT',
                'CERTIFICATION',
                'PERSONAL',
                'OTHER'
            )
        ),

    title TEXT NOT NULL
        CHECK (length(trim(title)) > 0),

    deadline_at TEXT NOT NULL,

    importance TEXT NOT NULL
        CHECK (
            importance IN (
                'HIGH',
                'MEDIUM',
                'LOW'
            )
        ),

    target_minutes INTEGER
        CHECK (
            target_minutes IS NULL
            OR target_minutes >= 0
        ),

    note TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (participant_id)
        REFERENCES participants(id)
        ON DELETE CASCADE,

    FOREIGN KEY (study_target_id)
        REFERENCES study_targets(id)
        ON DELETE CASCADE
);


CREATE TABLE goal_ranges (
    id INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL,

    start_position INTEGER NOT NULL,
    end_position INTEGER NOT NULL,

    CHECK (start_position <= end_position),

    FOREIGN KEY (goal_id)
        REFERENCES goals(id)
        ON DELETE CASCADE
);


CREATE TABLE learning_policies (
    id INTEGER PRIMARY KEY,

    participant_id TEXT NOT NULL,
    study_target_id INTEGER NOT NULL,

    purpose TEXT NOT NULL
        CHECK (length(trim(purpose)) > 0),

    policy_priority TEXT NOT NULL
        CHECK (
            policy_priority IN (
                'HIGH',
                'MEDIUM',
                'LOW'
            )
        ),

    normal_sessions_per_week INTEGER NOT NULL
        CHECK (
            normal_sessions_per_week
            BETWEEN 0 AND 7
        ),

    normal_minutes INTEGER NOT NULL
        CHECK (
            normal_minutes >= 0
            AND normal_minutes % 5 = 0
        ),

    minimum_sessions_per_week INTEGER NOT NULL
        CHECK (
            minimum_sessions_per_week
            BETWEEN 0 AND 7
        ),

    minimum_minutes INTEGER NOT NULL
        CHECK (
            minimum_minutes >= 0
            AND minimum_minutes % 5 = 0
        ),

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE (
        participant_id,
        study_target_id
    ),

    FOREIGN KEY (participant_id)
        REFERENCES participants(id)
        ON DELETE CASCADE,

    FOREIGN KEY (study_target_id)
        REFERENCES study_targets(id)
        ON DELETE CASCADE
);


CREATE TABLE available_times (
    id INTEGER PRIMARY KEY,

    participant_id TEXT NOT NULL,

    weekday INTEGER NOT NULL
        CHECK (weekday BETWEEN 0 AND 6),

    start_minute_of_day INTEGER NOT NULL,
    end_minute_of_day INTEGER NOT NULL,

    CHECK (
        0 <= start_minute_of_day
        AND start_minute_of_day < end_minute_of_day
        AND end_minute_of_day <= 1440
    ),

    FOREIGN KEY (participant_id)
        REFERENCES participants(id)
        ON DELETE CASCADE
);


CREATE TABLE busy_events (
    id INTEGER PRIMARY KEY,

    participant_id TEXT NOT NULL,

    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,

    note TEXT,

    CHECK (start_at < end_at),

    FOREIGN KEY (participant_id)
        REFERENCES participants(id)
        ON DELETE CASCADE
);


CREATE TABLE extra_available_times (
    id INTEGER PRIMARY KEY,

    participant_id TEXT NOT NULL,

    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,

    note TEXT,

    CHECK (start_at < end_at),

    FOREIGN KEY (participant_id)
        REFERENCES participants(id)
        ON DELETE CASCADE
);


CREATE TABLE plans (
    id INTEGER PRIMARY KEY,

    participant_id TEXT NOT NULL,

    version_no INTEGER NOT NULL
        CHECK (version_no >= 1),

    created_at TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    horizon_end TEXT NOT NULL,

    source_planning_data_version INTEGER NOT NULL
        CHECK (source_planning_data_version >= 0),

    CHECK (effective_from < horizon_end),

    UNIQUE (
        participant_id,
        version_no
    ),

    FOREIGN KEY (participant_id)
        REFERENCES participants(id)
        ON DELETE CASCADE
);


CREATE TABLE plan_items (
    id INTEGER PRIMARY KEY,

    plan_id INTEGER NOT NULL,
    study_target_id INTEGER NOT NULL,

    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,

    origin TEXT NOT NULL
        CHECK (
            origin IN (
                'SYSTEM_GENERATED',
                'USER_MODIFIED',
                'USER_CREATED'
            )
        ),

    is_cancelled INTEGER NOT NULL DEFAULT 0
        CHECK (is_cancelled IN (0, 1)),

    cancelled_at TEXT,

    carried_from_plan_item_id INTEGER,

    planned_minutes INTEGER NOT NULL
        CHECK (
            planned_minutes > 0
            AND planned_minutes % 5 = 0
        ),

    range_start INTEGER,
    range_end INTEGER,

    created_at TEXT NOT NULL,

    CHECK (start_at < end_at),

    CHECK (
        (
            range_start IS NULL
            AND range_end IS NULL
        )
        OR
        (
            range_start IS NOT NULL
            AND range_end IS NOT NULL
            AND range_start <= range_end
        )
    ),

    CHECK (
        (
            is_cancelled = 0
            AND cancelled_at IS NULL
        )
        OR
        (
            is_cancelled = 1
            AND cancelled_at IS NOT NULL
        )
    ),

    FOREIGN KEY (plan_id)
        REFERENCES plans(id)
        ON DELETE CASCADE,

    FOREIGN KEY (study_target_id)
        REFERENCES study_targets(id)
        ON DELETE CASCADE,

    FOREIGN KEY (carried_from_plan_item_id)
        REFERENCES plan_items(id)
        ON DELETE SET NULL
);


CREATE TABLE plan_item_adjustments (
    id INTEGER PRIMARY KEY,

    plan_item_id INTEGER NOT NULL,

    adjustment_type TEXT NOT NULL,

    created_at TEXT NOT NULL,

    old_snapshot_json TEXT NOT NULL,
    new_snapshot_json TEXT NOT NULL,

    FOREIGN KEY (plan_item_id)
        REFERENCES plan_items(id)
        ON DELETE CASCADE
);


CREATE TABLE study_results (
    id INTEGER PRIMARY KEY,

    participant_id TEXT NOT NULL,

    plan_item_id INTEGER NOT NULL,
    study_target_id INTEGER NOT NULL,

    status TEXT NOT NULL
        CHECK (
            status IN (
                'COMPLETED',
                'PARTIAL',
                'NOT_DONE'
            )
        ),

    actual_end_position INTEGER,

    actual_minutes INTEGER
        CHECK (
            actual_minutes IS NULL
            OR actual_minutes >= 0
        ),

    time_feeling TEXT,
    memo TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE (plan_item_id),

    FOREIGN KEY (participant_id)
        REFERENCES participants(id)
        ON DELETE CASCADE,

    FOREIGN KEY (plan_item_id)
        REFERENCES plan_items(id)
        ON DELETE CASCADE,

    FOREIGN KEY (study_target_id)
        REFERENCES study_targets(id)
        ON DELETE CASCADE
);


CREATE TABLE study_result_revisions (
    id INTEGER PRIMARY KEY,

    study_result_id INTEGER NOT NULL,

    revised_at TEXT NOT NULL,

    old_snapshot_json TEXT NOT NULL,
    new_snapshot_json TEXT NOT NULL,

    FOREIGN KEY (study_result_id)
        REFERENCES study_results(id)
        ON DELETE CASCADE
);


CREATE TABLE plan_generation_attempts (
    id INTEGER PRIMARY KEY,

    participant_id TEXT NOT NULL,

    operation_type TEXT NOT NULL
        CHECK (
            operation_type IN (
                'INITIAL',
                'REPLAN_NOW',
                'REPLAN_TOMORROW'
            )
        ),

    source_planning_data_version INTEGER NOT NULL
        CHECK (
            source_planning_data_version >= 0
        ),

    status TEXT NOT NULL
        CHECK (
            status IN (
                'IN_PROGRESS',
                'SUCCEEDED',
                'FAILED',
                'ABANDONED'
            )
        ),

    stage TEXT NOT NULL
        CHECK (
            stage IN (
                'FEASIBILITY',
                'AWAITING_GOAL_DECISION',
                'AI_PLANNING',
                'SCHEDULING'
            )
        ),

    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    completed_at TEXT,
    error_type TEXT,

    resulting_plan_id INTEGER,

    FOREIGN KEY (participant_id)
        REFERENCES participants(id)
        ON DELETE CASCADE,

    FOREIGN KEY (resulting_plan_id)
        REFERENCES plans(id)
        ON DELETE SET NULL
);


CREATE UNIQUE INDEX
ux_plan_attempt_one_in_progress
ON plan_generation_attempts(participant_id)
WHERE status = 'IN_PROGRESS';


CREATE TABLE plan_goal_decisions (
    id INTEGER PRIMARY KEY,

    attempt_id INTEGER NOT NULL,
    goal_id INTEGER NOT NULL,

    mode TEXT NOT NULL
        CHECK (
            mode IN (
                'STRICT',
                'BEST_EFFORT'
            )
        ),

    decision_source TEXT NOT NULL
        CHECK (
            decision_source IN (
                'AUTO_ALL_STRICT',
                'USER_CONFIRMED'
            )
        ),

    individually_feasible INTEGER NOT NULL
        CHECK (
            individually_feasible IN (0, 1)
        ),

    estimated_required_minutes INTEGER NOT NULL
        CHECK (
            estimated_required_minutes >= 0
        ),

    individual_shortage_minutes INTEGER NOT NULL
        CHECK (
            individual_shortage_minutes >= 0
        ),

    created_at TEXT NOT NULL,

    UNIQUE (
        attempt_id,
        goal_id
    ),

    FOREIGN KEY (attempt_id)
        REFERENCES plan_generation_attempts(id)
        ON DELETE CASCADE,

    FOREIGN KEY (goal_id)
        REFERENCES goals(id)
        ON DELETE CASCADE
);


CREATE TABLE plan_feasibility_snapshots (
    id INTEGER PRIMARY KEY,

    attempt_id INTEGER NOT NULL,

    phase TEXT NOT NULL
        CHECK (
            phase IN (
                'BASELINE_ALL_STRICT',
                'FINAL_SELECTION'
            )
        ),

    total_projected_capacity_minutes INTEGER NOT NULL
        CHECK (
            total_projected_capacity_minutes >= 0
        ),

    normalized_required_minutes INTEGER NOT NULL
        CHECK (
            normalized_required_minutes >= 0
        ),

    aggregate_shortage_minutes INTEGER NOT NULL
        CHECK (
            aggregate_shortage_minutes >= 0
        ),

    strict_set_feasible INTEGER NOT NULL
        CHECK (
            strict_set_feasible IN (0, 1)
        ),

    created_at TEXT NOT NULL,

    UNIQUE (
        attempt_id,
        phase
    ),

    FOREIGN KEY (attempt_id)
        REFERENCES plan_generation_attempts(id)
        ON DELETE CASCADE
);


CREATE TABLE plan_feasibility_deadline_snapshots (
    id INTEGER PRIMARY KEY,

    snapshot_id INTEGER NOT NULL,

    deadline_at TEXT NOT NULL,

    cumulative_required_minutes INTEGER NOT NULL
        CHECK (
            cumulative_required_minutes >= 0
        ),

    cumulative_available_minutes INTEGER NOT NULL
        CHECK (
            cumulative_available_minutes >= 0
        ),

    cumulative_shortage_minutes INTEGER NOT NULL
        CHECK (
            cumulative_shortage_minutes >= 0
        ),

    feasible INTEGER NOT NULL
        CHECK (
            feasible IN (0, 1)
        ),

    FOREIGN KEY (snapshot_id)
        REFERENCES plan_feasibility_snapshots(id)
        ON DELETE CASCADE
);


CREATE TABLE ai_interactions (
    id INTEGER PRIMARY KEY,

    participant_id TEXT NOT NULL,

    attempt_id INTEGER,

    operation_type TEXT NOT NULL,

    created_at TEXT NOT NULL,

    prompt_version TEXT NOT NULL,
    model_name TEXT NOT NULL,

    structured_output_json TEXT,

    status TEXT NOT NULL,
    error_type TEXT,

    FOREIGN KEY (participant_id)
        REFERENCES participants(id)
        ON DELETE CASCADE,

    FOREIGN KEY (attempt_id)
        REFERENCES plan_generation_attempts(id)
        ON DELETE CASCADE
);


CREATE INDEX idx_study_targets_participant
ON study_targets(participant_id);

CREATE INDEX idx_goals_participant
ON goals(participant_id);

CREATE INDEX idx_available_times_participant
ON available_times(participant_id);

CREATE INDEX idx_busy_events_participant
ON busy_events(participant_id);

CREATE INDEX idx_extra_available_times_participant
ON extra_available_times(participant_id);

CREATE INDEX idx_plans_participant
ON plans(participant_id);

CREATE INDEX idx_plan_items_plan
ON plan_items(plan_id);

CREATE INDEX idx_plan_items_study_target
ON plan_items(study_target_id);

CREATE INDEX idx_study_results_participant
ON study_results(participant_id);

CREATE INDEX idx_attempts_participant
ON plan_generation_attempts(participant_id);

CREATE INDEX idx_ai_interactions_participant
ON ai_interactions(participant_id);