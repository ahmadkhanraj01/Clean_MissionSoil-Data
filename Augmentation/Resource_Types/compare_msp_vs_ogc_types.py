"""
Compare MSP-KH-DEV records against OGC_records.json.

For each MSP record that can be matched in the OGC catalogue, compare:
  - msp_type  : records.resource_type  (from msp-kh-dev DB)
  - ogc_type  : feature.properties.type (from OGC_records.json)

Output CSV contains only rows where msp_type != ogc_type.

Matching strategy (in priority order):
  1. MSP identifier == OGC feature.id              (direct UUID/DOI match)
  2. MSP identifier found in OGC feature link hrefs (e.g. DOI as a URL in links)
  3. MSP title == OGC title  AND  OGC links contain the MSP identifier
     (validated title match — prevents false positives from shared titles)
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
import re
import csv
import urllib.parse

# ── Paths ──────────────────────────────────────────────────────────────────────
DATA_DIR     = str(DATA_DIR)

MSP_DEV_JSON = os.path.join(DATA_DIR, "msp-kh-dev.json")
OGC_JSON     = os.path.join(DATA_DIR, "OGC_records.json")
OUTPUT_CSV   = os.path.join(DATA_DIR, "msp_type_mismatches.csv")

# ── Helpers ────────────────────────────────────────────────────────────────────
def normalize_title(t):
    if not t:
        return ""
    return re.sub(r"\s+", " ", t.strip().lower())

def normalize_url(url):
    """Decode percent-encoding and strip trailing slash for consistent comparison."""
    if not url:
        return ""
    return urllib.parse.unquote(url.strip()).rstrip("/")

def extract_hrefs(feat):
    """Return a set of normalized hrefs from an OGC feature's links array."""
    hrefs = set()
    for link in feat.get("links", []):
        href = link.get("href", "") if isinstance(link, dict) else str(link)
        if href:
            hrefs.add(normalize_url(href))
    return hrefs

# ── Step 1: Load MSP-KH-DEV records ───────────────────────────────────────────
print("Loading msp-kh-dev.json ...")
with open(MSP_DEV_JSON, encoding="utf-8") as f:
    msp_data = json.load(f)

msp_records = msp_data.get("records", [])
print(f"  → {len(msp_records)} records loaded from {MSP_DEV_JSON}")

# ── Step 2: Load and index OGC_records.json ────────────────────────────────────
print("Loading OGC_records.json ...")
with open(OGC_JSON, encoding="utf-8") as f:
    ogc_data = json.load(f)

features = ogc_data.get("features", [])
print(f"  → {len(features)} OGC features loaded")

# Build three indexes:
#   ogc_by_id    : feature.id (UUID/DOI) → (ogc_type, hrefs)
#   ogc_by_url   : each link href        → (ogc_type, feature_id)
#   ogc_by_title : normalized title      → (ogc_type, hrefs)
ogc_by_id    = {}   # lower(id)    → {"type": ..., "hrefs": set(), "id": ...}
ogc_by_url   = {}   # lower(href)  → {"type": ..., "id": ...}
ogc_by_title = {}   # norm title   → {"type": ..., "hrefs": set(), "id": ...}

for feat in features:
    fid   = str(feat.get("id", "")).strip()
    props = feat.get("properties", {})
    ftype = props.get("type", "")
    ftitle_norm = normalize_title(props.get("title", ""))
    hrefs = extract_hrefs(feat)

    entry = {"type": ftype, "hrefs": hrefs, "id": fid}

    if fid:
        ogc_by_id[fid.lower()] = entry

    # Index every href → points back to this feature
    for href in hrefs:
        ogc_by_url[href.lower()] = entry

    # Title index (last-write-wins for duplicates)
    if ftitle_norm:
        ogc_by_title[ftitle_norm] = entry

print(f"  → {len(ogc_by_id)} OGC features indexed by id")
print(f"  → {len(ogc_by_url)} OGC href entries indexed")

