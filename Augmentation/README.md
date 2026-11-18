# Augmentation

Improves data quality, before and after harmonization.

| Folder | When | Works on | Pipeline steps |
|---|---|---|---|
| `Enrichment/` | **before** Harmonize | `harvest.items` | 8 |
| `Cleanning-Scripts/` | after Harmonize | `validate.subjects`, `validate.records`, junctions | 12, 13, 14 |
| `Resource_Types/` | after Harmonize | `validate.records.resource_type` | 15 – 19 |
| `Backfill/` | after cleaning (12–14) | `validate.records` (`title`, `abstract`, `raw_metadata`, `url`), `validate.distributions` | 30 – 39 |
| `SoilVoc/` | after cleaning (12–14) | `validate.soilvoc`, `validate.record_soilvoc`, `validate.subjects.vocabulary_name` | 20 – 29 |
| `Backfill/` | one-off repairs, already applied (Oct 2026); **not in the runner** | `validate.records`, `validate.distributions` | – |

Every script that writes to the DB either has a dry run that is the **default** (`--commit` / `--execute` to apply), or takes `--dry-run`. The ones that change `validate` create a timestamped backup table before they commit.

`Backfill/` holds the abstract, messy-text and URL backfills with their reports and undo tooling. Its writers use the same dry-run-by-default rule (`--apply`) and write a before-image first. See [`Backfill/README.md`](Backfill/README.md).

`SoilVoc/` (copied from `soil-vocabs/tasks`) works differently: its builders (steps 20–23, 26, 27, 29) only read the DB and write CSV/JSON, and the three writers (steps 24, 25, 28) have no dry run, so read their CSV outputs before running them. `load_record_soilvoc.py` backs up `validate.subjects` first and refuses any DB except `msp-kh-stage`. See [`SoilVoc/README.md`](SoilVoc/README.md).

`Backfill/` (copied from `SoilWise_metadata_backfill`, without `crosscheck/`) is a dry run unless `--apply`. Each write takes a before-image or saves the inserted ids, runs in one transaction and checks the row count. The text-cleanup apply stays manual, because a person must sign off the diff. See [`Backfill/README.md`](Backfill/README.md).
