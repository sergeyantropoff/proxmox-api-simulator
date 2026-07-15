ALTER TABLE realms DROP CONSTRAINT IF EXISTS realms_kind_check;
ALTER TABLE realms
    ADD CONSTRAINT realms_kind_check
    CHECK (kind IN ('pam', 'pve', 'openid', 'ldap', 'ad'));
ALTER TABLE realms
    ADD COLUMN IF NOT EXISTS config jsonb NOT NULL DEFAULT '{}'::jsonb;
UPDATE realms
SET config = config || jsonb_build_object(
    'comment',
    CASE name
        WHEN 'pam' THEN 'Linux PAM standard authentication'
        WHEN 'pve' THEN 'Proxmox VE authentication server'
        ELSE COALESCE(config->>'comment', '')
    END
)
WHERE name IN ('pam', 'pve')
  AND COALESCE(config->>'comment', '') = '';
