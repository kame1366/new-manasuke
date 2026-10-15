-- StudyTargetのアーカイブ状態
ALTER TABLE study_targets
ADD COLUMN archived_at TEXT DEFAULT NULL;

-- Goalのアーカイブ状態
ALTER TABLE goals
ADD COLUMN archived_at TEXT DEFAULT NULL;

-- 有効なデータの検索用
CREATE INDEX IF NOT EXISTS
idx_study_targets_participant_archived
ON study_targets(participant_id, archived_at);

CREATE INDEX IF NOT EXISTS
idx_goals_participant_archived
ON goals(participant_id, archived_at);