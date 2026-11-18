# Selects for dimension tables
SELECT_ALL_SOURCES = "SELECT id, name FROM sources;"
SELECT_ALL_PERSONS = "SELECT id, name, email FROM persons;"
SELECT_ALL_ORGANIZATIONS = "SELECT id, name FROM organizations;"
SELECT_ALL_SUBJECTS = "SELECT id, label, uri FROM subjects;"

# Inserts for dimension tables
INSERT_SOURCE = """
    INSERT INTO sources (id, name)
    VALUES %s
"""
INSERT_PERSON = """
    INSERT INTO persons (id, name, email)
    VALUES %s
"""
INSERT_ORGANIZATION = """
    INSERT INTO organizations (id, name)
    VALUES %s
"""
INSERT_SUBJECT = """
    INSERT INTO subjects (id, label, uri)
    VALUES %s
"""

# Upsert for records table
# We only insert into 'records' returning the id.
UPSERT_RECORD = """
    INSERT INTO records (
        id, identifier, title, abstract, resource_type,
        license, language, thumbnail,
        publication_date, resource_creation_date, resource_updated_date,
        harvest_date, spatial, temporal_start, temporal_end, raw_metadata
    )
    VALUES %s
    ON CONFLICT (identifier) DO UPDATE SET
        title = EXCLUDED.title,
        abstract = EXCLUDED.abstract,
        resource_type = EXCLUDED.resource_type,
        license = EXCLUDED.license,
        language = EXCLUDED.language,
        thumbnail = EXCLUDED.thumbnail,
        publication_date = EXCLUDED.publication_date,
        resource_creation_date = EXCLUDED.resource_creation_date,
        resource_updated_date = EXCLUDED.resource_updated_date,
        harvest_date = EXCLUDED.harvest_date,
        spatial = EXCLUDED.spatial,
        temporal_start = EXCLUDED.temporal_start,
        temporal_end = EXCLUDED.temporal_end,
        raw_metadata = EXCLUDED.raw_metadata,
        updated_at = NOW()
    RETURNING id
"""

# Junction Table Inserts (Do nothing on conflict)
INSERT_RECORD_SOURCE = """
    INSERT INTO record_source (id, record_id, source_id)
    VALUES %s
    ON CONFLICT ON CONSTRAINT uq_record_source DO NOTHING
"""

INSERT_RECORD_PERSON = """
    INSERT INTO record_person (id, record_id, person_id)
    VALUES %s
    ON CONFLICT ON CONSTRAINT uq_record_person DO NOTHING
"""

INSERT_RECORD_ORGANIZATION = """
    INSERT INTO record_organization (id, record_id, organization_id)
    VALUES %s
    ON CONFLICT ON CONSTRAINT uq_record_organization DO NOTHING
"""

INSERT_RECORD_SUBJECT = """
    INSERT INTO record_subject (id, record_id, subject_id)
    VALUES %s
    ON CONFLICT ON CONSTRAINT uq_record_subject DO NOTHING
"""

# Distributions table
# DELETE_DISTRIBUTIONS_BY_RECORD = """
#     DELETE FROM distributions WHERE record_id = %s
# """

INSERT_DISTRIBUTION = """
    INSERT INTO distributions (id, record_id, name, format, access_url)
    VALUES %s
"""
