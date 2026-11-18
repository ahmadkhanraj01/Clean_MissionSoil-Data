#!/usr/bin/env python3
"""[helper] Check whether view_* values really are JSON-encoded strings. READ-ONLY.

Feeds two known records through json.loads the same way the cleaner does, so
you can see parse-OK vs parse-FAILED before trusting clean_json_list().
"""

# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import get_connection, default_schema  # noqa: E402  (loads <repo>/.env)
# validate since 2026-10-07; the queries use unqualified table names, so search_path is pinned
DB_SCHEMA = default_schema()
# ------------------------------------------------------------------------------------------
import json
import os
from pathlib import Path

import psycopg2
conn = get_connection(search_path=DB_SCHEMA)
cur = conn.cursor()

cur.execute("select id, raw_metadata->'view_contacts' from records where identifier='10.1002/wat2.1616'")
row = cur.fetchone()
print(row[0])
for item in row[1]:
    print(repr(item))
    try:
        parsed = json.loads(item)
        print('  parsed OK:', parsed)
    except Exception as e:
        print('  parse FAILED:', e)

cur.execute("select id, raw_metadata->'contact_persons' from records where identifier='10.5281/zenodo.15019232'")
row = cur.fetchone()
print(row[0])
for item in row[1]:
    print(repr(item))

cur.close()
conn.close()
