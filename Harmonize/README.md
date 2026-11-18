# Harmonize

Turns the raw `harvest.*` payloads into the relational, UUID-keyed **`validate`** schema. New records get `approval_status='pending'`.

| `validate` table | Holds | Key used for upsert |
|---|---|---|
| `records` | one row per resource (title, abstract, type, language, dates, url, `raw_metadata` JSONB) | `identifier` (unique) |
| `sources`, `projects` | lookup tables | `name` (unique) |
| `subjects`, `persons`, `organizations` | lookup tables | no unique key; de-duplicated through in-memory caches loaded at start |
| `distributions` | access links per record | no unique key |
| `record_source`, `record_subject`, `record_person`, `record_organization`, `record_project` | junction tables | `(record_id, <x>_id)` unique |

Run order: `harmonize_projects_to_validate.py` → `harmonize_all_to_validate.py` → `insert_eucap_practices.py`.
All three take `--dry-run`, which runs everything inside a transaction and rolls it back.

> **Read-only note:** `--dry-run` writes and then rolls back, so it cannot run with `MSP_READ_ONLY=1`. It stops at the first INSERT (verified on stage: caches load and rows parse first).

---

## `harmonize_projects_to_validate.py` (pipeline step 9)

**Purpose:** builds the project side of `validate`.
- **Step 1:** every distinct acronym in `harvest.projects` becomes a `validate.projects` row.
- **Step 2:** every project item in `harvest.items` (CORDIS / EU CAP MCF YAML) becomes a `validate.records` row. Its partner organisations, keywords, CORDIS / website links and project link are filled in as well.

| Direction | Table | Operation | Details |
|---|---|---|---|
| Input | `harvest.projects` | SELECT | `code, grantnr` (distinct) |
| Input | `harvest.items` | SELECT | `identifier, identifiertype, uri, resultobject, resulttype, project, title` (project items) |
| Input | `validate.projects`, `records`, `organizations`, `subjects` | SELECT | load caches (name/identifier → id) |
| Output | `validate.projects` | INSERT | `(id, name)` · `ON CONFLICT (name) DO NOTHING` |
| Output | `validate.records` | INSERT | `id, identifier, title, abstract, resource_type, language, publication_date, temporal_start, temporal_end, url, raw_metadata, approval_status…` · `ON CONFLICT (identifier) DO UPDATE SET title, abstract, resource_type, language, publication_date, temporal_start, temporal_end, url, raw_metadata, updated_at` |
| Output | `validate.organizations` | INSERT | `id, name, country, city, street_address, website_url` (new names only) |
| Output | `validate.subjects` | INSERT | `id, label` (new labels only) |
| Output | `validate.distributions` | INSERT | `id, record_id, name, format, access_url` (CORDIS page + project website) |
| Output | `validate.record_project` / `record_organization` / `record_subject` | INSERT | `ON CONFLICT (record_id, …) DO NOTHING` |

```bash
python Harmonize/harmonize_projects_to_validate.py --dry-run --limit 10
python Harmonize/harmonize_projects_to_validate.py
```
Optional: `--host --port --dbname --user --password` (defaults come from `.env`).

---

## `harmonize_all_to_validate.py` (pipeline step 10)

**Purpose:** the generic harmonizer. It reads **every** `harvest.items` row, source by source, and picks a parser by `resulttype`:

| `resulttype` | Parser | Typical sources |
|---|---|---|
| `yaml` | `parse_mcf_yaml` | CORDIS, EU CAP Network |
| `schema.org` | `parse_schema_org` | Solr records, EU-FarmBook contributions |
| anything else | `parse_solr_json` | old flat Solr JSON |

Each batch (default 500) runs inside a SAVEPOINT. A failed batch is rolled back, the caches are restored, and the run continues.

