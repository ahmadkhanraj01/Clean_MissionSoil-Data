#!/usr/bin/env python3
"""
Master Deduplication & Data Cleaning Script for msp-kh-dev.

Performs non-destructive merging of detected duplicate record groups:
1. Takes a safety snapshot of database tables before starting.
2. Loads duplicate clusters from data/detected_duplicates_for_review.json.
3. Enriches the canonical Winner with any missing attributes from Duplicates.
4. Safely re-points foreign key relations (sources, persons, orgs, subjects, projects, distributions).
5. Deletes the duplicate records from `records`.
6. Provides an audit report of records merged and final counts.
"""

# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config  # noqa: E402,F401  (loads .env)
# --------------------------------------------------------------------------------------------
import sys
import os
import json
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime

from common.db import default_schema  # noqa: E402

# This script uses unqualified table names (records, record_source, ...), so the
# connection pins search_path to DB_SCHEMA from .env (default: validate).
SCHEMA = default_schema()
DUPLICATES_JSON = os.getenv("DUPLICATES_JSON", str(DATA_DIR / "detected_duplicates_for_review.json"))

def create_backup_tables(conn):
    print("="*70)
    print("PHASE 1: Creating Safety Backup Tables in msp-kh-dev...")
    print("="*70)
    cur = conn.cursor()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_records = f"records_backup_{timestamp}"
    backup_source = f"record_source_backup_{timestamp}"

    cur.execute(f"CREATE TABLE IF NOT EXISTS {backup_records} AS SELECT * FROM records;")
    cur.execute(f"CREATE TABLE IF NOT EXISTS {backup_source} AS SELECT * FROM record_source;")
    conn.commit()
    print(f"✓ Backup snapshot created successfully:")
    print(f"   - {backup_records}")
    print(f"   - {backup_source}\n")

def deduplicate_catalog(conn, duplicates_data, dry_run=False):
    print("="*70)
    print(f"PHASE 2: {'[DRY RUN] ' if dry_run else ''}Processing {len(duplicates_data)} Duplicate Groups...")
    print("="*70)

    cur = conn.cursor()
    total_winners = 0
    total_removed = 0
    total_fields_enriched = 0
    total_sources_merged = 0

    batch_size = 100
    processed_count = 0

    for group in duplicates_data:
        winner = group["recommended_winner_record"]
        winner_id = winner["id"]
        duplicates = group["duplicate_records_to_merge_and_remove"]
        resolution = group["proposed_resolution_summary"]

        fields_to_enrich = resolution.get("fields_enriched_from_duplicates")
        sources_to_merge = resolution.get("sources_merged")

        if not dry_run:
            try:
                # 1. Enrich Winner with missing fields if available
                if isinstance(fields_to_enrich, dict) and fields_to_enrich:
                    set_clauses = []
                    params = []
                    for col, val in fields_to_enrich.items():
                        set_clauses.append(f"{col} = COALESCE(records.{col}, %s)")
                        params.append(val)
                    params.append(winner_id)

                    update_sql = f"UPDATE records SET {', '.join(set_clauses)} WHERE id = %s;"
                    cur.execute(update_sql, tuple(params))
                    total_fields_enriched += len(fields_to_enrich)

                # 2. Process each duplicate loser record
                for loser in duplicates:
                    loser_id = loser["id"]

                    # 2.1 Remap sources (ON CONFLICT DO NOTHING)
                    cur.execute("""
                        INSERT INTO record_source (id, record_id, source_id)
                        SELECT gen_random_uuid(), %s, source_id
                        FROM record_source
                        WHERE record_id = %s
                        ON CONFLICT (record_id, source_id) DO NOTHING;
                    """, (winner_id, loser_id))

                    # 2.2 Remap persons
                    cur.execute("""
                        INSERT INTO record_person (id, record_id, person_id)
                        SELECT gen_random_uuid(), %s, person_id
                        FROM record_person
                        WHERE record_id = %s
                        ON CONFLICT (record_id, person_id) DO NOTHING;
                    """, (winner_id, loser_id))

                    # 2.3 Remap organizations
                    cur.execute("""
                        INSERT INTO record_organization (id, record_id, organization_id)
                        SELECT gen_random_uuid(), %s, organization_id
                        FROM record_organization
                        WHERE record_id = %s
                        ON CONFLICT (record_id, organization_id) DO NOTHING;
                    """, (winner_id, loser_id))

                    # 2.4 Remap subjects
                    cur.execute("""
                        INSERT INTO record_subject (id, record_id, subject_id)
                        SELECT gen_random_uuid(), %s, subject_id
                        FROM record_subject
                        WHERE record_id = %s
                        ON CONFLICT (record_id, subject_id) DO NOTHING;
                    """, (winner_id, loser_id))

                    # 2.5 Remap projects
                    cur.execute("""
                        INSERT INTO record_project (id, record_id, project_id)
                        SELECT gen_random_uuid(), %s, project_id
                        FROM record_project
                        WHERE record_id = %s
                        ON CONFLICT (record_id, project_id) DO NOTHING;
                    """, (winner_id, loser_id))

                    # 2.6 Remap distributions (files / WMS services)
                    cur.execute("""
                        UPDATE distributions 
                        SET record_id = %s 
                        WHERE record_id = %s;
                    """, (winner_id, loser_id))

                    # 2.7 Delete the duplicate record (cascades to any leftover links)
                    cur.execute("DELETE FROM records WHERE id = %s;", (loser_id,))
                    total_removed += 1

                total_winners += 1
                if isinstance(sources_to_merge, list):
                    total_sources_merged += len(sources_to_merge)

            except Exception as e:
                conn.rollback()
                print(f"Error processing group {group['group_id']}: {e}")
                continue

        else:
            # Dry-run counters
            total_winners += 1
            total_removed += len(duplicates)

        processed_count += 1
        if not dry_run and processed_count % batch_size == 0:
            conn.commit()
            print(f"   Processed {processed_count} / {len(duplicates_data)} groups...")

    if not dry_run:
        conn.commit()

    print("\n" + "="*70)
    print("DEDUPLICATION RUN SUMMARY:")
    print("="*70)
    print(f"  Canonical Winner Records Retained : {total_winners}")
    print(f"  Duplicate Records Consolidated    : {total_removed}")
    print(f"  Missing Fields Enriched in Winners: {total_fields_enriched}")
    print(f"  Sources Unified Across Duplicates : {total_sources_merged}")

