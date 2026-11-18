-- SoilVoc in the DB (see reports/soilvoc_levels_vs_db/IMPLEMENTATION.md)
-- Stage only, schema validate. Idempotent: safe to run more than once. Run as k2xadmin.
--
--   validate.soilvoc          one row per SoilVoc concept (id = SoilVoc URI)
--   validate.record_soilvoc   one row per (record, SoilVoc concept), FK to records and soilvoc
--
-- History: soilvoc_types (code, parent_code) was renamed to soilvoc (id, parent_id);
-- subject_soilvoc and the array-shaped record_soilvoc were replaced by this record_soilvoc.

BEGIN;

-- 1. rename soilvoc_types -> soilvoc, code -> id, parent_code -> parent_id (existing installs)
DO $$
BEGIN
    IF to_regclass('validate.soilvoc_types') IS NOT NULL AND to_regclass('validate.soilvoc') IS NULL THEN
        ALTER TABLE validate.soilvoc_types RENAME TO soilvoc;
        ALTER TABLE validate.soilvoc RENAME COLUMN code TO id;
        ALTER TABLE validate.soilvoc RENAME COLUMN parent_code TO parent_id;
        ALTER TABLE validate.soilvoc RENAME CONSTRAINT soilvoc_types_pkey TO soilvoc_pkey;
        ALTER TABLE validate.soilvoc RENAME CONSTRAINT soilvoc_types_parent_code_fkey TO soilvoc_parent_id_fkey;
        ALTER TABLE validate.soilvoc RENAME CONSTRAINT soilvoc_types_level_check TO soilvoc_level_check;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS validate.soilvoc (
    id         text PRIMARY KEY,                    -- SoilVoc URI, e.g. https://w3id.org/eusoilvoc#Soil
    level      smallint CONSTRAINT soilvoc_level_check CHECK (level BETWEEN 1 AND 8),
                                                    -- NULL = detached procedure concept
    parent_id  text CONSTRAINT soilvoc_parent_id_fkey REFERENCES validate.soilvoc(id),
    name       text NOT NULL,                       -- preferred label
    alt_labels text[]                               -- all alternative labels in one array
);
CREATE INDEX IF NOT EXISTS soilvoc_parent_id_idx ON validate.soilvoc (parent_id);

-- 2. record_soilvoc: drop the earlier array-shaped version (it had a "codes" column)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'validate' AND table_name = 'record_soilvoc'
                 AND column_name = 'codes') THEN
        DROP TABLE validate.record_soilvoc;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS validate.record_soilvoc (
    record_id     uuid NOT NULL REFERENCES validate.records(id) ON DELETE CASCADE,
    soilvoc_id    text NOT NULL REFERENCES validate.soilvoc(id),
    link_type     text NOT NULL CHECK (link_type IN
                      ('exact', 'synonym', 'translation', 'mapped', 'variant', 'broader', 'inside')),
    status        text NOT NULL DEFAULT 'accepted' CHECK (status IN ('accepted', 'pending')),
    run_id        text NOT NULL,                    -- load run, e.g. 20261103-160000
    classified_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (record_id, soilvoc_id)
);
CREATE INDEX IF NOT EXISTS record_soilvoc_soilvoc_id_idx ON validate.record_soilvoc (soilvoc_id);

-- 3. the earlier subject-level link table is not used any more
DROP TABLE IF EXISTS validate.subject_soilvoc;

COMMIT;
