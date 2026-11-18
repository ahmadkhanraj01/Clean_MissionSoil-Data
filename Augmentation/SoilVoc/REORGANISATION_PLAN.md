# Plan: reorganise our work into one folder

Goal: put all of our own work (K2X tasks) into **one folder, `tasks/`**, with **one folder per task**.
Each task folder has the same layout:

- `README.md` – what the task was, how to run it, and the purpose of every file
- `docs/` – the Markdown plans and reports
- `scripts/` – the code
- `outputs/` – the CSV / JSON / Markdown files the scripts produce

Status: **done** (files moved with `git mv`, paths in `tasks/paths.py`, READMEs written). Old `reports/`, `curation/`, `mistral/` and most of `scripts/` no longer exist; the 01 to 06 old README files are kept as `docs/*_README.md`.

## What stays where it is (upstream SoilVoc project)

This repo is a fork of `soilwise-he/soil-vocabs`. These files belong to the upstream project and are used by its API, viewer, Docker image and GitHub workflows. Moving them would break those, so they **stay in place**:

- `SoilVoc.ttl`, `SoilVoc_augmented.ttl`, `SoilVoc_concepts.csv` (Dockerfile, workflows, `api/vocab.py`, viewer)
- `api/`, `viewer/`, `docker/`, `.github/`, `templates/`, `ontovocabs/`
- `scripts/log_issue_csv.py` (GitHub workflow), `scripts/restore_soilvoc_from_csv.py`, `scripts/uk2us.py` (also imported by our matching)
- `soil_vocabs.ipynb`, `README.md`, `CITATION.cff`, `LICENSE`, `requirements.txt`, `Soil Taxonomy — Category List.txt`
- `.env` stays in the repo root (all scripts read it from there)

## New layout

```text
tasks/
├── README.md                         index of all tasks, order, shared rules (.env, stage only)
├── paths.py                          one place for all paths (ROOT, .env, SoilVoc.ttl, task folders)
├── curation/                         hand-edited inputs shared by several tasks
│   ├── README.md
│   └── *.csv, translated_labels.json
├── 01_subjects_vs_soilvoc/           first comparison of DB subjects with SoilVoc
│   ├── README.md
│   ├── docs/      SUBJECT_FACETS_PLAN.md, MATCH_IMPROVEMENT_PLAN.md, CURATION_BATCHES.md
│   ├── scripts/   compare_subjects_to_soilvoc.py
│   └── outputs/   report.md, matched.csv, unmatched.csv, noise.csv, soilvoc_not_in_db.csv
├── 02_llm_subject_extraction/        LLM suggestions for records without subjects
│   ├── README.md
│   ├── docs/      LLM_EXTRACTION.md, MISTRAL.md
│   ├── scripts/   llm_extract_subjects.py, progress_ui.py, run_extraction.sh, mistral/
│   └── outputs/   mistral runs (estimate.json, estimate.md)
├── 03_stage_vs_dev/                  stage vs dev subject and field comparison
│   ├── README.md
│   ├── docs/      report.md, full_comparison.md
│   ├── scripts/   compare_stage_dev.py, compare_stage_dev_fields.py
│   └── outputs/   *.csv
├── 04_soilvoc_hierarchy/             SoilVoc by level, Mermaid chart, JSON tree
│   ├── README.md
│   ├── scripts/   soilvoc_levels.py, soilvoc_mermaid.py, soilvoc_json.py
│   └── outputs/   soilvoc_keywords_by_level.csv, soilvoc_hierarchy.md, soilvoc_hierarchy.json
├── 05_soilvoc_db_coverage/           how much of SoilVoc is in the DB (subjects, titles, abstracts)
│   ├── README.md
│   ├── docs/      report.md, records_and_keywords.md, title_abstract_report.md
│   ├── scripts/   soilvoc_levels_vs_db.py, soilvoc_db_counts.py, soilvoc_in_text.py, soilvoc_presence.py
│   └── outputs/   soilvoc_levels_with_db.csv, coverage_by_level.csv, coverage_by_branch.csv,
│                  concept_presence.csv, concept_hits.csv, record_hits.csv
├── 06_keyword_cleaning/              cleaning, translation and SoilVoc matching of keywords (CSV only)
│   ├── README.md
│   ├── docs/      report.md
│   ├── scripts/   clean_subjects.py, soilvoc_terms_in_db.py, review_inside_keywords.py
│   └── outputs/   subjects_cleaned.csv, record_soilvoc.csv, soilvoc_terms_in_db.csv,
│                  soilvoc_keywords_in_db.csv
└── 07_populate_soilvoc_db/           Task #206: load SoilVoc into stage (validate) for noise filtering
    ├── README.md
    ├── docs/      PLAN.md, IMPLEMENTATION.md
    ├── scripts/   create_soilvoc_tables.py, sql/create_soilvoc_tables.sql, load_soilvoc.py,
    │              build_soilvoc_links.py, make_review_sheet.py, build_record_soilvoc.py,
    │              load_record_soilvoc.py, check_soilvoc_vs_json.py
    └── outputs/   dry_run_links.csv, dry_run_record_soilvoc.csv, noise_subjects.csv, review_sheet.csv,
                   multi_parent_concepts.csv
```

