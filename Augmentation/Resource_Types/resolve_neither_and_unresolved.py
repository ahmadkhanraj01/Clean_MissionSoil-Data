#!/usr/bin/env python3
"""
resolve_neither_and_unresolved.py
--------------------------------------------------------------------------------
Resolves resource types for the remaining 'neither' (836) and 'unresolved' (879)
records in Mission Soil / SoilWise data pipeline, and updates `validate.records`
in PostgreSQL (`msp-kh-dev`).

Resolution Strategy:
1. NEITHER (Crossref / DataCite returned a type, but neither MSP nor OGC was an exact match):
   - Direct registry-proven mappings:
     • 'JournalArticle'         -> 'Journal Article'
     • 'ConferencePaper' / 'proceedings-article' -> 'Conference Proceeding'
     • 'book-chapter'           -> 'Book Chapter'
     • 'posted-content'         -> 'Preprint' (bioRxiv, medRxiv, ChemRxiv)
     • 'Dataset'                -> 'Dataset'
     • 'ComputationalNotebook'  -> 'Computational Notebook'
     • 'OutputManagementPlan'   -> 'Output Management Plan'
     • 'peer-review'            -> 'Other'
     • 'Text' (Zenodo/DataCite) -> Context-aware: 'Report' (deliverables/whitepapers),
                                  'Conference Proceeding', or 'Dissertation' depending
                                  on academic genre.

2. UNRESOLVED (No standard DOI found; OpenAIRE IDs or EU Portal URLs):
   - EU Funding & Tenders downloadPublic URLs -> 'Report' (project deliverables).
   - Project vs Report -> 'Report' (deliverables harvested under project entities).
   - Generic 'Dataset' vs Curated OGC types -> Accept curated OGC type
     ('Education and Training Material', 'Best Practices', 'Policy Document', etc.).
   - Conference communications (HAL/OpenAIRE) -> 'Conference Proceeding'.
   - Fix 3 specific malformed/unparsed DOIs (Frontiers, EGUsphere, B2SHARE).

Features:
- Generates enriched CSV: `data/msp_type_mismatches_fully_resolved.csv`
- Safe dry-run mode by default (rolls back without touching database).
- Automatic database safety snapshot table when run with `--execute`.
--------------------------------------------------------------------------------
"""

# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config  # noqa: E402,F401  (loads .env)
# --------------------------------------------------------------------------------------------
import argparse
import os
import sys
from datetime import datetime
import pandas as pd
import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = str(_ROOT)
DEFAULT_ENV = os.path.join(PROJECT_ROOT, ".env")
INPUT_CSV = os.path.join(PROJECT_ROOT, "data", "msp_type_mismatches_with_correct_type.csv")
OUTPUT_CSV = os.path.join(PROJECT_ROOT, "data", "msp_type_mismatches_fully_resolved.csv")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Resolve 'neither' and 'unresolved' resource types and update database."
    )
    parser.add_argument(
        "--input-csv",
        default=INPUT_CSV,
        help=f"Path to input CSV (default: {INPUT_CSV})"
    )
    parser.add_argument(
        "--output-csv",
        default=OUTPUT_CSV,
        help=f"Path to save fully resolved CSV (default: {OUTPUT_CSV})"
    )
    parser.add_argument(
        "--schema",
        default="validate",
        help="Target database schema (default: validate)"
    )
    parser.add_argument(
        "--dbname",
        default=None,
        help="Target database name (default: DB_NAME from .env)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute and COMMIT changes to PostgreSQL. Omit for DRY RUN."
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating a backup table snapshot before updating."
    )
    parser.add_argument(
        "--identifier", "-i",
        default=None,
        help="Inspect and debug a single identifier step-by-step."
    )
    return parser.parse_args()


def load_db_config(dbname):
    # .env is loaded by common.db
    return db_config(dbname)


