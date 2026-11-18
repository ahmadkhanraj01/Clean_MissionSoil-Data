#!/usr/bin/env python3
"""
migrate_metadata_to_kh_dev.py
-----------------------------
Migrates harmonized metadata records from `msp-testing` to `msp-kh-dev`.
Modified to handle NULL names in organizations/persons by using fallback names
and mapping them precisely via their source database IDs.
"""

import argparse
import json
import os
import re
import uuid
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import Json, execute_values

from dotenv import load_dotenv
load_dotenv()

DEFAULT_HOST = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST")
DEFAULT_PORT = os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT", "5432")
DEFAULT_USER = os.getenv("DB_USER") or os.getenv("POSTGRES_USER")
DEFAULT_PASS = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")

SOURCE_DB = os.getenv("SOURCE_DB", "msp-testing")
TARGET_DB = os.getenv("TARGET_DB") or os.getenv("DB_NAME") or "msp-kh-dev"
PAGE_SIZE = 1000

STRIP_HTML = re.compile(r"<[^>]+>")

def clean_grant_number(grant: str) -> str:
    if not grant: return ""
    g = re.sub(r"^.*?10\.3030/", "", str(grant).strip())
    return g.split("/")[-1].strip()

def strip_html(text: str | None) -> str | None:
    if not text: return text
    return STRIP_HTML.sub("", text).strip()

def parse_ts(val):
    if not val: return None
    if isinstance(val, datetime): return val
    try:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None

def to_jsonb(val):
    if val is None: return None
    if isinstance(val, (dict, list)): return Json(val)
    if isinstance(val, str):
        try: return Json(json.loads(val))
        except (json.JSONDecodeError, ValueError): return Json({"raw": val})
    return Json(val)

