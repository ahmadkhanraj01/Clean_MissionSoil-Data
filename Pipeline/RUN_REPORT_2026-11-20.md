# Augmentation dry run on `msp-kh-dev` (2026-11-20)

| | |
|---|---|
| Database | `msp-kh-dev`, schema `validate` |
| Mode | **Dry run**, read-only session (`MSP_READ_ONLY=1`). Nothing was written to `validate`. |
| Record limit | 1,000 records for the API-bound steps 8, 32, 36 and 42 (`--limit 1000`). Other steps read the whole schema. |
| Started / finished | 15:19:42 / 15:47:34, **27 min 52 s** |
| Steps | 31: **24 OK** (after the step 36/37 fix, see §3), 4 skipped, **3 failed** |
| Command | `MSP_READ_ONLY=1 python Pipeline/run_pipeline.py --run --keep-going --limit 1000 --only 8 12 13 14 15 16 17 42 18 19 20 … 40` |
| Raw files | `Pipeline/logs/report_20261120_151942_dry.md`, `Pipeline/logs/run_20261120_151942_dry.log` |

## 1. Step results

| Step | Script | Status | Time | Detail |
|---:|---|---|---:|---|
| 8 | `enrich_missing_abstracts.py` | OK | 622 s | missing abstracts from Crossref / DataCite / OpenAlex, 1,000 records |
| 12 | `clean_stage_subjects.py` | OK | 265 s | dry run; applies only with `--commit` |
| 13 | `clean_record_languages.py` | OK | 2.5 s | dry run; applies only with `--commit` |
| 14 | `clean_and_deduplicate_kh_dev.py` | **FAILED** | 0.0 s | `data/detected_duplicates_for_review.json` not found |
| 15 | `fetch_soilwise_records.py` | SKIPPED | – | no dry-run mode (downloads the whole OGC catalogue) |
| 16 | `fetch_msp_kh_records.py` | OK | 367 s | refreshed `data/msp-kh-dev.json` |
| 17 | `compare_msp_vs_ogc_types.py` | OK | 2.9 s | wrote `data/msp_type_mismatches.csv` |
| 42 | `resolve_types_from_doi_registries.py` | OK | 135 s | 1,000 rows (see §2) |
| 18 | `update_resource_types_from_ogc.py` | OK (read-only) | 4.8 s | ran up to its first write, blocked by the read-only session |
| 19 | `resolve_neither_and_unresolved.py` | OK (read-only) | 8.2 s | same |
| 20 | `soilvoc_levels.py` | OK | 0.8 s | 131 concepts with several parents |
| 21 | `soilvoc_json.py` | OK | 0.0 s | 1,215 tree nodes, 249 detached |
| 22 | `clean_subjects.py` | OK | 30.8 s | |
| 23 | `review_inside_keywords.py` | OK | 0.2 s | 2,819 pairs: same 34/199, narrower 2,615/5,343, unclear 33/89, wrong 137/329 |
| 24 | `create_soilvoc_tables.py` | SKIPPED | – | no dry-run mode (writes) |
| 25 | `load_soilvoc.py` | SKIPPED | – | no dry-run mode (writes) |
| 26 | `build_soilvoc_links.py` | OK | 11.0 s | 48,824 subjects, 303,520 `record_subject` uses |
| 27 | `build_record_soilvoc.py` | **FAILED** | 6.9 s | `relation "validate.soilvoc" does not exist` |
| 28 | `load_record_soilvoc.py` | SKIPPED | – | no dry-run mode (writes) |
| 29 | `check_soilvoc_vs_json.py` | **FAILED** | 2.1 s | `relation "validate.soilvoc" does not exist` |
| 30 | `test_url_rules.py` | OK | 0.0 s | 31 test cases pass |
| 31 | `find_messy.py` | OK | 86.8 s | scan of messy text |
| 32 | `dry_run.py` | OK | 13.1 s | wrote `output/dryrun/messy_cleanup_before_after.csv` |
| 33 | `analyse_diff.py` | OK | 0.1 s | 0 rows without a known rule |
| 34 | `verify_diff.py` | OK | 0.1 s | **RESULT: PASS** (on stage it said NEEDS REVIEW) |
| 35 | `fill_abstract_from_title.py` | OK | 4.4 s | dry run; applies only with `--apply` |
| 36 | `find_urls_external.py` | OK (rerun after fix) | 58.3 s | first run failed with `AttributeError`; passes after the `url_rules.py` fix |
| 37 | `build_url_column.py` | OK (rerun after fix) | 23.9 s | same |
| 38 | `add_missing_distributions.py` | OK | 8.1 s | dry run; applies only with `--apply` |
| 39 | `compare_url_accessurl.py` | OK | 13.7 s | wrote `docs/url/url_vs_accessurl_report.md` |
| 40 | `compute_crossborder.py` | OK | 25.1 s | nothing written |

## 2. Resource types (steps 42, 18, 19)

Step 42 asked Crossref and then DataCite about the first 1,000 rows of the mismatch list. 995 have a DOI; 987 lookups were new, 99 were cached.

| `correct_side` | Rows |
|---|---:|
| ogc | 946 |
| msp | 43 |
| unresolved | 6 |
| neither | 5 |

Steps 18 and 19 stopped at their first UPDATE (read-only session), after printing what they would change.

## 3. The failures (3 left; 36 and 37 were fixed)

| Step | Cause | Fix |
|---|---|---|
| 14 | `data/detected_duplicates_for_review.json` does not exist, and nothing in the repo creates it | Write a duplicate detector (DOI, identifier and normalised title) |
| 27, 29 | `validate.soilvoc` does not exist on **dev**. The SoilVoc tables live on stage; steps 24 and 25 (create and load them) were skipped | Run these steps on stage, or create the tables on dev first |
| 36, 37 | **Fixed.** `Backfill/url/url_rules.py` assumed `raw_metadata["distribution"]` is a dict, but some records hold a list. `url_from_raw()` now accepts a dict or a list of dicts. Tests (31 cases) and a rerun of both steps pass | – |

## 4. Skipped steps

Steps 15, 24, 25 and 28 have no dry-run mode. Step 15 downloads the whole OGC catalogue (36,148 records); the others write to the database.

## 5. Notes

- The runner now streams each step's output live, writes `Pipeline/logs/status.json`, and ends with a report. `python Pipeline/progress_ui.py` serves a small progress and ETA page at http://localhost:8765.
- The earlier 500-record check of steps 42 and 19 (files in `data/run500/`) found that step 19 wrote the text "nan" for records with no OGC type. That is fixed: blanks stay blank and empty types are skipped.
- A live run has not been done. Several steps are not safe to run live yet (the migration, step 14, and the SoilVoc steps on dev).
