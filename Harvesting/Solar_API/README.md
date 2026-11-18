# Harvesting/Solar_API

The SoilWise catalogue (Solr) aggregates records from OpenAIRE, BonaRes, CORDIS, Impact4Soil, data.europa.eu and others. This folder harvests the whole catalogue and stores each record as standard schema.org JSON-LD.

---

## `harvest_solr_records.py` (pipeline step 7)

**Purpose:** pages through the Solr search API (default 500 records per page). Each document is converted to schema.org with `solr_schema_mapper.py`. The table columns are derived from the schema.org object: item type, title, language, date, project, and the primary provider as `source`. Rows are upserted into `harvest.items` on their MD5 hash, so reruns are idempotent.

| Direction | Source / target | Details |
|---|---|---|
| Input | `https://catalogue.soilwise-he.eu/search-api/solr/search` | paginated `*:*` query |
| Output | `harvest.items` | `resulttype='schema.org'`, `source` = primary provider |

**Database operations**

| Table | Operation | Columns | Conflict handling |
|---|---|---|---|
| `harvest.items` | INSERT (batch per page, `execute_values`) | `identifier, identifiertype, uri, resultobject, resulttype, itemtype, title, source, language, date, project, hash, insert_date, updated_date` | `ON CONFLICT (hash) DO UPDATE SET resultobject, resulttype, itemtype, title, source, language, date, project, updated_date = NOW()` |

There are no DB reads. One commit per page. With `--dry-run` it only fetches and maps.

**Run**
```bash
python Harvesting/Solar_API/harvest_solr_records.py --dry-run --limit 1000
python Harvesting/Solar_API/harvest_solr_records.py
python Harvesting/Solar_API/harvest_solr_records.py --batch-size 200
```

> **Known issue on `msp-kh-stage`:** `harvest.items` has no `updated_date` column there, so the INSERT fails. Either add the column (`ALTER TABLE harvest.items ADD COLUMN updated_date timestamp`) or remove it from the statement.

---

## `solr_schema_mapper.py` (library, no CLI)

**Purpose:** a crosswalk from a raw Solr document to schema.org JSON-LD that keeps every field. It is imported by `harvest_solr_records.py`.

| Function | Does |
|---|---|
| `solr_to_schema_org(doc)` | Full conversion: name, description, creator/contributor, keywords, links → `distribution`, dates, spatial, funding/projects, license, language |
| `extract_source(doc)` | Primary provider (first entry of `sources`, lower-case) |
| `extract_identifier_and_type(doc)` | Normalises the identifier (strips `https://doi.org/`, `doi:`) and returns `doi` / `url` / `other` |
| `extract_uri(doc, identifier)` | Landing URL (DOI resolver or Solr record URL) |
| `clean_project_name(value)` | Decodes JSON-encoded project values; drops noise like `-`, `null`, `n/a` |
| `clean_keyword_text(text)` | Re-exported from `common/text_cleaning.py` |

There are no database or file operations.
