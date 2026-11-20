# Clean_MissionSoil-Data: Reorganization Plan

**Source:** `MissionSoil-Data`, branch `mahnoor` (HEAD `c9ed49c`, "50% work done in automation pipeline")
**Scope:** the scripts in `msp-harvester/`, `src/scripts/`, `src/scripts/clean sripts/`, plus the harmonization scripts they hand off to in `msp-md-harmonization/` and `src/db/`
**Date:** 2026-11-12

---

## 1. How the current workflow runs

The data passes through three database layers in PostgreSQL (`msp-kh-dev`):

```
 EXTERNAL SOURCES                       harvest schema (raw)            validate schema (relational)      metadata schema (final)
 ─────────────────                      ────────────────────            ────────────────────────────      ───────────────────────
 ESDAC + Mission Soil Platform ─┐
 EU-FarmBook projects ──────────┼──►  harvest.projects ─┐
 EU CAP Network projects ───────┘     (code, grantnr)   │
                                                        │ grantnr
 CORDIS SPARQL  ◄───────────────────────────────────────┘
      │ MCF YAML (partners, abstract, dates)
      ▼
 harvest.items  ◄── EU-FarmBook contributions (schema.org JSON)
      ▲         ◄── EU CAP project CORDIS enrichment (MCF YAML)
      │         ◄── SoilWise Solr API records (schema.org JSON via solr_schema_mapper)
      │
 enrich_missing_abstracts (Crossref → DataCite → OpenAlex)
      │
      ▼
 harmonize_to_validate      (harvest.projects + CORDIS items → validate.projects/records/orgs/...)
 harmonize_all_to_validate  (ALL harvest.items → validate.records + subjects/persons/orgs/distributions/junctions)
 insert_eucap_practices     (data/eu_cap_practice_abstracts.json → validate.records; skips the harvest layer)
      │
      ▼
 validate.* ──► clean_stage_subjects / clean_and_deduplicate / resource-type fixes
      │
      ▼
 SoilVoc (Augmentation/SoilVoc, from soil-vocabs/tasks): SoilVoc.ttl → validate.soilvoc,
          cleaned subjects → validate.record_soilvoc, noise → validate.subjects.vocabulary_name
      │
      ▼
 migrate_validate_to_metadata  (validate.* → metadata.*)
```

### Execution order (dependencies)

| Step | Script | Reads | Writes | Must run after |
|---|---|---|---|---|
| 1 | `harvest_esdac_projects.py` | ESDAC + MSP web pages | `harvest.projects` | none |
| 2 | `harvest_eufarmbook_projects.py` | eufarmbook.eu (Playwright) | `harvest.projects` | none |
| 3 | `harvest_eucap_projects.py` | eu-cap-network.ec.europa.eu + CORDIS SPARQL | `harvest.projects`, `harvest.items` (YAML) | none |
| 4 | `harvest_cordis_project_metadata.py` | `harvest.projects.grantnr` + CORDIS SPARQL | `harvest.items` (YAML) | 1, 2, 3 |
| 5 | `harvest_eufarmbook_contributions.py` | `harvest.projects` (source=EU-FarmBook) + eufarmbook.eu | `harvest.items` (schema.org) | 2 |
| 6 | `harvest_eucap_practice_abstracts.py` | EU CAP portal + `harvest.projects` | `data/eu_cap_practice_abstracts.json` | 1–3 |
| 7 | `harvest_solr_records.py` | SoilWise Solr search API | `harvest.items` (schema.org) | none |
| 8 | `enrich_missing_abstracts.py` | `harvest.items` (empty abstract + DOI) | `harvest.items` | 4–7 |
| 9 | `harmonize_to_validate.py` | `harvest.projects`, `harvest.items` | `validate.*` | 1–4 |
| 10 | `harmonize_all_to_validate.py` | `harvest.items` | `validate.*` | 4–8 |
| 11 | `insert_eucap_practices.py` | practice-abstracts JSON + `validate.projects` | `validate.records`, `record_project`, `distributions` | 6, 9 |
| 12 | `clean_stage_subjects.py` | `validate.subjects`, `record_subject` | same (backup tables first) | 10 |
| 13 | `clean_record_languages.py` (new, from notebook 01 §29–30) | `data/language_recovered.csv`, `validate.records` | `validate.records.language` | 10 |
| 14 | `clean_and_deduplicate_kh_dev.py` | `data/detected_duplicates_for_review.json` | `validate.records` and FK tables | 10 |
| 15 | resource-type scripts (see §3.2) | `validate.records`, OGC JSON, Crossref/DataCite | `validate.records.resource_type` | 10 |
| 16 | SoilVoc tasks 04 → 06 → 07 (`Augmentation/SoilVoc`, see §3.2) | `SoilVoc.ttl`, `validate.subjects`, `record_subject`, curation CSVs | `validate.soilvoc`, `validate.record_soilvoc`, `validate.subjects.vocabulary_name` | 12–14 |
| 17 | Backfill (`Augmentation/Backfill`, see §3.2): text cleanup, abstracts ← title, `records.url`, distributions | `validate.records`, `validate.distributions`, OpenAIRE API | `validate.records` (`title`, `abstract`, `raw_metadata`, `url`), `validate.distributions` | 12–14 |
| 18 | Crossborder `compute_crossborder.py` (`Augmentation/Crossborder`, see §10) | `validate.records.spatial`, country GeoJSON | `validate.record_crossborder` | 12–14 |
| 19 | `migrate_validate_to_metadata.py` | `validate.*` | `metadata.*` | 12–18 |

`Pipeline/run_pipeline.py` numbers the steps one script at a time: 1–14 as above, resource types 15–19, SoilVoc 20–29, backfill 30–39, crossborder 40, migration 41.

---

## 2. Folder structure (as built)

All folders now exist. They were first proposed here as "(new)" next to your "(existing)" ones. The folder names `Solar_API` and `Cleanning-Scripts` were kept as you created them. Every folder has its own `README.md` (purpose of each script, input/output tables, read/write operations).

