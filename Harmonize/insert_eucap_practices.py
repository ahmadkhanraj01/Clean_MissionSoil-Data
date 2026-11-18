#!/usr/bin/env python3
"""
insert_eucap_practices.py
--------------------------
Inserts EU CAP Network practice abstracts from JSON directly into
the validate schema tables:
  - validate.records
  - validate.record_project   (links to existing projects)
  - validate.distributions    (practice URL only)

Usage:
  python insert_eucap_practices.py            # live run
  python insert_eucap_practices.py --dry-run  # rollback, no changes saved
"""

# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config  # noqa: E402,F401  (loads .env)
# --------------------------------------------------------------------------------------------
import argparse
import json
import logging
import os
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values, Json

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Environment is loaded by common.db (repo-root .env)

DEFAULT_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")

DB_DEFAULTS = {
    "host":   os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST"),
    "port":   int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or 5432),
    "dbname": os.getenv("DB_NAME") or os.getenv("POSTGRES_DB"),
    "user":   os.getenv("DB_USER") or os.getenv("POSTGRES_USER"),
}

JSON_PATH = DATA_DIR / "eu_cap_practice_abstracts.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def is_valid_url(url: str | None) -> bool:
    return bool(url and url.strip().startswith("http"))


def get_db_conn(password: str = DEFAULT_PASSWORD):
    return psycopg2.connect(**DB_DEFAULTS, password=password)


