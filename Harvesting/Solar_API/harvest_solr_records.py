#!/usr/bin/env python3
"""
harvest_solr_records.py
--------------------------------------------------------------------------------
Harvests records from SoilWise Solr Search API, maps them directly into
standardized Schema.org JSON-LD objects, and streams them into `harvest.items`.

Key Specifications:
1. Directly standardizes every incoming Solr record into Schema.org JSON-LD
   (resulttype = 'schema.org') via solr_schema_mapper before database insertion.
2. Identifies and stores the authoritative primary provider source
   (e.g., 'openaire', 'bonares', 'cordis', 'impact4soil', 'data.europa.eu').
3. Derives all table metadata columns (itemtype, title, language, dates, project)
   directly from the Schema.org object.
4. MD5 hash deduplication with idempotent upsert on conflict.
5. Streams in configurable batches (default 500) to keep memory footprint minimal.
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
import json
import time
import hashlib
import argparse
import logging
from typing import Dict, Any, Tuple, Optional
import requests
import psycopg2
from psycopg2.extras import execute_values

# solr_schema_mapper.py sits next to this script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from solr_schema_mapper import (
    solr_to_schema_org,
    extract_source,
    extract_identifier_and_type,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("harvest_solr")

SOLR_SEARCH_URL = "https://catalogue.soilwise-he.eu/search-api/solr/search"


def get_db_connection():
    cfg = db_config()
    logger.info(f"Connecting to DB {cfg['dbname']} at {cfg['host']}:{cfg['port']} as {cfg['user']}...")
    return get_connection()


def map_doc_to_row(doc: Dict[str, Any]) -> Tuple:
    """
    Directly standardizes a Solr doc into Schema.org JSON-LD and prepares the tuple
    for harvest.items insertion with resulttype = 'schema.org'.
    """
    # 1. Transform directly to Schema.org JSON-LD
    schema = solr_to_schema_org(doc)

    # 2. Extract core identifiers and primary source
    identifier = schema.get("identifier") or ""
    _, id_type = extract_identifier_and_type(doc)
    source = extract_source(doc)
    uri = schema.get("@id") or schema.get("url") or ""

    # 3. Extract primary project/funder if available
    funders = schema.get("funder") or []
    project = (
        funders[0].get("name")
        if (funders and isinstance(funders, list) and isinstance(funders[0], dict))
        else None
    )

    # 4. Hash for deduplication
    doc_hash = (
        hashlib.md5(f"{identifier}:{source}".encode("utf-8")).hexdigest()
        if identifier
        else hashlib.md5(json.dumps(doc, sort_keys=True).encode("utf-8")).hexdigest()
    )

    schema_json = json.dumps(schema, ensure_ascii=False)

    return (
        identifier,
        id_type,
        uri,
        schema_json,
        "schema.org",
        schema.get("@type", "Dataset"),
        schema.get("name", "Untitled"),
        source,
        schema.get("inLanguage", "en"),
        schema.get("datePublished") or schema.get("dateCreated"),
        project,
        doc_hash,
    )


UPSERT_SQL = """
    INSERT INTO harvest.items (
        identifier, identifiertype, uri, resultobject, resulttype,
        itemtype, title, source, language, date, project, hash,
        insert_date, updated_date
    ) VALUES %s
    ON CONFLICT (hash) DO UPDATE SET
        resultobject = EXCLUDED.resultobject,
        resulttype   = EXCLUDED.resulttype,
        itemtype     = EXCLUDED.itemtype,
        title        = EXCLUDED.title,
        source       = EXCLUDED.source,
        language     = EXCLUDED.language,
        date         = EXCLUDED.date,
        project      = EXCLUDED.project,
        updated_date = NOW();
