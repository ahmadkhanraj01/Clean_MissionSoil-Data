# output

Files the Backfill scripts write. The folder is git-ignored apart from this README. Keep everything in `apply/` and every `*before_image*` and `*inserted_ids*` file: those files are how you undo a write.

| Folder / file | Written by | What |
|---|---|---|
| `scan/messy_records.csv` | `cleanup/find_messy.py` (step 31) | flagged records and their issue types |
| `dryrun/messy_cleanup_{dryrun,before_after}.csv` | `cleanup/dry_run.py` (32) | the diff; `_before_after.csv` is what a person signs off |
| `dryrun/messy_cleanup_{changes,summary}.csv` | `cleanup/analyse_diff.py` (33) | each change labelled, plus counts |
| `apply/messy_cleanup_backup_<ts>.jsonl` | `cleanup/apply_cleanup.py --apply` | before-image; undo with `--restore` |
| `apply/abstract_from_title[_placeholders]_backup_<ts>.jsonl` | `abstracts/fill_abstract_from_title.py --apply` (35) | before-image; undo with `--restore … --apply` |
| `url/url_candidates_DE.csv` | `url/find_urls_external.py` (36) | tier D/E candidate URLs with evidence |
| `url/url_preview.csv`, `url/url_before_image_<ts>.csv` | `url/build_url_column.py` (37) | derived URL per record; state before `--apply` |
| `url/missing_distributions_inserted_ids_<ts>.csv` | `url/add_missing_distributions.py --apply` (38) | inserted ids; undo = `DELETE FROM validate.distributions WHERE id IN (…)` |
| `url/url_vs_dist_*.csv` | `url/compare_url_accessurl.py` (39) | `records.url` vs `distributions.access_url` |
| `url/url_status.csv`, `url_check_cache.csv`, `url_check_status.json` | `url/check_urls.py`, `url_check_ui.py` | HTTP status per record and per URL |
| `url/source_url_check*.csv`, `source_urls_*`, `source_distributions_inserted_ids.csv` | the one-off 2026-10-07 source pass | not present: those files stay in the original backfill repo or machine |
