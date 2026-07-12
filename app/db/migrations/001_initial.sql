CREATE TABLE contract_snapshots (
    checksum text PRIMARY KEY,
    source_version text NOT NULL,
    document jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE nodes (
    id uuid PRIMARY KEY,
    name text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('online', 'offline'))
);
CREATE TABLE resources (
    id uuid PRIMARY KEY,
    node_id uuid NOT NULL REFERENCES nodes(id) ON DELETE RESTRICT,
    kind text NOT NULL,
    external_id text NOT NULL,
    state jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (kind, external_id)
);
CREATE INDEX resources_node_id_idx ON resources(node_id);
CREATE TABLE principals (
    id uuid PRIMARY KEY,
    name text NOT NULL UNIQUE,
    password_hash text
);
CREATE TABLE roles (
    name text PRIMARY KEY,
    privileges text[] NOT NULL DEFAULT '{}'
);
CREATE TABLE acl_entries (
    principal_id uuid NOT NULL REFERENCES principals(id) ON DELETE CASCADE,
    role_name text NOT NULL REFERENCES roles(name) ON DELETE RESTRICT,
    path text NOT NULL,
    propagate boolean NOT NULL DEFAULT true,
    PRIMARY KEY (principal_id, role_name, path)
);
CREATE TABLE tasks (
    id uuid PRIMARY KEY,
    upid text NOT NULL UNIQUE,
    status text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tasks_status_created_idx ON tasks(status, created_at);
CREATE TABLE scenarios (
    id uuid PRIMARY KEY,
    name text NOT NULL UNIQUE,
    definition jsonb NOT NULL,
    enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE audit_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    principal text,
    action text NOT NULL,
    target text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX audit_events_occurred_idx ON audit_events(occurred_at);
