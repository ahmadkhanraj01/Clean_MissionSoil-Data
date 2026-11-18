"""
Fetch identifier and title from the records table in msp-kh-dev database
and save to msp-kh-dev.json
"""

# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config  # noqa: E402,F401  (loads .env)
# --------------------------------------------------------------------------------------------
import json
import os
import psycopg2

DB_CONFIG = db_config()

# compare_msp_vs_ogc_types.py reads data/msp-kh-dev.json (the original wrote msp-kh-dev2.json)
OUTPUT_FILE = os.environ.get("MSP_RECORDS_JSON", str(DATA_DIR / "msp-kh-dev.json"))

def fetch_records():
    print(f"Connecting to database '{DB_CONFIG['dbname']}' at {DB_CONFIG['host']}:{DB_CONFIG['port']}...")
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    query = "SELECT identifier, title, abstract, resource_type FROM validate.records ORDER BY identifier;"
    print(f"Executing: {query}")
    cursor.execute(query)

    rows = cursor.fetchall()
    colnames = [desc[0] for desc in cursor.description]
    print(f"Fetched {len(rows)} records.")

    records = [dict(zip(colnames, row)) for row in rows]
    cursor.close()
    conn.close()
    return records


def save_to_json(records, output_path):
    payload = {
        "database": DB_CONFIG["dbname"],
        "table": "records",
        "fields": ["identifier", "title","abstract","resource_type"],
        "total_records": len(records),
        "records": records,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(records)} records to '{output_path}'")


if __name__ == "__main__":
    records = fetch_records()
    save_to_json(records, OUTPUT_FILE)
    print("Done!")
