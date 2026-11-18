#!/usr/bin/env python3
"""
backfill_metadata_organizations.py
----------------------------------
Backfills `metadata.organization` and `metadata.contact_in_record` in `msp-testing`
by parsing the rich partner organisation data from CORDIS YAML in `harvest.items`.

Background:
  Due to a key mismatch in the original pipeline ('contacts' vs 'contact'),
  the harmonization step skipped organizations for CORDIS projects.
  This script safely backfills the missing organizations and contact linkages
  directly into `msp-testing.metadata`.

Usage:
  python src/scripts/backfill_metadata_organizations.py
"""

import os
import sys
import yaml
import json
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# Load .env from the repo root (two levels up from src/scripts/)
_env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(os.path.abspath(_env_path))

def _require_env(name: str) -> str:
    """Return env var value or exit with a clear error if it is missing."""
    value = os.getenv(name)
    if not value:
        print(f"[ERROR] Required environment variable '{name}' is not set. "
              f"Make sure .env is present in the project root.", file=sys.stderr)
        sys.exit(1)
    return value

DB_HOST = _require_env("DB_HOST")
DB_PORT = _require_env("DB_PORT")
DB_NAME = _require_env("DB_NAME")
DB_USER = _require_env("DB_USER")
DB_PASS = _require_env("DB_PASSWORD")

def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )

def main():
    print(f"Connecting to {DB_NAME} at {DB_HOST}:{DB_PORT} as {DB_USER}...")
    conn = get_connection()
    cur = conn.cursor()

    # 1. Fetch CORDIS items that contain YAML with contacts
    print("\n1. Fetching CORDIS projects from harvest.items...")
    cur.execute("""
        SELECT identifier, resultobject, source 
        FROM harvest.items 
        WHERE source = 'CORDIS' 
          AND resulttype = 'yaml'
          AND resultobject IS NOT NULL;
    """)
    rows = cur.fetchall()
    print(f"   Found {len(rows)} CORDIS items with YAML payloads.")

    # 2. Existing organizations cache in metadata.organization
    cur.execute("SELECT lower(name), id FROM metadata.organization WHERE name IS NOT NULL;")
    org_cache = {name: oid for name, oid in cur.fetchall()}
    print(f"   Existing organizations in metadata.organization: {len(org_cache)}")

    # 3. Parse and extract organizations from YAML
    new_orgs = []
    contact_links = []  # (record_id, org_id, role)

    for record_id, raw_yaml, source in rows:
        try:
            mcf = yaml.safe_load(raw_yaml)
        except Exception as e:
            continue

        if not isinstance(mcf, dict):
            continue

        # Look for both 'contacts' (what project-metadata.py wrote) and 'contact'
        contacts = mcf.get('contacts') or mcf.get('contact') or {}
        if not isinstance(contacts, dict):
            continue

        for cid, c in contacts.items():
            if not isinstance(c, dict):
                continue

            org_name = c.get('organization')
            if not org_name or not org_name.strip():
                continue

            org_name = org_name.strip()
            org_key = org_name.lower()
            role = (c.get('role') or 'contributor').lower()

            if org_key in org_cache:
                org_id = org_cache[org_key]
                contact_links.append((record_id, org_id, role))
            else:
                # Prepare for insert
                address = c.get('address')
                postalcode = c.get('postalcode')
                city = c.get('city')
                country = c.get('country')
                url = c.get('url')

                cur.execute("""
                    INSERT INTO metadata.organization (name, address, postalcode, city, country, url)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (org_name, address, postalcode, city, country, url))
                row = cur.fetchone()
                if row is None:
                    # Insert was silently skipped (e.g. conflict); fetch the existing id
                    cur.execute(
                        "SELECT id FROM metadata.organization WHERE name = %s;",
                        (org_name,)
                    )
                    row = cur.fetchone()
                if row is None:
                    print(f"   WARNING: Could not find or insert organization '{org_name}', skipping.")
                    continue
                org_id = row[0]
                org_cache[org_key] = org_id
                contact_links.append((record_id, org_id, role))

    conn.commit()
    print(f"   Total organizations now in metadata.organization: {len(org_cache)}")

    # 4. Insert contact links into metadata.contact_in_record
    print(f"\n2. Inserting contact links into metadata.contact_in_record...")
    if contact_links:
        # Check existing records to satisfy FK
        cur.execute("SELECT identifier FROM metadata.records;")
        existing_records = set(r[0] for r in cur.fetchall())

        # Check existing links in metadata.contact_in_record to avoid duplicates
        cur.execute("SELECT record_id, fk_organization, role FROM metadata.contact_in_record WHERE fk_organization IS NOT NULL;")
        existing_links = set((r[0], r[1], (r[2] or '').lower()) for r in cur.fetchall())

        valid_links = []
        seen_batch = set()
        for rid, oid, role in contact_links:
            key = (rid, oid, role.lower())
            if rid in existing_records and key not in existing_links and key not in seen_batch:
                seen_batch.add(key)
                valid_links.append((rid, oid, None, role))

        print(f"   New valid links to insert: {len(valid_links)}")

        if valid_links:
            execute_values(cur, """
                INSERT INTO metadata.contact_in_record (record_id, fk_organization, fk_person, role)
                VALUES %s;
            """, valid_links, page_size=1000)
            conn.commit()
            print(f"   Successfully inserted {len(valid_links)} contact links.")

    # 5. Verification
    # Ensure no lingering failed transaction blocks the verification queries.
    conn.rollback()
    print("\n================== VERIFICATION REPORT ==================")
    cur.execute("SELECT COUNT(*) FROM metadata.organization;")
    row = cur.fetchone()
    total_orgs = row[0] if row is not None else "N/A"
    cur.execute("SELECT COUNT(*) FROM metadata.contact_in_record WHERE fk_organization IS NOT NULL;")
    row = cur.fetchone()
    total_org_links = row[0] if row is not None else "N/A"

    print(f"  Total organizations in metadata.organization: {total_orgs}")
    print(f"  Total org links in metadata.contact_in_record: {total_org_links}")
    print("=========================================================\n")

    cur.close()
    conn.close()
    print("✓ Backfill completed successfully!")

if __name__ == "__main__":
    main()
