# Backfill

Quality fixes on records that are already in `validate`. It covers messy text in titles and abstracts, empty abstracts, the `records.url` column and the matching `distributions` rows.

The scripts were copied from [`ahmadkhanraj01/SoilWise_metadata_backfill`](https://github.com/ahmadkhanraj01/SoilWise_metadata_backfill) at commit `450a342` (2026-10-14). They were first run once by hand on `msp-kh-dev` in Sep/Oct 2026; here they are pipeline steps 30–39.
**`crosscheck/` was not copied**, because it needs the 130 MB Solr JSON export (`Sep8_SolrData.json`) and the source-page caches.

## What was changed in the copy

| Change | Where |
|---|---|
| The DB connection comes from the repo-root `.env` through `common/db.py` (`get_connection(search_path=DB_SCHEMA)`), not from `crosscheck/.env`. `MSP_READ_ONLY=1` works for every script | all DB scripts |
| `search_path` is pinned to `DB_SCHEMA` (`validate`). This fixes the repo's known issue that the older scripts failed with *relation "records" does not exist* after the move from `public` to `validate` | `cleanup/*`, `abstracts/*`, `url/build_url_column.py`, `url/find_urls_external.py`, `diagnostics/*` |
| The project root is now this folder, so `output/` and `docs/` are `Augmentation/Backfill/output` and `Augmentation/Backfill/docs` | all |
| **Bug fix:** `apply_cleanup.py` called `scripts/verify_diff.py`, which moved to `scripts/cleanup/` on 2026-10-08. The safety check therefore always failed. It now calls the file next to it | `cleanup/apply_cleanup.py` |
| **Bug fix:** `url_check_ui.py` re-ran `scripts/compare_url_accessurl.py` (old path) | `url/url_check_ui.py` |
| **Bug fix:** `compare_url_accessurl.py` crashed when `output/url/` did not exist yet; `check_urls*.py` printed the wrong report path; `db_check.py` listed every column twice (`validate` + `metadata`) | `url/`, `diagnostics/` |
| The backup and inserted-ids files get a timestamp, so a second `--apply` no longer stops with "refusing to overwrite" | `fill_abstract_from_title`, `apply_cleanup`, `build_url_column`, `add_missing_distributions` |
| **Bug fix:** the dry runs of `add_missing_distributions`, `add_source_distributions` and `fix_source_urls_unescape` ended with `sys.exit("dry run…")`, which is exit code 1. They now exit 0 | `url/` |
| `--env` is accepted but ignored (the settings come from `.env`) | `cleanup/find_messy`, `dry_run`, `apply_cleanup` |

The rules, SQL and checks are otherwise unchanged. `docs/` keeps the original reports. Their paths (`scripts/url/…`) are those of the source repo: read them as `Augmentation/Backfill/url/…`.

## Layout

| Folder | Job | Writes to the DB? | Pipeline steps |
|---|---|---|---|
| [`cleanup/`](cleanup/README.md) | messy text: scan → dry run → classify → verify → apply | only `apply_cleanup.py --apply` (manual) | 31–34 |
| [`abstracts/`](abstracts/README.md) | empty/placeholder `abstract` ← `title` | with `--apply` | 35 |
| [`url/`](url/README.md) | `records.url`, URL checks, `distributions` rows | `build_url_column`, `add_missing_distributions` (steps); `apply_source_urls`, `fix_source_urls_unescape`, `add_source_distributions` (one-off) — all with `--apply` | 30, 36–39 |
| [`diagnostics/`](diagnostics/README.md) | one-off inspectors | no | – |
| `docs/` | original reports and plans (cleanup, abstracts, url, known issues) | – | – |
| `output/` | generated files and **undo material** (git-ignored, see [`output/README.md`](output/README.md)) | – | – |

## Scripts: inputs, outputs, read/write (all on `validate`)

### cleanup/

| Script | Purpose | Input | Output | DB operation |
|---|---|---|---|---|
| `cleanup_rules.py` | Shared detection + cleaning rules (HTML tags twice, `\"`, mojibake via `ftfy`, placeholder `"\|"` entries, multi-space, emoji, edge pipes) | – | – | none (library) |
| `find_messy.py` (step 31) | Flags records with emoji, pipes, backslashes, control characters, mojibake, HTML tags, URL-encoding, irregular spacing | `records` (`id, identifier, title, abstract, raw_metadata`) | `output/scan/messy_records.csv` | SELECT |
| `dry_run.py` (step 32) | Applies the rules in memory and writes a before/after diff. `target` = `both` / `column` / `raw_metadata`. Never creates new jsonb keys | same | `output/dryrun/messy_cleanup_dryrun.csv`, `…_before_after.csv` | SELECT |
| `analyse_diff.py` (step 33) | Labels every change (html_tag, multi_space, mojibake, …) | `…_before_after.csv` | `…_changes.csv`, `…_summary.csv` | none |
| `verify_diff.py` (step 34) | Gate: leftover tags/mojibake, invalid targets, lost words. **Exit 1 = a person must review** | `…_before_after.csv` | console | none |
| `apply_cleanup.py <csv> --expect-records N --expect-rows M [--apply]` | Writes the signed-off diff. Runs `verify_diff` first, checks the live value still equals `before`, writes a before-image, one UPDATE per record in one transaction, then audits that only the intended fields changed. `--restore` undoes | `…_before_after.csv` | `output/apply/messy_cleanup_backup_<ts>.jsonl` | **UPDATE `records`** `title`, `abstract`, `raw_metadata` (`jsonb_set`, keys never created); `updated_at` only with `--touch-updated-at`. **Manual, not in the runner** |

### abstracts/

| Script | Purpose | Input | Output | DB operation |
|---|---|---|---|---|
| `fill_abstract_from_title.py [--placeholders "xx,x,xxx,-,NA,2022"] [--apply]` (step 35) | Copies `title` into an empty, NULL or placeholder `abstract`. Only the `abstract` column; never `raw_metadata` or `updated_at`. `--restore <jsonl> --apply` undoes | `records` | `output/apply/abstract_from_title[_placeholders]_backup_<ts>.jsonl` | SELECT; with `--apply` **UPDATE `records` SET abstract = title** (row count asserted, rollback on mismatch) |

### url/

| Script | Purpose | Input | Output | DB operation |
|---|---|---|---|---|
| `url_rules.py` | `classify(identifier, raw_metadata) → (type, url)`: DOI, URL, arXiv, handle, URN, `oai:` handle, MCF landing page, BONARES link | – | – | none (library) |
| `test_url_rules.py` (step 30) | 31 checks of the rules | – | console | none |
| `find_urls_external.py` (step 36) | Tier D: OpenAIRE Graph API title + year match. Tier E: a record link whose page contains the title | `records` (`id, identifier, title, publication_date, raw_metadata`); api.openaire.eu + the record pages | `output/url/url_candidates_DE.csv` | SELECT |
| `build_url_column.py [--candidates CSV] [--apply] [--refresh]` (step 37) | Derives a URL from each identifier (plus verified D/E candidates), runs a check gate, writes a preview. `--apply` fills only `url IS NULL` (with `--refresh`, also changed values) and checks that no other column changed (md5 of every row) | `records`, `information_schema`, `pg_depend` | `output/url/url_preview.csv`, `url_before_image_<ts>.csv` | SELECT; with `--apply`: **`ALTER TABLE records ADD COLUMN IF NOT EXISTS url`**, `ADD CONSTRAINT records_url_format_ck` if missing, **UPDATE `records.url`**, `VALIDATE CONSTRAINT` |
| `add_missing_distributions.py [--apply]` (step 38) | Adds a `distributions` row for every `records.url` the record does not have yet (`landing page`/`text/html`, or `download` for `downloadPublic` links). `access_url` is percent-encoded like the existing rows | `records.url`, `distributions` | `output/url/missing_distributions_inserted_ids_<ts>.csv` (undo = DELETE these ids) | SELECT; with `--apply` **INSERT `distributions`** (`id, name, format, access_url, record_id, created_at, updated_at`) |
| `compare_url_accessurl.py [--http]` (step 39) | Compares `records.url` with the decoded `distributions.access_url` per record (neither / url_only / dist_only / sets_equal …) | `records`, `distributions` | `output/url/url_vs_dist_per_record.csv`, `url_vs_dist_urls.csv`, `docs/url/url_vs_accessurl_report.md` | SELECT |
| `check_urls.py --preview CSV` | HTTP HEAD/GET of every URL in a preview (cached, resumable) | preview CSV | `output/url/url_status.csv`, `url_check_cache.csv`, `docs/url/url_check_report.md` | none. Manual (long) |
| `check_urls_source.py` | The same check with `source_` output names (duplicate of `check_urls.py`) | preview CSV | `output/url/source_url_status.csv`, `docs/url/source_url_check_report.md` | none. Manual |
| `url_check_ui.py` | The HTTP check with a local web UI at `127.0.0.1:8111` | `records`, `distributions` | `output/url/url_check_cache.csv`, `url_check_status.json` | SELECT. Manual |
| `apply_source_urls.py [--apply]` | Fills empty `url` from the 2026-10-07 source-catalogue search | `output/url/source_url_check.csv`, `source_url_check_pass2.csv` (**not in the repo**: made by scratch scripts) | `output/url/source_urls_before_image.csv` | with `--apply` **UPDATE `records.url`** (only empty ones). One-off |
| `fix_source_urls_unescape.py [--apply]` | Repairs `&amp;` in the URLs the step above wrote | `source_urls_before_image.csv` | `source_urls_unescape_before_image.csv` | with `--apply` **UPDATE `records.url`**. One-off |
| `add_source_distributions.py [--apply]` | One `distributions` row per source-pass URL | `source_urls_before_image.csv` | `source_distributions_inserted_ids.csv` | with `--apply` **INSERT `distributions`**. One-off |

### diagnostics/ (read-only, manual)

`db_check.py` (columns + row count of `records`), `db_check2.py` (one `raw_metadata` document), `inspect_types.py` (type of each jsonb key), `test_parse.py` (`view_*` values parse as JSON?), `inspect_singles.py` (`\xNN` escapes, control characters), `inspect_backslash.py` (kinds of backslash), `sample_issues.py` (real samples per field and issue). All are SELECT on `records` only.

## Run

```bash
python Pipeline/run_pipeline.py --run --stage backfill                 # dry run of steps 30-39
python Pipeline/run_pipeline.py --run --live --only 35 37 38           # the writers, with --apply (asks for the DB name)
python Augmentation/Backfill/cleanup/apply_cleanup.py \
       Augmentation/Backfill/output/dryrun/messy_cleanup_before_after.csv \
       --expect-records N --expect-rows M [--apply]                     # after a person has reviewed the diff
```
`N` and `M` are the `changed_records` and `field_changes` counts that `dry_run.py` prints.

Order: these steps run after Harmonize (9–11) and the cleaning steps (12–14), because they work on `validate.records`. Rerun them after every harmonize run: new records arrive with the same problems.

## Last read-only check on msp-kh-stage (2026-11-18)

| Step | Result |
|---|---|
| 30 rules test | 31 cases OK |
| 31–32 scan + dry run | 33,566 records scanned; 348 records / 353 field changes (301 title, 52 abstract) |
| 34 verify | **NEEDS REVIEW**: 2 rows may lose words. `practice-abstract--310` has `\x02` control characters between word parts; removing them joins the parts (`pro\x02teins` → `proteins` is right, but it can also glue two separate words). `10.3030/PRIMA-4CE-MED` loses the tokens `4CE`/`MED`. So `apply_cleanup.py` correctly refuses until someone reviews them |
| 35 abstracts | 1 record (`practice-abstract--1532`, abstract `NA`), but its title is also `NA` |
| 36 external search | 3,541 records searched (23 min): 151 verified OpenAIRE matches (tier D), 63 verified pages (tier E) |
| 37 url column | the column and `records_url_format_ck` already exist; of the 1,991 records without a URL, the identifier rules fill **0** and the verified D/E candidates fill **6** (5 D, 1 E). Most verified candidates belong to records that already have a URL from the harmonizer, and only empty URLs are filled |
| 39 compare | runs; writes the per-record comparison and the report |
| 38 distributions | 204 `records.url` values have no matching distribution row (all `landing page`). Fixed: the dry run exited with code 1, so the runner reported it as FAILED |
| diagnostics | all run |

> `build_url_column.py --apply` runs `ALTER TABLE records …` and `VALIDATE CONSTRAINT`, which need the table owner. On stage, `validate.records` is owned by `missionsoil_user`, while `.env` connects as a different user. The `ALTER … IF NOT EXISTS` may therefore fail with *must be owner* even though the column already exists; it was not tried, because all checks were read-only. If it fails, use the URL derivation without the ALTER, or run it as the owner.
