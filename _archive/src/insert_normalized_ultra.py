"""
insert_normalized_ultra.py
Ultimate batching script using a two-pass approach to completely eliminate network latency.
"""

import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone
from scripts.config import DATA_PATH
import psycopg2
from psycopg2.extras import Json, execute_values
from db.connection import get_db_connection
from db import queries

# ── Helpers ──────────────────────────────────────────────────────────
import re
STRIP_HTML = re.compile(r"<[^>]+>")

def strip_html(text: str | None) -> str | None:
    if not text:
        return text
    return STRIP_HTML.sub("", text).strip()

def parse_json_strings_in_list(lst):
    if not isinstance(lst, list):
        return lst
    parsed = []
    for item in lst:
        if isinstance(item, str):
            try:
                parsed.append(json.loads(item))
            except (json.JSONDecodeError, ValueError):
                parsed.append(item)
        else:
            parsed.append(item)
    return parsed

def parse_ts(val):
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None

def to_jsonb(val):
    if val is None:
        return None
    return Json(val)

def map_record(record: dict, record_id: str) -> dict:
    return {
        "id":                     record_id,
        "identifier":             record.get("identifier"),
        "title":                  record.get("title") or "Untitled",
        "abstract":               strip_html(record.get("abstract")),
        "resource_type":          record.get("type"),
        "persons":                to_jsonb(record.get("persons")),
        "organizations":          to_jsonb(record.get("organizations")),
        "contact_persons":        to_jsonb(record.get("contact_persons")),
        "contact_organizations":  to_jsonb(record.get("contact_organizations")),
        "links":                  to_jsonb(parse_json_strings_in_list(record.get("links"))),
        "subjects":               to_jsonb(record.get("subjects")),
        "sources":                to_jsonb(record.get("sources")),
        "license":                record.get("license") or None,
        "language":               record.get("language"),
        "thumbnail":              record.get("thumbnail") or None,
        "publication_date":       parse_ts(record.get("date_publication")),
        "resource_creation_date": parse_ts(record.get("date_creation")),
        "resource_updated_date":  parse_ts(record.get("date")),
        "harvest_date":           parse_ts(record.get("date_harvest")),
        "spatial":                record.get("spatial"),
        "temporal_start":         parse_ts(record.get("temporal_start")),
        "temporal_end":           parse_ts(record.get("temporal_end")),
        "raw_metadata":           to_jsonb(record),
    }

class DBManager:
    def __init__(self):
        self.conn = get_db_connection()
        self.cur = self.conn.cursor()
        
        # Caches
        self.sources_cache = {}
        self.persons_cache = {}
        self.organizations_cache = {}
        self.subjects_cache = {}

    def load_caches(self):
        print("Loading caches from DB...")
        self.cur.execute("SELECT name, id FROM sources;")
        for row in self.cur.fetchall():
            self.sources_cache[row[0]] = row[1]
            
        self.cur.execute("SELECT email, id, name FROM persons;")
        for row in self.cur.fetchall():
            self.persons_cache[row[0] or row[2]] = row[1]
            
        self.cur.execute("SELECT name, id FROM organizations;")
        for row in self.cur.fetchall():
            self.organizations_cache[row[0]] = row[1]
            
        self.cur.execute("SELECT label, id FROM subjects;")
        for row in self.cur.fetchall():
            self.subjects_cache[row[0]] = row[1]