```
Clean_MissionSoil-Data/
├── README.md                         run guide + folder table (no hosts or passwords)
├── CLEANUP_PLAN.md                   this plan: origin of every script and what was changed
├── pipeline_dfd.html                 data-flow diagram: which step reads/writes which table
├── .env                              your DB settings (not in git)
├── .env.template                     DB_*1 (stage), optional DB_*2 (dev), API keys, MSP_READ_ONLY
├── .gitignore                        .env, data/*, logs, large SoilVoc working files
├── requirements.txt                  derived from the imports in this repo (+ rdflib for SoilVoc)
├── common/                           shared code: db.py, database.py, utils.py, text_cleaning.py,
│                                     sources.py + source_aliases.json, config.py, keyword_matching.py
├── Harvesting/                       external sources → harvest.projects / harvest.items
│   ├── Projects_Registry/            ESDAC + Mission Soil Platform project lists (step 1)
│   ├── CORDIS/                       CORDIS SPARQL project metadata (step 4)
│   ├── EUFarmbook/                   projects (2) + contributions (5)
│   ├── EUCAP/                        projects (3) + practice abstracts (6) + JSON enricher
│   └── Solar_API/                    SoilWise Solr API harvester (7) + schema.org mapper
├── Augmentation/
│   ├── Enrichment/                   missing abstracts from Crossref/DataCite/OpenAlex (8)
│   ├── Cleanning-Scripts/            subjects (12), languages (13), record dedup (14)
│   ├── Resource_Types/               resource_type fixes from OGC + DOI registries (15–19)
│   ├── Backfill/                     text cleanup, abstracts ← title, records.url, distributions (30–39),
│   │                                 from SoilWise_metadata_backfill (without crosscheck/)
│   ├── Crossborder/                  records.spatial bbox → countries → validate.record_crossborder (40),
│   │                                 from K2X/polygons
│   └── SoilVoc/                      SoilVoc → validate.soilvoc / record_soilvoc / noise marks (20–29),
│                                     copied from soil-vocabs/tasks (tasks 01–07, curation/, vocab/)
├── Harmonize/                        harvest → validate (9–11)
├── Migration/                        validate_schema.sql (0), validate → metadata (41)
├── Pipeline/                         run_pipeline.py, verify_readonly.py, logs/
├── _archive/                         legacy/one-off scripts, reference only
└── data/                             local input/output files (git-ignored)
```

### 2.1 Expanded structure with scripts

Same tree, markers dropped, one line per folder saying what it does and which script does it.

```
Clean_MissionSoil-Data/
├── README.md                          short run guide: setup, run commands, folder table (no hosts or passwords)
├── .env.template                      DB_HOST1 … DB_SCHEMA1 (stage), optional DB_*2 (dev) + API keys — copy to .env and fill in
├── requirements.txt                   dependencies derived from the imports (+ rdflib for SoilVoc)
├── common/                            shared code imported by every script (finds .env, works from any directory)
│   ├── db.py                          env loader (DB_* / DB_*1 / POSTGRES_*), get_connection(), MSP_READ_ONLY=1
│   ├── database.py                    harvester DB helpers: dbQuery, dbUQuery, insQry, insertSQL, hasSource, reset
│   ├── utils.py                       DOI/PID helpers (doi_from_url, url_from_pid, pid_type, is_doi) + to_schema_org
│   ├── text_cleaning.py               clean_keyword_text(): the one keyword/subject cleaner
│   ├── sources.py                     canonical_source(): one validate.sources row per source, whatever the spelling
│   ├── source_aliases.json            canonical source name → known variants/typos (edit to add more)
│   ├── config.py                      data paths, Solr/OGC URLs, RECORD_TYPES, PAGE_LIMIT, REQUEST_DELAY
│   ├── keyword_matching.py            matchCountryUri(): country label → EU vocabulary URI (currently unused)
│   └── __init__.py                    package marker
│
├── Harvesting/                        external sources → raw harvest.* schema (projects, items, sources)
│   ├── Projects_Registry/
│   │   └── harvest_esdac_projects.py  ESDAC + Mission Soil Platform project lists → harvest.projects (step 1)
│   ├── CORDIS/
│   │   └── harvest_cordis_project_metadata.py  CORDIS SPARQL by grantnr → MCF YAML in harvest.items (step 4)
│   ├── EUFarmbook/
│   │   ├── harvest_eufarmbook_projects.py      eufarmbook.eu project cards → harvest.projects (step 2)
│   │   └── harvest_eufarmbook_contributions.py contribution pages → schema.org in harvest.items (step 5)
│   ├── EUCAP/
│   │   ├── harvest_eucap_projects.py           EU CAP scrape + CORDIS SPARQL → harvest.projects + harvest.items (step 3)
│   │   ├── harvest_eucap_practice_abstracts.py polite crawl → data/eu_cap_practice_abstracts.json (step 6, no DB writes)
│   │   └── enrich_eucap_practice_abstracts.py  fills missing acronym/grant/CORDIS URL in that JSON (helper after step 6)
│   └── Solar_API/
│       ├── harvest_solr_records.py             pages SoilWise Solr API → schema.org in harvest.items (step 7)
│       └── solr_schema_mapper.py               raw Solr doc → schema.org JSON-LD crosswalk (library, no CLI)
│
├── Augmentation/                      data quality fixes, before and after harmonization
│   ├── Enrichment/
│   │   └── enrich_missing_abstracts.py  empty abstract + DOI → Crossref → DataCite → OpenAlex, back into harvest.items (step 8)
│   ├── Resource_Types/
│   │   ├── fetch_soilwise_records.py      downloads OGC API records per type → data/<Type>_records.json (step 15)
│   │   ├── fetch_msp_kh_records.py        exports validate.records → data/msp-kh-dev.json (step 16, read-only)
│   │   ├── compare_msp_vs_ogc_types.py    matches MSP ↔ OGC features → data/msp_type_mismatches.csv (step 17)
│   │   ├── update_resource_types_from_ogc.py  applies OGC types the DOI registries confirm (step 18, dry run default)
│   │   └── resolve_neither_and_unresolved.py  rule-based types for "neither"/"unresolved" leftovers (step 19, dry run default)
│   ├── Cleanning-Scripts/
│   │   ├── clean_stage_subjects.py        cleans validate.subjects + rebuilds record_subject (step 12, dry run default)
│   │   ├── clean_record_languages.py      normalises validate.records.language from codes/names + optional CSV (step 13)
│   │   ├── clean_and_deduplicate_kh_dev.py merges duplicate clusters from a review JSON (step 14, writes by default!)
│   │   └── Language Column Data Cleanup .md  the original SQL write-up the language script was built from
│   ├── Backfill/                      copied from SoilWise_metadata_backfill (commit 450a342), crosscheck/ left out
│   │   ├── cleanup/                   cleanup_rules, find_messy (31), dry_run (32), analyse_diff (33), verify_diff (34),
│   │   │                              apply_cleanup (manual, after sign-off)
│   │   ├── abstracts/                 fill_abstract_from_title (35)
│   │   ├── url/                       url_rules, test_url_rules (30), find_urls_external (36), build_url_column (37),
│   │   │                              add_missing_distributions (38), compare_url_accessurl (39), check_urls*,
│   │   │                              url_check_ui, apply_source_urls / fix_source_urls_unescape / add_source_distributions (one-off)
│   │   ├── diagnostics/               7 read-only inspectors
│   │   ├── docs/                      original reports and plans
│   │   └── output/                    generated files + undo material (git-ignored)
│   ├── Crossborder/                   copied from K2X/polygons (2026-11-20)
│   │   ├── compute_crossborder.py     bbox → countries covered → validate.record_crossborder (step 40, --dry-run)
│   │   ├── PLAN_crossborder_spatial.md  the original design, counting rule, results and checks
│   │   └── data/                      countries_europe45.geojson, regions/NOR.geojson (GISCO file optional, git-ignored)
│   └── SoilVoc/                       copied from soil-vocabs/tasks; README has every script's tables and files
│       ├── paths.py                   all paths (repo root, vocab/, curation/, task outputs); applies MSP_READ_ONLY
│       ├── vocab/                     SoilVoc.ttl, SoilVoc_concepts.csv, ontovocabs/, uk2us.py (from soil-vocabs root)
│       ├── curation/                  hand-edited decisions, translations, stoplist, reviews
│       ├── 04_soilvoc_hierarchy/      soilvoc_levels (step 20), soilvoc_json (21), soilvoc_mermaid — files only
│       ├── 06_keyword_cleaning/       clean_subjects (22, DB read), review_inside_keywords (23), soilvoc_terms_in_db
│       ├── 07_populate_soilvoc_db/    create_soilvoc_tables (24), load_soilvoc (25), build_soilvoc_links (26),
│       │                              build_record_soilvoc (27), load_record_soilvoc (28), check_soilvoc_vs_json (29),
│       │                              make_review_sheet (manual), sql/
│       ├── 01_subjects_vs_soilvoc/    analysis + matching code imported by 03, 06
│       ├── 05_soilvoc_db_coverage/    analysis: SoilVoc use in keywords, titles, abstracts, soil-threat filter
│       └── 03_stage_vs_dev/           side task: stage vs dev (needs DB_*2)
│
├── Harmonize/                         harvest.* → validate.* (relational, UUID-keyed)
│   ├── harmonize_projects_to_validate.py   harvest.projects + CORDIS items → validate.projects/records/orgs (step 9)
│   ├── harmonize_all_to_validate.py        every harvest.items row → validate.records + junctions, 3 parsers; source names via common/sources.py (step 10)
│   └── insert_eucap_practices.py           practice-abstracts JSON → validate.records (step 11, skips harvest layer)
│
├── Migration/                         validate → metadata, plus schema DDL
│   ├── validate_schema.sql            DDL for the validate schema: 20 tables, FKs, indexes (step 0, run once)
│   └── migrate_validate_to_metadata.py  pg_dump DDL + copy validate.* → metadata.* with counts/orphan check (step 41)
│
├── Pipeline/                          runs and checks everything else; holds no pipeline logic itself
│   ├── run_pipeline.py                orchestrates the 42 steps in order: list / --stage / --only / --live (confirm), logs
│   ├── verify_readonly.py             scans scripts vs DB tables/columns, forces MSP_READ_ONLY=1, exit 1 on problems
│   └── logs/                          one timestamped log file per run
│
├── _archive/                          unchanged legacy/one-off scripts — reference only, won't run as-is
│   ├── msp-harvester/                 insert_eufarmbook_to_harvest, insert_missing_projects_to_harvest,
│   │                                  enrich_eucap_projects, insert_eucap_projects_to_harvest,
│   │                                  convert_harvest_to_schema_org, citation2doi
│   ├── src/                           backfill_metadata_organizations, migrate_metadata_to_kh_dev,
│   │                                  analyze_person_org_relations, insert_normalized_ultra, queries, connection
│   └── msp-md-harmonization/          process.py (old pygeometa harmonizer, replaced by Harmonize/)
│
└── data/                              local input/output files, git-ignored, found via common.db.DATA_DIR
```

