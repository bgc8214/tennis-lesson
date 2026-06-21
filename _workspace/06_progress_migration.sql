ALTER TABLE lesson_reports
  ADD COLUMN IF NOT EXISTS progress_message TEXT,
  ADD COLUMN IF NOT EXISTS progress_step    SMALLINT DEFAULT 0;
