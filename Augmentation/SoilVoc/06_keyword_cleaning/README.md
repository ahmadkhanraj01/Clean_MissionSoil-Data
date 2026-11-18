# 06 Keyword cleaning

**Purpose:** clean the DB keywords (case, punctuation, plurals, UK/US spelling, translation to English, noise) and
match them to SoilVoc, including terms found *inside* longer keywords. The result feeds task 07. Files only:
the DB is read, never written.

**Run (from the repo root):**
```bash
python Augmentation/SoilVoc/06_keyword_cleaning/scripts/clean_subjects.py --db 1
python Augmentation/SoilVoc/06_keyword_cleaning/scripts/review_inside_keywords.py
python Augmentation/SoilVoc/06_keyword_cleaning/scripts/soilvoc_terms_in_db.py
```

## Files

- `scripts/clean_subjects.py`: the cleaning pipeline (task 01's matching, `Augmentation/SoilVoc/curation`, task 04 levels). Writes `outputs/subjects_cleaned.csv`, `outputs/record_soilvoc.csv` (a cleaning output per record; not the DB table), `docs/report.md`.
- `scripts/review_inside_keywords.py`: rule-based review of "SoilVoc term inside a longer keyword" pairs. Writes `Augmentation/SoilVoc/curation/inside_keyword_review.csv`.
- `scripts/soilvoc_terms_in_db.py`: lists the SoilVoc terms used by records. Writes `outputs/soilvoc_terms_in_db.csv`, `outputs/soilvoc_keywords_in_db.csv`.
- `docs/report.md`: what the cleaning changed (476 terms used directly, 487 with inside matches).
- `outputs/subjects_cleaned.csv`: every subject: cleaned label, status (soilvoc, partial, noise, ...), matched URIs.
- `outputs/record_soilvoc.csv`: records with their SoilVoc matches after cleaning.
- `outputs/soilvoc_terms_in_db.csv`: one row per SoilVoc term used by records (487).
- `outputs/soilvoc_keywords_in_db.csv`: one row per DB keyword mapped to SoilVoc (1,063).
- `outputs/soilvoc_keywords_in_db_alpha.csv`: the same 1,063 rows sorted alphabetically by keyword.

Depends on: tasks 01 and 04, `Augmentation/SoilVoc/curation`. Used by: 07.