def main():
    # PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    json_path = DATA_PATH
    print(f"Loading JSON from: {json_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        records = json.load(f)
    print(f"Loaded {len(records)} records.")

    db = DBManager()
    db.load_caches()

    print("Phase 1: Pre-processing dimension tables...")
    unique_sources = set()
    unique_persons = set()
    unique_organizations = set()
    unique_subjects = set()

    for rec in records:
        for s in (rec.get("sources") or []):
            unique_sources.add(s)
        for p in (set(rec.get("persons") or []) | set(rec.get("contact_persons") or [])):
            unique_persons.add(p)
        for o in (set(rec.get("organizations") or []) | set(rec.get("contact_organizations") or [])):
            unique_organizations.add(o)
        for sub in (set(rec.get("subjects") or []) | set(rec.get("matched_subjects") or [])):
            unique_subjects.add(sub)

    # Filter out what's already in DB cache
    new_sources = [(str(uuid.uuid4()), s) for s in unique_sources if s not in db.sources_cache]
    new_persons = [(str(uuid.uuid4()), p, p if "@" in p else None) for p in unique_persons if p not in db.persons_cache]
    new_organizations = [(str(uuid.uuid4()), o) for o in unique_organizations if o not in db.organizations_cache]
    new_subjects = [(str(uuid.uuid4()), sub, None) for sub in unique_subjects if sub not in db.subjects_cache]

    print(f"  Inserting {len(new_sources)} new sources...")
    if new_sources: execute_values(db.cur, queries.INSERT_SOURCE + " ON CONFLICT DO NOTHING", new_sources, page_size=1000)

    print(f"  Inserting {len(new_persons)} new persons...")
    if new_persons: execute_values(db.cur, queries.INSERT_PERSON + " ON CONFLICT DO NOTHING", new_persons, page_size=1000)

    print(f"  Inserting {len(new_organizations)} new organizations...")
    if new_organizations: execute_values(db.cur, queries.INSERT_ORGANIZATION + " ON CONFLICT DO NOTHING", new_organizations, page_size=1000)

    print(f"  Inserting {len(new_subjects)} new subjects...")
    if new_subjects: execute_values(db.cur, queries.INSERT_SUBJECT + " ON CONFLICT DO NOTHING", new_subjects, page_size=1000)

    db.conn.commit()

    # Refresh the cache so we have the absolute perfect UUIDs directly from Postgres!
    db.load_caches()
    
    print("\nPhase 2: Inserting records and relationships...")
    
    existing_records = {}
    db.cur.execute("SELECT identifier, id FROM records;")
    for row in db.cur.fetchall():
        existing_records[row[0]] = row[1]
        
    total = len(records)
    inserted = 0

    record_cols = [
        "id", "identifier", "title", "abstract", "resource_type",
        "license", "language", "thumbnail",
        "publication_date", "resource_creation_date", "resource_updated_date",
        "harvest_date", "spatial", "temporal_start", "temporal_end", "raw_metadata"
    ]

    # Batch lists
    batch_records = []
    batch_record_source = []
    batch_record_person = []
    batch_record_organization = []
    batch_record_subject = []
    batch_distributions = []

    query_without_returning = queries.UPSERT_RECORD.replace("RETURNING id", "")

    def flush_batches():
        if batch_records: execute_values(db.cur, query_without_returning, batch_records, page_size=1000)
        if batch_record_source: execute_values(db.cur, queries.INSERT_RECORD_SOURCE, batch_record_source, page_size=1000)
        if batch_record_person: execute_values(db.cur, queries.INSERT_RECORD_PERSON, batch_record_person, page_size=1000)
        if batch_record_organization: execute_values(db.cur, queries.INSERT_RECORD_ORGANIZATION, batch_record_organization, page_size=1000)
        if batch_record_subject: execute_values(db.cur, queries.INSERT_RECORD_SUBJECT, batch_record_subject, page_size=1000)
        if batch_distributions: execute_values(db.cur, queries.INSERT_DISTRIBUTION, batch_distributions, page_size=1000)
        
        db.conn.commit()
        
        batch_records.clear()
        batch_record_source.clear()
        batch_record_person.clear()
        batch_record_organization.clear()
        batch_record_subject.clear()
        batch_distributions.clear()

    for rec in records:
        identifier = rec.get("identifier")
        record_db_id = existing_records.get(identifier)
        if not record_db_id:
            record_db_id = str(uuid.uuid4())
            existing_records[identifier] = record_db_id
            
        mapped = map_record(rec, record_db_id)
        row_tuple = tuple(mapped[col] for col in record_cols)
        batch_records.append(row_tuple)
        
        for s in (rec.get("sources") or []):
            batch_record_source.append((str(uuid.uuid4()), record_db_id, db.sources_cache[s]))
            
        for p in (set(rec.get("persons") or []) | set(rec.get("contact_persons") or [])):
            batch_record_person.append((str(uuid.uuid4()), record_db_id, db.persons_cache[p]))
            
        for o in (set(rec.get("organizations") or []) | set(rec.get("contact_organizations") or [])):
            batch_record_organization.append((str(uuid.uuid4()), record_db_id, db.organizations_cache[o]))
            
        for sub in (set(rec.get("subjects") or []) | set(rec.get("matched_subjects") or [])):
            batch_record_subject.append((str(uuid.uuid4()), record_db_id, db.subjects_cache[sub]))
            
        links = parse_json_strings_in_list(rec.get("links") or [])
        if links:
            for link in links:
                if isinstance(link, dict) and link.get("url"):
                    name = link.get("name") or link.get("format") or "Unknown"
                    batch_distributions.append((str(uuid.uuid4()), record_db_id, name, link.get("format"), link.get("url")))

        inserted += 1
        if inserted % 2000 == 0:
            flush_batches()
            print(f"  Processed {inserted}/{total} records...")

    # Flush remainder
    flush_batches()
    db.cur.close()
    db.conn.close()
    print(f"\nDone! {inserted} records processed via Ultra Batching.")

if __name__ == "__main__":
    main()
