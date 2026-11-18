import json, sys, hashlib, re, os
import yaml
from datetime import datetime
from dotenv import load_dotenv

# Load env
load_dotenv()
sys.path.append('utils')
# pyrefly: ignore [missing-import]
from database import dbInit

MISSING_PROJECTS = [
    "Crop-MATCHING",
    "FreeBirds",
    "GrazyDaiSy",
    "GREENRESILIENT",
    "POWER",
    "ProOrg",
    "ProRefine",
    "ProYoungStock"
]

def get_best_grant(p):
    url = (p.get("eufarmbook_url") or "").strip()
    m4 = re.search(r"/projects/([a-f0-9]{10,})", url)
    if m4:
        return f"eufb-{m4.group(1)[:12]}"
    return "UNKNOWN"

def build_schema_org(p):
    # Map project JSON to schema.org
    schema = {
        "@context": "https://schema.org",
        "@type": "ResearchProject",
        "name": p.get("title", ""),
        "description": p.get("description", ""),
        "url": p.get("eufarmbook_url", ""),
        "funder": {"@type": "Organization", "name": p.get("project_type", "")},
        "locationCreated": {"@type": "Place", "name": p.get("country", "")}
    }
    
    if p.get("start_date") and p.get("start_date") != "–":
        schema["startDate"] = p.get("start_date")
    if p.get("end_date") and p.get("end_date") != "–":
        schema["endDate"] = p.get("end_date")
        
    # Add contacts
    orgs = p.get("cordis_organisations", [])
    if orgs:
        authors = []
        for org in orgs:
            authors.append({"@type": "Organization", "name": org.get("name", "")})
        schema["author"] = authors
        
    return schema

def main():
    json_path = "../harvesters/cordis-projects/eufarmbook_projects.json"
    if not os.path.exists(json_path):
        print(f"File not found: {json_path}")
        return
        
    with open(json_path, 'r', encoding='utf-8') as f:
        all_projects = json.load(f)
        
    # Filter only the missing ones
    target_projects = [p for p in all_projects if p.get("title") in MISSING_PROJECTS]
    
    print(f"Found {len(target_projects)} of {len(MISSING_PROJECTS)} missing projects in JSON.")
    
    dbconn = dbInit()
    inserted = 0
    with dbconn.cursor() as cur:
        for p in target_projects:
            identifier = get_best_grant(p)
            schema_obj = build_schema_org(p)
            resultobject = json.dumps(schema_obj, ensure_ascii=False)
            hashcode = hashlib.md5(f"{identifier}EUFARMBOOK".encode()).hexdigest()
            
            values = {
                'identifier': identifier,
                'identifiertype': 'eufarmbook_id',
                'uri': p.get("eufarmbook_url", ""),
                'resultobject': resultobject,
                'resulttype': 'schema.org',
                'hash': hashcode,
                'source': 'EUFARMBOOK',
                'itemtype': 'project',
                'title': p.get("title", ""),
                'date': p.get("start_date") if p.get("start_date") != "–" else None,
                'project': identifier
            }
            
            try:
                # Upsert query
                fields = list(values.keys())
                cols = ",".join(fields)
                vals_placeholder = ",".join([f"%({f})s" for f in fields])
                set_clause = ",".join([f"{f}=EXCLUDED.{f}" for f in fields if f != 'hash'])
                
                query = f"""
                    INSERT INTO harvest.items ({cols}) 
                    VALUES ({vals_placeholder})
                    ON CONFLICT (hash) 
                    DO UPDATE SET {set_clause};
                """
                cur.execute(query, values)
                print(f"Inserted: {p.get('title')} ({identifier})")
                inserted += 1
            except Exception as e:
                print(f"Error inserting {identifier}: {e}")
                
    dbconn.commit()
    dbconn.close()
    print(f"\nDone! Successfully inserted {inserted} projects into harvest.items.")

if __name__ == "__main__":
    main()