def resolve_record_type(row):
    if row.get("resolution_reason") and row.get("final_resolved_type"):
        return str(row["final_resolved_type"]).strip(), str(row["resolution_reason"]).strip()

    side = str(row.get("original_correct_side") or row.get("correct_side", "")).strip()
    msp_t = str(row.get("msp_type", "")).strip()
    ogc_t = str(row.get("ogc_type", "")).strip()
    reg_t = str(row.get("registry_type", "")).strip()
    ident = str(row.get("identifier", "")).strip()
    curr_correct = str(row.get("correct_type", "")).strip()

    # 1. Previously resolved OGC records
    if side == "ogc":
        return curr_correct if curr_correct else ogc_t, "ogc_registry_resolution"

    # 2. Previously resolved MSP records
    if side == "msp":
        return curr_correct if curr_correct else msp_t, "msp_registry_resolution"

    # 3. NEITHER: Registry provided a type, but neither MSP nor OGC was an exact string match
    if side == "neither":
        if reg_t == "JournalArticle":
            return "Journal Article", "registry_explicit_article"
        elif reg_t in ("ConferencePaper", "proceedings-article"):
            return "Conference Proceeding", "registry_explicit_conference"
        elif reg_t == "book-chapter":
            return "Book Chapter", "registry_explicit_book_chapter"
        elif reg_t == "posted-content":
            return "Preprint", "registry_explicit_preprint"
        elif reg_t == "Dataset":
            return "Dataset", "registry_explicit_dataset"
        elif reg_t == "ComputationalNotebook":
            return "Computational Notebook", "registry_explicit_notebook"
        elif reg_t == "OutputManagementPlan":
            return "Output Management Plan", "registry_explicit_omp"
        elif reg_t == "peer-review":
            return "Other", "registry_explicit_peer_review"
        elif reg_t == "Text":
            # DataCite text documents
            if msp_t in ("Conference Proceeding", "Conference object"):
                return "Conference Proceeding", "datacite_text_conference"
            elif msp_t in ("Dissertation", "Thesis"):
                return "Dissertation", "datacite_text_dissertation"
            elif ogc_t == "Report" or msp_t == "Project":
                return "Report", "datacite_text_report"
            elif ogc_t in ("Journal Article", "Article"):
                return "Journal Article", "datacite_text_article"
            else:
                return ogc_t if ogc_t else "Report", "datacite_text_fallback"
        else:
            return ogc_t if ogc_t else msp_t, "neither_fallback"

    # 4. UNRESOLVED: Non-DOI identifiers (EU portal, OpenAIRE IDs, specialized portals)
    if side == "unresolved":
        # Dynamic DOI fallback for unparsed URLs / citation formats
        import re
        from urllib.parse import unquote
        doi_match = re.search(r"(10\.\d{4,9}/[^\s\"<>?#,]+)", unquote(ident))
        if doi_match:
            extracted_doi = doi_match.group(1).rstrip(".,;)").lower()
            if "10.3389" in extracted_doi:
                return "Journal Article", "dynamic_doi_article"
            elif "10.5194" in extracted_doi:
                return "Preprint", "dynamic_doi_preprint"
            elif "10.3220" in extracted_doi:
                return "Dataset", "dynamic_doi_dataset"

        # EU Horizon/FP7 Project Deliverable PDFs
        if "ec.europa.eu/research/participants/documents/downloadPublic" in ident:
            return "Report", "eu_deliverable_report"

        # MSP labeled as Project, but OGC identified actual document report
        if msp_t == "Project" and ogc_t == "Report":
            return "Report", "project_deliverable_report"

        # HAL / OpenAIRE conference communication
        if msp_t == "Conference Proceeding" and ogc_t == "Report":
            return "Conference Proceeding", "hal_conference_proceeding"

        # Specialized academic outputs in MSP
        if msp_t == "Dissertation":
            return "Dissertation", "dissertation_specific"
        if msp_t == "Output Management Plan":
            return "Output Management Plan", "omp_specific"

        # Curated OGC types where MSP defaulted generically to 'Dataset'
        if msp_t == "Dataset":
            return ogc_t, "curated_ogc_over_generic_dataset"

        # Default to curated OGC type if specific
        if ogc_t and ogc_t.lower() != "other":
            return ogc_t, "ogc_curated_fallback"

        return msp_t if msp_t else "Other", "msp_fallback"

    return curr_correct if curr_correct else ogc_t, "default_fallback"


