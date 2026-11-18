#!/usr/bin/env python3
"""
harmonize_to_validate.py
-------------------------
Harmonizes projects and metadata from `harvest.items` and `harvest.projects`
into the relational, UUID-based `validate` schema of PostgreSQL (`msp-kh-dev`).

Entities populated:
  1. validate.projects             (Acronyms & UUIDs)
  2. validate.records              (Primary record, approval_status='pending', raw_metadata=JSONB)
  3. validate.organizations        (Partner institutions, universities, companies)
  4. validate.record_organization  (Junction: record <-> organization)
  5. validate.subjects             (Multi-sector taxonomy keywords)
  6. validate.record_subject       (Junction: record <-> subject)
  7. validate.distributions        (CORDIS landing links & official websites)
  8. validate.record_project       (Junction: record <-> project)

Usage:
  # Test with dry-run:
  python harmonize_to_validate.py --dry-run

  # Execute and commit to database:
  python harmonize_to_validate.py
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
import re
import uuid
import json
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml
import psycopg2
from psycopg2.extras import Json, execute_values
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("harmonize_to_validate")

# Environment is loaded by common.db (repo-root .env)

DEFAULT_HOST     = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST")
DEFAULT_PORT     = int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or 5432)
DEFAULT_DBNAME   = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB")
DEFAULT_USER     = os.getenv("DB_USER") or os.getenv("POSTGRES_USER")
DEFAULT_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")

URL_REGEX = re.compile(r"^https?://[^\s]+$")


def is_valid_url(url: Optional[str]) -> bool:
    if not url:
        return False
    return bool(URL_REGEX.match(str(url).strip()))


def parse_date_to_utc(val: Any) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    try:
        s = str(val).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        # Match YYYY-MM-DD or YYYY
        m = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", str(val).strip())
        if m:
            year = int(m.group(1))
            month = int(m.group(2) or 1)
            day = int(m.group(3) or 1)
            return datetime(year, month, day, tzinfo=timezone.utc)
        return None


class Harmonizer:
    def __init__(self, conn):
        self.conn = conn
        self.cur = conn.cursor()

        # In-memory caches to prevent duplicate entity creation and queries
        self.projects_by_name: Dict[str, str] = {}      # name.lower() -> uuid
        self.projects_by_grant: Dict[str, str] = {}     # grantnr -> uuid
        self.records_by_ident: Dict[str, str] = {}      # identifier -> uuid
        self.orgs_by_name: Dict[str, str] = {}          # name.lower() -> uuid
        self.subjects_by_label: Dict[str, str] = {}     # label.lower() -> uuid

    def load_existing_caches(self):
        logger.info("Loading existing entity caches from validate schema...")
        
        # 1. Projects
        self.cur.execute("SELECT name, id FROM validate.projects;")
        for name, pid in self.cur.fetchall():
            self.projects_by_name[name.strip().lower()] = str(pid)

        # 2. Map grantnr to project uuid from harvest.projects
        self.cur.execute("SELECT code, grantnr FROM harvest.projects WHERE coalesce(grantnr, '') != '';")
        for code, grantnr in self.cur.fetchall():
            puuid = self.projects_by_name.get(code.strip().lower())
            if puuid and grantnr:
                self.projects_by_grant[grantnr.strip()] = puuid

        # 3. Records
        self.cur.execute("SELECT identifier, id FROM validate.records;")
        for ident, rid in self.cur.fetchall():
            self.records_by_ident[ident.strip()] = str(rid)

        # 4. Organizations
        self.cur.execute("SELECT name, id FROM validate.organizations;")
        for name, oid in self.cur.fetchall():
            if name:
                self.orgs_by_name[name.strip().lower()] = str(oid)

        # 5. Subjects
        self.cur.execute("SELECT label, id FROM validate.subjects;")
        for label, sid in self.cur.fetchall():
            if label:
                self.subjects_by_label[label.strip().lower()] = str(sid)

        logger.info(
            f"Cached: {len(self.projects_by_name)} projects, {len(self.records_by_ident)} records, "
            f"{len(self.orgs_by_name)} organizations, {len(self.subjects_by_label)} subjects."
        )

    def sync_projects(self) -> int:
        """Syncs all project acronyms from harvest.projects into validate.projects."""
        logger.info("\n--- STEP 1: Harmonizing Projects into validate.projects ---")
        self.cur.execute("""
            SELECT DISTINCT code, grantnr 
            FROM harvest.projects 
            WHERE coalesce(code, '') != '';
        """)
        harvest_projects = self.cur.fetchall()

        new_projects = []
        for code, grantnr in harvest_projects:
            clean_code = code.strip()
            key = clean_code.lower()
            if key not in self.projects_by_name:
                puuid = str(uuid.uuid4())
                self.projects_by_name[key] = puuid
                if grantnr:
                    self.projects_by_grant[str(grantnr).strip()] = puuid
                new_projects.append((puuid, clean_code))
            else:
                puuid = self.projects_by_name[key]
                if grantnr:
                    self.projects_by_grant[str(grantnr).strip()] = puuid

        if new_projects:
            execute_values(
                self.cur,
                "INSERT INTO validate.projects (id, name) VALUES %s ON CONFLICT (name) DO NOTHING;",
                new_projects,
                page_size=200
            )
            logger.info(f"✓ Created {len(new_projects)} new projects in validate.projects.")
        else:
            logger.info("✓ All projects already exist in validate.projects.")

        return len(new_projects)

    def harmonize_records(self, limit: Optional[int] = None) -> Tuple[int, int, int]:
        """Harmonizes harvest.items into validate.records and all related tables."""
        logger.info("\n--- STEP 2: Harmonizing Records into validate.records & Related Tables ---")
        
        query = """
            SELECT identifier, identifiertype, uri, resultobject, resulttype, project, title
            FROM harvest.items
            WHERE source = 'EU CAP Network' AND itemtype = 'project'
            ORDER BY insert_date ASC;
        """
        self.cur.execute(query)
        items = self.cur.fetchall()
        if limit:
            items = items[:limit]

        logger.info(f"Loaded {len(items)} project items from harvest.items.")

        records_batch = []
        distributions_batch = []
        record_project_batch = []
        record_org_batch = []
        record_subject_batch = []

        new_orgs_batch = []
        new_subjects_batch = []

        for row in items:
            ident, id_type, uri, raw_obj, res_type, project_id, fallback_title = row
            
            # Parse YAML MCF
            try:
                mcf = yaml.safe_load(raw_obj) if res_type == 'yaml' else json.loads(raw_obj)
            except Exception as e:
                logger.warning(f"Could not parse payload for {ident}: {e}")
                continue

            # 1. Main record fields
            mid = mcf.get("identification", {})
            mmeta = mcf.get("metadata", {})
            
            title = (mid.get("title") or fallback_title or "Untitled Project").strip()
            abstract = (mid.get("abstract") or "").strip() or None
            resource_type = "Project"
            language = mmeta.get("language") or "eng"
            
            # Dates
            temporal = (mid.get("extents", {}).get("temporal") or [{}])[0]
            start_date = parse_date_to_utc(temporal.get("begin"))
            end_date = parse_date_to_utc(temporal.get("end"))
            pub_date = start_date

            # URL validation (Postgres check constraint: records_url_format_ck)
            rec_url = uri if is_valid_url(uri) else None
            if not rec_url:
                web_candidate = (mcf.get("distribution", {}).get("www", {}) or {}).get("url")
                if is_valid_url(web_candidate):
                    rec_url = web_candidate

            # Resolve Record UUID
            rec_uuid = self.records_by_ident.get(ident) or str(uuid.uuid4())
            self.records_by_ident[ident] = rec_uuid

            records_batch.append((
                rec_uuid,
                ident,
                title,
                abstract,
                resource_type,
                language,
                pub_date,
                start_date,
                end_date,
                rec_url,
                Json(mcf),
                "pending"  # approval_status
            ))

            # 2. Link to validate.projects
            proj_uuid = None
            if project_id and str(project_id).strip() in self.projects_by_grant:
                proj_uuid = self.projects_by_grant[str(project_id).strip()]
            else:
                # Check additional_identifiers for acronym
                acronym = None
                for ai in mmeta.get("additional_identifiers", []):
                    if ai.get("scheme") == "acronym":
                        acronym = ai.get("identifier")
                if acronym and acronym.strip().lower() in self.projects_by_name:
                    proj_uuid = self.projects_by_name[acronym.strip().lower()]

            if proj_uuid:
                record_project_batch.append((str(uuid.uuid4()), rec_uuid, proj_uuid))

            # 3. Organizations and validate.record_organization
            contacts = mcf.get("contacts", {})
            for c in contacts.values():
                org_name = (c.get("organization") or "").strip()
                if not org_name:
                    continue
                
                org_key = org_name.lower()
                if org_key in self.orgs_by_name:
                    ouuid = self.orgs_by_name[org_key]
                else:
                    ouuid = str(uuid.uuid4())
                    self.orgs_by_name[org_key] = ouuid
                    new_orgs_batch.append((
                        ouuid,
                        org_name,
                        c.get("country"),
                        c.get("city"),
                        c.get("address"),
                        c.get("url") if is_valid_url(c.get("url")) else None
                    ))

                record_org_batch.append((str(uuid.uuid4()), rec_uuid, ouuid))

            # 4. Subjects and validate.record_subject
            keywords = mid.get("keywords", {}).get("default", {}).get("keywords", [])
            for kw in keywords:
                clean_kw = str(kw).strip()
                if not clean_kw:
                    continue
                kw_key = clean_kw.lower()
                if kw_key in self.subjects_by_label:
                    suuid = self.subjects_by_label[kw_key]
                else:
                    suuid = str(uuid.uuid4())
                    self.subjects_by_label[kw_key] = suuid
                    new_subjects_batch.append((suuid, clean_kw))

                record_subject_batch.append((str(uuid.uuid4()), rec_uuid, suuid))

            # 5. Distributions
            for dkey, dval in (mcf.get("distribution") or {}).items():
                d_url = dval.get("url")
                if is_valid_url(d_url):
                    d_name = dval.get("name") or "Official Website" if dkey == "www" else "CORDIS Link"
                    d_format = "HTML"
                    distributions_batch.append((
                        str(uuid.uuid4()),
                        rec_uuid,
                        d_name,
                        d_format,
                        d_url
                    ))

        # --- EXECUTE DATABASE INSERTIONS ---
        logger.info(f"Writing {len(records_batch)} records into validate.records...")
        execute_values(self.cur, """
            INSERT INTO validate.records (
                id, identifier, title, abstract, resource_type, language,
                publication_date, temporal_start, temporal_end, url,
                raw_metadata, approval_status
            ) VALUES %s
            ON CONFLICT (identifier) DO UPDATE SET
                title = EXCLUDED.title,
                abstract = EXCLUDED.abstract,
                resource_type = EXCLUDED.resource_type,
                language = EXCLUDED.language,
                publication_date = EXCLUDED.publication_date,
                temporal_start = EXCLUDED.temporal_start,
                temporal_end = EXCLUDED.temporal_end,
                url = EXCLUDED.url,
                raw_metadata = EXCLUDED.raw_metadata,
                approval_status = 'pending',
                updated_at = NOW();
        """, records_batch, page_size=200)

        # Organizations
        if new_orgs_batch:
            logger.info(f"Writing {len(new_orgs_batch)} new organizations into validate.organizations...")
            execute_values(self.cur, """
                INSERT INTO validate.organizations (id, name, country, city, street_address, website_url)
                VALUES %s;
            """, new_orgs_batch, page_size=200)

        # Subjects
        if new_subjects_batch:
            logger.info(f"Writing {len(new_subjects_batch)} new subjects into validate.subjects...")
            execute_values(self.cur, """
                INSERT INTO validate.subjects (id, label)
                VALUES %s;
            """, new_subjects_batch, page_size=200)

        # Distributions
        if distributions_batch:
            logger.info(f"Writing {len(distributions_batch)} distributions into validate.distributions...")
            execute_values(self.cur, """
                INSERT INTO validate.distributions (id, record_id, name, format, access_url)
                VALUES %s;
            """, distributions_batch, page_size=200)

        # Record-Project Links
        if record_project_batch:
            # Deduplicate by (record_id, project_id)
            seen_rp = set()
            unique_rp = []
            for r in record_project_batch:
                key = (r[1], r[2])
                if key not in seen_rp:
                    seen_rp.add(key)
                    unique_rp.append(r)

            logger.info(f"Writing {len(unique_rp)} project links into validate.record_project...")
            execute_values(self.cur, """
                INSERT INTO validate.record_project (id, record_id, project_id)
                VALUES %s
                ON CONFLICT (record_id, project_id) DO NOTHING;
            """, unique_rp, page_size=200)

        # Record-Organization Links
        if record_org_batch:
            seen_ro = set()
            unique_ro = []
            for r in record_org_batch:
                key = (r[1], r[2])
                if key not in seen_ro:
                    seen_ro.add(key)
                    unique_ro.append(r)

            logger.info(f"Writing {len(unique_ro)} organization links into validate.record_organization...")
            execute_values(self.cur, """
                INSERT INTO validate.record_organization (id, record_id, organization_id)
                VALUES %s
                ON CONFLICT (record_id, organization_id) DO NOTHING;
            """, unique_ro, page_size=200)

        # Record-Subject Links
        if record_subject_batch:
            seen_rs = set()
            unique_rs = []
            for r in record_subject_batch:
                key = (r[1], r[2])
                if key not in seen_rs:
                    seen_rs.add(key)
                    unique_rs.append(r)

            logger.info(f"Writing {len(unique_rs)} subject links into validate.record_subject...")
            execute_values(self.cur, """
                INSERT INTO validate.record_subject (id, record_id, subject_id)
                VALUES %s
                ON CONFLICT (record_id, subject_id) DO NOTHING;
            """, unique_rs, page_size=200)

        return len(records_batch), len(record_project_batch), len(record_org_batch)


def main():
    parser = argparse.ArgumentParser(description="Harmonize harvest.items into validate schema.")
    parser.add_argument("--dry-run", action="store_true", help="Run without committing database changes")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of items to harmonize")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Database host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Database port")
    parser.add_argument("--dbname", default=DEFAULT_DBNAME, help="Database name")
    parser.add_argument("--user", default=DEFAULT_USER, help="Database user")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Database password")
    args = parser.parse_args()

    print("=" * 65)
    print("HARMONIZATION PIPELINE: harvest.items -> validate schema")
    print(f"Target DB:     {args.dbname} on {args.host}:{args.port}")
    print(f"Mode:          {'DRY-RUN (No changes will be saved)' if args.dry_run else 'EXECUTE (Committing to DB)'}")
    print("=" * 65)

    conn = psycopg2.connect(
        host=args.host, port=args.port, dbname=args.dbname, user=args.user, password=args.password
    )

    try:
        harmonizer = Harmonizer(conn)
        harmonizer.load_existing_caches()

        # Step 1: Projects
        harmonizer.sync_projects()

        # Step 2: Harmonize Records & Junctions
        rec_cnt, rp_cnt, ro_cnt = harmonizer.harmonize_records(limit=args.limit)

        if args.dry_run:
            conn.rollback()
            print("\n[DRY-RUN] Harmonization verification successful. All transactions rolled back.")
        else:
            conn.commit()
            print("\n✓ SUCCESS: Harmonization completed and committed to validate schema!")

        # Verification stats
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM validate.records WHERE resource_type = 'Project';")
            tot_rec = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM validate.record_project;")
            tot_rp = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM validate.record_organization;")
            tot_ro = cur.fetchone()[0]

        print("\n" + "=" * 65)
        print("VALIDATE SCHEMA SUMMARY:")
        print(f"  • Total Project Records in validate.records: {tot_rec}")
        print(f"  • Project-Record Links in record_project:    {tot_rp}")
        print(f"  • Org-Record Links in record_organization:   {tot_ro}")
        print("=" * 65)

    except Exception as e:
        conn.rollback()
        logger.error(f"Harmonization error: {e}")
        raise e
    finally:
        conn.close()


if __name__ == "__main__":
    main()
