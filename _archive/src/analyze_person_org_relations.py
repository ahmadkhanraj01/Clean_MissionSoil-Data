import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '../..'))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')

# Candidate file paths for Solr records
candidate_files = [
    os.path.join(DATA_DIR, "Sep25_solrData.json"),
    os.path.join(DATA_DIR, "unified_clean_solrData.json"),
    os.path.join(DATA_DIR, "raw", "new_solr_all_records.json"),
    os.path.join(DATA_DIR, "July14_solrData.json")
]

target_file = next((f for f in candidate_files if os.path.exists(f)), None)
if not target_file:
    raise FileNotFoundError("No Solr records JSON file found in data directory.")

print(f"Analyzing relations in: {target_file}")
with open(target_file, "r", encoding="utf-8") as f:
    raw_data = json.load(f)

# Handle list or solr response docs wrapper
if isinstance(raw_data, list):
    records = raw_data
elif isinstance(raw_data, dict) and "response" in raw_data and "docs" in raw_data["response"]:
    records = raw_data["response"]["docs"]
elif isinstance(raw_data, dict) and "records" in raw_data:
    records = raw_data["records"]
else:
    records = [raw_data]

total_with_both = 0
matching_lengths = 0
one_org_multiple_persons = 0
one_person_multiple_orgs = 0

for r in records:
    persons = set(r.get("persons") or []) | set(r.get("contact_persons") or [])
    orgs = set(r.get("organizations") or []) | set(r.get("contact_organizations") or [])
    
    if persons and orgs:
        total_with_both += 1
        if len(persons) == len(orgs):
            matching_lengths += 1
        elif len(orgs) == 1 and len(persons) > 1:
            one_org_multiple_persons += 1
        elif len(persons) == 1 and len(orgs) > 1:
            one_person_multiple_orgs += 1

print(f"Total records with BOTH persons and orgs: {total_with_both}")
print(f"Records where count(persons) == count(orgs): {matching_lengths}")
print(f"Records with 1 org and multiple persons: {one_org_multiple_persons} (Safe to map all persons to the 1 org)")
print(f"Records with 1 person and multiple orgs: {one_person_multiple_orgs} (Safe to map the 1 person to all orgs)")

