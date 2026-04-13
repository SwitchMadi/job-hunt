-- Human captcha tasks (Slack + DCV). Webhook updates by slack_channel_id + slack_message_id.
-- Apply manually against your RDS instance when ready.
-- If you already created users.slack_interactive_requests, run 002_migrate_slack_interactive_to_captcha_tasks.sql instead.

CREATE TABLE IF NOT EXISTS users.captcha_tasks (
    id                          BIGSERIAL PRIMARY KEY,
    task_kind                   VARCHAR(64) NOT NULL DEFAULT 'captcha_dcv',
    status                      VARCHAR(32) NOT NULL DEFAULT 'pending',
    job_application_id          INTEGER REFERENCES users.job_applications (id) ON DELETE SET NULL,
    job_id                      INTEGER REFERENCES jobs.jobs (id) ON DELETE SET NULL,
    user_id                     INTEGER REFERENCES users.users (id) ON DELETE SET NULL,
    slack_channel_id            VARCHAR(64),
    slack_message_ts_epoch_ms   BIGINT,
    slack_message_id            VARCHAR(64),
    completed_by_slack_user_id VARCHAR(32),
    completed_at                TIMESTAMPTZ,
    resolution_notes            TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_captcha_task_status CHECK (
        status IN ('pending', 'completed', 'failed', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS idx_captcha_tasks_status_created
    ON users.captcha_tasks (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_captcha_tasks_slack_ts
    ON users.captcha_tasks (slack_channel_id, slack_message_ts_epoch_ms);

CREATE INDEX IF NOT EXISTS idx_captcha_tasks_slack_message
    ON users.captcha_tasks (slack_channel_id, slack_message_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_captcha_tasks_pending_per_application
    ON users.captcha_tasks (job_application_id)
    WHERE status = 'pending' AND task_kind = 'captcha_dcv';
