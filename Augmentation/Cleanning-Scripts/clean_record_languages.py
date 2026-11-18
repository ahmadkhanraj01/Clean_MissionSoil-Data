#!/usr/bin/env python3
"""
clean_record_languages.py
--------------------------------------------------------------------------------
Standardises `<schema>.records.language` (default schema: validate).

Built from two sources on branch `mahnoor`:
  - "Language Column Data Cleanup .md": the CASE mapping (codes -> full names).
  - notebooks/01_soilwise_pipeline_and_reconciliation.ipynb sections 29-30:
    filling remaining 'Unknown' rows from data/language_recovered.csv.

Step 1  normalise
  Maps codes and spellings to one full English name ('en'/'eng'/'enc' -> 'English',
  'fr'/'fra' -> 'French', ...). Values that are already a full name are KEPT.
  (The original SQL sent everything not in its code list to 'Unknown', which
  turns 'English' into 'Unknown' when run a second time.)
  NULL, '', 'null' and anything unrecognised become 'Unknown'.

Step 2  recover (only with --recovered-csv)
  For rows still NULL / '' / 'Unknown', sets the language from a CSV with
  columns identifier,language. Rows that already have a language are skipped,
  so a rerun resumes where the last run stopped.

Safety
  - Dry run by default: prints what would change, writes nothing.
  - --commit creates <schema>.records_lang_backup_<timestamp> (identifier, language)
    first, then applies both steps in one transaction (rollback on error).

Usage
  python clean_record_languages.py                                   # dry run
  python clean_record_languages.py --recovered-csv data/language_recovered.csv
  python clean_record_languages.py --commit [--recovered-csv ...]
--------------------------------------------------------------------------------
"""
# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config, default_schema  # noqa: E402  (loads .env)
# --------------------------------------------------------------------------------------------
import argparse
import csv
import logging
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("clean_record_languages")

UNKNOWN = "Unknown"

# From "Language Column Data Cleanup .md" (CASE statement), plus codes the harmonizers write.
CODE_TO_NAME = {
    "en": "English", "eng": "English", "enc": "English",
    "fr": "French", "fra": "French",
    "sk": "Slovak",
    "nn": "Norwegian Nynorsk",
    "bg": "Bulgarian",
    "fi": "Finnish",
    "cat": "Catalan", "ca": "Catalan",
    "http://publications.europa.eu/resource/authority/language/cat": "Catalan",
    "glg": "Galician",
    "hr": "Croatian",
    "cs": "Czech",
    "lt": "Lithuanian",
    "sv": "Swedish", "swedish": "Swedish",
    "ro": "Romanian",
    "de": "German",
    "nl": "Dutch",
    "sl": "Slovenian",
    "et": "Estonian",
    "ar": "Arabic",
    "pt": "Portuguese",
    "hu": "Hungarian",
    "el": "Greek",
    "pl": "Polish",
    "it": "Italian",
    "lv": "Latvian",
    "es": "Spanish",
    "da": "Danish",
    "bzj": "Belize Kriol",
    "ekk": "Estonian (Standard)",
    "und": "Undetermined", "indeterminado": "Undetermined",
    "other": "Other",
}
# ISO 639-2/3 codes (incl. EU vocabulary URIs .../language/deu) for the same languages
CODE_TO_NAME.update({
    "deu": "German", "ger": "German", "ita": "Italian", "spa": "Spanish", "nld": "Dutch", "dut": "Dutch",
    "por": "Portuguese", "pol": "Polish", "hun": "Hungarian", "ron": "Romanian", "rum": "Romanian",
    "swe": "Swedish", "dan": "Danish", "lav": "Latvian", "ces": "Czech", "cze": "Czech", "fin": "Finnish",
    "slk": "Slovak", "slo": "Slovak", "slv": "Slovenian", "est": "Estonian", "hrv": "Croatian",
    "nno": "Norwegian Nynorsk", "lit": "Lithuanian", "bul": "Bulgarian", "ara": "Arabic",
    "ell": "Greek", "gre": "Greek", "fre": "French", "gl": "Galician",
    "zh": "Chinese", "zho": "Chinese", "chi": "Chinese", "mk": "Macedonian", "mkd": "Macedonian",
    "sr": "Serbian", "srp": "Serbian", "cnr": "Montenegrin",
})

# Full names that may already be in the table and must be kept as they are.
# (Chinese, Macedonian, Montenegrin, Serbian are present in msp-kh-stage but not in the .md mapping.)
CANONICAL = set(CODE_TO_NAME.values()) | {UNKNOWN, "Chinese", "Macedonian", "Montenegrin", "Serbian"}
_CANON_LOWER = {c.lower(): c for c in CANONICAL}

EU_LANG_URI = re.compile(r"^https?://publications\.europa\.eu/resource/authority/language/([a-z]{3})$", re.I)


