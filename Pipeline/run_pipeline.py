#!/usr/bin/env python3
"""
run_pipeline.py
--------------------------------------------------------------------------------
Runs the MissionSoil pipeline steps in order (see pipeline_dfd.html).

  python Pipeline/run_pipeline.py                      # list the steps, run nothing
  python Pipeline/run_pipeline.py --run                # DRY RUN of every step that has one
  python Pipeline/run_pipeline.py --run --stage clean  # dry run of one stage
  python Pipeline/run_pipeline.py --run --only 13      # dry run of one step
  python Pipeline/run_pipeline.py --run --live --only 13   # REAL run (writes to the DB)

Dry run: each step gets its own dry-run flag. Steps without a dry-run mode are
skipped (they would write), and the runner says so.
Live run: requires --live and asks you to type the database name to confirm.
Every run writes a log to Pipeline/logs/.
--------------------------------------------------------------------------------
"""
# --- Clean_MissionSoil-Data bootstrap ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import db_config  # noqa: E402
# ----------------------------------------

import argparse
import subprocess
import sys
import time
from datetime import datetime

_SV = "Augmentation/SoilVoc"
_TTL = f"{_SV}/vocab/SoilVoc.ttl"
_LEVELS = f"{_SV}/04_soilvoc_hierarchy/outputs/soilvoc_keywords_by_level.csv"
_TREE = f"{_SV}/04_soilvoc_hierarchy/outputs/soilvoc_hierarchy.json"
_BF = "Augmentation/Backfill"
_MC = f"{_BF}/output/dryrun/messy_cleanup"
_MC_CSV = _MC + "_before_after.csv"
_PH = "xx,x,xxx,-,NA,2022"                      # abstract values treated as empty
_DE = f"{_BF}/output/url/url_candidates_DE.csv"  # written by step 36

