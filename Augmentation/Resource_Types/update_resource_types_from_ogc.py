#!/usr/bin/env python3
"""
update_resource_types_from_ogc.py
--------------------------------------------------------------------------------
Updates the `resource_type` field in `validate.records` (database: msp-kh-dev)
for records where OGC was determined to be the correct resource type by official
DOI registries (Crossref / DataCite).

Key characteristics:
- Matches records strictly on `identifier` (1-to-1 unique match).
- Creates an automatic snapshot backup table in PostgreSQL before modifying data.
- Supports --dry-run mode for zero-risk pre-execution verification.
- Displays comprehensive pre- and post-update distribution statistics.
--------------------------------------------------------------------------------
"""

# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config  # noqa: E402,F401  (loads .env)
# --------------------------------------------------------------------------------------------
import argparse
import os
import sys
from datetime import datetime
import pandas as pd
import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv

# Base paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = str(_ROOT)
DEFAULT_ENV = os.path.join(PROJECT_ROOT, ".env")
DEFAULT_CSV = os.path.join(PROJECT_ROOT, "data", "msp_type_mismatches_with_correct_type.csv")

def parse_args():
    parser = argparse.ArgumentParser(
        description="Update resource_type in validate.records using OGC/DOI registry resolutions."
    )
    parser.add_argument(
        "--csv",
        default=DEFAULT_CSV,
        help=f"Path to CSV with mismatch resolutions (default: {DEFAULT_CSV})"
    )
    parser.add_argument(
        "--schema",
        default="validate",
        help="Database schema name (default: validate)"
    )
    parser.add_argument(
        "--dbname",
        default=None,
        help="Target database name (default: DB_NAME from .env)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute and COMMIT changes to the database. If omitted, runs in DRY-RUN mode."
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating an automatic backup snapshot table."
    )
    return parser.parse_args()


def load_db_config(dbname):
    # .env is loaded by common.db
    return db_config(dbname)


def create_backup_table(cur, schema):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_table = f"records_backup_ogc_types_{timestamp}"
    full_backup_name = f"{schema}.{backup_table}"
    print(f"\n[Safety Backup] Creating snapshot table: {full_backup_name}...")
    cur.execute(f"CREATE TABLE {full_backup_name} AS SELECT * FROM {schema}.records;")
    cur.execute(f"SELECT COUNT(*) FROM {full_backup_name};")
    backup_count = cur.fetchone()[0]
    print(f"✓ Backup created successfully ({backup_count:,} total records backed up).")
    return full_backup_name


