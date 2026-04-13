-- Slack human-in-the-loop requests (e.g. captcha + DCV). Webhook handler should UPDATE by id or by slack_message_ts + channel.
-- Apply manually against your RDS instance when ready.

CREATE TABLE IF NOT EXISTS users.slack_interactive_requests (
    id                  BIGSERIAL PRIMARY KEY,
    request_kind        VARCHAR(64) NOT NULL DEFAULT 'captcha_dcv',
    status              VARCHAR(32) NOT NULL DEFAULT 'pending',
    job_application_id  INTEGER REFERENCES users.job_applications (id) ON DELETE SET NULL,
    job_id              INTEGER REFERENCES jobs.jobs (id) ON DELETE SET NULL,
    user_id             INTEGER REFERENCES users.users (id) ON DELETE SET NULL,
    slack_channel_id    VARCHAR(64),
    slack_message_ts    VARCHAR(32),
    slack_user_completed VARCHAR(64),
    dcv_session_token   VARCHAR(512) NOT NULL,
    dcv_public_url      TEXT NOT NULL,
    completed_at        TIMESTAMPTZ,
    resolution_notes    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_slack_interactive_status CHECK (
        status IN ('pending', 'completed', 'failed', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS idx_slack_interactive_status_created
    ON users.slack_interactive_requests (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_slack_interactive_slack_msg
    ON users.slack_interactive_requests (slack_channel_id, slack_message_ts);

-- At most one pending captcha escalation per application row (avoids Slack spam on retries).
CREATE UNIQUE INDEX IF NOT EXISTS uq_slack_interactive_pending_captcha_per_app
    ON users.slack_interactive_requests (job_application_id)
    WHERE status = 'pending' AND request_kind = 'captcha_dcv';
