# Crossborder

For each record in `validate.records` with a `spatial` value (a WKT bounding box), works out which of the **45 European countries** in `countries.geojson` the box covers, and flags it as cross-border when it covers more than one. Pipeline **step 40** (stage `spatial`).

This folder is a copy of `K2X/polygons` (2026-11-20); the original folder was not changed. The design, counting rule, results and checks are in [`PLAN_crossborder_spatial.md`](PLAN_crossborder_spatial.md), copied unchanged. Where that plan says `polygons/…`, read `Augmentation/Crossborder/…`.

## `compute_crossborder.py`

| Direction | Schema / table / file | Operation | Details |
|---|---|---|---|
| Input | `validate.records` (`id`, `spatial`) | SELECT | read-only session, always |
| Input | `data/countries_europe45.geojson` | read | the 45 countries (ISO3 `code`, `name`) |
| Input | `data/regions/NOR.geojson` | read | patches Norway, which is only Svalbard + Jan Mayen in the countries file |
| Input | `data/CNTR_RG_01M_2020_4326.geojson` | read | GISCO borders, **only** for `--scope hybrid/world/europe/eu27`. Not in git: copy it from `K2X/polygons/data/` if you need those scopes |
| Output | `validate.record_crossborder` | CREATE TABLE IF NOT EXISTS; INSERT … ON CONFLICT (record_id) DO UPDATE; DELETE rows of older runs | live run only, one transaction, verified before commit (row count, no stale `spatial`) |
| Output | `--csv <file>` | write | optional per-record results |

```bash
python Augmentation/Crossborder/compute_crossborder.py --dry-run               # read only, prints the counts
python Augmentation/Crossborder/compute_crossborder.py --dry-run --csv out.csv # + per-record CSV
python Augmentation/Crossborder/compute_crossborder.py                         # live: create/upsert/verify
python Pipeline/run_pipeline.py --run --only 40                                # same dry run, through the runner
```

Options: `--scope` (default `europe45`), `--iou 0.80`, `--share 0.10`, `--inside 0.80`, `--floor 0`, `--countries-file`, `--csv`, `--dry-run`.

Rows have `ON DELETE CASCADE` to `validate.records`, so the step runs after cleaning and dedup (12–14). Rerun it after every harvest or import: it is idempotent and replaces the previous run.

## Changes from `K2X/polygons`

- DB settings come from the repo `.env` through `common/db.py` (not `polygons/.env`), so `MSP_READ_ONLY=1` makes the run read-only, as in every other step.
- Data paths point to `./data`. Only `NOR.geojson` of the 36 regions files was copied: it is the only one that patches a country.
- The GISCO file is read only by the scopes that use it, so the default `europe45` scope runs without it. Before, it was always loaded.
- The table comment names this path instead of `polygons/compute_crossborder.py`.

**Verified (2026-11-20, read-only on `msp-kh-stage`):** the `--dry-run --csv` output of this copy is byte-identical to the original's. 4,857 records have `spatial` (1,018 distinct boxes), giving 4,010 rows, 1,558 of them cross-border (39%). 843 records touch none of the 45 countries and 4 are `0 0` placeholders, so these get no row.

## Notes

- `metadata.record_crossborder` exists on stage (4,010 rows) but is not written by this script. The migration (step 41) does not copy this table yet, see `Migration/README.md`.
- `msp-kh-dev` has no `record_crossborder` table. A live run there creates it.
- Known limitations (microstates, regional boxes spilling over borders, wrong boxes at the source) are listed in §6 of the plan.
