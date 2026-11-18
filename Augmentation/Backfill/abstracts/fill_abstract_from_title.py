#!/usr/bin/env python3
"""Fill empty/NULL ``records.abstract`` from ``records.title``.

Top-level **``abstract`` column only** -- never touches ``raw_metadata``,
``title``, ``updated_at`` or anything else (unlike the cleanup apply pass).

    python3 fill_abstract_from_title.py                 # dry run (read-only)
    python3 fill_abstract_from_title.py --apply         # writes, takes a backup
    python3 fill_abstract_from_title.py --placeholders "xx,x,xxx,-,NA,2022" --apply
    python3 fill_abstract_from_title.py --restore output/apply/<file>.jsonl --apply

Target set (re-checked live at write time, so re-running is safe):

    (abstract IS NULL OR abstract = '')
    [ OR lower(btrim(abstract)) IN (<--placeholders>) ]      # placeholder values
    AND title IS NOT NULL AND btrim(title) <> ''

``--apply`` writes a before-image JSONL of the old abstract values first
(``output/apply/abstract_from_title_backup.jsonl``, or
``abstract_from_title_placeholders_backup.jsonl`` when ``--placeholders`` is
used; refuses to overwrite), runs the UPDATE in one transaction, asserts the
affected row count equals the dry-run count, and rolls back on any mismatch.
"""
from __future__ import annotations

# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import get_connection, default_schema  # noqa: E402  (loads <repo>/.env)
# validate since 2026-10-07; the queries use unqualified table names, so search_path is pinned
DB_SCHEMA = default_schema()
# ------------------------------------------------------------------------------------------

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Augmentation/Backfill
BASE_WHERE = ("(abstract IS NULL OR abstract = '') "
              "AND title IS NOT NULL AND btrim(title) <> ''")


def target_where(placeholders: list[str]) -> tuple[str, list[str]]:
    """WHERE clause for the target set; placeholders are extra 'empty' values."""
    where, params = BASE_WHERE, []
    if placeholders:
        cond = ("(abstract IS NULL OR abstract = '' "
                "OR lower(btrim(abstract)) = ANY(%s))")
        where = (cond + " AND title IS NOT NULL AND btrim(title) <> ''")
        params = [placeholders]
    return where, params


def connect():
    return get_connection(search_path=DB_SCHEMA)


def restore(path: str) -> int:
    """Write recorded before-images back into the abstract column."""
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    print(f"restoring {len(rows)} abstracts from {path}")
    sql = "UPDATE records SET abstract = %s WHERE id = %s"
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(sql, [(r["abstract"], r["id"]) for r in rows])
        print(f"committed: {cur.rowcount} rows touched")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="actually write")
    ap.add_argument("--show", type=int, default=8, help="sample rows to print")
    ap.add_argument("--placeholders", default="", metavar="V1,V2,...",
                    help="comma-separated abstract values to treat as empty too "
                         "(e.g. \"xx,x,xxx,-,NA,2022\")")
    ap.add_argument("--backup", default=None, help="before-image JSONL path")
    ap.add_argument("--restore", metavar="BACKUP.jsonl",
                    help="undo: write the recorded abstract values back and exit")
    args = ap.parse_args()

    if args.restore:
        return restore(args.restore)

    placeholders = [v.strip().lower() for v in args.placeholders.split(",") if v.strip()]
    where, wparams = target_where(placeholders)

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT id, identifier, title, abstract,
                                   abstract IS NULL AS is_null
                            FROM records WHERE {where}
                            ORDER BY identifier""", wparams)
            rows = cur.fetchall()
            cur.execute("""SELECT count(*) FROM records
                           WHERE (abstract IS NULL OR abstract = '')
                             AND (title IS NULL OR btrim(title) = '')""")
            skipped = cur.fetchone()[0]

        kind = "empty/NULL" + (f" or placeholder {placeholders}" if placeholders else "")
        print(f"targets: {len(rows)} ({kind}; skipped, empty title: {skipped})")
        for _id, ident, title, abstract, is_null in rows[: args.show]:
            old = "<NULL>" if is_null else repr(abstract)
            print(f"  {ident}\n      before: {old}\n      after : {title[:75]!r}")
        if len(rows) > args.show:
            print(f"  ... and {len(rows) - args.show} more")

        if not rows:
            print("\nNothing to do.")
            return 0
        if not args.apply:
            print("\nDry run. Re-run with --apply to write.")
            return 0

        suffix = "_placeholders" if placeholders else ""
        backup = args.backup or str(
            PROJECT_ROOT / "output" / "apply" /
            f"abstract_from_title{suffix}_backup_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")   # timestamped: reruns never collide
        Path(backup).parent.mkdir(parents=True, exist_ok=True)
        if Path(backup).exists():
            sys.exit(f"backup exists, refusing to overwrite: {backup}")
        with open(backup, "w", encoding="utf-8") as fh:
            for _id, ident, title, abstract, is_null in rows:
                fh.write(json.dumps(
                    {"id": _id, "identifier": ident,
                     "abstract": abstract, "was_null": bool(is_null)},
                    ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        print(f"\nbefore-image: {backup} ({len(rows)} records)")

        with conn.cursor() as cur:
            cur.execute(f"UPDATE records SET abstract = title WHERE {where}", wparams)
            if cur.rowcount != len(rows):
                conn.rollback()
                sys.exit(f"expected {len(rows)} rows, UPDATE hit {cur.rowcount}; "
                         "rolled back (someone touched the data mid-run)")
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM records "
                        "WHERE (abstract IS NULL OR abstract = '')")
            still = cur.fetchone()[0]
            cur.execute(f"SELECT count(*) FROM records WHERE {where}", wparams)
            remaining = cur.fetchone()[0]
        print(f"committed. empty/NULL abstracts in table: {still} "
              f"(targets left for this rule: {remaining})")
        print(f"undo: python3 scripts/abstracts/fill_abstract_from_title.py "
              f"--restore {backup} --apply")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
