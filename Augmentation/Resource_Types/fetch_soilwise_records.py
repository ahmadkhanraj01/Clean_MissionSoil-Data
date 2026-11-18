# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config  # noqa: E402,F401  (loads .env)
# --------------------------------------------------------------------------------------------
import requests
import json
import time
import os

# Import configuration
try:
    from common.config import RECORD_TYPES, DATA_DIR, CATALOGUE_ITEMS_URL, PAGE_LIMIT, REQUEST_DELAY
except ImportError:
    # Fallback default values if run directly without config.py in path
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    DATA_DIR = os.path.join(BASE_DIR, "data")
    CATALOGUE_ITEMS_URL = "https://repository.soilwise-he.eu/cat/collections/metadata:main/items"
    PAGE_LIMIT = 50
    REQUEST_DELAY = 0.2
    RECORD_TYPES = [
        "Dataset",
        "Journal Article",
        "Report",
        "Service",
        "Project",
        "Software",
        "Education and Training Material",
        "Best Practices",
        "Policy Document",
        "Scientific",
        "Interview",
        "Conference Proceeding",
        "Computational Notebook",
        "Text",
        "Data Paper",
    ]


def fetch_records_for_type(record_type, output_dir=DATA_DIR):
    """
    Fetch all records matching 'record_type' from SoilWise HE Catalogue API
    and save them to a JSON file in output_dir.
    """
    # Ensure data folder exists
    os.makedirs(output_dir, exist_ok=True)

    # Format filename (e.g., Dataset_records.json, Report_records.json)
    safe_name = record_type.replace(" ", "_")
    output_file = os.path.join(output_dir, f"{safe_name}_records.json")

    headers = {
        "User-Agent": "SoilwiseHarvester/1.0",
        "Accept": "application/json"
    }

    all_features = []
    offset = 0
    total_matched = None
    page_num = 1

    print(f"\n{'=' * 60}")
    print(f"▶ Starting Type : '{record_type}'")
    print(f"▶ Output File   : '{output_file}'")
    print(f"{'=' * 60}")

    while True:
        params = {
            "f": "json",
            "type": record_type,
            "limit": PAGE_LIMIT,
            "offset": offset
        }

        try:
            response = requests.get(CATALOGUE_ITEMS_URL, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Error fetching page {page_num} (offset {offset}): {e}")
            break

        if total_matched is None:
            total_matched = data.get("numberMatched", 0)
            print(f"  ℹ Total matching records found on server: {total_matched}")
            if total_matched == 0:
                print("  ℹ No records found for this type. Skipping.")
                break

        features = data.get("features", [])
        number_returned = data.get("numberReturned", len(features))

        if not features:
            break

        all_features.extend(features)
        print(f"  → Page {page_num:03d} (offset {offset:05d}): +{len(features)} records | Total: {len(all_features)} / {total_matched}")

        # Stop when all matched records are collected
        if len(all_features) >= total_matched or number_returned == 0:
            break

        offset += number_returned
        page_num += 1

        if REQUEST_DELAY > 0:
            time.sleep(REQUEST_DELAY)

    # Save to JSON
    output_payload = {
        "type_filter": record_type,
        "total_records": len(all_features),
        "total_matched": total_matched,
        "features": all_features
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)

    print(f"✔ Saved {len(all_features)} records to '{output_file}'")
    return output_file


def fetch_all_configured_types():
    """
    Loops through all types in RECORD_TYPES and saves each to its own JSON file.
    """
    print(f"\n========================================================")
    print(f" Starting Batch Harvest for {len(RECORD_TYPES)} Types")
    print(f" Target Folder: {DATA_DIR}")
    print(f" Types: {', '.join(RECORD_TYPES)}")
    print(f"========================================================")

    for idx, r_type in enumerate(RECORD_TYPES, 1):
        print(f"\n[{idx}/{len(RECORD_TYPES)}] Processing '{r_type}'...")
        fetch_records_for_type(r_type)

    print(f"\n🎉 All types completed successfully! Files saved in '{DATA_DIR}'.\n")


if __name__ == "__main__":
    fetch_all_configured_types()
