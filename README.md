# Clean_MissionSoil-Data

The cleaned MissionSoil data pipeline. It harvests soil-knowledge records into PostgreSQL and moves them through three layers:

```
external sources ──► harvest.* (raw payloads) ──► validate.* (relational, cleaned, linked) ──► metadata.* (published)
```

It combines three sources:

| From | What | Folders here |
|---|---|---|
| `MissionSoil-Data`, branch `mahnoor` | harvesters, harmonizers, cleaning, resource types, migration | `Harvesting/`, `Harmonize/`, `Augmentation/{Enrichment,Cleanning-Scripts,Resource_Types}/`, `Migration/` |
| `soil-vocabs/tasks` | SoilVoc concepts and record links, noise keywords (tasks 01, 03–07; the LLM task 02 was not copied) | `Augmentation/SoilVoc/` |
| `github.com/ahmadkhanraj01/SoilWise_metadata_backfill` | text cleanup, empty abstracts, `records.url`, `distributions` (without `crosscheck/`) | `Augmentation/Backfill/` |

The originals were only read. Everything here is a copy; the changes are listed in `CLEANUP_PLAN.md`.

| Document | What |
|---|---|
| `README.md` | this file: setup, how to run, folders |
| `CLEANUP_PLAN.md` | where every script came from, what was changed, problems found, status |
| `pipeline_dfd.html` | data-flow diagram: every step, the tables and files it reads and writes (zoomable overview). Published at https://claude.ai/artifact/Mjc7awFNtsZ8fHSTqD4MUH |
| `<folder>/README.md` | every folder: purpose of each script, input/output tables and files, read/write operations |

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium        # only for the EU-FarmBook harvesters
cp .env.template .env              # then fill in the DB settings
```

`requirements.txt` also lists `rdflib` (SoilVoc) and `ftfy` (Backfill text cleanup). `pg_dump` must be on the PATH for the migration.

**`.env`:** use the suffixed names from `.env.template`:
- `DB_HOST1 … DB_SCHEMA1` is the working database (stage, schema `validate`).
- `DB_*2` (dev) is optional and only used by `Augmentation/SoilVoc/03_stage_vs_dev`.

`common/db.py` also accepts the unsuffixed `DB_*` and `POSTGRES_*` spellings. The SoilVoc scripts read `DB_*1` directly, so keep the suffix. Every script finds the repo-root `.env` itself, so it can run from any directory.

## Run

```bash
python Pipeline/run_pipeline.py                            # list the 40 steps and their dry-run flags
python Pipeline/run_pipeline.py --run                      # dry run of every step that has one
python Pipeline/run_pipeline.py --run --stage backfill     # dry run of one stage
python Pipeline/run_pipeline.py --run --live --only 35     # real run of one step (asks you to type the DB name)
python Pipeline/verify_readonly.py                         # read-only check: tables/columns used by the scripts vs the DB
MSP_READ_ONLY=1 python <any script>                        # PostgreSQL rejects every write from that process
```

Each run writes a log to `Pipeline/logs/`. `--keep-going` continues after a failed step.

| Stage | Steps | Folder | Reads → writes |
|---|---|---|---|
| setup | 0 | `Migration/validate_schema.sql` | creates `validate.*` (empty database only) |
| harvest | 1–7 | `Harvesting/*` | ESDAC, EU-FarmBook, EU CAP, CORDIS, SoilWise Solr → `harvest.projects`, `harvest.items` |
| augment | 8 | `Augmentation/Enrichment` | Crossref / DataCite / OpenAlex → missing abstracts in `harvest.items` |
| harmonize | 9–11 | `Harmonize/` | `harvest.*` → `validate.*`; source names are made consistent through `common/sources.py` |
| clean | 12–14 | `Augmentation/Cleanning-Scripts` | subjects, languages, duplicate records in `validate.*` |
| types | 15–19 | `Augmentation/Resource_Types` | OGC API + DOI registries → `validate.records.resource_type` |
| soilvoc | 20–29 | `Augmentation/SoilVoc` | SoilVoc.ttl + subjects → `validate.soilvoc`, `validate.record_soilvoc`, noise marks |
| backfill | 30–39 | `Augmentation/Backfill` | text cleanup, abstracts ← title, `records.url`, `distributions` |
| migrate | 40 | `Migration/` | `validate.*` → `metadata.*` |

### What a dry run does

- **Skipped (no dry run):** steps 1, 2, 4, 5, 6, 15, 24, 25, 28 and 40. Run them on purpose with `--live --only N`.
- **Write, then roll back:** most other steps. They stop at the first write when `MSP_READ_ONLY=1` is set.
- **Read only, write files:** SoilVoc 20–23, 26, 27, 29 and Backfill 30–34, 36, 39.
- **Manual on purpose, not in the runner:**
  - `Backfill/cleanup/apply_cleanup.py` needs a person to sign off the diff.
  - `SoilVoc/07…/make_review_sheet.py` would overwrite verdicts people filled in.
  - The HTTP URL checks take hours.

## Folders

| Folder | Purpose |
|---|---|
| `common/` | `db.py` (`.env`, connections, read-only switch), `database.py` (harvester DB helpers), `utils.py` (DOI/PID), `text_cleaning.py` (keyword cleaner), `sources.py` + `source_aliases.json` (one name per source), `config.py`, `keyword_matching.py` |
| `Harvesting/Projects_Registry/` | ESDAC + Mission Soil Platform projects → `harvest.projects` |
| `Harvesting/CORDIS/` | CORDIS SPARQL project metadata → `harvest.items` |
| `Harvesting/EUFarmbook/` | EU-FarmBook projects → `harvest.projects`, contributions → `harvest.items` |
| `Harvesting/EUCAP/` | EU CAP projects → `harvest.projects` + `harvest.items`; practice abstracts → JSON |
| `Harvesting/Solar_API/` | SoilWise Solr API → `harvest.items` (schema.org) |
| `Augmentation/Enrichment/` | missing abstracts from Crossref / DataCite / OpenAlex |
| `Harmonize/` | `harvest.*` → `validate.*` |
| `Augmentation/Cleanning-Scripts/` | subjects, languages and duplicate records in `validate.*` |
| `Augmentation/Resource_Types/` | `validate.records.resource_type` from the OGC API and DOI registries |
| `Augmentation/SoilVoc/` | SoilVoc → `validate.soilvoc`, `validate.record_soilvoc`, noise subjects; plus analyses (tasks 01, 03, 05), `curation/`, `vocab/` |
| `Augmentation/Backfill/` | messy-text cleanup, empty abstracts ← title, `records.url`, missing `distributions`, URL checks, diagnostics |
| `Migration/` | `validate_schema.sql`, `validate.*` → `metadata.*` |
| `Pipeline/` | `run_pipeline.py`, `verify_readonly.py`, `logs/` |
| `_archive/` | one-off and legacy scripts, kept for reference only (they will not run as-is) |
| `data/` | local input/output files (git-ignored) |

## Open issues (checked read-only on msp-kh-stage)

| # | Issue | Where |
|---|---|---|
| 1 | **Do not run the migration (step 40) on stage as it is.** It drops `metadata` and copies only 16 tables. `soilvoc`, `record_soilvoc`, `record_landcover`, `record_landuse` and the type tables would be lost, and `recommendation_events` would shrink from 3,051 to 1,004 rows | `Migration/migrate_validate_to_metadata.py` |
| 2 | The Solr harvester inserts `harvest.items.updated_date`, which does not exist on stage | `Harvesting/Solar_API/harvest_solr_records.py` |
| 3 | The CORDIS harvester needs `harvest.sources`, which does not exist on stage | `Harvesting/CORDIS/` |
| 4 | The subject cleaner turns `'4 per 1000" initiative'` into `'per 1000" initiative'` | `Augmentation/Cleanning-Scripts/clean_stage_subjects.py` |
| 5 | No script produces `data/language_recovered.csv` or `data/detected_duplicates_for_review.json` | steps 13, 14 |
| 6 | Rerunning `harmonize_all_to_validate.py` duplicates distributions, and `--sync-distributions` empties `validate.distributions` | `Harmonize/` |
| 7 | The cleanup diff needs review: `verify_diff` reports 2 rows that may lose words | Backfill step 34 |
| 8 | `build_url_column.py --apply` runs `ALTER TABLE`, which needs the owner of `validate.records` | Backfill step 37 |
| 9 | `record_soilvoc` rows are deleted together with their record, so rerun SoilVoc 22–29 after a dedup (step 14) | SoilVoc |
