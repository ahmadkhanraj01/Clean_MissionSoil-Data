# 07 Populate SoilVoc in the DB (PO task #206)

**Purpose:** put SoilVoc in the DB so the Keywords/Subjects filter can hide noise and filter by SoilVoc.
PO decision: SoilVoc is linked **directly to records** (not to subjects).

- `soilvoc(id, level, parent_id, name, alt_labels)`: 1,464 concepts.
- `record_soilvoc(record_id, soilvoc_id, link_type, status, run_id, classified_at)`: 18,601 rows.
- `subjects.vocabulary_name = 'noise'` for 1,534 noise subjects. Labels are never changed.

**Stage only** (`msp-kh-stage`, schema `validate`). Dev is never touched. Every writing script refuses any other DB.
Empty copies of both tables also exist in stage `metadata` (alembic-managed: add them to a migration).

**Order (from the repo root):**
```bash
python Augmentation/SoilVoc/07_populate_soilvoc_db/scripts/create_soilvoc_tables.py     # tables (idempotent)
python Augmentation/SoilVoc/07_populate_soilvoc_db/scripts/load_soilvoc.py              # soilvoc from SoilVoc.ttl
python Augmentation/SoilVoc/07_populate_soilvoc_db/scripts/build_soilvoc_links.py       # subject -> concept links (dry run, files)
python Augmentation/SoilVoc/07_populate_soilvoc_db/scripts/build_record_soilvoc.py      # record -> concept rows (dry run, read-only)
python Augmentation/SoilVoc/07_populate_soilvoc_db/scripts/load_record_soilvoc.py       # writes record_soilvoc + noise marks
python Augmentation/SoilVoc/07_populate_soilvoc_db/scripts/check_soilvoc_vs_json.py     # tally with task 04 JSON (read-only)
```

## Files

- `scripts/sql/create_soilvoc_tables.sql`: tables in `validate` (renames the old `soilvoc_types`, drops the old array `record_soilvoc` and `subject_soilvoc`).
- `scripts/sql/create_soilvoc_tables_metadata.sql`: the same two tables, empty, in `metadata`.
- `scripts/create_soilvoc_tables.py`: runs the `validate` SQL in one transaction (stage only).
- `scripts/load_soilvoc.py`: loads the concepts with level and tree parent (same BFS as task 04); writes `outputs/multi_parent_concepts.csv`.
- `scripts/build_soilvoc_links.py`: turns task 06's cleaned subjects into subject -> concept links with a link type; writes `outputs/dry_run_links.csv` and `outputs/noise_subjects.csv`.
- `scripts/make_review_sheet.py`: lists doubtful links for a person to decide; writes `outputs/review_sheet.csv`.
- `scripts/build_record_soilvoc.py`: expands links to one row per record and concept (strongest link type wins; accepted beats pending); writes `outputs/dry_run_record_soilvoc.csv`.
- `scripts/load_record_soilvoc.py`: one transaction: backs up subjects, replaces `record_soilvoc`, sets `vocabulary_name = 'noise'`.
- `scripts/check_soilvoc_vs_json.py`: checks levels, parents and children in the DB against the task 04 JSON (result: no mismatches).
- `docs/PLAN.md`: plan, ERD, fields, SQL, API response examples.
- `docs/IMPLEMENTATION.md`: step-by-step log of what was done on stage.
- `docs/DB_SCHEMA.md`: SQL plus field tables for records, subjects, record_subject, soilvoc, record_soilvoc.
- `outputs/dry_run_links.csv`: subject -> concept links.
- `outputs/dry_run_record_soilvoc.csv`: the rows loaded into `record_soilvoc`.
- `outputs/noise_subjects.csv`: the 1,534 noise subjects.
- `outputs/review_sheet.csv`: 257 doubtful links (no verdicts filled yet).
- `outputs/multi_parent_concepts.csv`: 131 concepts with more than one parent.

Depends on: tasks 04 and 06, `Augmentation/SoilVoc/curation/inside_keyword_review.csv`.
Open: review of `review_sheet.csv`, doubtful direct matches (biomass, immissionen, ...), API and harvest integration.