class MetadataMigrator:
    def __init__(self, src_db, tgt_db, host, port, user, password):
        self.src_conn = psycopg2.connect(host=host, port=port, dbname=src_db, user=user, password=password)
        self.src_cur = self.src_conn.cursor()
        self.tgt_conn = psycopg2.connect(host=host, port=port, dbname=tgt_db, user=user, password=password)
        self.tgt_cur = self.tgt_conn.cursor()

        self.projects_cache = {}      # name -> uuid
        self.grant_to_name_map = {}   # grant_number -> name
        self.records_cache = {}       # identifier -> uuid
        self.sources_cache = {}       # name -> uuid
        self.persons_cache = {}       # (name, email) -> uuid
        self.orgs_cache = {}          # name -> uuid
        self.subjects_cache = {}      # label -> uuid
        
        # ID maps for entities that might have NULL names
        self.org_id_to_uuid = {}
        self.person_id_to_uuid = {}

    def load_target_caches(self):
        print("\nLoading existing target IDs into cache...")
        self.tgt_cur.execute("SELECT name, id FROM projects;")
        for name, pid in self.tgt_cur.fetchall():
            self.projects_cache[name] = pid

        self.tgt_cur.execute("SELECT identifier, id FROM records;")
        for ident, rid in self.tgt_cur.fetchall():
            self.records_cache[ident] = rid

        self.tgt_cur.execute("SELECT name, id FROM sources;")
        for name, sid in self.tgt_cur.fetchall():
            self.sources_cache[name.lower()] = sid

        self.tgt_cur.execute("SELECT name, email, id FROM persons;")
        for name, email, pid in self.tgt_cur.fetchall():
            self.persons_cache[(name.strip().lower(), (email or '').strip().lower())] = pid

        self.tgt_cur.execute("SELECT name, id FROM organizations;")
        for name, oid in self.tgt_cur.fetchall():
            self.orgs_cache[name.strip().lower()] = oid

        self.tgt_cur.execute("SELECT label, id FROM subjects;")
        for label, sid in self.tgt_cur.fetchall():
            self.subjects_cache[label.strip().lower()] = sid
        print(f"  Existing projects: {len(self.projects_cache)}, records: {len(self.records_cache)}")

    def migrate_projects(self):
        print("\nMigrating projects from harvest.projects...")
        self.src_cur.execute("SELECT grantnr, code, title FROM harvest.projects WHERE coalesce(grantnr, '') != ''")
        project_rows = []
        for grantnr, code, title in self.src_cur.fetchall():
            clean_g = clean_grant_number(grantnr)
            if not clean_g: continue
            
            proj_name = code or title or clean_g
            proj_name = proj_name.strip()
            self.grant_to_name_map[clean_g] = proj_name

            if proj_name not in self.projects_cache:
                proj_id = str(uuid.uuid4())
                self.projects_cache[proj_name] = proj_id
                project_rows.append((proj_id, proj_name))

        if project_rows:
            execute_values(self.tgt_cur, """
                INSERT INTO projects (id, name) VALUES %s ON CONFLICT (name) DO NOTHING
            """, project_rows, page_size=PAGE_SIZE)
            self.tgt_conn.commit()
        print(f"  ✓ Migrated {len(project_rows)} new projects.")

    def migrate_dimensions(self):
        print("\nMigrating dimension tables...")
        # Sources
        self.src_cur.execute("SELECT DISTINCT name FROM metadata.sources WHERE coalesce(name, '') != '';")
        new_sources = []
        for (name,) in self.src_cur.fetchall():
            nl = name.strip().lower()
            if nl not in self.sources_cache:
                sid = str(uuid.uuid4())
                self.sources_cache[nl] = sid
                new_sources.append((sid, name.strip()))
        if new_sources:
            execute_values(self.tgt_cur, "INSERT INTO sources (id, name) VALUES %s ON CONFLICT (name) DO NOTHING;", new_sources)

        # Subjects
        self.src_cur.execute("SELECT DISTINCT label, uri FROM metadata.subjects WHERE coalesce(label, '') != '';")
        new_subjects = []
        for label, s_uri in self.src_cur.fetchall():
            ll = label.strip().lower()
            if ll not in self.subjects_cache:
                sub_id = str(uuid.uuid4())
                self.subjects_cache[ll] = sub_id
                new_subjects.append((sub_id, label.strip(), s_uri or None))
        if new_subjects:
            execute_values(self.tgt_cur, "INSERT INTO subjects (id, label, uri) VALUES %s;", new_subjects)

        # Organizations (Handle NULL names)
        self.src_cur.execute("SELECT id, name, country, url FROM metadata.organization;")
        new_orgs = []
        for old_id, name, country, o_url in self.src_cur.fetchall():
            actual_name = name.strip() if name and name.strip() else f"Unknown Organization (ID: {old_id})"
            ol = actual_name.lower()
            
            if ol in self.orgs_cache:
                oid = self.orgs_cache[ol]
            else:
                oid = str(uuid.uuid4())
                self.orgs_cache[ol] = oid
                new_orgs.append((oid, actual_name, country or None, o_url or None))
            
            self.org_id_to_uuid[old_id] = oid
            
        if new_orgs:
            execute_values(self.tgt_cur, "INSERT INTO organizations (id, name, country, website_url) VALUES %s;", new_orgs)

        # Persons (Handle NULL names)
        self.src_cur.execute("SELECT id, name, email, orcid FROM metadata.person;")
        new_persons = []
        for old_id, name, email, orcid in self.src_cur.fetchall():
            actual_name = name.strip() if name and name.strip() else f"Unknown Person (ID: {old_id})"
            key = (actual_name.lower(), (email or '').strip().lower())
            
            if key in self.persons_cache:
                pid = self.persons_cache[key]
            else:
                pid = str(uuid.uuid4())
                self.persons_cache[key] = pid
                new_persons.append((pid, actual_name, email or None, orcid or None))
                
            self.person_id_to_uuid[old_id] = pid
            
        if new_persons:
            execute_values(self.tgt_cur, "INSERT INTO persons (id, name, email, orcid) VALUES %s;", new_persons)

        self.tgt_conn.commit()
        print("  ✓ Dimension tables populated (Including organizations/persons with NULL names).")

    def migrate_records(self):
        print("\nMigrating harmonized records...")
        self.src_cur.execute("""
            SELECT identifier, title, abstract, type, source, license, language, 
                   thumbnail, publicationdate, creationdate, revisiondate, harvest_date, 
                   spatial, temporal_start, temporal_end, raw_mcf
            FROM metadata.records;
        """)
        
        records_batch = []
        record_sources_batch = []
        
        while True:
            rows = self.src_cur.fetchmany(PAGE_SIZE)
            if not rows: break

            for r in rows:
                ident = r[0]
                rec_id = self.records_cache.get(ident) or str(uuid.uuid4())
                self.records_cache[ident] = rec_id
                
                source_val = r[4]
                if source_val:
                    sid = self.sources_cache.get(source_val.strip().lower())
                    if sid:
                        record_sources_batch.append((str(uuid.uuid4()), rec_id, sid))

                records_batch.append((
                    rec_id, ident, strip_html(r[1]) or "Untitled", strip_html(r[2]), 
                    r[3] or "document", r[5] or None, (r[6] or "en")[:20], r[7] or None, 
                    parse_ts(r[8]), parse_ts(r[9]), parse_ts(r[10]), parse_ts(r[11]), 
                    r[12] or None, parse_ts(r[13]), parse_ts(r[14]), to_jsonb(r[15])
                ))

            if records_batch:
                execute_values(self.tgt_cur, """
                    INSERT INTO records (
                        id, identifier, title, abstract, resource_type, license, language, 
                        thumbnail, publication_date, resource_creation_date, resource_updated_date, 
                        harvest_date, spatial, temporal_start, temporal_end, raw_metadata
                    ) VALUES %s
                    ON CONFLICT (identifier) DO UPDATE SET
                        title = EXCLUDED.title, abstract = EXCLUDED.abstract, resource_type = EXCLUDED.resource_type,
                        license = EXCLUDED.license, language = EXCLUDED.language, thumbnail = EXCLUDED.thumbnail,
                        publication_date = EXCLUDED.publication_date, resource_creation_date = EXCLUDED.resource_creation_date,
                        resource_updated_date = EXCLUDED.resource_updated_date, harvest_date = EXCLUDED.harvest_date,
                        spatial = EXCLUDED.spatial, temporal_start = EXCLUDED.temporal_start, temporal_end = EXCLUDED.temporal_end,
                        raw_metadata = EXCLUDED.raw_metadata, updated_at = NOW()
                """, records_batch, page_size=PAGE_SIZE)
                
                if record_sources_batch:
                    execute_values(self.tgt_cur, """
                        INSERT INTO record_source (id, record_id, source_id) VALUES %s
                        ON CONFLICT ON CONSTRAINT uq_record_source DO NOTHING
                    """, record_sources_batch, page_size=PAGE_SIZE)
                
                self.tgt_conn.commit()
                records_batch.clear()
                record_sources_batch.clear()
        print("  ✓ Records migrated.")

    def migrate_record_project(self):
        print("\nLinking records to projects...")
        self.src_cur.execute("SELECT record_id, project FROM metadata.record_in_project WHERE coalesce(project, '') != '';")
        rip_rows = self.src_cur.fetchall()
        
        self.src_cur.execute("SELECT identifier, project FROM harvest.items WHERE coalesce(project, '') != '';")
        hi_rows = self.src_cur.fetchall()

        all_links = set()
        for r_id, prj in rip_rows: all_links.add((r_id, clean_grant_number(prj)))
        for ident, prj in hi_rows: all_links.add((ident, clean_grant_number(prj)))

        rp_batch = []
        for record_ident, grant_num in all_links:
            rec_uuid = self.records_cache.get(record_ident)
            proj_name = self.grant_to_name_map.get(grant_num)
            
            if proj_name:
                proj_uuid = self.projects_cache.get(proj_name)
                if rec_uuid and proj_uuid:
                    rp_batch.append((str(uuid.uuid4()), rec_uuid, proj_uuid))

        if rp_batch:
            execute_values(self.tgt_cur, """
                INSERT INTO record_project (id, record_id, project_id) VALUES %s
                ON CONFLICT ON CONSTRAINT uq_record_project DO NOTHING;
            """, rp_batch, page_size=PAGE_SIZE)
            self.tgt_conn.commit()
        print(f"  ✓ Linked {len(rp_batch)} records to projects.")

    def migrate_distributions_and_junctions(self):
        print("\nMigrating distributions and remaining junctions...")
        
        # Distributions
        self.src_cur.execute("SELECT record_id, name, format, url, description FROM metadata.distributions WHERE url IS NOT NULL;")
        dist_batch = []
        for rec_ident, name, fmt, url_val, desc in self.src_cur.fetchall():
            rec_uuid = self.records_cache.get(rec_ident)
            if rec_uuid and url_val:
                dist_batch.append((str(uuid.uuid4()), rec_uuid, name or "Document", fmt or None, url_val, desc or None))

        if dist_batch:
            execute_values(self.tgt_cur, """
                INSERT INTO distributions (id, record_id, name, format, access_url, description) VALUES %s
            """, dist_batch, page_size=PAGE_SIZE)
            self.tgt_conn.commit()

        # Record - Subjects
        self.src_cur.execute("SELECT rs.record_id, s.label FROM metadata.record_subject rs JOIN metadata.subjects s ON rs.subject_id = s.id;")
        rsub_batch = []
        for rec_ident, label in self.src_cur.fetchall():
            rec_uuid = self.records_cache.get(rec_ident)
            sub_uuid = self.subjects_cache.get(label.strip().lower())
            if rec_uuid and sub_uuid:
                rsub_batch.append((str(uuid.uuid4()), rec_uuid, sub_uuid))

        if rsub_batch:
            execute_values(self.tgt_cur, "INSERT INTO record_subject (id, record_id, subject_id) VALUES %s ON CONFLICT ON CONSTRAINT uq_record_subject DO NOTHING;", rsub_batch)

        # Record - Organizations (Using internal ID map to handle NULL names safely)
        self.src_cur.execute("SELECT record_id, fk_organization FROM metadata.contact_in_record WHERE fk_organization IS NOT NULL;")
        rorg_batch = []
        for rec_ident, fk_org in self.src_cur.fetchall():
            rec_uuid = self.records_cache.get(rec_ident)
            org_uuid = self.org_id_to_uuid.get(fk_org)
            if rec_uuid and org_uuid:
                rorg_batch.append((str(uuid.uuid4()), rec_uuid, org_uuid))

        if rorg_batch:
            execute_values(self.tgt_cur, "INSERT INTO record_organization (id, record_id, organization_id) VALUES %s ON CONFLICT ON CONSTRAINT uq_record_organization DO NOTHING;", rorg_batch)

        # Record - Persons (Using internal ID map to handle NULL names safely)
        self.src_cur.execute("SELECT record_id, fk_person FROM metadata.contact_in_record WHERE fk_person IS NOT NULL;")
        rpers_batch = []
        for rec_ident, fk_person in self.src_cur.fetchall():
            rec_uuid = self.records_cache.get(rec_ident)
            pers_uuid = self.person_id_to_uuid.get(fk_person)
            if rec_uuid and pers_uuid:
                rpers_batch.append((str(uuid.uuid4()), rec_uuid, pers_uuid))

        if rpers_batch:
            execute_values(self.tgt_cur, "INSERT INTO record_person (id, record_id, person_id) VALUES %s ON CONFLICT ON CONSTRAINT uq_record_person DO NOTHING;", rpers_batch)

        self.tgt_conn.commit()
        print("  ✓ Junctions linked.")

    def close(self):
        self.src_cur.close()
        self.src_conn.close()
        self.tgt_cur.close()
        self.tgt_conn.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", default=SOURCE_DB)
    parser.add_argument("--target-db", default=TARGET_DB)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASS)
    args = parser.parse_args()

    migrator = MetadataMigrator(args.source_db, args.target_db, args.host, args.port, args.user, args.password)
    try:
        migrator.load_target_caches()
        migrator.migrate_projects()
        migrator.migrate_dimensions()
        migrator.migrate_records()
        migrator.migrate_record_project()
        migrator.migrate_distributions_and_junctions()
        print("\n🎉 Migration completed successfully!")
    finally:
        migrator.close()

if __name__ == "__main__":
    main()