> Script list verified against the files on disk (`**/*.py`). `Augmentation/Resource_Types/config.py`, proposed in §3.2, was merged into `common/config.py` and no longer exists in that folder.

---

## 3. Folder-by-folder plan

**Action legend:**
- **Copy:** move the file as it is, apart from the shared cleanup rules in §4.
- **Clean:** move it and fix the specific issues listed.
- **Merge:** fold it into another script or module.
- **Archive:** don't carry it into the active pipeline.

### 3.0 `common/` (new)

**Purpose:** a single place for the DB connection, `.env` loading, and helpers. Today every script has its own `get_db_connection()`. Some read `DB_*` variables, some read `POSTGRES_*`, and the imports use the cwd-dependent `sys.path.append('utils')`.

| File | Origin | Purpose | Action |
|---|---|---|---|
| `db.py` | `msp-harvester/utils/database.py` + `src/db/connection.py` + the per-script `get_db_connection()` copies | One connection factory: walks up to find `.env`, reads `DB_*` with `POSTGRES_*` fallback, and provides `dbQuery`, `insertRecord`, `hasSource`, `reset(source)` | Merge |
| `utils.py` | `msp-harvester/utils/utils.py` | DOI/PID helpers (`doi_from_url`, `url_from_pid`, `pid_type`, `is_doi`) and generic `to_schema_org` | Copy |
| `text_cleaning.py` | `clean_keyword_text()` from `clean sripts/solr_schema_mapper.py` and `clean_stage_subjects.py` | One keyword/subject cleaner (strip HTML, classification codes, split on `;`, drop noise numbers). It's currently duplicated in 2 files | Merge |
| `cordis.py` | SPARQL code in `harvest_cordis_project_metadata.py` + `harvest_eucap_projects.py` + `enrich_eucap_projects.py` | Shared CORDIS SPARQL client: build the query for a batch of grant IDs, run it with retry, map rows to MCF YAML | Merge |
| `mappings/eucap_project_overrides.json` | `SUPPLEMENTAL_MAPPING` / `TITLE_BASED_ENRICHMENT` dicts | Manual title → acronym/grant/CORDIS overrides. The same table is hard-coded in 3 scripts today | Merge (move from code to data) |
| `sources.py` + `source_aliases.json` | **new** (2026-11-13) | One canonical name per source for `validate.sources`. Ignores case, spaces, URL scheme, `www.` and a trailing `/`, and maps the listed variants/typos (e.g. `data.erupa.eu` → `data.europa.eu`). Warns about look-alike names it does not know | New; used by `harmonize_all_to_validate.py` |
| `keyword_matching.py` + `country_data.json` | `msp-harvester/utils/keyword_matching.py` | Country label → EU vocabulary URI | Copy (only if a harvester still imports it; otherwise Archive) |

### 3.1 `Harvesting/`: external sources → `harvest.projects` / `harvest.items`

