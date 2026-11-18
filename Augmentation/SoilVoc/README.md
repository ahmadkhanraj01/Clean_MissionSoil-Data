# SoilVoc

Links the records to the **SoilVoc** vocabulary and marks noise keywords, so the Knowledge Hub's Keywords/Subjects filter can hide noise and filter by SoilVoc concept (PO task #206).
The SoilVoc concepts are linked **directly to records**, not to subjects.

Copied from `soil-vocabs/tasks/` (branch `main`, working tree of 2026-11-13). The vocabulary files the tasks need (`SoilVoc.ttl`, `SoilVoc_concepts.csv`, `ontovocabs/`, `uk2us.py`) were copied from the soil-vocabs repo root into [`vocab/`](vocab/README.md).
Task `02_llm_subject_extraction` (LLM suggestions for records without subjects) was **not copied**: it was not used, and nothing else reads its code or outputs (the original stays in soil-vocabs). Only paths were changed (`paths.py`, `tasks/…` → `Augmentation/SoilVoc/…`). Every script, curation file and output is otherwise the same. Rerunning tasks 04, 06 and 07 from this folder against stage (read-only) gave byte-identical outputs.

| What it writes on stage (`validate`) | Rows now |
|---|---|
| `soilvoc (id, level, parent_id, name, alt_labels)`: one row per SoilVoc concept | 1,464 |
| `record_soilvoc (record_id, soilvoc_id, link_type, status, run_id, classified_at)` | 18,601 |
| `subjects.vocabulary_name = 'noise'` (labels are never changed) | 1,534 subjects |

## Layout

| Folder | What it does | DB access | Pipeline steps |
|---|---|---|---|
| [`04_soilvoc_hierarchy/`](04_soilvoc_hierarchy/README.md) | Level and tree parent for every concept; JSON tree, Mermaid charts | none (files only) | 20, 21 |
| [`06_keyword_cleaning/`](06_keyword_cleaning/README.md) | Cleans, translates and matches the DB keywords to SoilVoc (CSV only) | read | 22, 23 |
| [`07_populate_soilvoc_db/`](07_populate_soilvoc_db/README.md) | Creates and fills `soilvoc` and `record_soilvoc` and marks the noise subjects | **writes `validate`** | 24 – 29 |
| [`01_subjects_vs_soilvoc/`](01_subjects_vs_soilvoc/README.md) | Analysis: which subjects are SoilVoc, which are not, which are noise. Its matching code is imported by 03 and 06 | read | (helper) |
| [`05_soilvoc_db_coverage/`](05_soilvoc_db_coverage/README.md) | Analysis: how much of SoilVoc the DB uses (keywords, titles, abstracts, soil-threat filter) | read | not in runner |
| [`03_stage_vs_dev/`](03_stage_vs_dev/README.md) | Side task: stage vs dev comparison (needs `DB_*2` in `.env`) | read (both DBs) | not in runner |
| [`curation/`](curation/README.md) | Hand-edited inputs: decisions, translations, stoplist, reviews | – | – |
| [`vocab/`](vocab/README.md) | SoilVoc.ttl, SoilVoc_concepts.csv, ontovocabs/, uk2us.py | – | – |
| `paths.py` | Every path used by the scripts. Also applies `MSP_READ_ONLY=1` | – | – |
| `REORGANISATION_PLAN.md` | History: how soil-vocabs/tasks was laid out (paths in it are the old ones) | – | – |

Order: **04 → 06 → 07**. Task 07 uses the outputs of 04 and 06. Tasks 01, 03 and 05 are analyses.
Run SoilVoc **after** the cleaning steps 12–14. `record_soilvoc` rows are deleted together with their record (`ON DELETE CASCADE`), so a later dedup run removes links. Rerun 22–29 after it.

## Run

From the repo root (paths are absolute through `paths.py`, so the working directory does not matter for the defaults):

```bash
python Pipeline/run_pipeline.py --run --stage soilvoc            # steps 20-29; DB writers (24, 25, 28) are skipped
python Pipeline/run_pipeline.py --run --live --only 24 25 28     # the writes (asks for the DB name)
MSP_READ_ONLY=1 python Augmentation/SoilVoc/07_populate_soilvoc_db/scripts/load_record_soilvoc.py   # check only: stops at the first write
```

`.env`: these scripts read the **suffixed** names directly: `DB_HOST1 … DB_SCHEMA1` = stage, and `DB_HOST2 … DB_SCHEMA2` = dev (task 03 only). `--db 1` is the default and the only value the writers accept.

