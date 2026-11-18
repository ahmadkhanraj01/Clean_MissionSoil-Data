#!/usr/bin/env python3
"""[helper] Find literal \\xNN escapes and control characters in abstracts. READ-ONLY.

Supports the two one-off manual-fix cases called out in the cleanup report:
`S\\xF6derstr\\xF6m` (double-mangled name) and stray \\x7f DEL characters.
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
cur.execute("select identifier, abstract from records where abstract like '%\\\\x%'")
for ident, ab in cur.fetchall():
    idx = ab.find('\\x')
    print(ident, repr(ab[max(0, idx - 60):idx + 60]))

print('---control char---')
cur.execute(r"select identifier, abstract from records where abstract ~ '[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]'")
for ident, ab in cur.fetchall():
    for i, c in enumerate(ab):
        if ord(c) < 32 and c not in '\n\t\r' or ord(c) == 127:
            print(ident, 'char code', ord(c), repr(ab[max(0, i - 40):i + 40]))
cur.close()
conn.close()
