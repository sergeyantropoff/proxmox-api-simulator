CREATE TABLE group_acl_entries (
    group_id uuid NOT NULL REFERENCES identity_groups(id) ON DELETE CASCADE,
    role_name text NOT NULL REFERENCES roles(name) ON DELETE RESTRICT,
    path text NOT NULL,
    propagate boolean NOT NULL DEFAULT true,
    PRIMARY KEY (group_id, role_name, path)
);
CREATE INDEX identity_group_members_principal_idx
    ON identity_group_members(principal_id, group_id);
