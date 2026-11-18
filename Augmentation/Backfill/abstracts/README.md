# Backfill/abstracts/

> **In Clean_MissionSoil-Data:** copied from `SoilWise_metadata_backfill/scripts/abstracts/` (commit `450a342`). Run from the repo root as `python Augmentation/Backfill/abstracts/<script>.py`. Wherever this file says `scripts/abstracts/`, read `Augmentation/Backfill/abstracts/`. The DB settings come from the repo-root `.env` (via `common/db.py`, `search_path = validate`), not `crosscheck/.env`, so the *schema* known issue below is fixed. The table of inputs, outputs and DB operations for every script is in [`../README.md`](../README.md).

| File | What it does |
| :-- | :-- |
| `fill_abstract_from_title.py` | Fills empty/NULL `abstract` from `title` — **top-level `abstract` column only**, never `raw_metadata` or `updated_at`. Dry run by default; `--apply` takes a before-image backup and asserts the row count; `--restore BACKUP.jsonl --apply` undoes it. `--placeholders "xx,x,xxx,-,NA,2022"` also treats those literal values as empty. |

Run history (2026-10-01): 2,133 empty/NULL abstracts filled, then 31 placeholders — 0 remain.
Before-images: `../output/apply/abstract_from_title*_backup.jsonl` (not copied into this repo). The
`empty_abstracts_2133.csv` extract from the original run is not in this repo either; the script selects the rows
itself. Full write-up with every SQL statement and the undo:
[`../docs/abstracts/abstract_from_title_backfill_report.md`](../docs/abstracts/abstract_from_title_backfill_report.md).

```bash
python3 Augmentation/Backfill/abstracts/fill_abstract_from_title.py             # dry run
python3 Augmentation/Backfill/abstracts/fill_abstract_from_title.py --apply
```

Connection: `common.db` loads `<repo>/.env` and pins `search_path` to `DB_SCHEMA` (default `validate`), so the unqualified
`records` in the SQL is `validate.records`. Parent overview: [`../README.md`](../README.md).
