#!/usr/bin/env python3
"""
verify_readonly.py
--------------------------------------------------------------------------------
Read-only check that the scripts in this repo match the database in .env.

For every script it extracts the schema-qualified tables it reads/writes
(FROM/JOIN/INTO/UPDATE <schema>.<table>) and the column lists of its INSERTs,
then checks them against information_schema. It also prints row counts and
lists tables that exist in the DB but no script touches.

The connection runs with default_transaction_read_only=on (MSP_READ_ONLY=1),
so nothing can be written even by mistake.

Usage:
  python Pipeline/verify_readonly.py [--dbname NAME]
--------------------------------------------------------------------------------
"""
import os
os.environ["MSP_READ_ONLY"] = "1"  # must be set before common.db is imported

# --- Clean_MissionSoil-Data bootstrap ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import get_connection, db_config  # noqa: E402
# ----------------------------------------

import argparse
import re
from collections import defaultdict

SCHEMAS = ("harvest", "validate", "metadata")
SCRIPT_DIRS = ("Harvesting", "Augmentation", "Harmonize", "Migration")

TABLE_RE = re.compile(r"\b(FROM|JOIN|INTO|UPDATE|TABLE(?: IF NOT EXISTS)?)\s+\"?(harvest|validate|metadata)\"?\.\"?([a-z_]+)\"?", re.I)
INSERT_RE = re.compile(r"INSERT\s+INTO\s+(harvest|validate|metadata)\.([a-z_]+)\s*\(([^)]*)\)", re.I | re.S)
UPDATE_SET_RE = re.compile(r"UPDATE\s+(harvest|validate|metadata)\.([a-z_]+)\s+(?:AS\s+\w+\s+)?SET\s+(.*?)(?:\bFROM\b|\bWHERE\b|$)", re.I | re.S)
WRITE_KW = {"INTO", "UPDATE"}


def scan_scripts():
    uses = defaultdict(lambda: defaultdict(set))   # script -> table -> {READ, WRITE, DDL}
    inserts = defaultdict(list)                    # script -> [(table, [cols])]
    updates = defaultdict(list)                    # script -> [(table, [cols])]
    for d in SCRIPT_DIRS:
        for path in sorted((_ROOT / d).rglob("*.py")):
            rel = str(path.relative_to(_ROOT))
            src = path.read_text(encoding="utf-8", errors="replace")
            for kw, schema, table in TABLE_RE.findall(src):
                kind = "WRITE" if kw.upper() in WRITE_KW else ("DDL" if kw.upper().startswith("TABLE") else "READ")
                uses[rel][f"{schema.lower()}.{table.lower()}"].add(kind)
            for schema, table, cols in INSERT_RE.findall(src):
                names = [c.strip().strip('"').lower() for c in cols.split(",")]
                if names and all(re.fullmatch(r"[a-z_][a-z0-9_]*", n) for n in names):
                    inserts[rel].append((f"{schema.lower()}.{table.lower()}", names))
            for schema, table, body in UPDATE_SET_RE.findall(src):
                cols = re.findall(r"(?:^|,)\s*([a-z_][a-z0-9_]*)\s*=", body, re.I)
                if cols:
                    updates[rel].append((f"{schema.lower()}.{table.lower()}", [c.lower() for c in cols]))
    return uses, inserts, updates


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dbname", default=None)
    args = ap.parse_args()

    cfg = db_config(args.dbname)
    conn = get_connection(args.dbname)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor()
    cur.execute("SHOW transaction_read_only")
    ro = cur.fetchone()[0]
    print(f"Database : {cfg['dbname']} @ {cfg['host']}:{cfg['port']}   read-only: {ro}")
    if ro != "on":
        print("Refusing to continue: connection is not read-only.")
        return 2

    cur.execute("""SELECT table_schema, table_name, column_name FROM information_schema.columns
                   WHERE table_schema = ANY(%s)""", (list(SCHEMAS),))
    columns = defaultdict(set)
    for s, t, c in cur.fetchall():
        columns[f"{s}.{t}"].add(c)
    counts = {}
    for t in sorted(columns):
        s, n = t.split(".")
        cur.execute(f'SELECT count(*) FROM "{s}"."{n}"')
        counts[t] = cur.fetchone()[0]

    uses, inserts, updates = scan_scripts()
    problems = 0
    touched = set()
    print("\n=== Tables per script ===")
    for script in sorted(uses):
        print(f"\n{script}")
        for table, kinds in sorted(uses[script].items()):
            touched.add(table)
            exists = table in columns
            status = f"{counts[table]:>9,} rows" if exists else "  MISSING"
            if not exists:
                problems += 1
            print(f"   {'/'.join(sorted(kinds)):<16} {table:<38} {status}")
        for label, items in (("INSERT", inserts.get(script, [])), ("UPDATE", updates.get(script, []))):
            for table, cols in items:
                if table not in columns:
                    continue
                missing = [c for c in cols if c not in columns[table]]
                if missing:
                    problems += 1
                    print(f"   !! {label} {table}: columns not in DB: {', '.join(missing)}")

    print("\n=== Tables in the DB that no script references ===")
    for t in sorted(set(columns) - touched):
        if re.search(r"_backup_|_pre_", t):
            continue
        print(f"   {t:<40} {counts[t]:>9,} rows")

    print(f"\nProblems found: {problems}")
    conn.close()
    return 1 if problems else 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)
