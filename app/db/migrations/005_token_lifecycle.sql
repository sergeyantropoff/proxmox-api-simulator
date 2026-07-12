INSERT INTO realms(name, kind) VALUES ('test', 'pve') ON CONFLICT (name) DO NOTHING;
ALTER TABLE api_tokens
    ADD COLUMN comment text,
    ADD COLUMN privilege_separation boolean NOT NULL DEFAULT true,
    ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