# ---------------------------------------------------------------------------
# Main inserter
# ---------------------------------------------------------------------------
class PracticeInserter:
    def __init__(self, conn):
        self.conn = conn
        self.cur = conn.cursor()

        # caches: key -> UUID
        self.projects_by_grant: dict[str, str] = {}    # grant_number -> uuid
        self.projects_by_acronym: dict[str, str] = {}  # lower(acronym) -> uuid
        self.records_by_ident: dict[str, str] = {}     # identifier -> uuid

    # ------------------------------------------------------------------
    def load_caches(self):
        logger.info("Loading existing entity caches from validate schema...")

        # Projects — validate.projects only has id and name
        self.cur.execute("SELECT id, name FROM validate.projects;")
        for row in self.cur.fetchall():
            pid, name = row
            if name:
                self.projects_by_acronym[name.strip().lower()] = str(pid)

        # Existing records — avoid re-inserting duplicates
        self.cur.execute("SELECT id, identifier FROM validate.records;")
        for row in self.cur.fetchall():
            self.records_by_ident[row[1]] = str(row[0])

        logger.info(
            f"Cached: {len(self.projects_by_acronym)} projects (by acronym), "
            f"{len(self.records_by_ident)} existing records."
        )

    # ------------------------------------------------------------------
    def run(self, data: list[dict]):
        records_batch        = []
        distributions_batch  = []
        record_project_batch = []

        skipped = 0

        for item in data:
            ident = (item.get("id") or "").strip()
            if not ident:
                skipped += 1
                continue

            # Skip if already in DB
            if ident in self.records_by_ident:
                skipped += 1
                continue

            # Resolve project first — skip entirely if no match
            acronym = str(item.get("project_acronym") or "").strip().lower()
            proj_uuid = self.projects_by_acronym.get(acronym)
            if not proj_uuid:
                skipped += 1
                continue

            title = (item.get("title") or "").strip()
            if not title:
                # fallback to project title so NOT NULL constraint is satisfied
                title = (item.get("project_title") or "").strip() or None
            abstract = (item.get("abstract") or "").strip() or None

            # Skip record if we still have no title
            if not title:
                skipped += 1
                continue
            url           = item.get("url", "").strip()
            rec_url       = url if is_valid_url(url) else None
            resource_type = "Practice Abstract"

            rec_uuid = str(uuid.uuid4())
            self.records_by_ident[ident] = rec_uuid

            records_batch.append((
                rec_uuid,
                ident,
                title,
                abstract,
                resource_type,
                "English",   # language
                None,        # publication_date — not in JSON
                None,        # temporal_start
                None,        # temporal_end
                rec_url,
                Json(item),  # raw_metadata — full JSON object
                "pending",   # approval_status
            ))

            # Distribution — practice URL only
            if rec_url:
                distributions_batch.append((
                    str(uuid.uuid4()),
                    rec_uuid,
                    "EU CAP Network Page",
                    "HTML",
                    rec_url,
                ))

            # Project link
            record_project_batch.append((
                str(uuid.uuid4()),
                rec_uuid,
                proj_uuid,
            ))

        logger.info(f"Skipped (no project match / already exist / no ID): {skipped}")

        # ---- INSERT validate.records ----
        logger.info(f"Writing {len(records_batch)} records into validate.records...")
        execute_values(self.cur, """
            INSERT INTO validate.records (
                id, identifier, title, abstract, resource_type, language,
                publication_date, temporal_start, temporal_end, url,
                raw_metadata, approval_status
            ) VALUES %s
            ON CONFLICT (identifier) DO NOTHING;
        """, records_batch, page_size=500)

        # ---- INSERT validate.distributions ----
        if distributions_batch:
            logger.info(f"Writing {len(distributions_batch)} distributions...")
            execute_values(self.cur, """
                INSERT INTO validate.distributions (id, record_id, name, format, access_url)
                VALUES %s
                ON CONFLICT DO NOTHING;
            """, distributions_batch, page_size=500)

        # ---- INSERT validate.record_project ----
        if record_project_batch:
            logger.info(f"Writing {len(record_project_batch)} project links into validate.record_project...")
            execute_values(self.cur, """
                INSERT INTO validate.record_project (id, record_id, project_id)
                VALUES %s
                ON CONFLICT DO NOTHING;
            """, record_project_batch, page_size=500)

        return len(records_batch), len(distributions_batch), len(record_project_batch)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Insert EU CAP practice abstracts into validate schema.")
    parser.add_argument("--dry-run", action="store_true", help="Rollback at the end — no changes saved.")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Database password")
    args = parser.parse_args()

    mode = "DRY-RUN (No changes will be saved)" if args.dry_run else "EXECUTE (Committing to DB)"

    print("=" * 65)
    print("INSERT EU CAP PRACTICE ABSTRACTS -> validate schema")
    print(f"Source:  {JSON_PATH}")
    print(f"Target:  msp-kh-dev on {DB_DEFAULTS['host']}:{DB_DEFAULTS['port']}")
    print(f"Mode:    {mode}")
    print("=" * 65)

    # Load JSON
    logger.info(f"Loading practice abstracts from {JSON_PATH}...")
    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    logger.info(f"Loaded {len(data)} practice abstracts from JSON.")

    conn = get_db_conn(password=args.password)
    try:
        inserter = PracticeInserter(conn)
        inserter.load_caches()

        rec_cnt, dist_cnt, rp_cnt = inserter.run(data)

        if args.dry_run:
            conn.rollback()
            print("\n[DRY-RUN] All transactions rolled back — nothing saved.")
        else:
            conn.commit()
            print("\n SUCCESS: All practice abstracts committed to validate schema!")

        # Post-run summary counts
        inserter.cur.execute("SELECT COUNT(*) FROM validate.records;")
        total_records = inserter.cur.fetchone()[0]

        inserter.cur.execute("SELECT COUNT(*) FROM validate.record_project;")
        total_rp = inserter.cur.fetchone()[0]

        print("\n" + "=" * 65)
        print("VALIDATE SCHEMA SUMMARY:")
        print(f"  Records inserted this run:          {rec_cnt}")
        print(f"  Distributions inserted this run:    {dist_cnt}")
        print(f"  Project links inserted this run:    {rp_cnt}")
        print(f"  Total records in validate.records:  {total_records}")
        print(f"  Total links in record_project:      {total_rp}")
        print("=" * 65)

    except Exception as e:
        conn.rollback()
        logger.error(f"Error: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