# n, stage, script, dry-run args (None = no dry-run mode), live args
STEPS = [
    (1,  "harvest",   "Harvesting/Projects_Registry/harvest_esdac_projects.py",          None,                 []),
    (2,  "harvest",   "Harvesting/EUFarmbook/harvest_eufarmbook_projects.py",            None,                 []),
    (3,  "harvest",   "Harvesting/EUCAP/harvest_eucap_projects.py",                      ["--dry-run"],        []),
    (4,  "harvest",   "Harvesting/CORDIS/harvest_cordis_project_metadata.py",            None,                 []),
    (5,  "harvest",   "Harvesting/EUFarmbook/harvest_eufarmbook_contributions.py",       None,                 []),
    (6,  "harvest",   "Harvesting/EUCAP/harvest_eucap_practice_abstracts.py",            None,                 []),
    (7,  "harvest",   "Harvesting/Solar_API/harvest_solr_records.py",                    ["--dry-run"],        []),
    (8,  "augment",   "Augmentation/Enrichment/enrich_missing_abstracts.py",             ["--dry-run"],        []),
    (9,  "harmonize", "Harmonize/harmonize_projects_to_validate.py",                     ["--dry-run"],        []),
    (10, "harmonize", "Harmonize/harmonize_all_to_validate.py",                          ["--dry-run"],        []),
    (11, "harmonize", "Harmonize/insert_eucap_practices.py",                             ["--dry-run"],        []),
    (12, "clean",     "Augmentation/Cleanning-Scripts/clean_stage_subjects.py",          [],                   ["--commit"]),
    (13, "clean",     "Augmentation/Cleanning-Scripts/clean_record_languages.py",        [],                   ["--commit"]),
    (14, "clean",     "Augmentation/Cleanning-Scripts/clean_and_deduplicate_kh_dev.py",  ["--dry-run"],        []),
    (15, "types",     "Augmentation/Resource_Types/fetch_soilwise_records.py",           None,                 []),
    (16, "types",     "Augmentation/Resource_Types/fetch_msp_kh_records.py",             [],                   []),
    (17, "types",     "Augmentation/Resource_Types/compare_msp_vs_ogc_types.py",         [],                   []),
    (18, "types",     "Augmentation/Resource_Types/update_resource_types_from_ogc.py",   [],                   ["--execute"]),
    (19, "types",     "Augmentation/Resource_Types/resolve_neither_and_unresolved.py",   [],                   ["--execute"]),
    # SoilVoc (Augmentation/SoilVoc, from soil-vocabs/tasks): runs after cleaning, because
    # record_soilvoc rows are deleted with their record (ON DELETE CASCADE) by step 14.
    (20, "soilvoc",   f"{_SV}/04_soilvoc_hierarchy/scripts/soilvoc_levels.py",            [_TTL, _LEVELS],      [_TTL, _LEVELS]),
    (21, "soilvoc",   f"{_SV}/04_soilvoc_hierarchy/scripts/soilvoc_json.py",              [_LEVELS, _TREE],     [_LEVELS, _TREE]),
    (22, "soilvoc",   f"{_SV}/06_keyword_cleaning/scripts/clean_subjects.py",             ["--db", "1"],        ["--db", "1"]),
    (23, "soilvoc",   f"{_SV}/06_keyword_cleaning/scripts/review_inside_keywords.py",     [],                   []),
    (24, "soilvoc",   f"{_SV}/07_populate_soilvoc_db/scripts/create_soilvoc_tables.py",   None,                 []),
    (25, "soilvoc",   f"{_SV}/07_populate_soilvoc_db/scripts/load_soilvoc.py",            None,                 []),
    (26, "soilvoc",   f"{_SV}/07_populate_soilvoc_db/scripts/build_soilvoc_links.py",     [],                   []),
    (27, "soilvoc",   f"{_SV}/07_populate_soilvoc_db/scripts/build_record_soilvoc.py",    [],                   []),
    (28, "soilvoc",   f"{_SV}/07_populate_soilvoc_db/scripts/load_record_soilvoc.py",     None,                 []),
    (29, "soilvoc",   f"{_SV}/07_populate_soilvoc_db/scripts/check_soilvoc_vs_json.py",   [],                   []),
    # Backfill (Augmentation/Backfill, from github.com/ahmadkhanraj01/SoilWise_metadata_backfill,
    # without crosscheck/): text cleanup, empty abstracts, records.url, distributions.
    (30, "backfill",  f"{_BF}/url/test_url_rules.py",                                    [],                   []),
    (31, "backfill",  f"{_BF}/cleanup/find_messy.py",                                    ["--force"],          ["--force"]),
    (32, "backfill",  f"{_BF}/cleanup/dry_run.py",                                       ["--out-prefix", _MC, "--force"], ["--out-prefix", _MC, "--force"]),
    (33, "backfill",  f"{_BF}/cleanup/analyse_diff.py",                                  [_MC_CSV],            [_MC_CSV]),
    (34, "backfill",  f"{_BF}/cleanup/verify_diff.py",                                   [_MC_CSV],            [_MC_CSV]),
    (35, "backfill",  f"{_BF}/abstracts/fill_abstract_from_title.py",                    ["--placeholders", _PH], ["--placeholders", _PH, "--apply"]),
    (36, "backfill",  f"{_BF}/url/find_urls_external.py",                                [],                   []),
    (37, "backfill",  f"{_BF}/url/build_url_column.py",                                  ["--candidates", _DE], ["--candidates", _DE, "--apply"]),
    (38, "backfill",  f"{_BF}/url/add_missing_distributions.py",                         [],                   ["--apply"]),
    (39, "backfill",  f"{_BF}/url/compare_url_accessurl.py",                             [],                   []),
    (40, "migrate",   "Migration/migrate_validate_to_metadata.py",                       None,                 []),
]
# Backfill: 30-34, 36 and 39 only read the DB (and write files under Augmentation/Backfill/output, docs).
# 34 exits 1 when the cleanup diff needs a person to review it, which stops the run (use --keep-going).
# 35, 37, 38 are dry runs unless --live (then --apply). Not in the runner on purpose:
#   cleanup/apply_cleanup.py      needs a signed-off diff and its counts (--expect-records/--expect-rows)
#   url/check_urls*.py, url_check_ui.py   long HTTP checks of every URL
#   url/apply_source_urls.py, fix_source_urls_unescape.py, add_source_distributions.py
#                                 one-off 2026-10-07 pass; its input CSVs are not in the repo
#   diagnostics/*                 one-off inspectors
# Steps 15 and 17 only read external/local files and write local files, so their
# "dry run" is the real run. Step 16 only reads the DB and writes a local JSON.
# Steps 20-23, 26, 27 and 29 only read the DB (read-only sessions) and write local files.
# Not in the runner on purpose: 07 make_review_sheet.py (rewrites review_sheet.csv and so
# would erase verdicts people filled in), and the analysis tasks 01, 03, 05.


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="Execute the selected steps (default: just list them)")
    ap.add_argument("--live", action="store_true", help="Real run instead of dry run (writes to the DB)")
    ap.add_argument("--stage", choices=sorted({s[1] for s in STEPS}), help="Only this stage")
    ap.add_argument("--only", type=int, nargs="+", help="Only these step numbers")
    ap.add_argument("--keep-going", action="store_true", help="Continue after a failed step")
    args = ap.parse_args()

    steps = [s for s in STEPS
             if (not args.stage or s[1] == args.stage) and (not args.only or s[0] in args.only)]
    cfg = db_config()

    if not args.run:
        print(f"Database from .env: {cfg['dbname']} @ {cfg['host']}:{cfg['port']}\n")
        for n, stage, script, dry, live in steps:
            mode = "dry-run: " + (" ".join(dry) or "(default)") if dry is not None else "no dry-run (skipped in dry runs)"
            print(f"  {n:>2}  {stage:<9}  {script:<66} {mode}")
        print("\nAdd --run to execute (dry run), --run --live for a real run.")
        return 0

    if args.live:
        typed = input(f"LIVE run writes to '{cfg['dbname']}' on {cfg['host']}. Type the database name to continue: ")
        if typed.strip() != cfg["dbname"]:
            print("Cancelled.")
            return 1

    log_dir = _ROOT / "Pipeline" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}_{'live' if args.live else 'dry'}.log"
    summary = []
    with open(log_path, "w", encoding="utf-8") as log:
        for n, stage, script, dry, live in steps:
            if not args.live and dry is None:
                summary.append((n, script, "SKIPPED (no dry-run)", 0.0))
                continue
            cmd = [sys.executable, str(_ROOT / script)] + (live if args.live else dry)
            print(f"\n=== Step {n}: {script} {' '.join(cmd[2:])}")
            log.write(f"\n=== Step {n}: {' '.join(cmd)}\n")
            log.flush()
            t0 = time.time()
            proc = subprocess.run(cmd, cwd=_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            log.write(proc.stdout)
            print(proc.stdout[-3000:])
            status = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
            summary.append((n, script, status, time.time() - t0))
            if proc.returncode != 0 and not args.keep_going:
                break

    print("\n" + "=" * 90)
    for n, script, status, secs in summary:
        print(f"  {n:>2}  {status:<22} {secs:>7.1f}s  {script}")
    print(f"\nLog: {log_path}")
    return 0 if all(s[2] in ("OK",) or s[2].startswith("SKIPPED") for s in summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
