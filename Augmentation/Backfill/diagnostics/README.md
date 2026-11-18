# Backfill/diagnostics/

> **In Clean_MissionSoil-Data:** copied from `SoilWise_metadata_backfill/scripts/diagnostics/` (commit `450a342`). Run from the repo root as `python Augmentation/Backfill/diagnostics/<script>.py`. Wherever this file says `scripts/diagnostics/`, read `Augmentation/Backfill/diagnostics/`. The DB settings come from the repo-root `.env` (via `common/db.py`, `search_path = validate`), not `crosscheck/.env`, so the *schema* known issue below is fixed. The table of inputs, outputs and DB operations for every script is in [`../README.md`](../README.md).

One-off, **read-only** inspectors kept so earlier decisions can be reproduced. None writes to the database.

| File | What it answers |
| :-- | :-- |
| `db_check.py` | schema of `records` + row count |
| `db_check2.py` | what one `raw_metadata` document looks like |
| `inspect_types.py` | type of each jsonb key (str / list / list-of-JSON) |
| `test_parse.py` | do `view_*` items parse as JSON? |
| `inspect_singles.py` | literal `\xNN` escapes and control characters (the two manual-fix cases) |
| `inspect_backslash.py` | classify every backslash: `\xNN` vs LaTeX-like vs other |
| `sample_issues.py` | print real samples for each (field, issue) before encoding a rule |

All query an unqualified `records`. They connect with `search_path` set to `DB_SCHEMA` (default `validate`) through
`common.db`, so it resolves to `validate.records`. The older failure is described in
[`../docs/known_issues_schema_validate.md`](../docs/known_issues_schema_validate.md) (resolved).

```bash
python3 Augmentation/Backfill/diagnostics/db_check.py     # from the repo root; any directory works
```
