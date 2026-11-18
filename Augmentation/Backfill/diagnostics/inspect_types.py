#!/usr/bin/env python3
"""[helper] Print the Python types of every cleaning-relevant raw_metadata key. READ-ONLY.

Confirms which keys are str, list[str] or list-of-JSON-string before choosing
a cleaner (clean_list_plain vs clean_json_list) for them.
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
cur.execute("select id, raw_metadata from records where raw_metadata ? 'persons' limit 1")
id_, raw = cur.fetchone()
for f in ['persons', 'organizations', 'contact_persons', 'contact_organizations',
          'matched_subjects', 'license', 'soilmission', 'project_acronyms',
          'projects', 'sources', 'view_authors', 'view_contacts']:
    print(f, '->', type(raw.get(f)), repr(raw.get(f))[:200])
cur.close()
conn.close()
