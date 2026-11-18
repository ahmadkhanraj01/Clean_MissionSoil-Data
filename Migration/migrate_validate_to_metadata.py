#!/usr/bin/env python3
"""
migrate_validate_to_metadata.py
--------------------------------------------------------------------------------
Copies the entire `validate` schema (tables, foreign keys, relations, and data)
into the `metadata` schema in PostgreSQL database `msp-kh-dev`.

Safety guarantees:
- 100% READ-ONLY on `validate` schema. Nothing in `validate` is modified or deleted.
- Skips temporary backup tables (`validate.records_backup_*`).
- Repoints all 15 foreign keys strictly to `metadata.*`.
- Inserts data in topological dependency order to avoid foreign key violations.
- Performs automated row count and orphan validation post-migration.
--------------------------------------------------------------------------------
"""

# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config  # noqa: E402,F401  (loads .env)
# --------------------------------------------------------------------------------------------
import os
import sys
import subprocess
import re
import psycopg2
from dotenv import load_dotenv

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = str(_ROOT)
DEFAULT_ENV = os.path.join(PROJECT_ROOT, ".env")

TIER_1_PARENTS = [
    "sources",
    "organizations",
    "persons",
    "projects",
    "subjects",
    "alembic_version"
]

TIER_2_CORE = [
    "records"
]

TIER_3_JUNCTIONS_AND_CHILDREN = [
    "person_organization",
    "record_source",
    "record_person",
    "record_organization",
    "record_project",
    "record_subject",
    "distributions",
    "attributes",
    "recommendation_events"
]

ALL_MIGRATION_TABLES = TIER_1_PARENTS + TIER_2_CORE + TIER_3_JUNCTIONS_AND_CHILDREN


def load_db_config():
    # .env is loaded by common.db
    return db_config()


def generate_metadata_ddl(db_config):
    """Uses pg_dump to extract DDL for validate, repointing it to metadata."""
    print("\n[Step 1] Extracting DDL from 'validate' and repointing to 'metadata'...")
    env = os.environ.copy()
    env["PGPASSWORD"] = db_config["password"]

    cmd = [
        "pg_dump",
        "-h", str(db_config["host"]),
        "-p", str(db_config["port"]),
        "-U", str(db_config["user"]),
        "-d", str(db_config["dbname"]),
        "--schema=validate",
        "--schema-only",
        "--no-owner",
        "--no-privileges",
        "--exclude-table=validate.records_backup_*"
    ]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
    sql = res.stdout

    # Strip psql backslash commands (e.g. \restrict), create schema, and repoint validate to metadata
    clean_lines = [line for line in sql.splitlines() if not line.strip().startswith("\\")]
    sql = "\n".join(clean_lines)
    sql = re.sub(r"CREATE SCHEMA validate;\n?", "", sql)
    sql = re.sub(r"\bvalidate\b", "metadata", sql)
    return sql


