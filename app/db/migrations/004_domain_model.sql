CREATE TABLE clusters (
    id uuid PRIMARY KEY,
    external_id text NOT NULL UNIQUE,
    name text NOT NULL,
    version integer NOT NULL DEFAULT 1,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO clusters(id, external_id, name)
VALUES ('dc760c47-d8d7-57e6-9404-f0c6f2395d8f', 'default', 'pve-simulator');

ALTER TABLE nodes
    ADD COLUMN cluster_id uuid NOT NULL DEFAULT 'dc760c47-d8d7-57e6-9404-f0c6f2395d8f'
        REFERENCES clusters(id) ON DELETE CASCADE,
    ADD COLUMN version integer NOT NULL DEFAULT 1,
    ADD COLUMN metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE resources
    ADD COLUMN cluster_id uuid NOT NULL DEFAULT 'dc760c47-d8d7-57e6-9404-f0c6f2395d8f'
        REFERENCES clusters(id) ON DELETE CASCADE,
    ADD COLUMN version integer NOT NULL DEFAULT 1,
    ADD COLUMN metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
CREATE UNIQUE INDEX resources_cluster_vmid_idx
    ON resources(cluster_id, external_id) WHERE kind IN ('qemu', 'lxc');

CREATE TABLE virtual_machines (
    resource_id uuid PRIMARY KEY REFERENCES resources(id) ON DELETE CASCADE,
    cluster_id uuid NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    vmid integer NOT NULL CHECK (vmid BETWEEN 100 AND 999999999),
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    lock text,
    template boolean NOT NULL DEFAULT false,
    UNIQUE (cluster_id, vmid)
);
CREATE TABLE containers (
    resource_id uuid PRIMARY KEY REFERENCES resources(id) ON DELETE CASCADE,
    cluster_id uuid NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    vmid integer NOT NULL CHECK (vmid BETWEEN 100 AND 999999999),
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    lock text,
    template boolean NOT NULL DEFAULT false,
    UNIQUE (cluster_id, vmid)
);
CREATE TABLE vm_disks (
    id uuid PRIMARY KEY,
    resource_id uuid NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    device text NOT NULL,
    storage_id text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (resource_id, device)
);
CREATE TABLE vm_network_interfaces (
    id uuid PRIMARY KEY,
    resource_id uuid NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    device text NOT NULL,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (resource_id, device)
);

CREATE TABLE storages (
    resource_id uuid PRIMARY KEY REFERENCES resources(id) ON DELETE CASCADE,
    cluster_id uuid NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    storage_id text NOT NULL,
    storage_type text NOT NULL,
    shared boolean NOT NULL DEFAULT false,
    capacity_bytes bigint CHECK (capacity_bytes >= 0),
    used_bytes bigint CHECK (used_bytes >= 0),
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (cluster_id, storage_id)
);
CREATE TABLE storage_contents (
    id uuid PRIMARY KEY,
    storage_resource_id uuid NOT NULL REFERENCES storages(resource_id) ON DELETE CASCADE,
    volume_id text NOT NULL,
    content_type text NOT NULL,
    size_bytes bigint NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (storage_resource_id, volume_id)
);

CREATE TABLE snapshots (
    id uuid PRIMARY KEY,
    resource_id uuid NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    name text NOT NULL,
    parent_name text,
    description text,
    state jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (resource_id, name)
);
CREATE TABLE backups (
    id uuid PRIMARY KEY,
    resource_id uuid REFERENCES resources(id) ON DELETE SET NULL,
    storage_resource_id uuid NOT NULL REFERENCES storages(resource_id) ON DELETE CASCADE,
    volume_id text NOT NULL,
    size_bytes bigint NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (storage_resource_id, volume_id)
);
CREATE TABLE pools (
    id uuid PRIMARY KEY,
    cluster_id uuid NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    pool_id text NOT NULL,
    comment text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (cluster_id, pool_id)
);
CREATE TABLE pool_members (
    pool_id uuid NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
    resource_id uuid NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    PRIMARY KEY (pool_id, resource_id)
);

CREATE TABLE identity_groups (
    id uuid PRIMARY KEY,
    group_id text NOT NULL UNIQUE,
    comment text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE identity_group_members (
    group_id uuid NOT NULL REFERENCES identity_groups(id) ON DELETE CASCADE,
    principal_id uuid NOT NULL REFERENCES principals(id) ON DELETE CASCADE,
    PRIMARY KEY (group_id, principal_id)
);
CREATE TABLE auth_tickets (
    id uuid PRIMARY KEY,
    principal_id uuid NOT NULL REFERENCES principals(id) ON DELETE CASCADE,
    ticket_hash text NOT NULL UNIQUE,
    issued_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz
);
CREATE INDEX auth_tickets_expiry_idx ON auth_tickets(expires_at) WHERE revoked_at IS NULL;

CREATE TABLE contract_paths (
    snapshot_checksum text NOT NULL REFERENCES contract_snapshots(checksum) ON DELETE CASCADE,
    path text NOT NULL,
    document jsonb NOT NULL,
    PRIMARY KEY (snapshot_checksum, path)
);
CREATE TABLE contract_methods (
    snapshot_checksum text NOT NULL,
    path text NOT NULL,
    verb text NOT NULL,
    fingerprint text NOT NULL,
    document jsonb NOT NULL,
    PRIMARY KEY (snapshot_checksum, path, verb),
    FOREIGN KEY (snapshot_checksum, path)
        REFERENCES contract_paths(snapshot_checksum, path) ON DELETE CASCADE
);
CREATE TABLE contract_parameters (
    snapshot_checksum text NOT NULL,
    path text NOT NULL,
    verb text NOT NULL,
    name text NOT NULL,
    location text NOT NULL,
    document jsonb NOT NULL,
    PRIMARY KEY (snapshot_checksum, path, verb, name, location),
    FOREIGN KEY (snapshot_checksum, path, verb)
        REFERENCES contract_methods(snapshot_checksum, path, verb) ON DELETE CASCADE
);
CREATE TABLE contract_schema_fragments (
    id uuid PRIMARY KEY,
    snapshot_checksum text NOT NULL REFERENCES contract_snapshots(checksum) ON DELETE CASCADE,
    fingerprint text NOT NULL,
    document jsonb NOT NULL,
    UNIQUE (snapshot_checksum, fingerprint)
);
CREATE TABLE observed_contracts (
    id uuid PRIMARY KEY,
    source_version text NOT NULL,
    method_fingerprint text NOT NULL,
    observation jsonb NOT NULL,
    observed_at timestamptz NOT NULL,
    UNIQUE (source_version, method_fingerprint, observed_at)
);

CREATE TABLE scenario_rules (
    id uuid PRIMARY KEY,
    scenario_id uuid NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    priority integer NOT NULL DEFAULT 0,
    matcher jsonb NOT NULL,
    action jsonb NOT NULL,
    enabled boolean NOT NULL DEFAULT true
);
CREATE INDEX scenario_rules_scenario_priority_idx ON scenario_rules(scenario_id, priority DESC);
CREATE TABLE fault_injections (
    id uuid PRIMARY KEY,
    scenario_id uuid REFERENCES scenarios(id) ON DELETE CASCADE,
    fault_type text NOT NULL,
    matcher jsonb NOT NULL,
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    active_from timestamptz,
    active_until timestamptz,
    enabled boolean NOT NULL DEFAULT true
);
