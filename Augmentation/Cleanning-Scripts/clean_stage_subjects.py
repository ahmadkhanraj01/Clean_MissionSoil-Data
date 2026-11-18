#!/usr/bin/env python3
"""
clean_stage_subjects.py
--------------------------------------------------------------------------------
Cleans and standardizes the `validate.subjects` taxonomy and junction links in
`msp-kh-stage` (or specified database) with 100% transactional safety.

Safety Guarantees:
1. Runs in --dry-run mode by default. Zero database modifications unless --commit is passed.
2. Creates automatic timestamped backup tables before any commit:
   - validate.subjects_backup_YYYYMMDD_HHMMSS
   - validate.record_subject_backup_YYYYMMDD_HHMMSS
3. Entire operation runs in a single atomic transaction block with rollback on error.
4. Never deletes or modifies primary records in `validate.records`.

Transformations:
1. Discard pure noise: pure numbers ('01', '02', '03', '2300', '310'), dates, punctuation.
2. Strip numeric classification prefixes ('01 natural sciences' -> 'natural sciences').
3. Unbundle semicolon-separated keywords ('soil; fungi; bacteria' -> 3 distinct subjects).
4. Strip HTML tags ('<i>zea mays</i>' -> 'zea mays') and unescape HTML entities.
5. Deduplicate & merge: re-links records to existing canonical subjects without duplicate links.
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
import re
import html
import uuid
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple
import psycopg2
from psycopg2.extras import execute_values


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("clean_subjects")


def get_db_connection(dbname: str = None):
    cfg = db_config(dbname)
    logger.info(f"Connecting to DB '{cfg['dbname']}' on {cfg['host']}:{cfg['port']} as {cfg['user']}...")
    return get_connection(dbname)


# Keyword cleaner shared with solr_schema_mapper.py (identical logic, verified)
from common.text_cleaning import VALID_2_CHAR_KEYWORDS as VALID_2_CHAR, clean_keyword_text  # noqa: E402


def create_safety_backups(conn, schema: str = "validate") -> Tuple[str, str]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sub_backup = f"subjects_backup_{timestamp}"
    rec_sub_backup = f"record_subject_backup_{timestamp}"

    with conn.cursor() as cur:
        logger.info(f"Creating safety backup: {schema}.{sub_backup}...")
        cur.execute(f"CREATE TABLE {schema}.{sub_backup} AS SELECT * FROM {schema}.subjects;")

        logger.info(f"Creating safety backup: {schema}.{rec_sub_backup}...")
        cur.execute(f"CREATE TABLE {schema}.{rec_sub_backup} AS SELECT * FROM {schema}.record_subject;")

    logger.info("✅ Safety backup tables created successfully.")
    return sub_backup, rec_sub_backup


def run_clean_subjects(dbname: str = None, commit: bool = False):
    conn = get_db_connection(dbname)
    conn.autocommit = False

    try:
        cur = conn.cursor()

        logger.info("=" * 65)
        logger.info(f"STARTING SUBJECTS CLEANING ON: {dbname}")
        logger.info(f"  Mode : {'LIVE COMMIT' if commit else 'DRY-RUN (Simulated)'}")
        logger.info("=" * 65)

        # 1. Fetch all existing subjects
        logger.info("Fetching existing subjects from validate.subjects...")
        cur.execute("SELECT id, label FROM validate.subjects;")
        raw_subjects = cur.fetchall()
        initial_subjects_count = len(raw_subjects)

        # 2. Fetch all existing record_subject links
        logger.info("Fetching existing junction links from validate.record_subject...")
        cur.execute("SELECT record_id, subject_id FROM validate.record_subject;")
        raw_links = cur.fetchall()
        initial_links_count = len(raw_links)

        logger.info(f"  Initial Subjects Count     : {initial_subjects_count:,}")
        logger.info(f"  Initial Record Links Count : {initial_links_count:,}")

        # Map each subject to its cleaning outcome
        # Canonical index of clean lower-cased label -> existing ID
        canonical_map: Dict[str, str] = {}
        for sid, label in raw_subjects:
            cl = clean_keyword_text(label)
            if len(cl) == 1 and cl[0] == label:
                canonical_map[label.lower()] = str(sid)

        discard_ids: Set[str] = set()
        discard_samples: List[str] = []
        renamed_subjects: List[Tuple[str, str]] = []  # (id, new_label)
        merged_ids_map: Dict[str, str] = {}          # old_id -> canonical_id
        unbundle_map: Dict[str, List[str]] = {}       # old_bundled_id -> list of clean_kw_labels
        prefix_samples: List[Tuple[str, str]] = []

        for sid, label in raw_subjects:
            sid_str = str(sid)
            cleaned = clean_keyword_text(label)

            if not cleaned:
                # Rule 1: Discard pure numbers / noise
                discard_ids.add(sid_str)
                if len(discard_samples) < 25:
                    discard_samples.append(label)
            elif len(cleaned) > 1:
                # Rule 3: Unbundle semicolon strings
                unbundle_map[sid_str] = cleaned
            else:
                new_lbl = cleaned[0]
                if new_lbl != label:
                    if len(prefix_samples) < 15:
                        prefix_samples.append((label, new_lbl))
                    target_key = new_lbl.lower()
                    if target_key in canonical_map and canonical_map[target_key] != sid_str:
                        # Existing clean subject already present -> merge
                        merged_ids_map[sid_str] = canonical_map[target_key]
                    else:
                        # Rename in place
                        renamed_subjects.append((sid_str, new_lbl))
                        canonical_map[target_key] = sid_str

        logger.info("\n--- Cleaning Classification ---")
        logger.info(f"  • To Discard (pure numbers/symbols) : {len(discard_ids):,}")
        logger.info(f"  • To Merge into existing canonical  : {len(merged_ids_map):,}")
        logger.info(f"  • To Rename in-place (strip prefix) : {len(renamed_subjects):,}")
        logger.info(f"  • To Unbundle (semicolon strings)   : {len(unbundle_map):,}")
        logger.info(f"  • Clean & Untouched                 : {initial_subjects_count - len(discard_ids) - len(merged_ids_map) - len(renamed_subjects) - len(unbundle_map):,}")

        logger.info("\nSample Discarded Numbers/Noise:")
        for sample in discard_samples[:15]:
            logger.info(f"  - {repr(sample)}")

        logger.info("\nSample Cleaned Prefix Mappings:")
        for old, new in prefix_samples[:10]:
            logger.info(f"  - {repr(old)}  -->  {repr(new)}")

        # 3. Simulate / Plan New Links
        # Link resolution:
        # new_subject_id_map: kw_label -> subject_id
        new_subjects_to_insert: Dict[str, str] = {}  # kw_label -> new_uuid

        for bundled_id, kws in unbundle_map.items():
            for kw in kws:
                kw_key = kw.lower()
                if kw_key not in canonical_map and kw not in new_subjects_to_insert:
                    new_id = str(uuid.uuid4())
                    new_subjects_to_insert[kw] = new_id
                    canonical_map[kw_key] = new_id

        # Compute new junction links
        final_links_set: Set[Tuple[str, str]] = set()
        discarded_links_count = 0

        for rec_id, sub_id in raw_links:
            rec_str = str(rec_id)
            sub_str = str(sub_id)

            if sub_str in discard_ids:
                discarded_links_count += 1
                continue
            elif sub_str in merged_ids_map:
                # Map to merged canonical subject
                final_links_set.add((rec_str, merged_ids_map[sub_str]))
            elif sub_str in unbundle_map:
                # Add link for each unbundled keyword
                for kw in unbundle_map[sub_str]:
                    target_id = canonical_map.get(kw.lower()) or new_subjects_to_insert.get(kw)
                    if target_id:
                        final_links_set.add((rec_str, target_id))
            else:
                final_links_set.add((rec_str, sub_str))

        # Final subject counts
        final_subjects_count = initial_subjects_count - len(discard_ids) - len(merged_ids_map) - len(unbundle_map) + len(new_subjects_to_insert)

        logger.info("=" * 65)
        logger.info("PROJECTED CLEANING SUMMARY")
        logger.info("=" * 65)
        logger.info(f"  Subjects Before Cleaning     : {initial_subjects_count:,}")
        logger.info(f"  Subjects After Cleaning      : {final_subjects_count:,} (net change: {final_subjects_count - initial_subjects_count:+,})")
        logger.info(f"  Record Links Before Cleaning : {initial_links_count:,}")
        logger.info(f"  Record Links After Cleaning  : {len(final_links_set):,} (net change: {len(final_links_set) - initial_links_count:+,})")
        logger.info(f"  Garbage Links Removed        : {discarded_links_count:,}")

        # -------------------------------------------------------------------
        # Execute DB Writes if --commit is passed
        # -------------------------------------------------------------------
        if commit:
            create_safety_backups(conn, "validate")

            logger.info("\n[1/4] Inserting newly unbundled subjects into validate.subjects...")
            if new_subjects_to_insert:
                execute_values(cur, """
                    INSERT INTO validate.subjects (id, label) VALUES %s;
                """, [(sub_id, label) for label, sub_id in new_subjects_to_insert.items()], page_size=1000)

            logger.info("[2/4] Renaming in-place cleaned subjects in validate.subjects...")
            if renamed_subjects:
                execute_values(cur, """
                    UPDATE validate.subjects AS s
                    SET label = d.label
                    FROM (VALUES %s) AS d(id, label)
                    WHERE s.id = d.id::uuid;
                """, [(sid, label) for sid, label in renamed_subjects], page_size=1000)

            logger.info("[3/4] Re-populating clean junction links in validate.record_subject...")
            cur.execute("TRUNCATE TABLE validate.record_subject;")
            link_rows = [(str(uuid.uuid4()), rec_id, sub_id) for rec_id, sub_id in final_links_set]
            execute_values(cur, """
                INSERT INTO validate.record_subject (id, record_id, subject_id)
                VALUES %s;
            """, link_rows, page_size=5000)

            logger.info("[4/4] Deleting discarded and obsolete subjects from validate.subjects...")
            ids_to_remove = list(discard_ids) + list(merged_ids_map.keys()) + list(unbundle_map.keys())
            if ids_to_remove:
                cur.execute("DELETE FROM validate.subjects WHERE id = ANY(%s::uuid[]);", (ids_to_remove,))

            conn.commit()
            logger.info("=" * 65)
            logger.info("✅ SUCCESS: All cleaned subjects and links COMMITTED permanently.")
            logger.info("=" * 65)
        else:
            conn.rollback()
            logger.info("\n🔒 DRY-RUN COMPLETE: Transaction ROLLED BACK. No changes were made to the database.")
            logger.info("To apply these changes permanently, re-run with: --commit")

    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error encountered: {e}", exc_info=True)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Safely clean and standardize subjects in validate.subjects")
    parser.add_argument("--dbname", type=str, default=None, help="Target database name (default: DB_NAME from .env)")
    parser.add_argument("--commit", action="store_true", help="Execute and commit changes permanently (default: dry-run)")

    args = parser.parse_args()
    run_clean_subjects(dbname=args.dbname, commit=args.commit)
