"""
Insert EU-FarmBook projects and contributions into harvest.items.
- Projects:      itemtype='project',      source='EUFARMBOOK'
- Contributions: itemtype='contribution', source='EUFARMBOOK'

Contributions are stored as schema.org JSON (resulttype='schema.org') so that
process.py in md-harmonization can parse them directly via import_metadata('schema-org')
without any special-casing.

Linkage: both rows share the same grant_number in the `project` column.
"""

import json, hashlib, asyncio, sys
from pathlib import Path
import os 

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
load_dotenv()

_host = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST")
_port = os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT", "5432")
_user = os.getenv("DB_USER") or os.getenv("POSTGRES_USER")
_password = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")
_dbname = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB")

_default_url = f"postgresql://{_user}:{_password}@{_host}:{_port}/{_dbname}" if (_user and _password and _host) else ""
DB_URL = os.getenv("DB_URL") or _default_url

PROJECTS_JSON      = Path(__file__).parent / "eufarmbook_projects.json" if (Path(__file__).parent / "eufarmbook_projects.json").exists() else Path(__file__).parent.parent / "data" / "eufarmbook_projects.json"
CONTRIBUTIONS_JSON = Path(__file__).parent / "eufarmbook_contributions2.json" if (Path(__file__).parent / "eufarmbook_contributions2.json").exists() else Path(__file__).parent.parent / "data" / "eufarmbook_contributions2.json"

SOURCE = "EUFARMBOOK"

INSERT_SQL = """
    INSERT INTO harvest.items
        (identifier, identifiertype, uri, resultobject, resulttype,
         itemtype, title, source, project, date, hash)
    VALUES
        (:identifier, :identifiertype, :uri, :resultobject, :resulttype,
         :itemtype, :title, :source, :project, :date, :hash)
    ON CONFLICT (hash) DO UPDATE SET
        resultobject = EXCLUDED.resultobject,
        resulttype   = EXCLUDED.resulttype
"""

def make_hash(identifier: str, source: str) -> str:
    return hashlib.md5(f"{identifier}{source}".encode()).hexdigest()


def to_schema_org(contrib: dict) -> dict:
    """
    Convert a raw EU-FarmBook contribution dict into a schema.org-shaped JSON
    object. process.py routes resulttype='schema.org' to
    import_metadata('schema-org', txt), which expects this shape.
    """
    authors = contrib.get("authors") or []
    # authors may be a list or a single string
    if isinstance(authors, str):
        authors = [authors]

    keywords = contrib.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]

    schema = {
        "@context": "https://schema.org",
        "@type":    "CreativeWork",
        "identifier": contrib.get("identifier") or contrib.get("doi", ""),
        "@id":        contrib.get("doi") or contrib.get("identifier", ""),
        "url":        contrib.get("doi"),
        "name":       contrib.get("title"),
        "description": contrib.get("description"),
        "keywords":   keywords,
        "inLanguage": contrib.get("language"),
        "dateCreated": contrib.get("creation_date"),
        "license":    contrib.get("license"),
        # file/document download link
        "contentUrl": contrib.get("file_type_link"),
        # purpose maps to about
        "about":      contrib.get("purpose"),
        # location of the contribution subject
        "spatialCoverage": contrib.get("location"),
    }

    res_type = contrib.get("resource_type")
    if res_type:
        schema["additionalType"] = res_type
        schema["genre"]          = res_type
        schema["resource_type"]  = res_type

    if authors:
        schema["author"] = [
            {"@type": "Person", "name": a} for a in authors
        ]

    # strip None values to keep the object clean
    return {k: v for k, v in schema.items() if v not in (None, [], "")}


async def insert_contributions(db: databases.Database, contribs: list) -> int:
    values_list = []
    skipped = 0
    for contrib in contribs:
        identifier = contrib.get("identifier") or contrib.get("doi", "")
        if not identifier:
            skipped += 1
            continue

        schema_obj = to_schema_org(contrib)
        h = make_hash(identifier, SOURCE)

        values_list.append({
            "identifier":     identifier,
            "identifiertype": "eufarmbook_id",
            "uri":            contrib.get("doi"),           # contribution page URL
            "resultobject":   json.dumps(schema_obj),       # schema.org JSON ✅
            "resulttype":     "schema.org",                 # process.py routes here ✅
            "itemtype":       contrib.get("resource_type") or "contribution",
            "title":          contrib.get("title"),
            "source":         SOURCE,
            "project":        contrib.get("project_grantnr"),  # links to parent project
            "date":           contrib.get("creation_date"),
            "hash":           h,
        })

    if values_list:
        await db.execute_many(INSERT_SQL, values_list)

    if skipped:
        print(f"  Skipped {skipped} contributions with no identifier.")
    return len(values_list)


async def main():
    print("Loading JSON files...")
    contribs = json.loads(CONTRIBUTIONS_JSON.read_text(encoding="utf-8"))
    print(f"  Contributions: {len(contribs)}")

    async with databases.Database(DB_URL) as db:
        print("\nInserting contributions as schema.org JSON...")
        n_contrib = await insert_contributions(db, contribs)
        print(f"  Done: {n_contrib} contributions inserted/updated (schema.org format)")

    print("\nVerifying counts in DB...")
    async with databases.Database(DB_URL) as db:
        r = await db.fetch_all("""
            SELECT itemtype, resulttype, COUNT(*) as cnt
            FROM harvest.items
            WHERE source = 'EUFARMBOOK'
            GROUP BY itemtype, resulttype
            ORDER BY itemtype
        """)
        for row in r:
            print(f"  {row['itemtype']:<15} | {row['resulttype']:<20} → {row['cnt']} rows")

    print("\nAll done! Contributions are now stored as schema.org JSON.")
    print("Run process.py with PROCESS_SOURCES=EUFARMBOOK to harmonize them into metadata.records.")


if __name__ == "__main__":
    asyncio.run(main())
