# 05 SoilVoc coverage in the DB

**Purpose:** measure how much of SoilVoc the DB uses: in subjects (keywords), and in record titles and abstracts.
Per level and per branch. Read-only.

**Run (from the repo root):**
```bash
python Augmentation/SoilVoc/05_soilvoc_db_coverage/scripts/soilvoc_levels_vs_db.py Augmentation/SoilVoc/01_subjects_vs_soilvoc/outputs/matched.csv Augmentation/SoilVoc/04_soilvoc_hierarchy/outputs/soilvoc_keywords_by_level.csv Augmentation/SoilVoc/05_soilvoc_db_coverage/outputs "stage"
python Augmentation/SoilVoc/05_soilvoc_db_coverage/scripts/soilvoc_in_text.py --db 1
python Augmentation/SoilVoc/05_soilvoc_db_coverage/scripts/soilvoc_presence.py
python Augmentation/SoilVoc/05_soilvoc_db_coverage/scripts/soilvoc_db_counts.py --db 1
python Augmentation/SoilVoc/05_soilvoc_db_coverage/scripts/soil_threat_filter_values.py
python Augmentation/SoilVoc/05_soilvoc_db_coverage/scripts/soil_threat_records.py
python Augmentation/SoilVoc/05_soilvoc_db_coverage/scripts/all_keywords_with_records.py
```
Note: re-running `soilvoc_levels_vs_db.py` now gives slightly different numbers than the committed files, because task 01's `matched.csv` has since been regenerated.

## Files

- `scripts/soilvoc_levels_vs_db.py`: joins task 01's matches with the levels; writes `soilvoc_levels_with_db.csv`, `coverage_by_level.csv`, `coverage_by_branch.csv`.
- `scripts/soilvoc_in_text.py`: searches SoilVoc labels in record titles and abstracts (DB read-only); writes `concept_hits.csv`, `record_hits.csv`.
- `scripts/soilvoc_presence.py`: combines subject use and text use; writes `concept_presence.csv` (strong / weak / absent).
- `scripts/soilvoc_db_counts.py`: counts records and keywords per SoilVoc concept in the DB.
- `scripts/soil_threat_filter_values.py`: soil-threat filter values with record counts (stage, read-only; also reads task 07 `multi_parent_concepts.csv`); writes `outputs/soil_threat_filter_values.csv`.
- `scripts/soil_threat_records.py`: every record linked to a concept under `soil threats`, with concept level/parent and the record's identifier, title and abstract (stage, read-only); writes `outputs/soil_threat_records.csv`.
- `scripts/all_keywords_with_records.py`: every keyword in the DB with its number of records, alphabetically (stage, read-only); writes `outputs/all_keywords_with_records.csv`.
- `scripts/soil_threat_records.py`: lists the records linked to the soil threats branch (stage, read-only); writes `outputs/soil_threat_records.csv`.
- `scripts/compare_site_soil_erosion.py`: compares the two Knowledge Hub scrapes with stage; writes `outputs/soil_erosion_site_comparison.csv`.
- `docs/report.md`: coverage by level and branch.
- `docs/soil_threat_filter.md`: soil-threat filter values and coverage: output, ASCII charts, queries and script.
- `docs/records_and_keywords.md`: number of records and keywords that use SoilVoc.
- `docs/title_abstract_report.md`: SoilVoc terms found in titles and abstracts.
- `outputs/soilvoc_levels_with_db.csv`: each concept with its number of keywords and records.
- `outputs/coverage_by_level.csv`, `coverage_by_branch.csv`: summaries.
- `outputs/concept_presence.csv`: strong/weak/absent per concept.
- `outputs/soil_threat_filter_values.csv`: one row per soil-threat filter value with its counts and a note, for the PO to review.
- `outputs/soil_threat_records.csv`: one row per (record, soil-threat concept) link with the concept's level/parent and the record's identifier, title and abstract.
- `outputs/all_keywords_with_records.csv`: one row per keyword with its record count and noise flag, alphabetical.
- `outputs/soilvoc_keywords_with_records.xlsx`: all 1,464 SoilVoc terms with their record count (sheet 1) and the 1,004 terms with 0 records (sheet 2).
- `outputs/soil_threat_records.csv`: one row per record and soil-threat concept: value, concept, level, parent, link type, status, identifier, title, abstract.
- `outputs/soil_erosion_site_comparison.csv`: the 236 records in the soil erosion branch and whether the site lists them.
- `squarex website scraper.csv`, `squarex-2026-11-05.csv`: scrapes of the Knowledge Hub search `q=soil erosion` (inputs).
- `outputs/concept_hits.csv`, `record_hits.csv`: text matches per concept and per record.

Depends on: tasks 01 and 04.