## Where every file goes

**Root Markdown files**
- `SUBJECT_FACETS_PLAN.md`, `MATCH_IMPROVEMENT_PLAN.md`, `CURATION_BATCHES.md` → `tasks/01_subjects_vs_soilvoc/docs/`
- `LLM_EXTRACTION.md` → `tasks/02_llm_subject_extraction/docs/`
- `requirements-llm.txt` → `tasks/02_llm_subject_extraction/requirements-llm.txt`

**`curation/` → `tasks/curation/`** (used by tasks 01, 03, 06, 07)
- `keyword_decisions.csv`, `stoplist.csv`, `path_qualifiers.csv`, `translated_labels.json`, `translated_review.csv`, `review_sheet.csv`, `soilvoc_new_terms.csv`, `soilvoc_synonym_candidates.csv`, `new_term_groups.csv` (task 01)
- `category_labels.csv`, `keyword_translations.csv`, `keyword_kinds.csv`, `inside_keyword_review.csv` (task 06)

**`scripts/` (ours only) → task folders**
- `compare_subjects_to_soilvoc.py` → 01
- `llm_extract_subjects.py`, `progress_ui.py`, `run_extraction.sh` → 02
- `compare_stage_dev.py`, `compare_stage_dev_fields.py` → 03
- `soilvoc_levels.py`, `soilvoc_mermaid.py`, `soilvoc_json.py` → 04
- `soilvoc_levels_vs_db.py`, `soilvoc_db_counts.py`, `soilvoc_in_text.py`, `soilvoc_presence.py` → 05
- `clean_subjects.py`, `soilvoc_terms_in_db.py`, `review_inside_keywords.py` → 06
- `create_soilvoc_tables.py`, `sql/create_soilvoc_tables.sql`, `load_soilvoc.py`, `build_soilvoc_links.py`, `make_review_sheet.py`, `build_record_soilvoc.py`, `load_record_soilvoc.py`, `check_soilvoc_vs_json.py` → 07

**`mistral/` → `tasks/02_llm_subject_extraction/scripts/mistral/`**
- `mistral/README.md` → `docs/MISTRAL.md`; `mistral/runs/` → `outputs/mistral_runs/`

**`reports/` → task outputs and docs**
- `subjects_vs_soilvoc/` → 01 (`README.md` merged into the task README, `report.md` → `docs/`, CSVs → `outputs/`)
- `stage_vs_dev/` → 03 (`report.md`, `full_comparison.md` → `docs/`, CSVs → `outputs/`)
- `soilvoc_keywords_by_level.csv`, `soilvoc_hierarchy.md`, `soilvoc_hierarchy.json` → 04 `outputs/`
- `soilvoc_levels_vs_db/report.md`, `records_and_keywords.md` → 05 `docs/`; `soilvoc_levels_with_db.csv`, `coverage_by_*.csv`, `concept_presence.csv` → 05 `outputs/`
- `soilvoc_in_title_abstract/` → 05 (`report.md` → `docs/title_abstract_report.md`, CSVs → `outputs/`)
- `subjects_cleaned/` → 06 (`report.md` → `docs/`, CSVs → `outputs/`)
- `soilvoc_levels_vs_db/PLAN.md`, `IMPLEMENTATION.md` → 07 `docs/`; `dry_run_links.csv`, `dry_run_record_soilvoc.csv`, `noise_subjects.csv`, `review_sheet.csv`, `multi_parent_concepts.csv` → 07 `outputs/`