| Direction | Table | Operation | Details |
|---|---|---|---|
| Input | `harvest.items` | SELECT | `identifier, identifiertype, uri, resultobject, resulttype, doimetadata, source, insert_date, itemtype, title, language, date, project`, per source |
| Input | `harvest.projects` | SELECT | `grantnr, code` (grant → acronym map) |
| Input | `validate.sources`, `records`, `subjects`, `persons`, `organizations`, `projects` | SELECT | load caches |
| Output | `validate.sources` | INSERT | canonical name from `common/sources.py` · `ON CONFLICT (name) DO NOTHING` |
| Output | `validate.records` | INSERT | `ON CONFLICT (identifier) DO UPDATE SET title, abstract, resource_type, license, language, thumbnail, publication_date, resource_creation_date, resource_updated_date, harvest_date, spatial, temporal_start, temporal_end, url, raw_metadata, updated_at` |
| Output | `validate.subjects`, `persons`, `organizations` | INSERT | new names only (cache check) |
| Output | `validate.projects` | INSERT | `ON CONFLICT (name) DO NOTHING` |
| Output | `validate.distributions` | INSERT | `id, record_id, name, format, access_url`; de-duplicated within a batch only |
| Output | `validate.record_source` / `record_subject` / `record_person` / `record_organization` / `record_project` | INSERT | `ON CONFLICT (record_id, …) DO NOTHING` |
| Output | `validate.distributions` | **TRUNCATE**, then INSERT | only with `--sync-distributions` |

```bash
python Harmonize/harmonize_all_to_validate.py --dry-run --source openaire --limit 100
python Harmonize/harmonize_all_to_validate.py --missing-only        # only identifiers not yet in validate.records
python Harmonize/harmonize_all_to_validate.py                       # everything
python Harmonize/harmonize_all_to_validate.py --sync-distributions  # rebuild validate.distributions
```

**Source names:** `harvest.items.source` is mapped to one canonical name before it is looked up or inserted, so `Data.Europa.EU`, `https://data.europa.eu/` and the aliases in `common/source_aliases.json` (typos such as `data.erupa.eu`) all go to the one `data.europa.eu` row. If an unlisted name looks like an existing one (e.g. `data.europe.eu`), the run logs a WARNING and creates it as a new source. Add the variant to `source_aliases.json` if it is the same source. Each record is linked to a source once (`UNIQUE (record_id, source_id)`). Existing variant rows already in `validate.sources` are **not** merged: new links go to the canonically named row.

> **Warnings**
> - Rerunning without `--missing-only` updates existing records **and inserts their distributions again**, which creates duplicate links.
> - `--sync-distributions` empties `validate.distributions` and rebuilds it from `harvest.items` only. That also removes links written by `harmonize_projects_to_validate.py` and `insert_eucap_practices.py`.

---

## `insert_eucap_practices.py` (pipeline step 11)

**Purpose:** loads the EU CAP Practice Abstracts JSON (from `Harvesting/EUCAP/`) directly into `validate`: one record per abstract, its URL as a distribution, and a link to its project (matched by acronym or grant number against `validate.projects.name`).

| Direction | Source / table | Operation | Details |
|---|---|---|---|
| Input | `data/eu_cap_practice_abstracts.json` | read file | |
| Input | `validate.projects` | SELECT | `id, name` |
| Input | `validate.records` | SELECT | `id, identifier` (skip existing) |
| Output | `validate.records` | INSERT | `resource_type='Practice Abstract'`, `approval_status='pending'` · `ON CONFLICT (identifier) DO NOTHING` |
| Output | `validate.distributions` | INSERT | practice URL · `ON CONFLICT DO NOTHING` |
| Output | `validate.record_project` | INSERT | `ON CONFLICT DO NOTHING` |

```bash
python Harmonize/insert_eucap_practices.py --dry-run
python Harmonize/insert_eucap_practices.py
```
This script skips the `harvest` layer. It can be retired once the practice-abstract harvester writes to `harvest.items` (see `CLEANUP_PLAN.md`).