def normalise(value):
    """Return the standard full name for a raw language value."""
    if value is None:
        return UNKNOWN
    v = value.strip()
    if not v or v.lower() == "null":
        return UNKNOWN
    low = v.lower()
    if low in CODE_TO_NAME:
        return CODE_TO_NAME[low]
    if low in _CANON_LOWER:                      # already a full name (any case)
        return _CANON_LOWER[low]
    m = EU_LANG_URI.match(v)                     # EU vocabulary URI with a known 3-letter code
    if m and m.group(1).lower() in CODE_TO_NAME:
        return CODE_TO_NAME[m.group(1).lower()]
    return UNKNOWN


def read_recovered_csv(path: Path):
    rows, seen = [], set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ident, lang = (row.get("identifier") or "").strip(), (row.get("language") or "").strip()
            if ident and lang and ident not in seen:
                seen.add(ident)
                rows.append((ident, normalise(lang)))
    return rows


def main():
    ap = argparse.ArgumentParser(description="Standardise records.language (dry run unless --commit).")
    ap.add_argument("--schema", default=default_schema(), help="Schema holding records (default: DB_SCHEMA from .env, else validate)")
    ap.add_argument("--dbname", default=None, help="Database (default: DB_NAME from .env)")
    ap.add_argument("--recovered-csv", default=None,
                    help=f"CSV identifier,language to fill remaining Unknown rows (e.g. {DATA_DIR / 'language_recovered.csv'})")
    ap.add_argument("--commit", action="store_true", help="Apply changes (default: dry run)")
    args = ap.parse_args()

    schema = args.schema
    table = f"{schema}.records"
    cfg = db_config(args.dbname)
    print("=" * 70)
    print(f"  LANGUAGE CLEANUP  {table}  on {cfg['dbname']} @ {cfg['host']}:{cfg['port']}")
    print(f"  Mode: {'COMMIT' if args.commit else 'DRY RUN (no writes)'}")
    print("=" * 70)

    conn = get_connection(args.dbname)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # ---- Step 1: normalise distinct values ----
            cur.execute(f"SELECT language, count(*) FROM {table} GROUP BY language")
            dist = cur.fetchall()
            mapping = {}
            changes = Counter()
            for raw, n in dist:
                new = normalise(raw)
                if raw != new:
                    mapping[raw] = new
                    changes[(raw, new)] += n
            total = sum(changes.values())
            print(f"\nStep 1 normalise: {len(dist)} distinct values, {len(mapping)} to change, {total:,} rows affected")
            for (raw, new), n in sorted(changes.items(), key=lambda x: -x[1])[:40]:
                print(f"   {raw!r:>40} -> {new:<22} {n:>8,}")

            # ---- Step 2: recover Unknown from CSV ----
            recovered = []
            if args.recovered_csv:
                csv_rows = read_recovered_csv(Path(args.recovered_csv))
                cur.execute(f"SELECT identifier, language FROM {table} WHERE identifier = ANY(%s)",
                            ([r[0] for r in csv_rows],))
                current = dict(cur.fetchall())
                pending_unknown = lambda ident: normalise(current.get(ident)) == UNKNOWN  # noqa: E731
                recovered = [(i, l) for i, l in csv_rows if i in current and pending_unknown(i) and l != UNKNOWN]
                not_found = sum(1 for i, _ in csv_rows if i not in current)
                print(f"\nStep 2 recover: {len(csv_rows):,} rows in CSV | {len(recovered):,} to fill | "
                      f"{len(csv_rows) - len(recovered) - not_found:,} already have a language | {not_found:,} not in DB")

            if not args.commit:
                print("\nDry run: nothing written. Re-run with --commit to apply.")
                conn.rollback()
                return

            # ---- Apply ----
            backup = f"{schema}.records_lang_backup_{datetime.now():%Y%m%d_%H%M%S}"
            cur.execute(f"CREATE TABLE {backup} AS SELECT identifier, language FROM {table}")
            logger.info(f"Backup created: {backup}")

            updated1 = 0
            for raw, new in mapping.items():
                if raw is None:
                    cur.execute(f"UPDATE {table} SET language = %s WHERE language IS NULL", (new,))
                else:
                    cur.execute(f"UPDATE {table} SET language = %s WHERE language = %s", (new, raw))
                updated1 += cur.rowcount

            updated2 = 0
            if recovered:
                execute_values(cur, f"""
                    UPDATE {table} AS r SET language = v.lang
                    FROM (VALUES %s) AS v(identifier, lang)
                    WHERE r.identifier = v.identifier
                      AND (r.language IS NULL OR r.language IN ('', 'Unknown'))
                """, recovered, page_size=500)
                updated2 = cur.rowcount  # rowcount of the last page only
                cur.execute(f"SELECT count(*) FROM {table} t JOIN {backup} b USING (identifier) "
                            f"WHERE t.language IS DISTINCT FROM b.language")
                logger.info(f"Rows changed vs backup (steps 1+2): {cur.fetchone()[0]:,}")
            conn.commit()
            print(f"\nCommitted: step 1 updated {updated1:,} rows, step 2 updated {updated2:,} rows. Backup: {backup}")
    except Exception:
        conn.rollback()
        logger.exception("Failed, transaction rolled back")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