"""

def harvest_solr(batch_size=500, limit=None, dry_run=False):
    session = requests.Session()
    
    # Step 1: Initial query to discover total numFound
    logger.info("Connecting to Solr API to check total record count...")
    r0 = session.post(SOLR_SEARCH_URL, json={"query": "*:*", "limit": 1}, timeout=30)
    if r0.status_code != 200:
        logger.error(f"Failed to query Solr endpoint: HTTP {r0.status_code}: {r0.text}")
        sys.exit(1)

    total_records = r0.json().get("response", {}).get("numFound", 0)
    logger.info(f"Solr reports total available records: {total_records:,}")

    if limit and limit < total_records:
        target_records = limit
        logger.info(f"Harvest limit set: targeting {target_records:,} records.")
    else:
        target_records = total_records

    conn = None
    if not dry_run:
        conn = get_db_connection()
        conn.autocommit = False

    offset = 0
    total_processed = 0
    source_stats = {}
    seen_versions = set()
    start_time = time.time()

    try:
        while offset < target_records:
            current_limit = min(batch_size, target_records - offset)
            payload = {
                "query": "*:*",
                "limit": current_limit,
                "offset": offset
            }

            resp = session.post(SOLR_SEARCH_URL, json=payload, timeout=45)
            if resp.status_code != 200:
                logger.warning(f"HTTP {resp.status_code} at offset {offset}. Retrying after 2s...")
                time.sleep(2.0)
                resp = session.post(SOLR_SEARCH_URL, json=payload, timeout=45)
                if resp.status_code != 200:
                    logger.error(f"Repeated error at offset {offset}. Stopping.")
                    break

            data = resp.json()
            docs = data.get("response", {}).get("docs", [])
            if not docs:
                logger.info(f"No more docs returned at offset {offset}. Finished.")
                break

            # Loop detection using Solr _version_
            versions = [d.get("_version_") for d in docs if d.get("_version_")]
            if versions and all(v in seen_versions for v in versions):
                logger.warning(f"Offset {offset} returned repeated records (_version_ loop). Halting.")
                break
            seen_versions.update(versions)

            rows_to_insert = []
            for doc in docs:
                row = map_doc_to_row(doc)
                src = row[7]
                source_stats[src] = source_stats.get(src, 0) + 1
                rows_to_insert.append(row)

            # Deduplicate within batch by hash to prevent PostgreSQL CardinalityViolation
            dedup_batch = {}
            for r in rows_to_insert:
                dedup_batch[r[-1]] = r
            unique_batch = list(dedup_batch.values())

            if not dry_run and conn and unique_batch:
                cur = conn.cursor()
                execute_values(
                    cur,
                    UPSERT_SQL,
                    unique_batch,
                    template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())",
                    page_size=len(unique_batch)
                )
                conn.commit()

            total_processed += len(docs)
            offset += len(docs)
            elapsed = time.time() - start_time
            rate = total_processed / elapsed if elapsed > 0 else 0

            logger.info(
                f"Ingested {total_processed:,} / {target_records:,} records "
                f"({(total_processed / target_records) * 100:.1f}%) | "
                f"Speed: {rate:.1f} docs/sec | Elapsed: {elapsed:.1f}s"
            )

            # Polite pause to prevent server throttling
            time.sleep(0.05)

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error during harvesting: {e}", exc_info=True)
        raise
    finally:
        if conn:
            conn.close()

    total_time = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"HARVEST COMPLETED in {total_time:.1f} seconds")
    logger.info(f"Total records processed: {total_processed:,}")
    logger.info("Breakdown by Authoritative Source:")
    for src, count in sorted(source_stats.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"  • {src:25} : {count:,} records")
    logger.info("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Harvest Solr records directly into harvest.items")
    parser.add_argument("--batch-size", type=int, default=500, help="Number of records per Solr page request")
    parser.add_argument("--limit", type=int, default=None, help="Max number of records to harvest (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse without writing to database")

    args = parser.parse_args()
    harvest_solr(batch_size=args.batch_size, limit=args.limit, dry_run=args.dry_run)
