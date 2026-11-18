# Migration

Schema setup and the final copy from `validate` (staging) to `metadata` (published).

---

## `validate_schema.sql` (pipeline step 0)

**Purpose:** DDL for the `validate` schema, with primary/foreign keys and indexes. It creates 20 tables:
- `records`, `sources`, `subjects`, `persons`, `organizations`, `projects`, `distributions`, `attributes`
- `landcover_types`, `landuse_types`, `recommendation_events`, `alembic_version`
- the junctions `record_source`, `record_subject`, `record_person`, `record_organization`, `record_project`, `record_landcover`, `record_landuse`, `person_organization`

Run it once on an empty database.

| Direction | Target | Operation |
|---|---|---|
| Output | `validate.*` | CREATE SCHEMA / TABLE / INDEX / constraints |

```bash
psql "$(python -c 'import sys; sys.path.insert(0,"."); from common.db import db_url; print(db_url())')" -f Migration/validate_schema.sql
```
On `msp-kh-stage` the schema is managed by Alembic (`validate.alembic_version`) and also has `soilvoc` and `record_soilvoc`, which this file does **not** create. Check it against the live schema before using it.

---

## `migrate_validate_to_metadata.py` (pipeline step 40)

**Purpose:** publishes `validate` as `metadata`.
1. `pg_dump --schema-only --schema=validate` (excluding `validate.records_backup_*`) gives the DDL. The script rewrites `validate` → `metadata` in it.
2. It drops the `metadata` schema and recreates it from that DDL.
3. It copies the data table by table in dependency order:

| Tier | Tables copied |
|---|---|
| 1, parents | `sources`, `organizations`, `persons`, `projects`, `subjects`, `alembic_version` |
| 2, core | `records` |
| 3, children | `person_organization`, `record_source`, `record_person`, `record_organization`, `record_project`, `record_subject`, `distributions`, `attributes`, `recommendation_events` |

4. It compares row counts (validate vs metadata) and checks for orphans in the junction tables.

| Direction | Schema / table | Operation | Details |
|---|---|---|---|
| Input | `validate.*` | `pg_dump` (schema only), SELECT * | **read only**: nothing in `validate` is changed |
| Input | `information_schema.tables` | SELECT | which tables exist |
| Output | `metadata` | **DROP SCHEMA metadata CASCADE**; CREATE SCHEMA; run DDL | all existing `metadata` tables and data are removed |
| Output | `metadata.<table>` | INSERT INTO … SELECT * FROM validate.<table> | for the 16 tables above |
| Check | `metadata.*`, `validate.*` | SELECT count(*), orphan joins | printed report |

Autocommit is on, so each statement is applied immediately. There is no dry run.

```bash
python Migration/migrate_validate_to_metadata.py
```
It requires `pg_dump` on the PATH.

> ⚠ **Do not run on `msp-kh-stage` as it is.** The DDL recreates all validate tables, but only the 16 listed above get their data back. On stage, `metadata` also holds `record_soilvoc` (18,587 rows), `record_landcover` (14,842), `record_landuse` (14,419), `soilvoc` (543), `landcover_types` (99) and `landuse_types` (52). Those would end up empty or reduced to whatever `validate` has. `metadata.recommendation_events` (3,051 rows) would be replaced by validate's 1,004. `validate.soilvoc` (1,464) and `validate.record_soilvoc` (18,601), written by `Augmentation/SoilVoc` (steps 24–28), are not copied either. Add the missing tables to the tier lists (`soilvoc`, `landcover_types`, `landuse_types` with the parents; `record_soilvoc`, `record_landcover`, `record_landuse` with the children), and decide what should happen to `recommendation_events`, before running it.
