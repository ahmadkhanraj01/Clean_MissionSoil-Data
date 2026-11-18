#!/usr/bin/env python3
"""
enrich_missing_abstracts.py
============================
Enriches harvest.items records that have empty/null abstracts by querying
external registries (Crossref → DataCite → OpenAlex, in priority order).

Strategy per source:
  - openaire   (DOI records only): Try Crossref → DataCite → OpenAlex
  - prepsoil   (YouTube/web URLs): No enrichment possible; kept as-is
  - impact4soil (empty stubs)    : Records with BOTH empty title AND empty
                                   abstract are flagged / optionally deleted
  - Others                       : DOI-based enrichment where applicable

What this script does:
  1. Reads all harvest.items rows where abstract is empty/null AND
     identifiertype = 'doi'.
  2. For each DOI, queries Crossref → DataCite → OpenAlex in order.
  3. If an abstract is found, updates resultobject JSON (abstract field)
     via a JSON patch.
  4. Keeps a running stats report on console.

Usage:
    # Dry run (no DB writes):
    python enrich_missing_abstracts.py --dry-run

    # Enrich all missing-abstract DOI records:
    python enrich_missing_abstracts.py

    # Limit to N records for testing:
    python enrich_missing_abstracts.py --limit 100

    # Restrict to a specific source:
    python enrich_missing_abstracts.py --source openaire

    # Use multiple threads for faster API calls:
    python enrich_missing_abstracts.py --workers 5

Author: MissionSoil Data Pipeline
"""

# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config  # noqa: E402,F401  (loads .env)
# --------------------------------------------------------------------------------------------
import argparse
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import psycopg2
import requests
from psycopg2.extras import execute_values

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# DB settings come from the repo-root .env via common.db (the original hard-coded DB_NAME = "msp-kh-dev")

CROSSREF_API = "https://api.crossref.org/works/{doi}"
DATACITE_API = "https://api.datacite.org/dois/{doi}"
OPENALEX_API = "https://api.openalex.org/works/https://doi.org/{doi}"

HEADERS_CROSSREF = {
    "User-Agent": "MissionSoilHarvester/1.0 (mailto:admin@soilwise.eu)"
}
HEADERS_OPENALEX = {
    "User-Agent": "mailto:admin@soilwise.eu"
}

REQUEST_TIMEOUT = 10  # seconds per API call
POLITE_DELAY = 0.1    # seconds between batches

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("enrich_abstracts")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db_connection():
    return get_connection()


def fetch_records_missing_abstracts(
    conn, source: Optional[str] = None, limit: Optional[int] = None
):
    """Return list of (hash, identifier, source, resultobject_json) for DOI records with no abstract."""
    filters = [
        "identifiertype = 'doi'",
        # Only JSON payloads: YAML items (CORDIS / EU CAP, identifiertype 'doi') would make the
        # ::jsonb cast fail. CASE guarantees the cast is never evaluated for non-JSON rows.
        "resulttype IN ('schema.org', 'json')",
        "coalesce(trim(CASE WHEN resulttype IN ('schema.org', 'json') "
        "THEN resultobject::jsonb->>'abstract' END), '') = ''",
    ]
    if source:
        filters.append(f"source = '{source}'")

    where_clause = " AND ".join(filters)
    limit_clause = f"LIMIT {limit}" if limit else ""

    sql = f"""
        SELECT hash, identifier, source, resultobject
        FROM harvest.items
        WHERE {where_clause}
        ORDER BY identifier
        {limit_clause};
    """
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    logger.info(f"Found {len(rows):,} DOI records with missing abstracts.")
    return rows


# ---------------------------------------------------------------------------
# Abstract recovery helpers
# ---------------------------------------------------------------------------
def _strip_jats_xml(text: str) -> str:
    """Remove JATS XML tags from Crossref abstracts (e.g., <jats:p>)."""
    return re.sub(r"<[^>]+>", " ", text).strip()


