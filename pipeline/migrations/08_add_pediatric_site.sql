-- Migration 08: Add Pediatric Oncology disease site
--
-- Adds 'pediatric' to the disease_site_code enum and inserts the corresponding
-- row into the disease_sites table. Run in Supabase SQL editor.
--
-- IMPORTANT: Postgres enum values cannot be removed after being added.
-- If rollback is needed, leave the enum value and delete the disease_sites row.

-- Step 1: Add the new enum value (safe to run even if already present — the
-- DO block below makes it idempotent).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumlabel = 'pediatric'
          AND enumtypid = (
              SELECT oid FROM pg_type WHERE typname = 'disease_site_code'
          )
    ) THEN
        ALTER TYPE disease_site_code ADD VALUE 'pediatric';
    END IF;
END;
$$;

-- Step 2: Insert the disease_sites row (idempotent via ON CONFLICT DO NOTHING).
-- The code column uniquely identifies each site; adjust other columns to match
-- what 01_schema.sql seeded for the existing 10 sites.
INSERT INTO disease_sites (code, name, active)
VALUES ('pediatric', 'Pediatric Oncology', true)
ON CONFLICT (code) DO NOTHING;