def create_backup_table(cur, schema):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_table = f"records_backup_neither_unres_{timestamp}"
    full_backup_name = f"{schema}.{backup_table}"
    print(f"\n[Safety Backup] Creating snapshot table: {full_backup_name}...")
    cur.execute(f"CREATE TABLE {full_backup_name} AS SELECT * FROM {schema}.records;")
    cur.execute(f"SELECT COUNT(*) FROM {full_backup_name};")
    backup_count = cur.fetchone()[0]
    print(f"✓ Backup created successfully ({backup_count:,} total records backed up).")
    return full_backup_name


def debug_single_identifier(target_ident, csv_path=None, dbname=None, schema="validate"):
    print("=" * 80)
    print("  SINGLE RECORD INSPECTOR & RESOLUTION DEBUGGER")
    print("=" * 80)
    print(f"Target Identifier : {target_ident}")

    # Robust CSV path resolution
    if csv_path is None:
        candidates = [
            os.path.join(PROJECT_ROOT, "data", "msp_type_mismatches_fully_resolved.csv"),
            os.path.join(PROJECT_ROOT, "data", "neither_and_unresolved_resolved.csv"),
            os.path.join(PROJECT_ROOT, "data", "msp_type_mismatches_with_correct_type.csv"),
        ]
        for c in candidates:
            if os.path.exists(c):
                csv_path = c
                break
    elif not os.path.exists(csv_path):
        candidates = [
            os.path.join(PROJECT_ROOT, csv_path),
            os.path.join(PROJECT_ROOT, "data", os.path.basename(csv_path)),
            os.path.join(SCRIPT_DIR, "../../", csv_path),
            os.path.join(SCRIPT_DIR, "../../data", os.path.basename(csv_path)),
        ]
        for c in candidates:
            if os.path.exists(c):
                csv_path = c
                break

    # 1. Search in CSV
    if not csv_path or not os.path.exists(csv_path):
        print(f"[ERROR] CSV not found at: {csv_path}")
        return

    print(f"Loaded CSV file   : {csv_path}")
    df = pd.read_csv(csv_path, skipinitialspace=True)
    df.columns = df.columns.str.strip()
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()

    # Exact or substring match
    match = df[df["identifier"] == target_ident]
    if match.empty:
        match = df[df["identifier"].str.lower() == target_ident.lower()]
    if match.empty:
        match = df[df["identifier"].str.contains(target_ident, regex=False, case=False)]

    if match.empty:
        print(f"\n1. CSV MISMATCH STATUS:\n   ✗ Identifier '{target_ident}' was NOT found in mismatch CSV.")
    else:
        row = match.iloc[0]
        resolved_type, reason = resolve_record_type(row)

        if resolved_type.lower() == str(row.get("ogc_type", "")).strip().lower():
            decided_side = "ogc"
        elif resolved_type.lower() == str(row.get("msp_type", "")).strip().lower():
            decided_side = "msp"
        else:
            decided_side = "registry"

        print(f"\n1. CSV METADATA & MISMATCH PROFILE:")
        print(f"   • Matched Identifier : {row['identifier']}")
        print(f"   • Title              : {row.get('title', 'N/A')}")
        print(f"   • MSP Type (Solr)    : {row.get('msp_type', 'N/A')}")
        print(f"   • OGC Type           : {row.get('ogc_type', 'N/A')}")
        print(f"   • Registry Source    : {row.get('registry_src', 'N/A')}")
        print(f"   • Registry Type      : {row.get('registry_type', 'N/A')}")
        orig_side = row.get("original_correct_side") or row.get("correct_side", "N/A")
        print(f"   • Original Side Tag  : {orig_side}")

        print(f"\n2. STEP-BY-STEP RESOLUTION DECISION:")
        print(f"   • Applied Rule Reason: {reason}")
        print(f"   • Decided Resource Type: '{resolved_type}'")
        print(f"   • Decided Side       : '{decided_side}'")

    # 2. Query Live Database
    db_config = load_db_config(dbname)
    print(f"\n3. LIVE DATABASE STATUS ({dbname} -> {schema}.records):")
    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        cur.execute(f"SET search_path TO {schema}, public;")
        cur.execute(f"""
            SELECT id, identifier, title, resource_type, url, updated_at 
            FROM {schema}.records 
            WHERE identifier = %s;
        """, (target_ident,))
        db_row = cur.fetchone()

        if db_row:
            db_id, db_ident, db_title, db_type, db_url, db_updated = db_row
            print(f"   ✓ Record FOUND in {schema}.records (UUID: {db_id})")
            print(f"   • Current DB Type    : '{db_type}'")
            print(f"   • Source URL         : {db_url}")
            print(f"   • Last Updated In DB : {db_updated}")
            if not match.empty:
                if str(db_type) == str(resolved_type):
                    print(f"   • Comparison Status  : ✓ ALREADY UP TO DATE (matches resolved type)")
                else:
                    print(f"   • Comparison Status  : ⚠ UPDATE NEEDED: '{db_type}' -> '{resolved_type}'")
        else:
            print(f"   ✗ Identifier NOT found in {schema}.records table.")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"   [DB Query Error] Could not connect or query DB: {e}")

    print("=" * 80)


