#!/usr/bin/env python3
"""[helper] Classify every backslash in abstracts: \\xNN vs LaTeX-like vs other. READ-ONLY.

Produced the evidence that almost all backslashes are legitimate (LaTeX math,
R code, grant numbers) and only a handful are real corruption -- which is why
dry_run.py does NOT touch backslashes in body text.
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
import re
from pathlib import Path

import psycopg2
conn = get_connection(search_path=DB_SCHEMA)
cur = conn.cursor(name='c1')
cur.itersize = 2000
cur.execute("select identifier, abstract from records where abstract like '%\\\\%'")

literal_escape = re.compile(r'\\x[0-9A-Fa-f]{2}')
latex_like = re.compile(r'\\[A-Za-z]+')
n_literal = n_latex = n_other = 0
examples_other = []

for ident, ab in cur:
    if literal_escape.search(ab):
        n_literal += 1
    elif latex_like.search(ab):
        n_latex += 1
    else:
        n_other += 1
        if len(examples_other) < 5:
            idx = ab.find('\\')
            examples_other.append((ident, ab[max(0, idx - 80):idx + 80]))

print('literal_escape (\\xNN):', n_literal)
print('latex-like (\\Word):', n_latex)
print('other:', n_other)
for e in examples_other:
    print(e)

cur.close()
conn.close()