def main():
    print("=" * 80)
    print("  MISSION SOIL: MIGRATE 'validate' SCHEMA TO 'metadata' SCHEMA")
    print("=" * 80)
    db_config = load_db_config()
    print(f"Target Database : {db_config['dbname']} ({db_config['host']}:{db_config['port']})")
    print(f"Source Schema   : validate (READ-ONLY)")
    print(f"Target Schema   : metadata")
    print(f"Total Tables    : {len(ALL_MIGRATION_TABLES)} production tables")

    # 1. Generate repointed DDL
    ddl_sql = generate_metadata_ddl(db_config)
    print(f"✓ Generated DDL for metadata schema ({len(ddl_sql.splitlines())} lines).")

    # 2. Connect to Postgres
    conn = psycopg2.connect(**db_config)
    conn.autocommit = True
    cur = conn.cursor()

    try:
        # Ensure schema exists
        cur.execute("CREATE SCHEMA IF NOT EXISTS metadata;")

        # Check existing tables in metadata
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'metadata';
        """)
        existing_meta_tables = [r[0] for r in cur.fetchall()]
        if existing_meta_tables:
            print(f"\n[Notice] 'metadata' already has {len(existing_meta_tables)} tables. Cleaning first...")
            cur.execute("DROP SCHEMA metadata CASCADE; CREATE SCHEMA metadata;")
            print("✓ Fresh 'metadata' schema prepared.")

        # 3. Create Tables and Constraints
        print("\n[Step 2] Executing DDL in 'metadata' schema (creating 16 tables & 15 FKs)...")
        cur.execute(ddl_sql)
        print("✓ All tables, primary keys, indexes, and foreign keys created successfully in 'metadata'!")

        # 4. Copy Data in Topological Dependency Order
        print("\n[Step 3] Copying data in topological order (Parent -> Core -> Junctions)...")
        
        # Tier 1: Independent Parent Tables
        print("\n--- Tier 1: Independent Parent Entities ---")
        for table in TIER_1_PARENTS:
            cur.execute(f"INSERT INTO metadata.{table} SELECT * FROM validate.{table};")
            cur.execute(f"SELECT COUNT(*) FROM metadata.{table};")
            cnt = cur.fetchone()[0]
            print(f"  • metadata.{table:<25}: {cnt:,} rows copied")

        # Tier 2: Core Records
        print("\n--- Tier 2: Core Records ---")
        for table in TIER_2_CORE:
            cur.execute(f"INSERT INTO metadata.{table} SELECT * FROM validate.{table};")
            cur.execute(f"SELECT COUNT(*) FROM metadata.{table};")
            cnt = cur.fetchone()[0]
            print(f"  • metadata.{table:<25}: {cnt:,} rows copied")

        # Tier 3: Junctions and Child Tables
        print("\n--- Tier 3: Relational Junctions & Child Tables ---")
        for table in TIER_3_JUNCTIONS_AND_CHILDREN:
            cur.execute(f"INSERT INTO metadata.{table} SELECT * FROM validate.{table};")
            cur.execute(f"SELECT COUNT(*) FROM metadata.{table};")
            cnt = cur.fetchone()[0]
            print(f"  • metadata.{table:<25}: {cnt:,} rows copied")

        # 5. Verification & Parity Audit
        print("\n" + "=" * 80)
        print("  VERIFICATION AUDIT: 'validate' vs 'metadata'")
        print("=" * 80)
        print(f"{'Table Name':<30} | {'validate Count':<16} | {'metadata Count':<16} | {'Status'}")
        print("-" * 80)

        all_matched = True
        for table in ALL_MIGRATION_TABLES:
            cur.execute(f"SELECT COUNT(*) FROM validate.{table};")
            v_cnt = cur.fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM metadata.{table};")
            m_cnt = cur.fetchone()[0]

            status = "✓ MATCH" if v_cnt == m_cnt else "✗ MISMATCH"
            if v_cnt != m_cnt:
                all_matched = False
            print(f"{table:<30} | {v_cnt:>14,} | {m_cnt:>14,} | {status}")

        # Orphan Foreign Key Check
        print("\n--- Foreign Key Integrity Check in 'metadata' ---")
        orphan_checks = [
            ("record_person -> records", "SELECT COUNT(*) FROM metadata.record_person rp WHERE NOT EXISTS (SELECT 1 FROM metadata.records r WHERE r.id = rp.record_id)"),
            ("record_source -> records", "SELECT COUNT(*) FROM metadata.record_source rs WHERE NOT EXISTS (SELECT 1 FROM metadata.records r WHERE r.id = rs.record_id)"),
            ("record_organization -> records", "SELECT COUNT(*) FROM metadata.record_organization ro WHERE NOT EXISTS (SELECT 1 FROM metadata.records r WHERE r.id = ro.record_id)"),
            ("record_project -> records", "SELECT COUNT(*) FROM metadata.record_project rp WHERE NOT EXISTS (SELECT 1 FROM metadata.records r WHERE r.id = rp.record_id)"),
            ("distributions -> records", "SELECT COUNT(*) FROM metadata.distributions d WHERE NOT EXISTS (SELECT 1 FROM metadata.records r WHERE r.id = d.record_id)"),
            ("attributes -> records", "SELECT COUNT(*) FROM metadata.attributes a WHERE NOT EXISTS (SELECT 1 FROM metadata.records r WHERE r.id = a.record_id)"),
        ]

        orphans_found = False
        for name, query in orphan_checks:
            cur.execute(query)
            orph_count = cur.fetchone()[0]
            if orph_count == 0:
                print(f"  ✓ {name:<35}: 0 orphans (Perfect integrity)")
            else:
                print(f"  ✗ {name:<35}: {orph_count} orphans detected!")
                orphans_found = True

        print("=" * 80)
        if all_matched and not orphans_found:
            print("✓ MIGRATION 100% COMPLETE & VERIFIED SUCCESSFULLY!")
            print("  All 16 tables, relations, and data have been copied to 'metadata'.")
        else:
            print("⚠ Migration finished with warnings. Please inspect counts above.")
        print("=" * 80)

    except Exception as exc:
        print(f"\n[FATAL ERROR] Migration failed: {exc}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
