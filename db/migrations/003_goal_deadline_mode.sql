ALTER TABLE goals
ADD COLUMN deadline_is_date_only INTEGER NOT NULL DEFAULT 0
CHECK (deadline_is_date_only IN (0, 1));