#### `Harvesting/Projects_Registry/` (new)

**Purpose:** builds the seed project list. `harvest.projects` drives the CORDIS, EU-FarmBook contributions, and EU CAP practice-abstract steps.

| Script | Origin | Purpose | Action |
|---|---|---|---|
| `harvest_esdac_projects.py` | `msp-harvester/` | Scrapes the ESDAC EU-funded projects table and the Mission Soil Platform "funded projects" page, then upserts into `harvest.projects` on `(code, grantnr)` | Clean: wrap the top-level code in `main()`, use `common.db` |

#### `Harvesting/CORDIS/` (new)

**Purpose:** enriches every project with a grant number with its official CORDIS metadata.

| Script | Origin | Purpose | Action |
|---|---|---|---|
| `harvest_cordis_project_metadata.py` | `msp-harvester/` (same as `clean sripts/` copy) | Reads `grantnr` from `harvest.projects`, queries the CORDIS SPARQL endpoint in batches of 10, builds MCF YAML (abstract, dates, partner organisations, DOI), and inserts into `harvest.items` with `source='CORDIS'` | Clean: use `common.cordis`; add `--dry-run` / `--limit` |
| ~~`project-metadata.py`~~ | `msp-harvester/` | Duplicate of the script above (only 2 `sys.path` lines differ) | Archive (delete) |

#### `Harvesting/EUFarmbook/` (existing)

**Purpose:** EU-FarmBook projects and their contributions (documents, videos, practice material).

| Script | Origin | Purpose | Action |
|---|---|---|---|
| `harvest_eufarmbook_projects.py` | `msp-harvester/` (DB-only version) | Playwright scrape of Horizon 2020 / Horizon Europe projects on eufarmbook.eu. Gets past the Anubis bot check, picks the best grant ID (DOI `10.3030/…` → CORDIS URL → fallback), and upserts into `harvest.projects` (`source='EU-FarmBook'`) | Clean: the docstring says `--scrape`, but that flag was removed from argparse, so the documented command fails. Fix the docstring |
| `harvest_eufarmbook_contributions.py` | `msp-harvester/` (DB-only version) | Loads EU-FarmBook projects from `harvest.projects`, opens each project's Contributions tab and every contribution detail page, converts each one to schema.org JSON, and batch-inserts into `harvest.items` (`itemtype='contribution'`, `project=grant_number`) | Copy |
| `insert_eufarmbook_to_harvest.py` | `msp-harvester/` | Old two-step loader: reads `eufarmbook_projects.json` / `eufarmbook_contributions2.json` into `harvest.items`. The two scripts above now insert directly | Archive |
| `insert_missing_projects_to_harvest.py` | `msp-harvester/` | One-off gap fill for 8 named projects (Crop-MATCHING, FreeBirds…) with an `eufb-…` placeholder grant | Archive (one-off) |

> I took the `msp-harvester/` versions, not the `clean sripts/` versions, because they are the newer "no JSON, DB only" variants and match the automation-pipeline direction.

#### `Harvesting/EUCAP/` (existing)

**Purpose:** EU CAP Network Horizon 2020 / Horizon Europe projects and their Practice Abstracts.

