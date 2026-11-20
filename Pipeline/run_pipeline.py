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
from common.db import db_config, is_read_only  # noqa: E402
# ----------------------------------------

import argparse
import json
import re
import os
import subprocess
import threading
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
    # Step 42 (notebook 05 as a script) is listed here because it must run between 17 and 18;
    # its number comes after the migration so the numbers 18-41 stay as documented.
    (42, "types",     "Augmentation/Resource_Types/resolve_types_from_doi_registries.py", [],                  []),
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
    # Crossborder (Augmentation/Crossborder, from K2X/polygons): records.spatial bbox -> countries
    # covered -> validate.record_crossborder. After cleaning, since rows go with their record (CASCADE).
    (40, "spatial",   "Augmentation/Crossborder/compute_crossborder.py",                 ["--dry-run"],        []),
    (41, "migrate",   "Migration/migrate_validate_to_metadata.py",                       None,                 []),
]
# Backfill: 30-34, 36 and 39 only read the DB (and write files under Augmentation/Backfill/output, docs).
# 34 exits 1 when the cleanup diff needs a person to review it, which stops the run (use --keep-going).
# 35, 37, 38 are dry runs unless --live (then --apply). Not in the runner on purpose:
#   cleanup/apply_cleanup.py      needs a signed-off diff and its counts (--expect-records/--expect-rows)
#   url/check_urls*.py, url_check_ui.py   long HTTP checks of every URL
#   url/apply_source_urls.py, fix_source_urls_unescape.py, add_source_distributions.py
#                                 one-off 2026-10-07 pass; its input CSVs are not in the repo
#   diagnostics/*                 one-off inspectors
# Steps 15, 17 and 42 only read external/local files and write local files, so their
# "dry run" is the real run. Step 16 only reads the DB and writes a local JSON.
# Steps 20-23, 26, 27 and 29 only read the DB (read-only sessions) and write local files.
# Not in the runner on purpose: 07 make_review_sheet.py (rewrites review_sheet.csv and so
# would erase verdicts people filled in), and the analysis tasks 01, 03, 05.


