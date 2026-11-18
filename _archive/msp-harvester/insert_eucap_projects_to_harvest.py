#!/usr/bin/env python3
"""
Script: insert_eucap_projects_to_harvest.py
Purpose:
  Ingest the 206 missing EU CAP Network projects from
  `data/eucap_projects_not_in_msp_testing.json` into the `harvest.projects`
  table of the PostgreSQL database (`msp-kh-dev`).

Usage:
  python insert_eucap_projects_to_harvest.py [--dry-run] [--copy-testing-base]
"""

import os
import sys
import json
import argparse
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# Load environment
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DEFAULT_HOST     = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST")
DEFAULT_PORT     = int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or 5432)
DEFAULT_DBNAME   = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB")
DEFAULT_USER     = os.getenv("DB_USER") or os.getenv("POSTGRES_USER")
DEFAULT_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")

DEFAULT_JSON_PATH = os.path.join(BASE_DIR, "data", "eucap_projects_not_in_msp_testing.json")

def get_db_connection(host, port, dbname, user, password):
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password
    )

def ensure_harvest_table(conn):
    """Ensure harvest schema, harvest.projects table, and unique index exist."""
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS harvest;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS harvest.projects (
                code character varying(99) NOT NULL,
                title text,
                funding character varying(255),
                website text,
                grantnr character varying(99) NOT NULL,
                source character varying(99),
                keywords text[],
                description text,
                cordis_url text
            );
        """)
        # If the table already existed with older schema, ensure extra columns exist
        cur.execute("""
            ALTER TABLE harvest.projects ADD COLUMN IF NOT EXISTS keywords text[];
            ALTER TABLE harvest.projects ADD COLUMN IF NOT EXISTS description text;
            ALTER TABLE harvest.projects ADD COLUMN IF NOT EXISTS cordis_url text;
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_hrv_prj_grant_code 
            ON harvest.projects (code, grantnr);
        """)
    conn.commit()
    print("✓ harvest.projects table and indexes verified.")

def copy_base_projects_from_testing(conn, host, port, user, password, dry_run=False):
    """Optionally sync existing base projects from msp-testing.harvest.projects."""
    print("\n[Optional Sync] Checking existing base projects in msp-testing.harvest.projects...")
    try:
        test_conn = psycopg2.connect(
            host=host,
            port=port,
            dbname="msp-testing",
            user=user,
            password=password
        )
        with test_conn.cursor() as test_cur:
            test_cur.execute("SELECT code, title, funding, website, grantnr, source FROM harvest.projects;")
            rows = test_cur.fetchall()
        test_conn.close()

        print(f"  Found {len(rows)} base projects in msp-testing.harvest.projects.")
        if rows:
            with conn.cursor() as cur:
                execute_values(cur, """
                    INSERT INTO harvest.projects (code, title, funding, website, grantnr, source)
                    VALUES %s
                    ON CONFLICT (code, grantnr) DO NOTHING;
                """, rows, page_size=200)
            if not dry_run:
                conn.commit()
            print(f"  ✓ Synced {len(rows)} base projects into msp-kh-dev.harvest.projects.")
    except Exception as e:
        print(f"  ⚠ Notice: Could not sync from msp-testing: {e}")

def main():
    parser = argparse.ArgumentParser(description="Ingest missing EU CAP projects into harvest.projects.")
    parser.add_argument("--json", default=DEFAULT_JSON_PATH, help="Path to eucap_projects_not_in_msp_testing.json")
    parser.add_argument("--dbname", default=DEFAULT_DBNAME, help="Target DB name (default: msp-kh-dev)")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Target DB host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Target DB port")
    parser.add_argument("--user", default=DEFAULT_USER, help="Target DB user")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Target DB password")
    parser.add_argument("--copy-testing-base", action="store_true", help="Also sync the 341 base projects from msp-testing")
    parser.add_argument("--dry-run", action="store_true", help="Run without committing changes")
    args = parser.parse_args()

    print("=" * 60)
    print("INGEST MISSING EU CAP PROJECTS INTO HARVEST SCHEMA")
    print(f"Target DB:   {args.dbname} on {args.host}:{args.port}")
    print(f"Target Table: harvest.projects")
    print(f"Input JSON:  {args.json}")
    print(f"Mode:        {'DRY-RUN (No changes will be saved)' if args.dry_run else 'EXECUTE (Committing to DB)'}")
    print("=" * 60)

    if not os.path.exists(args.json):
        print(f"Error: JSON file not found at {args.json}")
        sys.exit(1)

    with open(args.json, "r", encoding="utf-8") as f:
        projects = json.load(f)

    print(f"Loaded {len(projects)} projects from JSON file.")

    # Prepare rows and deduplicate within batch to prevent CardinalityViolation
    unique_projects = {}
    dup_count = 0

    for p in projects:
        code = (p.get("acronym") or "").strip()
        grantnr = str(p.get("grant_number") or "").strip()
        title = (p.get("title") or "").strip()
        funding = (p.get("funding_source") or "").strip()
        website = (p.get("official_website") or p.get("url") or "").strip()
        source = "EU CAP Network"
        keywords = p.get("keywords") or []
        description = (p.get("description") or "").strip()
        cordis_url = (p.get("cordis_url") or "").strip()

        if not code or not grantnr:
            print(f"  ⚠ Skipping project due to missing code or grantnr: {title}")
            continue

        key = (code, grantnr)
        if key in unique_projects:
            dup_count += 1
            existing = unique_projects[key]
            # Merge keywords and keep longer description
            merged_kw = list(dict.fromkeys(existing[6] + keywords))
            best_desc = description if len(description) > len(existing[7]) else existing[7]
            best_web = website if len(website) > len(existing[3]) else existing[3]
            unique_projects[key] = (
                code,
                title,
                funding,
                best_web,
                grantnr,
                source,
                merged_kw,
                best_desc,
                cordis_url or existing[8]
            )
        else:
            unique_projects[key] = (
                code,
                title,
                funding,
                website,
                grantnr,
                source,
                keywords,
                description,
                cordis_url
            )

    row_tuples = list(unique_projects.values())
    print(f"Prepared {len(row_tuples)} unique rows for insertion ({dup_count} duplicate pairs merged).")

    # Connect to DB
    conn = get_db_connection(args.host, args.port, args.dbname, args.user, args.password)

    try:
        # Step 1: Ensure table exists
        ensure_harvest_table(conn)

        # Step 2: Optionally sync base from msp-testing
        if args.copy_testing_base:
            copy_base_projects_from_testing(conn, args.host, args.port, args.user, args.password, args.dry_run)

        # Step 3: Insert EU CAP missing projects
        upsert_sql = """
            INSERT INTO harvest.projects (
                code, title, funding, website, grantnr, source, keywords, description, cordis_url
            ) VALUES %s
            ON CONFLICT (code, grantnr) DO UPDATE SET
                title = EXCLUDED.title,
                funding = EXCLUDED.funding,
                website = EXCLUDED.website,
                source = EXCLUDED.source,
                keywords = EXCLUDED.keywords,
                description = EXCLUDED.description,
                cordis_url = EXCLUDED.cordis_url;
        """

        with conn.cursor() as cur:
            execute_values(cur, upsert_sql, row_tuples, page_size=200)

            # Verification query
            cur.execute("SELECT count(*) FROM harvest.projects;")
            total_in_db = cur.fetchone()[0]

            cur.execute("""
                SELECT count(*) 
                FROM harvest.projects 
                WHERE source = 'EU CAP Network';
            """)
            eucap_in_db = cur.fetchone()[0]

            cur.execute("""
                SELECT code, grantnr, title, website, array_length(keywords, 1)
                FROM harvest.projects
                WHERE source = 'EU CAP Network'
                LIMIT 3;
            """)
            samples = cur.fetchall()

        if args.dry_run:
            conn.rollback()
            print("\n[DRY-RUN] Verification successful. Transaction rolled back as requested.")
        else:
            conn.commit()
            print("\n✓ SUCCESS: Successfully committed to database!")

        print("\n" + "=" * 60)
        print("DATABASE SUMMARY (harvest.projects):")
        print(f"Total projects in harvest.projects:              {total_in_db}")
        print(f"EU CAP Network projects in harvest.projects:     {eucap_in_db}")
        print("\nSample records inserted:")
        for s in samples:
            print(f"  • [{s[0]}] Grant: {s[1]} | Keywords: {s[4]} | Title: {s[2][:50]}...")
        print("=" * 60)

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error during insertion: {e}")
        raise e
    finally:
        conn.close()

if __name__ == "__main__":
    main()