| Script | Origin | Purpose | Action |
|---|---|---|---|
| `harvest_eucap_projects.py` | `msp-harvester/` | Single EU CAP project pipeline. Scrapes project pages (including `a.chip--keyword` keywords), resolves acronym/grant/CORDIS URL, upserts `harvest.projects`, then queries CORDIS SPARQL and inserts MCF YAML into `harvest.items`. Flags: `--scrape`, `--skip-cordis`, `--dry-run`, `--limit` | Clean: remove the fallback to `data/eucap_*.json` seed files (always scrape, or add an explicit `--seed-json`); load overrides from `common/mappings`; use `common.cordis` |
| `harvest_eucap_practice_abstracts.py` | `msp-harvester/` | Polite crawl of all Practice Abstracts (rotating User-Agent, jitter, 429 cooldown, resume checkpoints). Matches each to a DB project and writes `data/eu_cap_practice_abstracts.json` | Clean: (1) it looks for `eufarmbook_projects.json`, which no longer exists, so use `harvest.projects` only; (2) **recommended:** write to `harvest.items` as schema.org instead of JSON, so the generic harmonizer can handle it |
| `enrich_eucap_practice_abstracts.py` | `msp-harvester/` | Post-fixes the practice-abstracts JSON: fills missing acronym/grant/CORDIS URL from the title override table | Merge into the harvester (apply overrides in memory before saving) |
| `enrich_eucap_projects.py` | `msp-harvester/` | Post-fixes the 206-project JSON with grant IDs from practice abstracts + CORDIS SPARQL. Already folded into `harvest_eucap_projects.py` | Archive |
| `insert_eucap_projects_to_harvest.py` | `msp-harvester/` | Loads the 206-project JSON into `harvest.projects`; `--copy-testing-base` copies the 341 base projects from `msp-testing`. Superseded by `harvest_eucap_projects.py` | Archive (keep `--copy-testing-base` as a separate one-off in `Migration/` if it's still needed) |

#### `Harvesting/Solar_API/` (existing, SoilWise Solr)

**Purpose:** pulls the SoilWise catalogue (OpenAIRE, BonaRes, CORDIS, Impact4Soil, data.europa.eu, …) and stores each record in a standard schema.org form.

| Script | Origin | Purpose | Action |
|---|---|---|---|
| `harvest_solr_records.py` | `clean sripts/` (identical to `msp-harvester/` apart from one lint comment) | Pages through the Solr search API (default 500 per page), maps each doc to schema.org, derives the table columns (itemtype, title, language, dates, project, primary source), and upserts into `harvest.items` on MD5 hash. Flags: `--batch-size`, `--limit`, `--dry-run` | Clean: replace the 5-level `sys.path` search with a normal package import |
| `solr_schema_mapper.py` | **`clean sripts/` version** | Crosswalk from raw Solr doc to schema.org JSON-LD: source extraction, DOI/identifier/URI, project-name cleanup, and keyword cleaning (`clean_keyword_text`, newer than the `msp-harvester/` copy) | Clean: import the keyword cleaner from `common.text_cleaning` |
| `convert_harvest_to_schema_org.py` | `msp-harvester/` | One-off migration: converts old `resulttype='json'` Solr rows already in `harvest.items` to schema.org | Archive (or `Migration/` if older DBs still have `json` rows) |

### 3.2 `Augmentation/`: improve data quality

#### `Augmentation/Enrichment/` (new)

**Purpose:** fills gaps in records using external registries.

| Script | Origin | Purpose | Action |
|---|---|---|---|
| `enrich_missing_abstracts.py` | `msp-harvester/` | For `harvest.items` rows with an empty abstract and a DOI, tries Crossref → DataCite → OpenAlex (rebuilds OpenAlex inverted-index abstracts, strips JATS XML) and patches `resultobject`. Flags: `--dry-run`, `--limit`, `--source`, `--workers` | Copy (runs **before** harmonization) |
| `backfill_metadata_organizations.py` | `src/scripts/` | Repair for an old bug (`contacts` vs `contact` key) that dropped CORDIS partner orgs. Backfills `metadata.organization` and `contact_in_record` from CORDIS YAML | Archive (the new harmonizer already reads `contacts`); keep only if old `metadata` data must still be repaired |

#### `Augmentation/Resource_Types/` (new)

**Purpose:** correct `validate.records.resource_type` by reconciling MSP, the OGC catalogue, and the DOI registries.

| Script | Origin | Purpose | Action |
|---|---|---|---|
| `fetch_msp_kh_records.py` | `src/scripts/` | Exports identifier + title from `validate.records` to `msp-kh-dev.json`, which `compare_msp_vs_ogc_types.py` reads as the MSP side | Copy |
| `fetch_soilwise_records.py` | `src/scripts/` | Downloads OGC API records per resource type into `data/` (input for the comparison) | Clean: use `config.py` constants from `common/` |
| `compare_msp_vs_ogc_types.py` | `src/scripts/` | Matches MSP records to OGC features (ID → link href → validated title) and writes a CSV of type mismatches | Clean: replace the hard-coded paths |
| `update_resource_types_from_ogc.py` | `src/scripts/` | Applies OGC types where Crossref/DataCite confirm OGC is right. Creates a backup table first; has `--dry-run` | Copy |
| `resolve_neither_and_unresolved.py` | `src/scripts/` | Rule-based resolution for the remaining "neither" and "unresolved" records (registry type map, EU portal deliverables → Report, …). Backup table, `--dry-run` | Copy |
| `config.py` | `src/scripts/` | Data paths, Solr/OGC URLs, record types list | Merge into `common/config.py` |

> `notebooks/05_doi_registry_type_resolution.ipynb` produces the registry cache these scripts use. Keep it in the original repo, or turn it into a script here if this step must be automated.

#### `Augmentation/Cleanning-Scripts/` (existing)

**Purpose:** clean and deduplicate the relational `validate` layer before migrating it.

| Script | Origin | Purpose | Action |
|---|---|---|---|
| `clean_stage_subjects.py` | `clean sripts/` | Cleans `validate.subjects`: drops noise numbers/dates, strips classification prefixes and HTML, splits `;` lists, merges duplicates, re-links `record_subject`. Dry-run by default, `--commit` to apply, timestamped backups, single transaction | Clean: use `common.text_cleaning`; change the default `--dbname` from `msp-kh-stage` to `.env` |
| `clean_record_languages.py` | **new**, from `notebooks/01_soilwise_pipeline_and_reconciliation.ipynb` §29–30 (cells 56 and 58) | Fills `validate.records.language` where it is NULL, `''` or `'Unknown'`, from `data/language_recovered.csv` (identifier, language). Commits every 100 rows and resumes on rerun. Only touches rows that are still empty | New script: use the §30 batch version and drop the one-row-at-a-time §29 version. Remove the DB URL with the password hard-coded in the notebook. Use `validate.records`, not the unqualified `records`. Add `--csv`, `--dry-run`. Also normalize codes to one standard: `harmonize_all_to_validate.py` defaults to `en`, `harmonize_to_validate.py` to `eng`. Nothing in the repo produces `language_recovered.csv`, so find or rebuild that step |
| `clean_and_deduplicate_kh_dev.py` | `src/scripts/` | Merges duplicate record clusters from `data/detected_duplicates_for_review.json`: snapshots tables, enriches the winner, re-points the FKs (sources, persons, orgs, subjects, projects, distributions), deletes the losers, prints an audit | Clean: add `--dry-run`, `--input` path, and document where the duplicates JSON comes from (`testing.ipynb`?) |

#### `Augmentation/SoilVoc/` (new, 2026-11-13; from `soil-vocabs/tasks`)

Puts SoilVoc in the DB (PO task #206): concepts → `validate.soilvoc`, one row per (record, concept) → `validate.record_soilvoc`, and noise subjects marked with `validate.subjects.vocabulary_name = 'noise'`. The task folders were copied unchanged with their docs, outputs and `curation/`; `SoilVoc.ttl`, `SoilVoc_concepts.csv`, `ontovocabs/` and `uk2us.py` went into `vocab/`. Full per-script table: `Augmentation/SoilVoc/README.md`.

| Folder / script | Origin | Purpose | Action |
|---|---|---|---|
| `paths.py` | `tasks/paths.py` | Every path; scripts find it by walking up | Changed: `ROOT` = repo root (via `common/db.py`), `VOCAB` = `vocab/`; applies `MSP_READ_ONLY=1` |
| `04_soilvoc_hierarchy/` (3 scripts) | `tasks/04_…` | Level + tree parent per concept; JSON tree; Mermaid | Copy (steps 20, 21) |
| `06_keyword_cleaning/` (3 scripts) | `tasks/06_…` | Cleans/translates/matches keywords to SoilVoc, CSV only | Copy (steps 22, 23) |
| `07_populate_soilvoc_db/` (7 scripts + 2 SQL) | `tasks/07_…` | Creates and fills `soilvoc` / `record_soilvoc`, marks noise | Copy (steps 24–29; `make_review_sheet.py` stays manual because it overwrites verdicts) |
| `01_…`, `05_…` | `tasks/01_…`, `tasks/05_…` | Analyses; 01's matching code is imported by 03, 06 | Copy (not in the runner) |
| `03_…` | `tasks/03_…` | Side task: stage vs dev | Copy |
| ~~`02_llm_subject_extraction`~~ | `tasks/02_…` | LLM suggestions for records without subjects (Ollama / Mistral) | **Not copied** (2026-11-18): not used; nothing else reads it |
| `curation/` | `tasks/curation/` | Hand-edited inputs | Copy |
| `vocab/` | soil-vocabs root | `SoilVoc.ttl`, `SoilVoc_concepts.csv`, `ontovocabs/`, `scripts/uk2us.py` | Copy |

Code changes in the scripts are limited to `ROOT / "SoilVoc.ttl"` → `SOILVOC_TTL`, `ROOT / "SoilVoc_concepts.csv"` → `SOILVOC_CSV`, `ROOT / "ontovocabs"` → `ONTOVOCABS`, and `tasks/…` → `Augmentation/SoilVoc/…` in usage text and docs.

#### `Augmentation/Backfill/` (new, 2026-11-18; from `github.com/ahmadkhanraj01/SoilWise_metadata_backfill`)

| Folder | Origin | Purpose | Action |
|---|---|---|---|
| `cleanup/` (6 scripts) | `scripts/cleanup/` | Messy text in `title` / `abstract` / `raw_metadata`: scan, dry run, classify, verify, apply | Copy. DB from `common/db.py` with `search_path = validate`. Fixed the `verify_diff.py` path in `apply_cleanup.py` (its preflight always failed). Timestamped backups. Apply stays manual |
| `abstracts/` (1) | `scripts/abstracts/` | Empty / placeholder `abstract` ← `title` | Copy, same changes (step 35) |
| `url/` (13) | `scripts/url/` | `records.url` from identifier rules + OpenAIRE/page search, `distributions` rows, URL checks | Copy. Fixed the `compare_url_accessurl.py` path in `url_check_ui.py`, a missing `mkdir` and a wrong report path. Steps 30, 36–39; HTTP checks and the 2026-10-07 source pass stay manual (its input CSVs are not in the repo) |
| `diagnostics/` (7) | `scripts/diagnostics/` | Read-only inspectors | Copy (`db_check.py` now filters by schema) |
| `docs/` | `docs/{cleanup,abstracts,url}`, `known_issues_schema_validate.md` | Reports and plans | Copy unchanged |
| ~~`crosscheck/`~~ | | Title/abstract recovery from the Solr JSON export and source pages | **Not copied**: needs `Sep8_SolrData.json` (130 MB) and the caches |

### 3.3 `Harmonize/` (existing): `harvest.*` → `validate.*`

**Purpose:** turns raw payloads (Solr JSON, schema.org JSON, MCF YAML) into the relational, UUID-based `validate` schema.

| Script | Origin | Purpose | Action |
|---|---|---|---|
| `harmonize_projects_to_validate.py` | `msp-md-harmonization/harmonize_to_validate.py` (renamed) | Builds `validate.projects` from `harvest.projects` and project records from CORDIS items: organisations, subjects, distributions (CORDIS/website links), `record_project`. `--dry-run`, `--limit` | Clean: rename for clarity; use `common.db` |
| `harmonize_all_to_validate.py` | `clean sripts/` (identical to `msp-md-harmonization/`) | Generic harmonizer for **all** `harvest.items`. Parsers: `parse_solr_json`, `parse_schema_org`, `parse_mcf_yaml`. Fills records, sources, subjects, persons, organisations, distributions, projects and all junction tables. Uses per-batch savepoints with cache rollback. Flags: `--source`, `--limit`, `--batch-size`, `--missing-only`, `--sync-distributions`, `--dry-run` | Clean: the docstring says "MCF YAML = EU CAP only", but CORDIS is YAML too, so update it; use `common.text_cleaning` for subjects. At 1,223 lines, consider splitting the parsers into `parsers/` |
| `insert_eucap_practices.py` | `msp-md-harmonization/` | Loads practice-abstracts JSON straight into `validate.records`, `record_project`, `distributions` | Clean now. Archive once the practice-abstract harvester writes to `harvest.items` (then `harmonize_all` covers it) |
| ~~`src/process.py`~~ | `msp-md-harmonization/src/` | Legacy pygeometa harmonizer from `harvest.vw_unique_harvest_items` → `metadata.*` (old async `databases` stack) | Archive (replaced by the `validate` path) |

### 3.4 `Migration/` (new): `validate.*` → `metadata.*` and DB setup

| File | Origin | Purpose | Action |
|---|---|---|---|
| `validate_schema.sql` | `src/scripts/` | DDL for the `validate` schema (tables, FKs, indexes) | Copy (run first on a fresh DB) |
| `migrate_validate_to_metadata.py` | `src/db/` | Read-only on `validate`. Generates the `metadata` DDL, re-points the 15 FKs, copies data in dependency order, skips `records_backup_*`, then validates counts and orphans | Copy |
| `migrate_metadata_to_kh_dev.py` | `src/scripts/` | Old cross-DB migration `msp-testing.metadata` → `msp-kh-dev` with null-name fallbacks | Archive unless a cross-DB copy is still needed |

### 3.5 `Pipeline/` (new): finishes the "50% automation pipeline"

| File | Purpose |
|---|---|
| `run_pipeline.py` | Runs the §1 steps in order as subprocesses or imported `main()`s. Flags: `--steps harvest,augment,harmonize,clean,migrate`, `--only <script>`, a global `--dry-run`, and stop-on-failure with a summary of row counts per step |
| `pipeline.yaml` | Ordered step list (script, args, enabled), so steps can be switched on/off without code changes |
| `logs/` | One timestamped log file per run |

### 3.6 Not carried over (stay in `MissionSoil-Data` or `_archive/`)

| File | Why |
|---|---|
| `src/db/insert_normalized_ultra.py`, `src/db/queries.py`, `src/db/connection.py` | Old "normalized" schema (`records`/`persons` without a schema prefix) fed from `merged.json`; replaced by `validate`. `connection.py` is merged into `common/db.py` |
| `src/api/search_api.py` | Separate Flask/SPARQL search service, not part of the data pipeline. Give it its own repo or folder if needed |
| `src/scripts/analyze_person_org_relations.py` | Ad-hoc analysis of local Solr JSON dumps |
| `src/scripts/testing.ipynb`, `msp-md-harmonization/src/cleaning_and_testing.ipynb`, `notebooks/*` | Exploration notebooks; keep them in the original repo |
| `msp-harvester/utils/citation2doi.py` | Standalone CSV tool with hard-coded `file.csv`; not imported by anything |
| `msp-harvester/project-metadata.py` | Duplicate of `harvest_cordis_project_metadata.py` |
| The one-off loaders and enrichers marked **Archive** above | Superseded by the unified harvesters |

---

## 4. Cleanup rules for every script

1. **One DB connection.** Every script imports `common.db.get_connection()`. Remove the per-script `get_db_connection()` copies, `--host/--port/--user/--password` duplication (keep only `--dbname` override), and `sys.path.append('utils')`.
2. **One env var set.** Use `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` (read `POSTGRES_*` as a fallback). Today `utils/database.py` reads **only** `POSTGRES_*` while most other scripts read `DB_*`.
3. **No secrets in docs.** The current README shows the DB host IP and user. The clean README should point to `.env.template` only.
4. **Same CLI for every DB-writing script:** `--dry-run` (roll back), `--limit N`, and `--source X` where it makes sense.
5. **`main()` guard.** Scripts like `harvest_esdac_projects.py` run at import time; wrap them in `def main()` + `if __name__ == "__main__":` so the orchestrator can import them.
6. **Logging.** Use `logging` instead of `print`, with the same format everywhere.
7. **No intermediate JSON in the main path.** Harvesters write to the DB. JSON caches are allowed only behind an explicit flag.
8. **Hard-coded mappings go into data files** (`common/mappings/*.json`), not Python dicts.
9. **Accurate docstrings and usage lines** (e.g. remove the `--scrape` example from `harvest_eufarmbook_projects.py`).

---

## 5. Problems found in the current branch

| # | Problem | Where | Fix in clean repo |
|---|---|---|---|
| 1 | The documented `python harvest_eufarmbook_projects.py --scrape` now fails with an argparse error (flag removed) | `msp-harvester/harvest_eufarmbook_projects.py` | Fix the docstring |
| 2 | Practice-abstract harvester looks for `eufarmbook_projects.json`, which is no longer produced | `harvest_eucap_practice_abstracts.py` | Use `harvest.projects` only |
| 3 | `harvest_eucap_projects.py` silently prefers old `data/eucap_*.json` seed files over scraping | `harvest_eucap_projects.py` | Explicit `--seed-json` flag |
| 4 | Practice abstracts bypass the `harvest` layer (JSON → `validate` directly) | `insert_eucap_practices.py` | Store them in `harvest.items` as schema.org |
| 5 | Two different `solr_schema_mapper.py` versions | `msp-harvester/` vs `clean sripts/` | Keep the `clean sripts/` one (has keyword cleaning) |
| 6 | Two EU-FarmBook script versions (JSON-cache vs DB-only) | `msp-harvester/` vs `clean sripts/` | Keep the `msp-harvester/` DB-only ones |
| 7 | Exact duplicates: `project-metadata.py` ≈ `harvest_cordis_project_metadata.py`; `harmonize_all_to_validate.py` in 2 places; `Today_progress.md` = `Todays_progress.md` | several | Keep one copy |
| 8 | Same override table hard-coded in 3 scripts | EU CAP enrich/harvest scripts | `common/mappings/eucap_project_overrides.json` |
| 9 | Mixed env var names (`DB_*` vs `POSTGRES_*`) | 20+ scripts | `common/db.py` |
| 10 | README lists scripts that no longer exist (`merge_solr_json.py`, `test_db_schema_relations.py`, `validate_links_and_sources.py`) | `README.md` | New README |
| 11 | Folder name typos | `src/scripts/clean sripts` (space + typo), `Cleanning-Scripts`, `Solar_API` | Suggest `Cleaning_Scripts`, `Solr_API` |

---

## 6. Migration steps

1. Create the new folders (`common/`, `Projects_Registry/`, `CORDIS/`, `Enrichment/`, `Resource_Types/`, `Migration/`, `Pipeline/`, `_archive/`).
2. Build `common/` first (`db.py`, `utils.py`, `text_cleaning.py`, `cordis.py`, `mappings/`), because every other script depends on it.
3. Copy the scripts into their folders as in §3 and apply the §4 rules one folder at a time.
4. Run each script once with `--dry-run --limit 5` against `msp-kh-dev`, and compare row counts with the original script.
5. Write `Pipeline/run_pipeline.py` + `pipeline.yaml` and do a full dry run.
6. Write the README (run order, `.env.template`, what each folder does).
7. Move the **Archive** items into `_archive/`, or leave them in `MissionSoil-Data`.

---

## 7. Execution status (2026-11-12)

**Done.** The original `MissionSoil-Data` folder was only read (`git status` is clean).

- Folders created. Scripts copied into place. One-off and legacy scripts are in `_archive/` (unchanged copies).
- `common/db.py`: one `.env` loader (accepts `DB_*`, `DB_*1`, `POSTGRES_*`), `get_connection()`, and `MSP_READ_ONLY=1` → `default_transaction_read_only=on` for every connection.
- `common/database.py` / `utils.py` / `config.py` / `text_cleaning.py` replace `msp-harvester/utils` and the two keyword-cleaner copies. The two copies were tested and give identical results.
- Every script: the `sys.path.append('utils')` / per-script `.env` search is replaced by the shared bootstrap. Hard-coded `/home/radio-analyzer/...` paths and `data/` paths now point to `<repo>/data`.
- Script fixes:
  - `harvest_eufarmbook_projects.py`: the docstring no longer shows the removed `--scrape` flag.
  - `harvest_esdac_projects.py`: wrapped in `main()`, so importing it no longer scrapes.
  - `harvest_eucap_projects.py`: scrapes by default. It no longer silently loads a seed JSON; there is an explicit `--seed-json` flag.
  - `harvest_eucap_practice_abstracts.py`: the dead `eufarmbook_projects.json` paths are removed.
  - `enrich_missing_abstracts.py`: no longer hard-wired to `msp-kh-dev`.
  - `clean_stage_subjects.py`: `--dbname` defaults to `.env`.
  - `clean_and_deduplicate_kh_dev.py`: `search_path` is pinned to `DB_SCHEMA`.
  - `fetch_msp_kh_records.py` / `compare_msp_vs_ogc_types.py`: output names now match what the next step reads.
- New `Augmentation/Cleanning-Scripts/clean_record_languages.py`. It combines the language .md mapping with the notebook 01 §29–30 recovery from CSV. It is idempotent, dry run by default, and backs up before `--commit`.
- New `Pipeline/run_pipeline.py` (ordered steps, dry run by default, confirmation for live runs, logs) and `Pipeline/verify_readonly.py`.
- `README.md`, `.env.template`, `.gitignore`, `requirements.txt`.

**Verified read-only against `msp-kh-stage`:**
- All scripts compile, and `--help` works from any directory.
- `verify_readonly.py` checks tables and columns against the DB.
- Dry runs of steps 12, 13 and 16 complete.
- Both harmonizers load the stage caches and parse real rows, then the read-only guard blocks the first INSERT, as intended.

**Problems found on stage (not fixed; need a decision):**
1. `harvest_solr_records.py` inserts `harvest.items.updated_date`, which does not exist on stage. The insert fails.
2. `harvest_cordis_project_metadata.py` calls `hasSource()` on `harvest.sources`, which does not exist on stage. `dbQuery` returns `None` and the script crashes. `harvest.item_duplicates` is also missing.
3. `migrate_validate_to_metadata.py` runs `DROP SCHEMA metadata CASCADE` but copies data for only 16 tables. `metadata` on stage has data it would not restore: `record_soilvoc` 18,587, `record_landcover` 14,842, `record_landuse` 14,419, `soilvoc` 543, landcover/landuse types. It would also replace `recommendation_events` (3,051 rows) with validate's 1,004. **Do not run it on stage as it is.**
4. `clean_stage_subjects.py` would rename `'4 per 1000" initiative'` to `'per 1000" initiative'`: the classification-number stripping hits a real term.
5. The language SQL in the .md is not safe to rerun (`'English'` → `'Unknown'`). The new script handles this.

**Not done yet (next pass):**
- `common/cordis.py` (shared SPARQL client).
- EU CAP override tables → `common/mappings/*.json`.
- Removing the per-script `--host/--port/--user/--password` flags. They still work, with defaults from `.env`.
- `logging` instead of `print`.
- Practice abstracts → `harvest.items` (so `insert_eucap_practices.py` can be retired).
- Splitting `harmonize_all_to_validate.py` into parsers.

## 8. Update (2026-11-13): source aliases and SoilVoc

**Source names (`common/sources.py`, `common/source_aliases.json`).** `harmonize_all_to_validate.py` used to match sources only by `strip().lower()`, so `https://data.europa.eu/` or a typo like `data.erupa.eu` would have created a second source. It now maps every name to a canonical one first. Unknown look-alikes (e.g. `data.europe.eu`) are logged as a WARNING and still created, because auto-merging short names like `eea` / `fao` would be unsafe. Stage today has 14 clean source names, 0 duplicate (record, source) pairs and `UNIQUE (record_id, source_id)`. The dedup script's `ON CONFLICT (record_id, source_id) DO NOTHING` already covers two duplicate records that share a source. Existing variant rows are not merged (no such rows on stage). Verified: harmonizer dry run on stage loads the 14 sources, then the read-only guard stops the first INSERT.

**SoilVoc (`Augmentation/SoilVoc`).** Copied from `soil-vocabs/tasks` (the soil-vocabs repo was only read: its 17 uncommitted changes are unchanged). Pipeline steps 20–29; migration moved to step 30.
- Verified on stage with every session read-only: steps 20–23, 26, 27, 29 run, and their outputs are **byte-identical** to the copied originals. `check_soilvoc_vs_json` reports no mismatches. The writers (24, 25, 28) load and validate their inputs, then stop at the first write. The outputs were then restored from a snapshot.
- Stage now: `validate.soilvoc` 1,464, `validate.record_soilvoc` 18,601 (one run), 1,534 subjects marked `noise`, three `subjects_pre_soilvoc_backup_*` tables.
- `.env.template` now uses the `DB_*1` names (the SoilVoc scripts read them directly), with optional `DB_*2` (dev, task 03 only). Your `.env` already has `DB_*1`. It has no `DB_*2`, so task 03 will not run until you add them.

**New findings:**
1. `migrate_validate_to_metadata.py` does not copy `soilvoc` / `record_soilvoc` either (adds to problem 3 above).
2. `make_review_sheet.py` overwrites `review_sheet.csv`, so a rerun would erase filled-in verdicts (no verdicts yet). It is kept out of the runner.
3. `record_soilvoc` is deleted with its record (`ON DELETE CASCADE`): rerun steps 22–29 after any dedup (step 14).

## 9. Update (2026-11-18): Backfill scripts

Copied from `SoilWise_metadata_backfill` (commit `450a342`) into `Augmentation/Backfill/`, without `crosscheck/`. 27 scripts in 4 folders; pipeline steps 30–39; migration moved to step 40. Details: `Augmentation/Backfill/README.md`.
- Every DB script now connects through `common/db.py` (repo `.env`, `MSP_READ_ONLY=1`, `search_path = validate`). This fixes the source repo's known issue that the older scripts no longer ran after the move to `validate`.
- Bugs fixed: `apply_cleanup.py` called `scripts/verify_diff.py` (moved), so its safety check always failed. `url_check_ui.py` called an old path. `compare_url_accessurl.py` crashed without `output/url/`. Three URL dry runs exited with code 1. Backup file names are now timestamped, so reruns don't stop.
- Verified read-only on stage (all 27 scripts compile; every DB script ran): scan 348 records / 353 field changes; `verify_diff` says NEEDS REVIEW (2 rows may lose words), so the apply is correctly blocked. 1 placeholder abstract. 0 new URLs from the identifier rules and 6 from the verified OpenAIRE/page candidates (1,991 still without). 204 URLs without a distribution row.
- Open: `build_url_column.py --apply` runs `ALTER TABLE`, which needs the owner of `validate.records` (`missionsoil_user`), not the `.env` user.

## 10. Update (2026-11-20): Crossborder (`K2X/polygons`)

Copied from `K2X/polygons` into `Augmentation/Crossborder/`; the original folder was only read. Pipeline step 40 (stage `spatial`); migration moved to step 41.

| Item | From `polygons/` | Action |
|---|---|---|
| `compute_crossborder.py` | root | Copy. DB settings from the repo `.env` via `common/db.py` (honours `MSP_READ_ONLY=1`) instead of `polygons/.env`; data paths → `./data`; the GISCO file is read only by the scopes that use it |
| `PLAN_crossborder_spatial.md` | root | Copy unchanged |
| `data/countries_europe45.geojson` | `data/` (= `geojson_data 1/geojson_data/countries.geojson`) | Copy |
| `data/regions/NOR.geojson` | `geojson_data 1/geojson_data/regions/` | Copy. The only regions file that patches a country; the other 35 change nothing |
| `CNTR_RG_01M_2020_4326.geojson` (62 MB) | `data/` | **Not copied** (git-ignored if added). Only the `hybrid`/`world`/`europe`/`eu27` scopes need it |
| `.env`, `.env.template` | root | Not copied: the repo `.env` is used |

- Verified read-only on stage: the copy's `--dry-run --csv` output is **byte-identical** to the original's (4,857 records with `spatial`, 4,010 rows, 1,558 cross-border).
- Stage already holds the table: `validate.record_crossborder` and `metadata.record_crossborder` (4,010 rows each). `msp-kh-dev` has neither, so a live run there would create it.
- The migration (step 41) does not copy `record_crossborder`, so it would empty `metadata.record_crossborder`. See the migration warning.

## 11. Update (2026-11-20): notebook 05 as step 42

`MissionSoil-Data/notebooks/05_doi_registry_type_resolution.ipynb` is now `Augmentation/Resource_Types/resolve_types_from_doi_registries.py` (step 42, listed between 17 and 18 in the runner) plus the notebook in `Resource_Types/notebooks/` (outputs cleared, the author's e-mail replaced by a placeholder; the script takes `--email` / `CROSSREF_EMAIL`). It produces `msp_type_mismatches_with_correct_type.csv`, the input of steps 18 and 19, so those no longer depend on a manual notebook run. `resolve_neither_and_unresolved.py` was already step 19. The notebook's CLI cell has a broken regex quote; the script uses the working regex of the batch cell.
