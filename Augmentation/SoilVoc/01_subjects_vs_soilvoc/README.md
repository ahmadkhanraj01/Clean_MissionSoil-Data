# 01 Subjects vs SoilVoc

**Purpose:** find out which DB keywords (subjects) are SoilVoc terms, which are not, and which are noise.
This was the first analysis and its matching code is reused by tasks 03 and 06.

**Run (read-only):** `python Augmentation/SoilVoc/01_subjects_vs_soilvoc/scripts/compare_subjects_to_soilvoc.py [--env .env] [--out DIR]`

## Files

- `scripts/compare_subjects_to_soilvoc.py`: matches every subject to SoilVoc (exact, mapped, variant, normalised, translated, manual decisions). Reads the DB (SELECT only), `SoilVoc_concepts.csv`, `ontovocabs/`, `Augmentation/SoilVoc/curation/*`. Writes `outputs/*` and some proposals into `Augmentation/SoilVoc/curation/`. Imported as a helper by other tasks.
- `docs/subjects_vs_soilvoc_README.md`: the original README of the report folder (columns of each CSV).
- `docs/report.md`: result of the comparison (counts by match type).
- `docs/SUBJECT_FACETS_PLAN.md`: plan for SoilVoc facets / a `record_concept` table (replaced by task 07).
- `docs/MATCH_IMPROVEMENT_PLAN.md`: how the matching was improved step by step.
- `docs/CURATION_BATCHES.md`: the batches of keywords that people reviewed.
- `outputs/matched.csv`: subjects matched to SoilVoc, with match type.
- `outputs/unmatched.csv`: subjects with no match.
- `outputs/noise.csv`: subjects that are noise (codes, portal tags, ...).
- `outputs/soilvoc_not_in_db.csv`: SoilVoc terms no subject uses.

Depends on: `.env`, `Augmentation/SoilVoc/curation`. Used by: 03, 05 (`matched.csv`), 06.
