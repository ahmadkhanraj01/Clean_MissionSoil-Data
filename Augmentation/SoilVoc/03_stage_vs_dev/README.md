# 03 Stage vs dev

**Purpose:** compare stage (`msp-kh-stage`) with dev (`msp-kh-dev`): which records and subjects are new, changed
or missing, and how many dev subjects match SoilVoc. Read-only on both databases.

**Run:**
```bash
python Augmentation/SoilVoc/03_stage_vs_dev/scripts/compare_stage_dev.py
python Augmentation/SoilVoc/03_stage_vs_dev/scripts/compare_stage_dev_fields.py
```

## Files

- `scripts/compare_stage_dev.py`: compares subjects and SoilVoc matches (uses task 01's matching and `Augmentation/SoilVoc/curation`). Writes `outputs/*.csv` and `docs/report.md`.
- `scripts/compare_stage_dev_fields.py`: compares every record field (joined on `records.identifier`). Writes `outputs/field_changes.csv` (about 19 MB, not in git) and `docs/full_comparison.md`.
- `docs/report.md`: subjects and SoilVoc, stage vs dev.
- `docs/full_comparison.md`: every field, stage vs dev.
- `docs/stage_vs_dev_README.md`: original README of the report folder.
- `outputs/common_subjects_changed.csv`: records in both DBs whose subjects differ.
- `outputs/new_in_dev.csv`, `new_in_dev_with_soilvoc.csv`, `new_in_dev_without_subjects.csv`, `new_in_dev_soilvoc_concepts.csv`: records and subjects only in dev, with and without SoilVoc matches.
- `outputs/only_in_stage.csv`: records only in stage.

Depends on: task 01, `.env` (`DB_*1` and `DB_*2`).

Note: the scripts write `report.md` / `full_comparison.md` into `outputs/` next to the CSVs; copy them to `docs/` after a re-run.