## Scripts: inputs, outputs, read/write

### 04_soilvoc_hierarchy (files only)

| Script | Purpose | Input | Output | DB |
|---|---|---|---|---|
| `soilvoc_levels.py <ttl> <out.csv>` (step 20) | BFS from the 17 top concepts in label order; first parent reached = tree parent. 1,215 concepts in levels 1–8, 249 detached lab procedure codes, 131 multi-parent | `vocab/SoilVoc.ttl` | `outputs/soilvoc_keywords_by_level.csv` | none |
| `soilvoc_json.py <levels.csv> <out.json>` (step 21) | The tree with children, descendants and other parents. Step 29 checks the DB against it | levels CSV | `outputs/soilvoc_hierarchy.json` | none |
| `soilvoc_mermaid.py <levels.csv> <out.md>` | 32 Mermaid diagrams of the hierarchy | levels CSV | `outputs/soilvoc_hierarchy.md` | none |

### 06_keyword_cleaning (reads the DB, writes CSV)

| Script | Purpose | Input | Output | DB |
|---|---|---|---|---|
| `clean_subjects.py --db 1` (step 22) | Cleans every subject label (case, punctuation, plurals, UK/US spelling, translation, separators, brackets, category labels) and matches it to SoilVoc, including terms *inside* longer keywords. Status per subject: soilvoc, partial, noise, … | `validate.subjects`, `validate.record_subject`, `validate.records`; `curation/*.csv`, `translated_labels.json`; task 04 levels CSV; task 01 matching code; `vocab/uk2us.py` | `outputs/subjects_cleaned.csv`, `outputs/record_soilvoc.csv` (a CSV, not the DB table), `outputs/report.md` | **SELECT only** (`readonly=True` session) |
| `review_inside_keywords.py` (step 23) | Rule-based verdict for each "SoilVoc term inside a longer keyword" pair: same / narrower / wrong / unclear (866 pairs) | `outputs/subjects_cleaned.csv` | `curation/inside_keyword_review.csv` (regenerated from the rules in the script) | none |
| `soilvoc_terms_in_db.py` | Lists the SoilVoc terms used by records (487) and the DB keywords mapped to them (1,063) | task 04 levels CSV, task 05 `soilvoc_levels_with_db.csv` | `outputs/soilvoc_terms_in_db.csv`, `outputs/soilvoc_keywords_in_db.csv` | none |

### 07_populate_soilvoc_db (writes stage)

| Script | Purpose | Input | Output | DB operation |
|---|---|---|---|---|
| `create_soilvoc_tables.py` (step 24) | Runs `scripts/sql/create_soilvoc_tables.sql` in one transaction. Idempotent | SQL file | tables | **DDL on `validate`**: renames old `soilvoc_types` → `soilvoc`; CREATE `soilvoc`, `record_soilvoc` IF NOT EXISTS; **DROP** the old array-shaped `record_soilvoc` (only if it has a `codes` column) and **DROP** `subject_soilvoc` |
| `load_soilvoc.py` (step 25) | Loads every `skos:Concept` with name, alt labels, level and tree parent (same BFS as step 20). Checks the level histogram and the 1,464 total first | `vocab/SoilVoc.ttl` | `outputs/multi_parent_concepts.csv` | **INSERT `validate.soilvoc` ON CONFLICT (id) DO UPDATE**, then UPDATE `parent_id`. No TRUNCATE |
| `build_soilvoc_links.py` (step 26) | Turns the cleaned subjects into subject → concept links with a link type (exact, synonym, translation, mapped, variant, broader, inside) and lists the noise subjects. Applies `keep`/`drop` verdicts from `outputs/review_sheet.csv` if it has any | `06/outputs/subjects_cleaned.csv`, `curation/inside_keyword_review.csv`, `validate.subjects`, `validate.record_subject` | `outputs/dry_run_links.csv`, `outputs/noise_subjects.csv` | SELECT only (record counts) |
| `build_record_soilvoc.py` (step 27) | Expands the links to one row per (record, concept): the strongest link type wins, accepted beats pending | `outputs/dry_run_links.csv`, `validate.record_subject`, `validate.soilvoc` | `outputs/dry_run_record_soilvoc.csv` | SELECT only (`readonly=True`) |
| `load_record_soilvoc.py` (step 28) | One transaction, rolled back on any error: refuses any DB but `msp-kh-stage`; checks every `soilvoc_id` and `record_id` exists; then writes | `outputs/dry_run_record_soilvoc.csv`, `outputs/noise_subjects.csv` | backup table | **CREATE `validate.subjects_pre_soilvoc_backup_<ts>`**; **DELETE all `validate.record_soilvoc`** + INSERT the new rows (`run_id` = this run); UPDATE `validate.subjects.vocabulary_name` (reset 'SoilVoc'/'noise', then 'noise' for the list). Never touches `label` or `uri` |
| `check_soilvoc_vs_json.py` (step 29) | Compares names, levels, parents, children, descendants, multi-parent and detached codes in the DB with the task 04 JSON. Last result: no mismatches | `04/outputs/soilvoc_hierarchy.json`, `validate.soilvoc` | console | SELECT only (`readonly=True`) |
| `make_review_sheet.py` | Lists the doubtful links (257) for a person to decide `keep`/`drop` | `outputs/dry_run_links.csv`, `06/outputs/subjects_cleaned.csv` | `outputs/review_sheet.csv` | none. **Not in the runner:** it overwrites `review_sheet.csv`, so it would erase filled-in verdicts. Run it by hand, before anyone fills the sheet |
| `sql/create_soilvoc_tables_metadata.sql` | The same two tables, empty, in `metadata` (stage `metadata` is Alembic-managed: add them to a migration) | – | – | DDL on `metadata` (run by hand) |

