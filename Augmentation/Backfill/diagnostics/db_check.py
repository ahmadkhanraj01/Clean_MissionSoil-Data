#!/usr/bin/env python3
"""[helper] Dump the DB schema of `records` + row count. READ-ONLY.

Use this first when connecting to a new environment: confirms column names
and that DB_TABLE in <repo>/.env points where you think it does.
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
import os
from pathlib import Path

import psycopg2
conn = get_connection(search_path=DB_SCHEMA)
cur = conn.cursor()
cur.execute(
    "select column_name, data_type from information_schema.columns "
    "where table_name=%s and table_schema=current_schema() order by ordinal_position",
    (os.getenv('DB_TABLE', 'records'),))
for r in cur.fetchall():
    print(r)
cur.execute("select count(*) from records")
print(cur.fetchone())
cur.close()
conn.close()
