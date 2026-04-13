-- Optional: only if you already applied the old slack_interactive_requests migration.
-- Review and run statements manually; names may differ per cluster.

-- ALTER TABLE users.slack_interactive_requests RENAME TO captcha_tasks;
-- ALTER TABLE users.captcha_tasks RENAME COLUMN request_kind TO task_kind;
-- ALTER TABLE users.captcha_tasks RENAME CONSTRAINT chk_slack_interactive_status TO chk_captcha_task_status;
-- Then rename indexes to match 001_captcha_tasks.sql or drop/recreate them.
