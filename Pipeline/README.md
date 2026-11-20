# Pipeline

Tools to run and check the whole pipeline. Neither tool contains pipeline logic itself; they call the scripts in the other folders.

---

## `run_pipeline.py`

**Purpose:** runs the 42 pipeline steps in order (see `../pipeline_dfd.html`), each as its own subprocess.

| Mode | Command | What happens |
|---|---|---|
| List | `python Pipeline/run_pipeline.py` | prints the steps and each one's dry-run flag; runs nothing |
| Dry run | `python Pipeline/run_pipeline.py --run` | runs every step with its dry-run flag. Steps **without** a dry run (1, 2, 4, 5, 6, 15, 24, 25, 28, 41) are skipped and reported as skipped |
| One stage / step | `--stage clean` · `--stage soilvoc` · `--only 12 13` | filter |
| Live | `--run --live` | real run; you must type the database name to confirm |
| Keep going | `--keep-going` | do not stop at the first failed step |

| Direction | Target | Details |
|---|---|---|
| Input | `.env` | via `common.db` (shows which DB will be used) |
| Output | `Pipeline/logs/run_<timestamp>_<dry|live>.log` | full output of every step |
| DB | none directly | each step does its own reads and writes (see the folder READMEs) |

Dry-run flag per step: `--dry-run` for steps 3, 7, 8, 9, 10, 11 and 14. Steps 12, 13, 18 and 19 are dry by default (`--commit` / `--execute` when live). Steps 16 and 17 only read and write local files. SoilVoc steps 20–23, 26, 27 and 29 only read the DB and write files under `Augmentation/SoilVoc/`, so their run is the same in dry and live mode. `make_review_sheet.py` is left out on purpose (it would overwrite filled-in verdicts).

Backfill: steps 35, 37 and 38 get `--apply` in a live run, and their dry run only reads. Step 34 (`verify_diff`) exits 1 when the cleanup diff needs a person to review it, which stops the run unless you pass `--keep-going`. `cleanup/apply_cleanup.py`, the HTTP URL checks and the one-off source-URL pass are not in the runner; see `Augmentation/Backfill/README.md`.

| Stage | Steps |
|---|---|
| harvest | 1–7 |
| augment | 8 |
| harmonize | 9–11 |
| clean | 12–14 |
| types | 15–19 and 42 (42 runs between 17 and 18) |
| soilvoc | 20–29 |
| backfill | 30–39 |
| spatial | 40 |
| migrate | 41 |

> Most `--dry-run` modes write inside a transaction and roll back. To check without any write at all, use `MSP_READ_ONLY=1` (below): such steps then stop at their first INSERT.

---

## `verify_readonly.py`

**Purpose:** a read-only health check comparing the code with the database in `.env`.
- Scans every script for `FROM / JOIN / INTO / UPDATE <schema>.<table>`, INSERT column lists and UPDATE … SET columns.
- Checks that each table and column exists, and shows row counts.
- Lists DB tables that no script references.

| Direction | Target | Operation |
|---|---|---|
| Input | all `*.py` under `Harvesting/`, `Augmentation/` (incl. `SoilVoc/`), `Harmonize/`, `Migration/` | read files |
| Input | `information_schema.columns`; `harvest`, `validate`, `metadata` tables | SELECT (column lists, `count(*)`) |
| Output | console report; exit code 1 if anything is missing | none |

It forces `MSP_READ_ONLY=1`, so the session has `default_transaction_read_only=on`, and it refuses to run if the session is not read-only.

```bash
python Pipeline/verify_readonly.py
```
Last result on `msp-kh-stage`: 1 problem (`harvest.items.updated_date` is used by `harvest_solr_records.py` but does not exist).

---

## Read-only mode for any script

```bash
MSP_READ_ONLY=1 python <any script>
```
`common/db.py` (and `Augmentation/SoilVoc/paths.py` for the SoilVoc scripts) then adds `-c default_transaction_read_only=on` to `PGOPTIONS`, and PostgreSQL rejects every INSERT / UPDATE / DELETE / DDL from that process.
