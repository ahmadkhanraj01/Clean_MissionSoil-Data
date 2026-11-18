#!/usr/bin/env python3
"""[helper] Print one sample `raw_metadata` jsonb document, pretty-printed. READ-ONLY.

Used to learn the shape of the jsonb (which keys exist, whether a key holds a
string, a list of strings, or a list of JSON-encoded strings) before writing
cleaning rules.
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
cur.execute("select raw_metadata from records where raw_metadata is not null limit 1")
row = cur.fetchone()
print(json.dumps(row[0], indent=2)[:3000])
cur.close()
conn.close()
