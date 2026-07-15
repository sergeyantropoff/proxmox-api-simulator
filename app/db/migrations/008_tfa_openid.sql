CREATE TABLE tfa_entries (
    principal_id uuid NOT NULL REFERENCES principals(id) ON DELETE CASCADE,
    entry_id text NOT NULL,
    tfa_type text NOT NULL CHECK (tfa_type IN ('totp', 'u2f', 'webauthn', 'recovery', 'yubico')),
    description text,
    enable boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    secret text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (principal_id, entry_id)
);
CREATE INDEX tfa_entries_principal_idx ON tfa_entries(principal_id);

ALTER TABLE principals
    ADD COLUMN IF NOT EXISTS tfa_locked_until timestamptz,
    ADD COLUMN IF NOT EXISTS totp_locked boolean NOT NULL DEFAULT false;

CREATE TABLE openid_pending (
    state text PRIMARY KEY,
    realm text NOT NULL REFERENCES realms(name) ON DELETE CASCADE,
    redirect_url text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
