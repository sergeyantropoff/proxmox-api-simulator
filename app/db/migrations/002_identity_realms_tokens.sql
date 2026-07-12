CREATE TABLE realms (
    name text PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('pam', 'pve', 'openid', 'ldap'))
);
INSERT INTO realms(name, kind) VALUES ('pam', 'pam'), ('pve', 'pve');
ALTER TABLE principals ADD COLUMN realm_name text REFERENCES realms(name) ON DELETE RESTRICT;
CREATE TABLE api_tokens (
    principal_id uuid NOT NULL REFERENCES principals(id) ON DELETE CASCADE,
    token_id text NOT NULL,
    secret_hash text NOT NULL,
    privileges text[] NOT NULL DEFAULT '{}',
    expires_at timestamptz,
    PRIMARY KEY (principal_id, token_id),
    CHECK (secret_hash LIKE 'scrypt$%')
);
CREATE INDEX api_tokens_expires_idx ON api_tokens(expires_at) WHERE expires_at IS NOT NULL;
