ALTER TABLE tasks
    ADD COLUMN task_type text NOT NULL DEFAULT 'generic',
    ADD COLUMN progress integer NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    ADD COLUMN result jsonb,
    ADD COLUMN error text,
    ADD COLUMN worker_id text,
    ADD COLUMN lease_expires_at timestamptz,
    ADD COLUMN cancel_requested boolean NOT NULL DEFAULT false,
    ADD COLUMN idempotency_key text UNIQUE,
    ADD COLUMN attempt integer NOT NULL DEFAULT 0,
    ADD CONSTRAINT tasks_status_check CHECK (status IN ('queued', 'running', 'success', 'error', 'cancelled'));
CREATE INDEX tasks_claim_idx ON tasks(status, lease_expires_at, created_at);
CREATE TABLE resource_locks (
    resource_key text PRIMARY KEY,
    task_id uuid NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
    acquired_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE task_logs (
    task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    sequence bigint GENERATED ALWAYS AS IDENTITY,
    created_at timestamptz NOT NULL DEFAULT now(),
    message text NOT NULL,
    PRIMARY KEY (task_id, sequence)
);
CREATE TABLE task_events (
    task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    sequence bigint GENERATED ALWAYS AS IDENTITY,
    created_at timestamptz NOT NULL DEFAULT now(),
    kind text NOT NULL,
    data jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (task_id, sequence)
);
