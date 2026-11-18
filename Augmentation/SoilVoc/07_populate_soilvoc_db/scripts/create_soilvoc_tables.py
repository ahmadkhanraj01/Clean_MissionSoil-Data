"""Create the SoilVoc tables on stage (soilvoc, record_soilvoc); renames soilvoc_types and drops old tables. Idempotent.

Usage: python Augmentation/SoilVoc/07_populate_soilvoc_db/scripts/create_soilvoc_tables.py [--db 1]

--db 1 = stage (DB_*1 in .env). Stage only: dev is never written.
Runs Augmentation/SoilVoc/07_populate_soilvoc_db/scripts/sql/create_soilvoc_tables.sql in one transaction as k2xadmin.
"""
import argparse
import sys
from pathlib import Path

import psycopg2
from dotenv import dotenv_values

import sys
sys.path.insert(0, next(str(p) for p in Path(__file__).resolve().parents if (p / "paths.py").exists()))
from paths import *  # noqa: E402,F401  (ROOT, CURATION, T0x_OUT, ...)
SQL_FILE = Path(__file__).resolve().parent / "sql" / "create_soilvoc_tables.sql"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", choices=("1",), default="1", help="1=stage (msp-kh-stage, schema validate). Dev is never written.")
    args = ap.parse_args()

    env = dotenv_values(ROOT / ".env")
    sfx = args.db
    for key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        if key + sfx not in env:
            sys.exit(f"missing {key}{sfx} in .env")
        env[key] = env[key + sfx]

    conn = psycopg2.connect(host=env["DB_HOST"], port=env["DB_PORT"], dbname=env["DB_NAME"],
                            user=env["DB_USER"], password=env["DB_PASSWORD"], connect_timeout=10)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(SQL_FILE.read_text())
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"OK: tables ensured in {env['DB_NAME']}.{env.get('DB_SCHEMA', 'validate')} (db {sfx})")


if __name__ == "__main__":
    main()