# ── Step 3: Compare MSP resource_type vs OGC type for each MSP record ─────────
print("Comparing types ...")

mismatches = []
stats = {
    "no_msp_type": 0,
    "no_ogc_match": 0,
    "same_type": 0,
    "diff_type": 0,
    "by_id": 0,
    "by_href": 0,
    "by_title_validated": 0,
}

for rec in msp_records:
    identifier  = (rec.get("identifier") or "").strip()
    title       = (rec.get("title") or "")
    msp_type    = (rec.get("resource_type") or "").strip()

    if not identifier:
        continue

    # Skip MSP records with no resource_type — nothing to compare
    if not msp_type:
        stats["no_msp_type"] += 1
        continue

    norm_id    = normalize_url(identifier)
    norm_title = normalize_title(title)

    # ── Find matching OGC entry ────────────────────────────────────────────────
    ogc_entry      = None
    match_method   = None

    # 1. Direct feature.id match (case-insensitive)
    ogc_entry = ogc_by_id.get(identifier.lower())
    if ogc_entry:
        match_method = "id"

    # 2. MSP identifier appears as a URL in OGC link hrefs
    #    e.g. identifier = "10.1002/jpln.200800317"
    #         OGC link   = "http://dx.doi.org/10.1002/jpln.200800317"
    if not ogc_entry:
        ogc_entry = ogc_by_url.get(norm_id.lower())
        if not ogc_entry and norm_id:
            # Also try the DOI as a dx.doi.org URL
            for candidate in [
                f"https://doi.org/{identifier}",
                f"http://doi.org/{identifier}",
                f"http://dx.doi.org/{identifier}",
                f"https://dx.doi.org/{identifier}",
            ]:
                norm_cand = normalize_url(candidate)
                ogc_entry = ogc_by_url.get(norm_cand.lower())
                if ogc_entry:
                    break
        if ogc_entry:
            match_method = "href"

    # 3. Validated title match: title matches AND OGC feature links contain
    #    the MSP identifier (prevents false positives from shared titles)
    if not ogc_entry and norm_title:
        title_entry = ogc_by_title.get(norm_title)
        if title_entry:
            id_in_href = any(
                identifier.lower() in href.lower()
                for href in title_entry["hrefs"]
            )
            if id_in_href:
                ogc_entry = title_entry
                match_method = "title_validated"

    if not ogc_entry:
        stats["no_ogc_match"] += 1
        continue

    ogc_type = (ogc_entry.get("type") or "").strip()
    stats[f"by_{match_method}"] = stats.get(f"by_{match_method}", 0) + 1

    # ── Compare types ──────────────────────────────────────────────────────────
    if msp_type.lower() == ogc_type.lower():
        stats["same_type"] += 1
    else:
        stats["diff_type"] += 1
        mismatches.append({
            "identifier":   identifier,
            "title":        title,
            "msp_type":     msp_type,
            "ogc_type":     ogc_type,
            "match_method": match_method,
        })

# ── Step 4: Print stats ────────────────────────────────────────────────────────
print(f"\n  Results:")
print(f"    MSP records with no resource_type : {stats['no_msp_type']}")
print(f"    No OGC match found                : {stats['no_ogc_match']}")
print(f"    Same type (excluded from CSV)     : {stats['same_type']}")
print(f"    Different type → saved to CSV     : {stats['diff_type']}")
print(f"\n  Match methods used:")
print(f"    Direct feature.id match           : {stats.get('by_id', 0)}")
print(f"    OGC link href contains MSP id     : {stats.get('by_href', 0)}")
print(f"    Validated title match             : {stats.get('by_title_validated', 0)}")

# ── Step 5: Save CSV ───────────────────────────────────────────────────────────
fieldnames = ["identifier", "title", "msp_type", "ogc_type", "match_method"]
with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(mismatches)

print(f"\n✔ Saved {len(mismatches)} mismatched records to:\n  {OUTPUT_CSV}")
