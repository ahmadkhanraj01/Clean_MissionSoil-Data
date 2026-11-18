#!/usr/bin/env python3
"""
convert_harvest_to_schema_org.py
--------------------------------------------------------------------------------
Converts existing Solr JSON records in `harvest.items` into standardized Schema.org
JSON-LD objects and updates `resulttype = 'schema.org'`.

Features:
- Preserves all metadata (title, abstract, authors, distributions, dates, keywords).
- Cleanly converts stringified JSON links and unquotes percent-encoded URLs.
- Safely streams in batches with transactional commit.
- Supports --dry-run and --limit for testing.
--------------------------------------------------------------------------------
"""

import os
import sys
import json
import time
import argparse
import logging
from typing import List, Tuple
import psycopg2
from psycopg2.extras import execute_batch
from dotenv import dotenv_values

from solr_schema_mapper import solr_to_schema_org

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("convert_schema_org")


def get_db_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    env_paths = [
        os.path.join(base_dir, ".env"),
        os.path.join(os.path.dirname(base_dir), ".env")
    ]
    env = {}
    for p in env_paths:
        if os.path.exists(p):
            env.update({k: v for k, v in dotenv_values(p).items() if v is not None})

    db_host = env.get("DB_HOST") or env.get("POSTGRES_HOST")
    db_port = int(env.get("DB_PORT") or env.get("POSTGRES_PORT") or 5432)
    db_name = env.get("DB_NAME") or env.get("POSTGRES_DB")
    db_user = env.get("DB_USER") or env.get("POSTGRES_USER")
    db_pass = env.get("DB_PASSWORD") or env.get("POSTGRES_PASSWORD")

    logger.info(f"Connecting to DB {db_name} at {db_host}:{db_port} as {db_user}...")
    return psycopg2.connect(
        dbname=db_name,
        user=db_user,
        password=db_pass,
        host=db_host,
        port=db_port
    )


def convert_records(batch_size: int = 1000, limit: int = None, dry_run: bool = False):
    conn = get_db_connection()
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT count(*) 
                FROM harvest.items 
                WHERE resulttype = 'json' AND resultobject IS NOT NULL;
            """)
            total_available = cur.fetchone()[0]

        target_count = min(total_available, limit) if limit else total_available
        logger.info(f"Found {total_available:,} 'json' records. Targeting: {target_count:,} (dry_run={dry_run}).")

        if target_count == 0:
            logger.info("No records to convert. Exiting.")
            return

        # Fetch records using server-side or source-based iteration
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT source FROM harvest.items WHERE resulttype = 'json' ORDER BY source;")
            sources = [r[0] for r in cur.fetchall()]

        total_converted = 0
        update_cur = conn.cursor()
        start_time = time.time()

        for src in sources:
            if limit and total_converted >= limit:
                break

            logger.info(f"\nProcessing source: {src}...")
            with conn.cursor() as read_cur:
                read_cur.execute("""
                    SELECT hash, identifier, resultobject, title
                    FROM harvest.items
                    WHERE source = %s AND resulttype = 'json' AND resultobject IS NOT NULL;
                """, (src,))

                batch_updates: List[Tuple[str, str]] = []
                while True:
                    rows = read_cur.fetchmany(batch_size)
                    if not rows:
                        break

                    for r_hash, ident, raw_obj, r_title in rows:
                        try:
                            doc = json.loads(raw_obj) if isinstance(raw_obj, str) else raw_obj
                        except Exception:
                            continue

                        schema_dict = solr_to_schema_org(doc)
                        schema_json = json.dumps(schema_dict, ensure_ascii=False)
                        batch_updates.append((schema_json, r_hash))

                        total_converted += 1
                        if limit and total_converted >= limit:
                            break

                    if len(batch_updates) >= batch_size:
                        if not dry_run:
                            execute_batch(update_cur, """
                                UPDATE harvest.items
                                SET resultobject = %s,
                                    resulttype = 'schema.org',
                                    updated_date = NOW()
                                WHERE hash = %s;
                            """, batch_updates, page_size=500)
                            conn.commit()
                        logger.info(f"  [{src}] Updated {len(batch_updates):,} items (total: {total_converted:,}/{target_count:,})...")
                        batch_updates = []

                    if limit and total_converted >= limit:
                        break

                if batch_updates:
                    if not dry_run:
                        execute_batch(update_cur, """
                            UPDATE harvest.items
                            SET resultobject = %s,
                                resulttype = 'schema.org',
                                updated_date = NOW()
                            WHERE hash = %s;
                        """, batch_updates, page_size=500)
                        conn.commit()
                    logger.info(f"  [{src}] Updated remaining {len(batch_updates):,} items (total: {total_converted:,}/{target_count:,})...")

        update_cur.close()
        elapsed = time.time() - start_time
        logger.info("\n" + "=" * 60)
        logger.info(f"CONVERSION COMPLETE: {total_converted:,} records converted in {elapsed:.1f}s (dry_run={dry_run})")

        with conn.cursor() as cur:
            cur.execute("SELECT resulttype, count(*) FROM harvest.items GROUP BY resulttype ORDER BY count(*) DESC;")
            logger.info("Current harvest.items resulttype distribution:")
            for rt, cnt in cur.fetchall():
                logger.info(f"  • {rt:15}: {cnt:,}")
        logger.info("=" * 60)

    except Exception as e:
        conn.rollback()
        logger.error(f"Error during conversion: {e}", exc_info=True)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert harvest.items Solr JSON to Schema.org JSON-LD")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for DB updates")
    parser.add_argument("--limit", type=int, default=None, help="Max records to convert (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Process and validate without writing to DB")

    args = parser.parse_args()
    convert_records(batch_size=args.batch_size, limit=args.limit, dry_run=args.dry_run)
