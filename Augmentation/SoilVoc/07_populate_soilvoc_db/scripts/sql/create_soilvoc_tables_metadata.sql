-- Empty SoilVoc tables in the metadata schema (stage), same structure as validate.soilvoc /
-- validate.record_soilvoc. Structure only: no rows are inserted.
-- Idempotent: safe to run more than once. Run as k2xadmin.
-- Note: the metadata schema is managed by alembic; add these tables to a migration as well.

BEGIN;

CREATE TABLE IF NOT EXISTS metadata.soilvoc (
    id         text     NOT NULL,              -- SoilVoc URI, e.g. https://w3id.org/eusoilvoc#Soil
    level      smallint,                       -- 1 (top concept) to 8; NULL = procedure code
    parent_id  text,                           -- broader concept (metadata.soilvoc.id)
    name       text     NOT NULL,              -- preferred label
    alt_labels text[],                         -- alternative labels and translations
    CONSTRAINT soilvoc_pkey           PRIMARY KEY (id),
    CONSTRAINT soilvoc_level_check    CHECK (level >= 1 AND level <= 8),
    CONSTRAINT soilvoc_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES metadata.soilvoc(id)
);
CREATE INDEX IF NOT EXISTS soilvoc_parent_id_idx ON metadata.soilvoc (parent_id);

CREATE TABLE IF NOT EXISTS metadata.record_soilvoc (
    record_id     uuid        NOT NULL,
    soilvoc_id    text        NOT NULL,
    link_type     text        NOT NULL,
    status        text        NOT NULL DEFAULT 'accepted',
    run_id        text        NOT NULL,
    classified_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT record_soilvoc_pkey PRIMARY KEY (record_id, soilvoc_id),
    CONSTRAINT record_soilvoc_record_id_fkey  FOREIGN KEY (record_id)  REFERENCES metadata.records(id) ON DELETE CASCADE,
    CONSTRAINT record_soilvoc_soilvoc_id_fkey FOREIGN KEY (soilvoc_id) REFERENCES metadata.soilvoc(id),
    CONSTRAINT record_soilvoc_link_type_check CHECK (link_type IN
        ('exact', 'synonym', 'translation', 'mapped', 'variant', 'broader', 'inside')),
    CONSTRAINT record_soilvoc_status_check CHECK (status IN ('accepted', 'pending'))
);
CREATE INDEX IF NOT EXISTS record_soilvoc_soilvoc_id_idx ON metadata.record_soilvoc (soilvoc_id);

COMMIT;
