CREATE TABLE IF NOT EXISTS audit_log (
    id           SERIAL PRIMARY KEY,
    tool_name    TEXT NOT NULL,
    arguments    JSONB,                        -- what params the AI passed
    result       TEXT,                         -- what we returned
    status       TEXT NOT NULL DEFAULT 'success',
    called_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit_log (tool_name);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log (called_at);