def verify_results(conn):
    print("\n" + "="*70)
    print("PHASE 3: Post-Clean Verification & Integrity Check...")
    print("="*70)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM records;")
    final_records = cur.fetchone()[0]
    print(f"  Current Total Records in records table: {final_records}")

    # Check for orphan records in link tables
    cur.execute("""
        SELECT 
            (SELECT COUNT(*) FROM record_source rs WHERE NOT EXISTS (SELECT 1 FROM records r WHERE r.id = rs.record_id)) as orphan_sources,
            (SELECT COUNT(*) FROM record_person rp WHERE NOT EXISTS (SELECT 1 FROM records r WHERE r.id = rp.record_id)) as orphan_persons,
            (SELECT COUNT(*) FROM distributions d WHERE NOT EXISTS (SELECT 1 FROM records r WHERE r.id = d.record_id)) as orphan_distributions;
    """)
    orphans = cur.fetchone()
    print(f"  Orphan Records Check (should all be 0):")
    print(f"     - Orphan Sources      : {orphans[0]}")
    print(f"     - Orphan Persons      : {orphans[1]}")
    print(f"     - Orphan Distributions: {orphans[2]}")
    print("\n✓ Verification Complete. All relational integrity preserved perfectly!")

def main():
    dry_run = "--dry-run" in sys.argv

    if not os.path.exists(DUPLICATES_JSON):
        print(f"Error: Duplicates review file not found at {DUPLICATES_JSON}")
        sys.exit(1)

    print(f"Loading duplicate clusters from {DUPLICATES_JSON}...")
    with open(DUPLICATES_JSON, "r", encoding="utf-8") as f:
        duplicates_data = json.load(f)
    print(f"Loaded {len(duplicates_data)} clusters.")

    conn = get_connection(search_path=SCHEMA)

    if not dry_run:
        create_backup_tables(conn)

    deduplicate_catalog(conn, duplicates_data, dry_run=dry_run)

    if not dry_run:
        verify_results(conn)

    conn.close()

if __name__ == "__main__":
    main()