def main():
    args = parse_args()

    # If --identifier is passed, run single record debugger and exit
    if args.identifier:
        debug_single_identifier(args.identifier.strip(), args.input_csv, args.dbname, args.schema)
        return

    print("=" * 80)
    print("  MISSION SOIL: RESOLVE 'NEITHER' & 'UNRESOLVED' RESOURCE TYPES")
    print("=" * 80)
    print(f"Mode          : {'[LIVE COMMIT]' if args.execute else '[DRY RUN - NO CHANGES COMMITTED]'}")
    print(f"Input CSV     : {args.input_csv}")
    print(f"Output CSV    : {args.output_csv}")
    print(f"Target DB     : {args.dbname} (schema: {args.schema})")

    # 1. Load Input CSV
    if not os.path.exists(args.input_csv):
        print(f"\n[ERROR] Input CSV not found: {args.input_csv}")
        sys.exit(1)

    print("\n[Step 1] Loading and applying resolution rules to mismatches...")
    df = pd.read_csv(args.input_csv, skipinitialspace=True)
    df.columns = df.columns.str.strip()
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()
    print(f"• Total rows in input CSV: {len(df):,}")

    resolutions = df.apply(resolve_record_type, axis=1)
    df["final_resolved_type"] = [r[0] for r in resolutions]
    df["resolution_reason"] = [r[1] for r in resolutions]

    # Preserve original side before updating
    df["original_correct_side"] = df["correct_side"]

    # Directly update correct_type
    df["correct_type"] = df["final_resolved_type"]

    # Directly update correct_side: 'ogc', 'msp', or 'registry'
    def determine_side(row):
        res_t = str(row["correct_type"]).strip().lower()
        ogc_t = str(row["ogc_type"]).strip().lower()
        msp_t = str(row["msp_type"]).strip().lower()
        if res_t == ogc_t:
            return "ogc"
        elif res_t == msp_t:
            return "msp"
        else:
            return "registry"

    df["correct_side"] = df.apply(determine_side, axis=1)

    # Save master enriched CSV
    df.to_csv(args.output_csv, index=False)
    print(f"✓ Saved fully resolved records to: {args.output_csv}")

    # Also save dedicated CSV for neither + unresolved
    dedicated_csv = os.path.join(os.path.dirname(args.output_csv), "neither_and_unresolved_resolved.csv")
    sub_neither_unres = df[df["original_correct_side"].isin(["neither", "unresolved"])].copy()
    sub_neither_unres.to_csv(dedicated_csv, index=False)
    print(f"✓ Saved dedicated resolved CSV to: {dedicated_csv}")

    # Summary of resolutions for neither & unresolved
    print("\nResolution breakdown for NEITHER (836 records):")
    sub_neither = df[df["original_correct_side"] == "neither"]
    for rtype, count in sub_neither["correct_type"].value_counts().items():
        print(f"  • {rtype:<30}: {count:,}")
    print("New correct_side for NEITHER:")
    for side, count in sub_neither["correct_side"].value_counts().items():
        print(f"    -> {side:<15}: {count:,}")

    print("\nResolution breakdown for UNRESOLVED (879 records):")
    sub_unres = df[df["original_correct_side"] == "unresolved"]
    for rtype, count in sub_unres["correct_type"].value_counts().items():
        print(f"  • {rtype:<30}: {count:,}")
    print("New correct_side for UNRESOLVED:")
    for side, count in sub_unres["correct_side"].value_counts().items():
        print(f"    -> {side:<15}: {count:,}")

    # 2. Connect to Database to check current differences
    db_config = load_db_config(args.dbname)
    print(f"\n[Step 2] Connecting to PostgreSQL ({db_config['host']}:{db_config['port']}/{db_config['dbname']})...")
    conn = psycopg2.connect(**db_config)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        cur.execute(f"SET search_path TO {args.schema}, public;")

        # Fetch current resource_type for all records
        cur.execute(f"SELECT identifier, resource_type FROM {args.schema}.records;")
        db_records = dict(cur.fetchall())
        print(f"• Total records in {args.schema}.records: {len(db_records):,}")

        # 3. Identify records needing update
        updates_to_perform = []
        for _, row in df.iterrows():
            ident = str(row["identifier"]).strip()
            target_type = row["final_resolved_type"]
            if ident in db_records:
                curr_type = db_records[ident]
                if curr_type != target_type:
                    updates_to_perform.append({
                        "identifier": ident,
                        "old_type": curr_type,
                        "new_type": target_type,
                        "side": row["correct_side"],
                        "reason": row["resolution_reason"]
                    })

        print(f"\n[Step 3] Comparing with Database State:")
        print(f"• Total rows needing DB update: {len(updates_to_perform):,} records")
        from collections import Counter
        side_counts = Counter(u["side"] for u in updates_to_perform)
        for s, cnt in side_counts.items():
            print(f"    - From '{s}': {cnt:,} updates")

        if not updates_to_perform:
            print("\n✓ No updates needed! All records in DB already match their resolved types.")
            return

        print("\nBreakdown of changes to be applied:")
        change_pairs = Counter(f"{u['old_type']} -> {u['new_type']}" for u in updates_to_perform)
        for pair, cnt in change_pairs.most_common(12):
            print(f"  • {pair:<45}: {cnt:,} records")

        # 4. Create safety backup if executing
        if args.execute and not args.no_backup:
            create_backup_table(cur, args.schema)

        # 5. Execute batch update
        update_batch = [(u["new_type"], u["identifier"]) for u in updates_to_perform]
        print(f"\n[Step 4] Executing UPDATE for {len(update_batch):,} records...")
        update_sql = f"""
            UPDATE {args.schema}.records 
            SET resource_type = %s,
                updated_at = NOW() 
            WHERE identifier = %s;
        """
        execute_batch(cur, update_sql, update_batch, page_size=1000)

        # 6. Verify in DB
        cur.execute(f"""
            SELECT resource_type, COUNT(*) 
            FROM {args.schema}.records 
            WHERE identifier IN %s 
            GROUP BY resource_type 
            ORDER BY COUNT(*) DESC;
        """, (tuple(u["identifier"] for u in updates_to_perform),))
        print("\n• New resource_type distribution for updated records:")
        for rtype, count in cur.fetchall():
            print(f"    - {str(rtype):<30}: {count:,}")

        # 7. Commit or Rollback
        print("\n" + "=" * 80)
        if args.execute:
            conn.commit()
            print("✓ SUCCESS: All changes COMMITTED to the database!")
            print(f"✓ Total records updated: {len(update_batch):,}")
        else:
            conn.rollback()
            print("✓ DRY RUN COMPLETE: Transaction was intentionally ROLLED BACK.")
            print("  No changes were saved to the database.")
            print("  To apply changes permanently, run with `--execute`:")
            print(f"    .venv/bin/python {os.path.relpath(__file__, os.getcwd())} --execute")
        print("=" * 80)

    except Exception as exc:
        conn.rollback()
        print(f"\n[FATAL ERROR] An exception occurred. Rolled back.\nDetails: {exc}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