### 01, 05 (analysis, read-only) · 03 (side task, read-only)

| Script | Purpose | DB input | File output |
|---|---|---|---|
| `01/compare_subjects_to_soilvoc.py [--out DIR]` | Matches every subject to SoilVoc (exact, mapped, variant, normalised, translated, manual decisions) | `subjects`, `record_subject`, `records` | `01/outputs/matched.csv`, `unmatched.csv`, `noise.csv`, `soilvoc_not_in_db.csv`, `report.md`; proposals into `curation/` |
| `05/soilvoc_levels_vs_db.py <matched> <levels> <outdir> <label>` | Joins task 01 matches with levels | none | `soilvoc_levels_with_db.csv`, `coverage_by_level.csv`, `coverage_by_branch.csv` |
| `05/soilvoc_in_text.py --db 1` | SoilVoc labels in titles and abstracts | `records`, `record_subject` | `concept_hits.csv`, `record_hits.csv` |
| `05/soilvoc_presence.py` | Strong / weak / absent per concept | none | `concept_presence.csv` |
| `05/soilvoc_db_counts.py --db 1 [--out]` | Records and keywords per concept | `records`, `record_subject`, `subjects` | Markdown report |
| `05/soil_threat_filter_values.py`, `soil_threat_records.py` | Soil-threat filter values and their records | `records`, `record_soilvoc`, `soilvoc` | `soil_threat_filter_values.csv`, `soil_threat_records.csv` |
| `05/all_keywords_with_records.py` | Every keyword with its record count | `subjects`, `record_subject`, `records` | `all_keywords_with_records.csv` |
| `05/compare_site_soil_erosion.py` | Knowledge Hub "soil erosion" scrape vs stage | `records`, `record_soilvoc`, `soilvoc` | `soil_erosion_site_comparison.csv` |
| `03/compare_stage_dev.py`, `compare_stage_dev_fields.py` | Stage vs dev: records, subjects, fields | both DBs: `records`, `record_subject`, `subjects` | `03/outputs/*.csv`, `report.md`, `full_comparison.md` |

All DB reads above use `set_session(readonly=True)`.

## Notes

- **Migration:** `Migration/migrate_validate_to_metadata.py` (step 40) does **not** copy `soilvoc` or `record_soilvoc`. Stage `metadata` has 543 / 18,587 rows from an earlier load. Add both tables to the migration's tier lists first (`soilvoc` with the parents, `record_soilvoc` with the children).
- **Two subject cleaners:** `Augmentation/Cleanning-Scripts/clean_stage_subjects.py` (step 12) **changes** `validate.subjects`. `06/clean_subjects.py` only writes CSVs and leaves labels alone. Step 22 reads what step 12 left.
- **Reports:** scripts that write a `report.md` (01, 03, 06) put it in `outputs/`. The copy in `docs/` is the committed one, so copy it over after a rerun.
- **Open (from task 07):** the review of `review_sheet.csv`, doubtful direct matches (biomass, immissionen, …), API and harvest integration.