# Steps that accept --limit N (a subset of records); the others are fast DB reads.
LIMIT_STEPS = {8, 32, 36, 42}
# Rough seconds per step for a 1,000-record run; used only for the ETA in the progress page.
EXPECTED = {8: 500, 16: 120, 17: 60, 32: 90, 36: 300, 42: 300, 22: 30, 26: 30, 27: 30}
DEFAULT_EXPECTED = 15


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="Execute the selected steps (default: just list them)")
    ap.add_argument("--live", action="store_true", help="Real run instead of dry run (writes to the DB)")
    ap.add_argument("--stage", choices=sorted({s[1] for s in STEPS}), help="Only this stage")
    ap.add_argument("--only", type=int, nargs="+", help="Only these step numbers")
    ap.add_argument("--keep-going", action="store_true", help="Continue after a failed step")
    ap.add_argument("--limit", type=int, default=0,
                    help="Use only N records in steps 8, 32, 36, 42 (the slow, API-bound ones)")
    ap.add_argument("--timeout", type=int, default=1800, help="Seconds allowed per step (default 1800)")
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
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}_{'live' if args.live else 'dry'}"
    log_path = log_dir / f"run_{stamp}.log"
    report_path = log_dir / f"report_{stamp}.md"
    secret_host = cfg.get("host") or ""
    clean = lambda t: t.replace(secret_host, "<host>") if secret_host else t
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None
    bar = tqdm(total=len(steps), unit="step", desc="pipeline", dynamic_ncols=True) if tqdm else None
    say = (bar.write if bar else print)
    t_start = datetime.now()
    summary = []   # (n, script, status, seconds, detail)
    cur_step = None
    status_path = log_dir / "status.json"

    def write_status(finished=False):
        """Progress for Pipeline/progress_ui.py: done steps, the current one, and an ETA."""
        exp = {n: EXPECTED.get(n, DEFAULT_EXPECTED) for n, *_ in steps}
        done_n = {x[0] for x in summary}
        actual = sum(x[3] for x in summary if x[2] != "SKIPPED")
        planned = sum(exp[x[0]] for x in summary if x[2] != "SKIPPED") or 1
        k = min(max(actual / planned, 0.3), 5)          # calibrate with how fast the done steps ran
        left = sum(exp[n] for n, *_ in steps if n not in done_n and not (cur_step and n == cur_step[0]))
        cur_left = 0
        if cur_step and not finished:
            el = time.time() - cur_step[2]
            pr = cur_step[4]
            if pr and pr[0] > 0:   # the step reports N/M: extrapolate from its own speed
                cur_left = max(el * (pr[1] - pr[0]) / pr[0], 1)
                k = 1.0 if not summary else k
            else:
                cur_left = max(exp[cur_step[0]] * k - el, 5)
        status_path.write_text(json.dumps({
            "mode": "live" if args.live else "dry run", "db": cfg["dbname"], "limit": args.limit,
            "started": t_start.timestamp(), "now": time.time(), "finished": finished,
            "total": len(steps), "done": len(summary),
            "current": ({"n": cur_step[0], "name": cur_step[1], "since": cur_step[2], "line": cur_step[3],
                         "progress": list(cur_step[4]) if cur_step[4] else None}
                        if cur_step and not finished else None),
            "eta_seconds": 0 if finished else round(left * k + cur_left),
            "steps": [{"n": n, "name": sc.rsplit("/", 1)[-1], "status": st, "secs": round(t, 1)} for n, sc, st, t, _ in summary],
            "pending": [n for n, *_ in steps if n not in done_n],
        }), encoding="utf-8")
    write_status()
    with open(log_path, "w", encoding="utf-8") as log:
        for i, (n, stage, script, dry, live) in enumerate(steps, 1):
            name = script.rsplit("/", 1)[-1]
            if not args.live and dry is None:
                summary.append((n, script, "SKIPPED", 0.0, "no dry-run mode (it would write)"))
                write_status()
                say(f"[{i}/{len(steps)}] step {n:>2} {name:<45} SKIPPED (no dry-run)")
                if bar: bar.update(1)
                continue
            if bar: bar.set_description(f"step {n} {name}")
            say(f"[{i}/{len(steps)}] step {n:>2} {name:<45} running ...")
            cmd = [sys.executable, str(_ROOT / script)] + (live if args.live else dry)
            if args.limit and n in LIMIT_STEPS:
                cmd += ["--limit", str(args.limit)]
            t0 = time.time()
            cur_step = (n, name, t0, "", None)
            write_status()
            log.write(f"\n=== Step {n}: {' '.join(cmd)}\n"); log.flush()
            # Stream the step's output live: a reader thread collects the lines, this loop keeps the
            # status file (last line, "N/M" progress) fresh and enforces the timeout.
            env = dict(os.environ, PYTHONUNBUFFERED="1")
            proc = subprocess.Popen(cmd, cwd=_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, env=env)
            buf, prog, seen, lastline = [], None, 0, ""
            reader = threading.Thread(target=lambda: [buf.append(l) for l in proc.stdout], daemon=True)
            reader.start()
            timed_out = False
            while reader.is_alive():
                reader.join(1.0)
                if len(buf) > seen:
                    new = clean("".join(buf[seen:])).replace("\r", "\n").splitlines()
                    seen = len(buf)
                    for ln in new:   # only "Progress: 300/1000", "[3/10]" or tqdm "n/m [" lines, never DOIs
                        m = re.search(r"(?i)progress\D{0,3}(\d[\d,]*)\s*/\s*(\d[\d,]*)", ln) or \
                            re.search(r"\[(\d+)/(\d+)\]", ln) or re.search(r"\b(\d+)/(\d+)\s*\[", ln)
                        if m and int(m[2].replace(",", "")):
                            prog = (int(m[1].replace(",", "")), int(m[2].replace(",", "")))
                    shown = [x for x in new if x.strip()]
                    if shown:
                        lastline = shown[-1].strip()[:160]
                    cur_step = (n, name, t0, lastline, prog)
                write_status()
                if time.time() - t0 > args.timeout:
                    proc.kill(); timed_out = True; break
            proc.wait()
            out, rc = clean("".join(buf)), (None if timed_out else proc.returncode)
            secs = time.time() - t0
            log.write(out); log.flush()
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            if rc is None:
                status, detail = "TIMEOUT", f"stopped after {args.timeout}s"
            elif rc == 0:
                status, detail = "OK", (lines[-1] if lines else "")
            elif "read-only transaction" in out or "ReadOnlySqlTransaction" in out:
                status, detail = "OK (read-only)", "ran up to its first write, which the read-only session blocked"
            else:
                status = f"FAILED (exit {rc})"
                err = [l for l in lines if re.search(r"error|exception|not found|no such|missing|Traceback", l, re.I)]
                detail = (err[-1] if err else (lines[-1] if lines else ""))
            detail = detail[:200].replace("|", "/")
            summary.append((n, script, status, secs, detail))
            say(f"[{i}/{len(steps)}] step {n:>2} {name:<45} {status}  ({secs:.1f}s)")
            cur_step = None
            write_status()
            if bar: bar.update(1)
            if status.startswith(("FAILED", "TIMEOUT")) and not args.keep_going:
                break
    if bar: bar.close()
    write_status(finished=True)

    good = lambda st: st.startswith("OK")
    n_ok = sum(good(x[2]) for x in summary); n_skip = sum(x[2] == "SKIPPED" for x in summary)
    n_bad = len(summary) - n_ok - n_skip
    lines = [f"# Pipeline report ({'LIVE' if args.live else 'dry run'})", "",
             f"- Database: `{cfg['dbname']}`, schema `validate`" + (" (session read-only)" if is_read_only() else ""),
             f"- Started {t_start:%Y-%m-%d %H:%M:%S}, finished {datetime.now():%H:%M:%S}, "
             f"total {sum(x[3] for x in summary):.0f}s",
             f"- Steps: {len(summary)} run or listed: **{n_ok} OK**, {n_skip} skipped, **{n_bad} failed**", "",
             "| Step | Script | Status | Time | Detail |", "|---:|---|---|---:|---|"]
    lines += [f"| {n} | `{sc.rsplit('/', 1)[-1]}` | {st} | {t:.1f}s | {d} |" for n, sc, st, t, d in summary]
    lines += ["", f"Full output: `{log_path.relative_to(_ROOT)}`", ""]
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "=" * 90)
    for n, script, status, secs, _ in summary:
        print(f"  {n:>2}  {status:<22} {secs:>7.1f}s  {script}")
    print(f"\nLog:    {log_path}\nReport: {report_path}")
    return 0 if n_bad == 0 else 1

if __name__ == "__main__":
    raise SystemExit(main())