def main():
    args = parse_args()

    print("=" * 80)
    print("  MISSION SOIL: OGC RESOURCE TYPE UPDATE IN 'validate.records'")
    print("=" * 80)
    print(f"Mode          : {'[LIVE COMMIT]' if args.execute else '[DRY RUN - NO CHANGES COMMITTED]'}")
    print(f"Target Schema : {args.schema}")
    print(f"Target DB     : {args.dbname}")
    print(f"Input CSV     : {args.csv}")

    # 1. Load and validate CSV
    if not os.path.exists(args.csv):
        print(f"\n[ERROR] CSV file not found at: {args.csv}")
        sys.exit(1)

    print("\n[Step 1] Loading and filtering CSV resolution data...")
    df = pd.read_csv(args.csv)
    
    # Filter for records where OGC was determined to be the correct side
    ogc_df = df[df["correct_side"] == "ogc"].copy()
    total_candidates = len(ogc_df)
    print(f"• Total rows in CSV                 : {len(df):,}")
    print(f"• Rows where correct_side == 'ogc' : {total_candidates:,}")

    if total_candidates == 0:
        print("[INFO] No records with correct_side == 'ogc' found to update.")
        return

    # Check for unique identifiers
    unique_ids = ogc_df["identifier"].nunique()
    if unique_ids != total_candidates:
        print(f"[WARNING] Duplicate identifiers detected in CSV ({unique_ids} unique out of {total_candidates}).")
        # Deduplicate taking the first occurrence
        ogc_df = ogc_df.drop_duplicates(subset=["identifier"], keep="first")
        total_candidates = len(ogc_df)
        print(f"• Proceeding with {total_candidates:,} unique identifier entries.")

    print("\nPlanned type updates from OGC resolution:")
    for type_name, count in ogc_df["correct_type"].value_counts().items():
        print(f"  • {type_name:<25}: {count:,} records")

    # 2. Connect to Database
    db_config = load_db_config(args.dbname)
    print(f"\n[Step 2] Connecting to PostgreSQL ({db_config['host']}:{db_config['port']}/{db_config['dbname']})...")
    conn = psycopg2.connect(**db_config)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # Set search path
        cur.execute(f"SET search_path TO {args.schema}, public;")

        # Verify target table exists
        cur.execute(f"""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_schema = '{args.schema}' AND table_name = 'records';
        """)
        if cur.fetchone()[0] == 0:
            raise RuntimeError(f"Table '{args.schema}.records' does not exist in database '{args.dbname}'!")

        # 3. Create backup if executing
        if args.execute and not args.no_backup:
            create_backup_table(cur, args.schema)

        # 4. Analyze Pre-update DB State
        print(f"\n[Step 3] Querying pre-update state in '{args.schema}.records'...")
        cur.execute(f"""
            SELECT COUNT(*) 
            FROM {args.schema}.records 
            WHERE identifier IN %s;
        """, (tuple(ogc_df["identifier"]),))
        matching_in_db = cur.fetchone()[0]
        print(f"• Matching identifiers found in DB: {matching_in_db:,} / {total_candidates:,}")

        cur.execute(f"""
            SELECT resource_type, COUNT(*) 
            FROM {args.schema}.records 
            WHERE identifier IN %s 
            GROUP BY resource_type 
            ORDER BY COUNT(*) DESC;
        """, (tuple(ogc_df["identifier"]),))
        print("• Current resource_type distribution in DB for these records:")
        for rtype, count in cur.fetchall():
            print(f"    - {str(rtype):<25}: {count:,}")

        # 5. Prepare batch update payload: (new_resource_type, identifier)
        update_batch = list(zip(ogc_df["correct_type"], ogc_df["identifier"]))

        print(f"\n[Step 4] Executing UPDATE for {len(update_batch):,} records...")
        update_sql = f"""
            UPDATE {args.schema}.records 
            SET resource_type = %s,
                updated_at = NOW() 
            WHERE identifier = %s;
        """
        execute_batch(cur, update_sql, update_batch, page_size=1000)

        # 6. Verify Post-update distribution
        cur.execute(f"""
            SELECT resource_type, COUNT(*) 
            FROM {args.schema}.records 
            WHERE identifier IN %s 
            GROUP BY resource_type 
            ORDER BY COUNT(*) DESC;
        """, (tuple(ogc_df["identifier"]),))
        print("\n• New resource_type distribution in DB after update:")
        for rtype, count in cur.fetchall():
            print(f"    - {str(rtype):<25}: {count:,}")

        # 7. Commit or Rollback
        print("\n" + "=" * 80)
        if args.execute:
            conn.commit()
            print("✓ SUCCESS: Changes committed to database!")
            print(f"✓ Total records updated: {len(update_batch):,}")
        else:
            conn.rollback()
            print("✓ DRY RUN COMPLETE: Transaction was intentionally ROLLED BACK.")
            print("  No changes were saved to the database.")
            print("  To apply changes permanently, run with the `--execute` flag:")
            print(f"    .venv/bin/python {os.path.relpath(__file__, os.getcwd())} --execute")
        print("=" * 80)

    except Exception as exc:
        conn.rollback()
        print(f"\n[FATAL ERROR] An exception occurred during execution. Rolled back.\nDetails: {exc}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