After the move, `reports/`, `curation/` and `mistral/` are gone from the root, and `scripts/` keeps only the 3 upstream scripts.

## What each README will contain

- **Purpose:** the task in two or three sentences, the PO request it answers, and the date
- **How to run:** the commands in order, which DB they read (stage, read-only) or write (only task 07, stage `validate`)
- **Files:** one bullet per file in `docs/`, `scripts/` and `outputs/` saying what it is for, what it reads and what it writes
- **Depends on:** which other task folders or curation files it uses (e.g. 06 uses the matching helpers from 01)
- **Key results:** the main numbers (e.g. 07: 1,464 concepts, 6,048 records with SoilVoc, 456 concepts, 18,601 record_soilvoc rows, 1,534 noise subjects)

`tasks/README.md` lists the tasks in order with one line each, and the shared rules: `.env` in the root, stage only, dev never written.
`tasks/curation/README.md` explains every curation file: who edits it, which script reads it, and what a row means.

## Code changes needed

The scripts have hard-coded paths such as `ROOT / "reports" / ...` and `ROOT / "curation" / ...`, and some import each other by path. To keep this tidy:

1. Add `tasks/paths.py` with every shared path in one place: `ROOT` (repo root), `ENV` (`.env`), `SOILVOC_TTL`, `SOILVOC_CSV`, `CURATION`, `UK2US`, and the `outputs/` folder of each task.
2. Each script gets `ROOT` from `paths.py` instead of `Path(__file__).parent.parent` (that would now point to the task folder, not the repo root).
3. Fix the cross-task imports:
   - `clean_subjects.py`, `compare_stage_dev.py`, `llm_extract_subjects.py`, `run_extraction.sh` → helpers from `tasks/01_subjects_vs_soilvoc/scripts/compare_subjects_to_soilvoc.py`
   - `compare_stage_dev_fields.py` → `compare_stage_dev.py` (same folder, no change)
   - `mistral/common.py` → `llm_extract_subjects.py` (one level up)
4. Fix the file paths between tasks:
   - 05 reads 01's `matched.csv` and 04's `soilvoc_keywords_by_level.csv`
   - 06 reads the curation files
   - 07 reads 06's `subjects_cleaned.csv`, 04's `soilvoc_hierarchy.json` and the curation review file
5. Update the links and commands inside the Markdown files (`PLAN.md`, `IMPLEMENTATION.md`, reports) and the usage lines at the top of each script.
6. Update `.gitignore` entries that point to old paths (e.g. `mistral/runs/extract`, `reports/llm_extraction`).
7. Add a short "Our work" section to the root `README.md` pointing to `tasks/README.md`.

## How we will do it

1. Use `git mv` for every move, so file history is kept.
2. Do it in one branch (`reorganise-tasks`) and one commit for the moves, then a second commit for the path fixes and READMEs, so the review is easy.
3. Write `tasks/paths.py` and update the scripts.
4. Write the 9 READMEs (index, curation, 7 tasks).
5. Check that nothing broke:
   - every script runs `--help` without errors
   - re-run the scripts that only read files (04 hierarchy, 06 `soilvoc_terms_in_db.py` and `review_inside_keywords.py`, 07 `build_soilvoc_links.py` dry run) and compare their outputs with the committed ones: they must be identical
   - re-run `check_soilvoc_vs_json.py` (read-only on stage): 0 mismatches
   - search for any left-over `reports/`, `curation/` or `mistral/` paths
   - **no script that writes to the DB is run**
6. Merge into `main` and push as ahmadkhanraj01.

## Things to decide first

- Folder name: `tasks/` (proposed) or something else, e.g. `k2x/`.
- Task numbering: by date as above, or by PO task number where we have one (only #206 is known).
- Tasks 04, 05 and 06 were all groundwork for #206. Keep them as separate folders (proposed) or put them inside `07_populate_soilvoc_db/`?
- The uncommitted changes in `reports/stage_vs_dev/` (from before) and `SoilVoc_concepts.csv`: commit, discard or keep as they are before the move. `git mv` carries the uncommitted `stage_vs_dev` changes along, so nothing is lost either way.