def try_crossref(doi: str) -> Optional[str]:
    """Query Crossref for an abstract."""
    try:
        url = CROSSREF_API.format(doi=doi)
        r = requests.get(url, headers=HEADERS_CROSSREF, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            abstract = r.json().get("message", {}).get("abstract")
            if abstract:
                return _strip_jats_xml(abstract)
        elif r.status_code == 404:
            return None
        else:
            logger.debug(f"Crossref HTTP {r.status_code} for DOI {doi}")
    except requests.exceptions.Timeout:
        logger.debug(f"Crossref timeout for DOI {doi}")
    except Exception as e:
        logger.debug(f"Crossref error for DOI {doi}: {e}")
    return None


def try_datacite(doi: str) -> Optional[str]:
    """Query DataCite for an abstract."""
    try:
        url = DATACITE_API.format(doi=doi)
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            descriptions = (
                r.json().get("data", {}).get("attributes", {}).get("descriptions", [])
            )
            # Prefer 'Abstract' type; fall back to first description
            for desc in descriptions:
                if desc.get("descriptionType", "").lower() == "abstract" and desc.get("description"):
                    return desc["description"].strip()
            if descriptions and descriptions[0].get("description"):
                return descriptions[0]["description"].strip()
        elif r.status_code == 404:
            return None
        else:
            logger.debug(f"DataCite HTTP {r.status_code} for DOI {doi}")
    except requests.exceptions.Timeout:
        logger.debug(f"DataCite timeout for DOI {doi}")
    except Exception as e:
        logger.debug(f"DataCite error for DOI {doi}: {e}")
    return None


def _reconstruct_from_inverted_index(inverted: dict) -> str:
    """Reconstruct plaintext abstract from OpenAlex abstract_inverted_index."""
    position_word = []
    for word, positions in inverted.items():
        for pos in positions:
            position_word.append((pos, word))
    position_word.sort()
    return " ".join(w for _, w in position_word)


def try_openalex(doi: str) -> Optional[str]:
    """Query OpenAlex for an abstract (inverted index reconstruction)."""
    try:
        url = OPENALEX_API.format(doi=doi)
        r = requests.get(url, headers=HEADERS_OPENALEX, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            ab_inv = data.get("abstract_inverted_index")
            if ab_inv:
                return _reconstruct_from_inverted_index(ab_inv)
        elif r.status_code == 404:
            return None
        else:
            logger.debug(f"OpenAlex HTTP {r.status_code} for DOI {doi}")
    except requests.exceptions.Timeout:
        logger.debug(f"OpenAlex timeout for DOI {doi}")
    except Exception as e:
        logger.debug(f"OpenAlex error for DOI {doi}: {e}")
    return None


def recover_abstract(doi: str) -> tuple:
    """
    Try registries in priority order: Crossref -> DataCite -> OpenAlex.
    Returns (abstract_text, source_used) or (None, None).
    """
    abstract = try_crossref(doi)
    if abstract:
        return abstract, "crossref"

    abstract = try_datacite(doi)
    if abstract:
        return abstract, "datacite"

    abstract = try_openalex(doi)
    if abstract:
        return abstract, "openalex"

    return None, None


# ---------------------------------------------------------------------------
# Core enrichment logic
# ---------------------------------------------------------------------------
def enrich_record(record: tuple):
    """
    Process a single record. Returns a dict with update info or None if no abstract found.

    record: (hash, identifier, source, resultobject_json_str)
    """
    rec_hash, doi, source, resultobject_raw = record

    abstract, registry_used = recover_abstract(doi)

    if not abstract:
        return None

    # Patch the resultobject JSON
    try:
        obj = json.loads(resultobject_raw) if resultobject_raw else {}
    except json.JSONDecodeError:
        obj = {}

    obj["abstract"] = abstract

    return {
        "hash": rec_hash,
        "doi": doi,
        "source": source,
        "registry": registry_used,
        "patched_resultobject": json.dumps(obj, ensure_ascii=False),
    }


UPDATE_SQL = """
    UPDATE harvest.items
    SET resultobject = data.resultobject::text,
        insert_date  = NOW()
    FROM (VALUES %s) AS data(rec_hash, resultobject)
    WHERE harvest.items.hash = data.rec_hash;
"""


def run_enrichment(
    dry_run: bool = False,
    source: Optional[str] = None,
    limit: Optional[int] = None,
    workers: int = 3,
):
    conn = get_db_connection()
    records = fetch_records_missing_abstracts(conn, source=source, limit=limit)

    if not records:
        logger.info("No records to enrich. Exiting.")
        conn.close()
        return

    stats = {
        "total": len(records),
        "recovered": 0,
        "not_found": 0,
        "crossref": 0,
        "datacite": 0,
        "openalex": 0,
    }

    updates_batch = []
    batch_size = 50
    processed = 0
    start_time = time.time()

    logger.info(
        f"Starting enrichment of {len(records):,} records "
        f"(workers={workers}, dry_run={dry_run})"
    )

    def flush_batch(batch):
        if dry_run or not batch:
            return
        cur = conn.cursor()
        execute_values(
            cur,
            UPDATE_SQL,
            batch,
            template="(%s, %s)",
        )
        conn.commit()
        cur.close()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(enrich_record, rec): rec for rec in records}

        for future in as_completed(futures):
            processed += 1
            result = future.result()

            if result:
                stats["recovered"] += 1
                stats[result["registry"]] += 1
                updates_batch.append((result["hash"], result["patched_resultobject"]))
                if dry_run:
                    logger.info(
                        f"[DRY RUN] Would update hash={result['hash'][:12]}... "
                        f"(DOI={result['doi']}) from {result['registry']}"
                    )
            else:
                stats["not_found"] += 1

            # Flush every batch_size records
            if len(updates_batch) >= batch_size:
                flush_batch(updates_batch)
                updates_batch.clear()

            # Progress log every 100
            if processed % 100 == 0 or processed == stats["total"]:
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                pct = processed / stats["total"] * 100
                logger.info(
                    f"Progress: {processed:,}/{stats['total']:,} ({pct:.1f}%) | "
                    f"Recovered: {stats['recovered']:,} | "
                    f"Speed: {rate:.1f} rec/sec"
                )

            time.sleep(POLITE_DELAY / workers)

    # Flush remaining
    flush_batch(updates_batch)

    conn.close()

    # Final summary
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("ENRICHMENT COMPLETE")
    logger.info(f"  Total DOI records processed : {stats['total']:,}")
    logger.info(f"  Abstracts recovered         : {stats['recovered']:,}  "
                f"({stats['recovered']/stats['total']*100:.1f}%)")
    logger.info(f"  Not found in any registry   : {stats['not_found']:,}")
    logger.info(f"  from Crossref               : {stats['crossref']:,}")
    logger.info(f"  from DataCite               : {stats['datacite']:,}")
    logger.info(f"  from OpenAlex               : {stats['openalex']:,}")
    logger.info(f"  Total time                  : {elapsed:.1f}s")
    if dry_run:
        logger.info("  [DRY RUN] -- No database writes were made.")
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Enrich harvest.items records with missing abstracts via Crossref/DataCite/OpenAlex"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch abstracts but do NOT write to the database.",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Only enrich records from a specific source (e.g. openaire, ejpsoil).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of records to process (default: all).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Number of parallel API request threads (default: 3). Be polite.",
    )

    args = parser.parse_args()

    run_enrichment(
        dry_run=args.dry_run,
        source=args.source,
        limit=args.limit,
        workers=args.workers,
    )
