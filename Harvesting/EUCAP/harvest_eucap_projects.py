#!/usr/bin/env python3
"""
harvest_eucap_projects.py

Single, unified end-to-end pipeline for EU CAP Network projects:
1. Harvests project metadata from EU CAP Network (in-memory, no intermediate JSON files).
2. Resolves official acronyms, grant agreement numbers, and CORDIS URLs.
3. Ingests directly into PostgreSQL `harvest.projects` table (`msp-kh-dev`).
4. Queries CORDIS SPARQL endpoint in-memory to enrich with partner institutions,
   abstracts, dates, and geographic locations.
5. Builds standard MCF YAML metadata and inserts directly into `harvest.items`.

Usage:
  # Fast execution using in-memory projects and CORDIS enrichment:
  python harvest_eucap_projects.py

  # Test mode (dry-run without saving changes to DB):
  python harvest_eucap_projects.py --dry-run

  # Live scrape from EU CAP Network directly into DB:
  python harvest_eucap_projects.py --scrape
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
import json
import time
import random
import hashlib
import argparse
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from itertools import islice
from pathlib import Path

import yaml
import requests
import psycopg2
from psycopg2.extras import execute_values
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("harvest_eucap_projects")

# Environment is loaded by common.db (repo-root .env); data files live in <repo>/data

DEFAULT_HOST     = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST")
DEFAULT_PORT     = int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or 5432)
DEFAULT_DBNAME   = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB")
DEFAULT_USER     = os.getenv("DB_USER") or os.getenv("POSTGRES_USER")
DEFAULT_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")

SPARQL_ENDPOINT = "https://cordis.europa.eu/datalab/sparql"
SPARQL_BATCH_SIZE = 15

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
]

# Authoritative CORDIS Grant ID & Acronym mappings for EU CAP projects
SUPPLEMENTAL_MAPPING = {
    "PLAID Peer-to-Peer learning:accessing innovation through demonstration": {
        "acronym": "PLAID", "grant": "727388", "cordis": "https://cordis.europa.eu/project/id/727388"
    },
    "Strengthening Organic Farming Competitiveness Via Organic Seeds Breeding Production and Availability   ORGAFARM": {
        "acronym": "LIVESEED", "grant": "727230", "cordis": "https://cordis.europa.eu/project/id/727230"
    },
    "Best markets for the exploitation of innovative sustainable food packaging solutions": {
        "acronym": "MYPACK", "grant": "774265", "cordis": "https://cordis.europa.eu/project/id/774265"
    },
    "Sino-EU Soil Observatory for intelligent Land Use Management": {
        "acronym": "SIEUSOIL", "grant": "818346", "cordis": "https://cordis.europa.eu/project/id/818346"
    },
    "TECH4EFFECT - Knowledge and Technologies for Effective Wood Procurement": {
        "acronym": "TECH4EFFECT", "grant": "720757", "cordis": "https://cordis.europa.eu/project/id/720757"
    },
    "Pro-Enrich: Development of novel functional proteins and bioactive ingredients from rapeseed, olive, tomato and citrus fruit side streams.": {
        "acronym": "Pro-Enrich", "grant": "792050", "cordis": "https://cordis.europa.eu/project/id/792050"
    },
    "SUSFERT - Sustainable, multifunctional fertilisers for plant phosphorus and iron supply fitting into existing production process.": {
        "acronym": "SUSFERT", "grant": "792021", "cordis": "https://cordis.europa.eu/project/id/792021"
    },
    "EcoStack - Stacking of ecosystem services: mechanisms and interactions for optimal crop protection, pollination enhancement, and productivity": {
        "acronym": "EcoStack", "grant": "773554", "cordis": "https://cordis.europa.eu/project/id/773554"
    },
    "Organic Farming Innovations Network Europe": {
        "acronym": "OH-FINE", "grant": "101183127", "cordis": "https://cordis.europa.eu/project/id/101183127"
    },
    "Waste Avoidance Strategies for Environmental Sustainability": {
        "acronym": "WASTEWISE", "grant": "101181915", "cordis": "https://cordis.europa.eu/project/id/101181915"
    },
    "FORest PEATland ecosystem assessment and targeted management for enhanced carbon sequestration, biodiversity and water quality": {
        "acronym": "ForPeat", "grant": "101219060", "cordis": "https://cordis.europa.eu/project/id/101219060"
    },
    "Accelerating collection and use of soil health information using AI technology to support the Soil Deal for Europe and EU Soil Observatory": {
        "acronym": "AI4SoilHealth", "grant": "101086179", "cordis": "https://cordis.europa.eu/project/id/101086179"
    },
    "UpSCALing Efficient alternatives for contentious InpuTs in organic farming": {
        "acronym": "SCALE-it", "grant": "101181496", "cordis": "https://cordis.europa.eu/project/id/101181496"
    },
    "Minor Root & Tuber Crops Fostering Agrobiodiversity & Ecosystem Services": {
        "acronym": "ROTATES", "grant": "101181532", "cordis": "https://cordis.europa.eu/project/id/101181532"
    },
    "COMBATTING DIET RELATED NON-COMMUNICABLE DISEASE THROUGH ENHANCED SURVEILLANCE": {
        "acronym": "CoDiet", "grant": "101084642", "cordis": "https://cordis.europa.eu/project/id/101084642"
    },
    "AGRI4POL- Promoting sustainable agriculture for pollinators": {
        "acronym": "AGRI4POL", "grant": "101181146", "cordis": "https://cordis.europa.eu/project/id/101181146"
    },
    "EU-FarmBook": {
        "acronym": "EU-FarmBook", "grant": "101060382", "cordis": "https://cordis.europa.eu/project/id/101060382"
    },
    "FOODMISSION: Engaging citizens as agents of change for sustainable food system transition with a novel gamified educational citizen science platform": {
        "acronym": "FOODMISSION", "grant": "101181774", "cordis": "https://cordis.europa.eu/project/id/101181774"
    },
    "VIROPLANT- VIROME NGS ANALYSIS OF PESTS AND PATHOGENS FOR PLANT PROTECTION": {
        "acronym": "VIROPLANT", "grant": "773567", "cordis": "https://cordis.europa.eu/project/id/773567"
    },
    "AGROinLOG - Demonstration of innovative integrated biomass logistics centres for the Agro-industry sector in Europe": {
        "acronym": "AGROinLOG", "grant": "727961", "cordis": "https://cordis.europa.eu/project/id/727961"
    },
    "Best4Soil": {
        "acronym": "BEST4SOIL", "grant": "817696", "cordis": "https://cordis.europa.eu/project/id/817696"
    },
    "SheepNet : SHaring Expertise and Experience towards sheep Productivity through NETworking (2 of 2)": {
        "acronym": "SheepNet", "grant": "727895", "cordis": "https://cordis.europa.eu/project/id/727895"
    },
    "Grape monitoring robot to help winegrowers manage their vineyards and find the best time to harvest": {
        "acronym": "VineScout", "grant": "737669", "cordis": "https://cordis.europa.eu/project/id/737669"
    },
    "BRIZONDER": {
        "acronym": "BRIZONDER", "grant": "POP3-NL-SOIL", "cordis": ""
    },
    "mEATquality - Linking extensive husbandry practices to the intrinsic quality of pork and broiler meat": {
        "acronym": "mEATquality", "grant": "101000344", "cordis": "https://cordis.europa.eu/project/id/101000344"
    },
    "TErrestrial Resilience and RestorAtion Strategies for (semi) Arid and Fragile Ecosystems through a multi-actor approach": {
        "acronym": "TERRASAFE", "grant": "101157373", "cordis": "https://cordis.europa.eu/project/id/101157373"
    },
    "TRANSFORM": {
        "acronym": "TRANSFORM", "grant": "101155748", "cordis": "https://cordis.europa.eu/project/id/101155748"
    },
    "Promoting Green Nudging for Sustainable Agriculture and Forestry": {
        "acronym": "PRUDENT", "grant": "101134051", "cordis": "https://cordis.europa.eu/project/id/101134051"
    },
    "Catalysing scientific innovation into food safety action": {
        "acronym": "CATALYSE", "grant": "101183092", "cordis": "https://cordis.europa.eu/project/id/101183092"
    },
    "Circular systemic solutions for regenerative agriculture, local food systems, and reusable packaging in cities and regions": {
        "acronym": "CIRCULANDIA", "grant": "101135275", "cordis": "https://cordis.europa.eu/project/id/101135275"
    },
    "Maximising the CO-benefits of agricultural Digitalisation through conducive digital ECoSystems": {
        "acronym": "CODECS", "grant": "101060179", "cordis": "https://cordis.europa.eu/project/id/101060179"
    },
    "DRAGONS develops and tests practical, co-created biodiversity innovations across diverse land-use contexts—including rural restoration and forest management—by combining behavioural science, inclusive governance, and stakeholder champion network": {
        "acronym": "DRAGONS", "grant": "101291624", "cordis": "https://cordis.europa.eu/project/id/101291624"
    },
    "Propelling health and sustainability through innovative food products and processes": {
        "acronym": "Sustain-a-bite", "grant": "101180399", "cordis": "https://cordis.europa.eu/project/id/101180399"
    },
    "Fostering agroecology transition in North Africa through multi-actor, evaluation, and networking": {
        "acronym": "NATAE", "grant": "101084647", "cordis": "https://cordis.europa.eu/project/id/101084647"
    },
    "LANDSUPPORT - Web-Based Land Decision Support System": {
        "acronym": "LANDSUPPORT", "grant": "787128", "cordis": "https://cordis.europa.eu/project/id/787128"
    },
    "WeLASER-SUSTAINABLE WEED MANAGEMENT IN AGRICULTURE WITH LASER-BASED AUTONOMOUS TOOLS": {
        "acronym": "WeLASER", "grant": "101000256", "cordis": "https://cordis.europa.eu/project/id/101000256"
    },
    "SheepNet : SHaring Expertise and Experience towards sheep Productivity through NETworking": {
        "acronym": "SheepNet", "grant": "727895", "cordis": "https://cordis.europa.eu/project/id/727895"
    },
    "HNV-Link - High Nature Value Farming: Learning, Innovation and Knowledge.": {
        "acronym": "HNV-Link", "grant": "696391", "cordis": "https://cordis.europa.eu/project/id/696391"
    },
    "Improving pig health and welfare in organic farms by preventing or rapidly detecting diseases or welfare problems": {
        "acronym": "ProPIG", "grant": "CORE-ORGANIC-291823", "cordis": "https://orgprints.org/id/eprint/22880/"
    },
    "Improving the stability of high-quality traits of berry in different environments and cultivation systems for the benefit of European farmer/consumer": {
        "acronym": "GoodBerry", "grant": "679303", "cordis": "https://cordis.europa.eu/project/id/679303"
    },
    "Smart beekeeping kept simple": {
        "acronym": "BPRACTICES", "grant": "696231", "cordis": "https://cordis.europa.eu/project/id/696231"
    },
    "Turn agrarian woody residues into valuable biomass": {
        "acronym": "uP_running", "grant": "691748", "cordis": "https://cordis.europa.eu/project/id/691748"
    },
    "Emergent soil, plant and food onsite digital services on chemical and biological contaminants": {
        "acronym": "E-SPFdigit", "grant": "101157922", "cordis": "https://cordis.europa.eu/project/id/101157922"
    },
    "Transforming Access to Excellence with Successful Alliances of Higher Education in Digital Agriculture": {
        "acronym": "TALLHEDA", "grant": "101136578", "cordis": "https://cordis.europa.eu/project/id/101136578"
    },
    "OLEAF4VALUE: Olive leaf multi-product cascade based biorefinery": {
        "acronym": "OLEAF4VALUE", "grant": "101023256", "cordis": "https://cordis.europa.eu/project/id/101023256"
    },
    "Innovative practices, tools and products to boost soil fertility and peat substitution in horticultural crops": {
        "acronym": "SPIN-FERT", "grant": "101157265", "cordis": "https://cordis.europa.eu/project/id/101157265"
    },
    "ZeroW - Systemic Innovations Towards a Zero Food Waste Supply Chain": {
        "acronym": "ZeroW", "grant": "101036388", "cordis": "https://cordis.europa.eu/project/id/101036388"
    },
    "Future-Proofing Food: Transforming Risk Analysis for a better and more adaptive food system": {
        "acronym": "HOLiFOOD", "grant": "101059813", "cordis": "https://cordis.europa.eu/project/id/101059813"
    },
    "Breeding European Legumes for Increased Sustainability": {
        "acronym": "BELIS", "grant": "101081878", "cordis": "https://cordis.europa.eu/project/id/101081878"
    },
    "Scalable CO₂-based precision fermentation for functional food ingredients": {
        "acronym": "FERM4FOOD", "grant": "101262970", "cordis": "https://cordis.europa.eu/project/id/101262970"
    },
    "New business for farmers and cooperatives in rural areas by local upcycling solutions using underutilized agricultural feedstocks": {
        "acronym": "PRIMARY", "grant": "101180167", "cordis": "https://cordis.europa.eu/project/id/101180167"
    },
    "CLImate Mitigation and Bioeconomy pathways for sustainable FORESTry": {
        "acronym": "CLIMB-FOREST", "grant": "101059888", "cordis": "https://cordis.europa.eu/project/id/101059888"
    }
}


def batched(iterable, size):
    it = iter(iterable)
    while True:
        batch = list(islice(it, size))
        if not batch:
            break
        yield batch


def ensure_tables(conn):
    """Ensure harvest schema, harvest.projects, and harvest.items tables exist."""
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS harvest;")
        
        # 1. harvest.projects
        cur.execute("""
            CREATE TABLE IF NOT EXISTS harvest.projects (
                code character varying(99) NOT NULL,
                title text,
                funding character varying(255),
                website text,
                grantnr character varying(99) NOT NULL,
                source character varying(99),
                keywords text[],
                description text,
                cordis_url text
            );
        """)
        cur.execute("""
            ALTER TABLE harvest.projects ADD COLUMN IF NOT EXISTS keywords text[];
            ALTER TABLE harvest.projects ADD COLUMN IF NOT EXISTS description text;
            ALTER TABLE harvest.projects ADD COLUMN IF NOT EXISTS cordis_url text;
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_hrv_prj_grant_code 
            ON harvest.projects (code, grantnr);
        """)

        # 2. harvest.items
        cur.execute("""
            CREATE TABLE IF NOT EXISTS harvest.items (
                identifier text,
                identifiertype text,
                uri text,
                resultobject text,
                resulttype text,
                doimetadata text,
                hash text,
                source text,
                insert_date timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
                itemtype text,
                title text,
                language text,
                date text,
                project text,
                turtle text,
                error text
            );
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_hrv_items_hash 
            ON harvest.items (hash);
        """)
    conn.commit()
    logger.info("✓ Database tables verified: harvest.projects and harvest.items.")


def load_pa_lookup() -> Dict[str, Dict[str, str]]:
    """Loads Practice Abstracts lookup if available to map URLs to grant numbers."""
    pa_path = DATA_DIR / "eu_cap_practice_abstracts.json"
    lookup = {}
    if pa_path.exists():
        try:
            with open(pa_path, "r", encoding="utf-8") as f:
                pa_list = json.load(f)
            for x in pa_list:
                u = x.get("project_url")
                g = x.get("project_grant_number")
                acr = x.get("project_acronym")
                cordis = x.get("cordis_url")
                if u and g and u not in lookup:
                    lookup[u] = {"grant": str(g).strip(), "acronym": (acr or "").strip(), "cordis": cordis or ""}
        except Exception as e:
            logger.warning(f"Could not load practice abstracts for lookup: {e}")
    return lookup


def resolve_project_identifiers(p: Dict[str, Any], pa_lookup: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    """Resolves authoritative acronym, grant agreement ID, and CORDIS link."""
    title = (p.get("title") or "").strip()
    url = (p.get("url") or "").strip()
    acronym = (p.get("acronym") or "").strip()
    grant = str(p.get("grant_number") or "").strip()
    cordis = (p.get("cordis_url") or "").strip()

    # Priority 1: Supplemental Mapping
    if title in SUPPLEMENTAL_MAPPING:
        m = SUPPLEMENTAL_MAPPING[title]
        return {
            **p,
            "acronym": m["acronym"],
            "grant_number": m["grant"],
            "cordis_url": m["cordis"]
        }

    # Priority 2: Practice Abstracts lookup
    if url in pa_lookup:
        m = pa_lookup[url]
        return {
            **p,
            "acronym": acronym or m["acronym"],
            "grant_number": grant or m["grant"],
            "cordis_url": cordis or m["cordis"]
        }

    # Priority 3: Fallback extraction
    if not grant:
        # Check details fields
        details = p.get("details_fields") or {}
        for k, v in details.items():
            if "grant" in k.lower() or "identifier" in k.lower():
                m = re.search(r"\b(\d{6,8})\b", v)
                if m:
                    grant = m.group(1)
                    break

    if not cordis and grant and grant.isdigit():
        cordis = f"https://cordis.europa.eu/project/id/{grant}"

    return {
        **p,
        "acronym": acronym,
        "grant_number": grant,
        "cordis_url": cordis
    }


def parse_project_page(html: str, url: str) -> Dict[str, Any]:
    """Parses full project HTML into a metadata dictionary."""
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    title = ""
    if h1:
        lang_div = h1.find("div", class_="js-lang")
        title = lang_div.get_text(strip=True) if lang_div else h1.get_text(strip=True)

    fields: Dict[str, str] = {}
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            fields[dt.get_text(strip=True)] = dd.get_text(strip=True)

    keywords = [
        a.get_text(strip=True)
        for a in soup.find_all("a", class_=lambda c: c and "chip--keyword" in c)
    ]

    description_parts = []
    for div in soup.find_all("div", class_=lambda c: c and "js-lang" in c):
        txt = div.get_text(separator="\n", strip=True)
        if len(txt) > 80 and txt != title:
            description_parts.append(txt)
    description = "\n\n".join(description_parts) if description_parts else ""

    status_tag = soup.find(lambda t: t.name in ["span", "div"] and any(s in t.text.lower() for s in ["ongoing", "completed"]))
    status = status_tag.get_text(strip=True) if status_tag else ""

    external_websites = []
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if h.startswith("http") and not any(d in h for d in ["europa.eu", "eu-cap-network", "twitter", "facebook", "youtube", "linkedin", "sibforms"]):
            external_websites.append(h)
    website = external_websites[0] if external_websites else ""

    acronym = fields.get("Project acronym") or fields.get("Acronym") or ""
    grant_number = fields.get("Project identifier") or fields.get("Grant agreement ID") or ""

    return {
        "title": title,
        "acronym": acronym,
        "grant_number": grant_number,
        "funding_source": fields.get("Main funding source") or fields.get("Funding source") or "Horizon Europe",
        "project_type": fields.get("Type of Horizon project") or "",
        "location": fields.get("Main geographical location") or "",
        "status": status,
        "keywords": keywords,
        "description": description,
        "official_website": website,
        "url": url,
        "cordis_url": ""
    }


def live_scrape_eucap(max_count: Optional[int] = None) -> List[Dict[str, Any]]:
    """Live scrape projects from EU CAP Network."""
    logger.info("Starting live crawl of EU CAP Network...")
    pa_lookup = load_pa_lookup()
    headers = {"User-Agent": random.choice(USER_AGENTS)}

    # Crawl search listing for Horizon projects
    search_url = "https://eu-cap-network.ec.europa.eu/projects_en?f%5B0%5D=funding_source%3A1259&f%5B1%5D=funding_source%3A1260"
    resp = requests.get(search_url, headers=headers, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")

    project_links = []
    for a in soup.find_all("a", href=True):
        if "/projects/" in a["href"] and not a["href"].endswith("/projects_en"):
            full = a["href"] if a["href"].startswith("http") else f"https://eu-cap-network.ec.europa.eu{a['href']}"
            if full not in project_links:
                project_links.append(full)

    logger.info(f"Discovered {len(project_links)} projects from search catalogue.")
    if max_count:
        project_links = project_links[:max_count]

    results = []
    for idx, u in enumerate(project_links, 1):
        try:
            r = requests.get(u, headers={"User-Agent": random.choice(USER_AGENTS)}, timeout=30)
            if r.status_code == 200:
                p = parse_project_page(r.text, u)
                enriched = resolve_project_identifiers(p, pa_lookup)
                results.append(enriched)
                logger.info(f"[{idx}/{len(project_links)}] Scraped: {enriched['acronym']} ({enriched['grant_number']})")
            time.sleep(random.uniform(1.0, 2.0))
        except Exception as e:
            logger.warning(f"Error scraping {u}: {e}")

    return results


def ingest_to_harvest_projects(conn, projects: List[Dict[str, Any]], dry_run: bool = False) -> int:
    """Inserts/upserts project profiles into harvest.projects."""
    logger.info("\n--- PHASE 1: Direct Ingest to harvest.projects ---")
    unique_projects = {}
    dup_count = 0

    for p in projects:
        code = (p.get("acronym") or "").strip()
        grantnr = str(p.get("grant_number") or "").strip()
        title = (p.get("title") or "").strip()
        funding = (p.get("funding_source") or "").strip()
        website = (p.get("official_website") or p.get("url") or "").strip()
        source = "EU CAP Network"
        keywords = p.get("keywords") or []
        description = (p.get("description") or "").strip()
        cordis_url = (p.get("cordis_url") or "").strip()

        if not code or not grantnr:
            continue

        key = (code, grantnr)
        if key in unique_projects:
            dup_count += 1
            existing = unique_projects[key]
            merged_kw = list(dict.fromkeys(existing[6] + keywords))
            best_desc = description if len(description) > len(existing[7]) else existing[7]
            best_web = website if len(website) > len(existing[3]) else existing[3]
            unique_projects[key] = (
                code, title, funding, best_web, grantnr, source, merged_kw, best_desc, cordis_url or existing[8]
            )
        else:
            unique_projects[key] = (
                code, title, funding, website, grantnr, source, keywords, description, cordis_url
            )

    rows = list(unique_projects.values())
    logger.info(f"Prepared {len(rows)} unique project rows ({dup_count} duplicates merged).")

    upsert_sql = """
        INSERT INTO harvest.projects (
            code, title, funding, website, grantnr, source, keywords, description, cordis_url
        ) VALUES %s
        ON CONFLICT (code, grantnr) DO UPDATE SET
            title = EXCLUDED.title,
            funding = EXCLUDED.funding,
            website = EXCLUDED.website,
            source = EXCLUDED.source,
            keywords = EXCLUDED.keywords,
            description = EXCLUDED.description,
            cordis_url = EXCLUDED.cordis_url;
    """

    with conn.cursor() as cur:
        execute_values(cur, upsert_sql, rows, page_size=200)
        cur.execute("SELECT count(*) FROM harvest.projects WHERE source = 'EU CAP Network';")
        count = cur.fetchone()[0]

    if not dry_run:
        conn.commit()
    logger.info(f"✓ Committed {len(rows)} projects to harvest.projects (Total EU CAP: {count})")
    return len(rows)


def run_cordis_sparql(grant_ids: List[str]) -> List[Dict[str, Any]]:
    """Query CORDIS SPARQL endpoint for a list of grant IDs."""
    quoted = ", ".join(f'"{gid}"' for gid in grant_ids)
    query = f"""
PREFIX eurio: <http://data.europa.eu/s66#>

SELECT DISTINCT
  ?projectId ?title ?abstract ?acronym ?startDate ?endDate ?totalCost ?doi ?prjWebsite 
  ?organisationName ?roleLabel ?orgCountry ?orgCity ?orgAddress ?postalCode ?orgWebsite ?longitude ?latitude
WHERE {{
  ?project a eurio:Project ;
           eurio:identifier ?projectId ;
           eurio:title ?title .
  
  FILTER(?projectId IN ({quoted}))

  OPTIONAL {{ ?project eurio:startDate ?startDate }}
  OPTIONAL {{ ?project eurio:endDate ?endDate }}
  OPTIONAL {{ ?project eurio:doi ?doi }}
  OPTIONAL {{ ?project eurio:abstract ?abstract }}
  OPTIONAL {{ ?project eurio:url ?prjWebsite }}
  
  OPTIONAL {{
    ?project eurio:hasInvolvedParty ?role .
    ?role eurio:roleLabel ?roleLabel ;
          eurio:isRoleOf ?org .
    ?org eurio:legalName ?organisationName .
    
    OPTIONAL {{ ?org eurio:url ?orgWebsite }}
    OPTIONAL {{
      ?org eurio:hasSite ?site .
      ?site a eurio:Site .
      OPTIONAL {{ ?site eurio:hasAddress ?addr . ?addr eurio:streetAddress ?orgAddress }}
      OPTIONAL {{ ?site eurio:hasAddress ?addr . ?addr eurio:postalCode ?postalCode }}
      OPTIONAL {{ ?site eurio:hasAddress ?addr . ?addr eurio:addressLocality ?orgCity }}
      OPTIONAL {{ ?site eurio:hasAddress ?addr . ?addr eurio:addressCountry ?orgCountry }}
      OPTIONAL {{ ?site eurio:hasCoordinates ?coords . ?coords eurio:longitude ?longitude }}   
      OPTIONAL {{ ?site eurio:hasCoordinates ?coords . ?coords eurio:latitude ?latitude }}   
    }}
  }}
}}
ORDER BY ?projectId ?organisationName
    """
    headers = {
        "Accept": "application/sparql-results+json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "SoilWiseHarvester/1.0 (contact: info@soilwise-he.eu)"
    }
    try:
        resp = requests.post(SPARQL_ENDPOINT, data={"query": query}, headers=headers, timeout=45)
        if resp.status_code == 200:
            return resp.json()["results"]["bindings"]
    except Exception as e:
        logger.warning(f"SPARQL error for chunk {grant_ids[:3]}...: {e}")
    return []


def build_mcf_objects(sparql_rows: List[Dict[str, Any]], projects_by_grant: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Builds unified MCF (Metadata Control Format) objects from SPARQL and fallback metadata."""
    mcf_docs: Dict[str, Dict[str, Any]] = {}

    for r in sparql_rows:
        pid = r["projectId"]["value"]
        doi_uri = r.get("doi", {}).get("value", f"https://doi.org/10.3030/{pid}")
        local_p = projects_by_grant.get(pid) or {}

        if pid not in mcf_docs:
            mcf_docs[pid] = {
                "mcf": {"version": "1.0"},
                "metadata": {
                    "identifier": f"10.3030/{pid}",
                    "hierarchylevel": "project",
                    "language": "eng",
                    "dataseturi": doi_uri
                },
                "identification": {
                    "title": r["title"]["value"],
                    "abstract": r.get("abstract", {}).get("value") or local_p.get("description", ""),
                    "keywords": {
                        "default": {
                            "keywords": local_p.get("keywords") or ["Soil", "Agriculture"]
                        }
                    },
                    "extents": {
                        "temporal": [{
                            "begin": r.get("startDate", {}).get("value"),
                            "end": r.get("endDate", {}).get("value")
                        }]
                    }
                },
                "contacts": {}
            }

            if local_p.get("acronym"):
                mcf_docs[pid]["metadata"]["additional_identifiers"] = [{
                    "identifier": local_p["acronym"],
                    "scheme": "acronym"
                }]

            web = r.get("prjWebsite", {}).get("value") or local_p.get("official_website")
            if web:
                mcf_docs[pid]["distribution"] = {"www": {"url": web, "type": "website"}}
                mcf_docs[pid]["identification"]["url"] = web

        # Add partner organizations
        if "organisationName" in r:
            org_name = r["organisationName"].get("value", "").capitalize()
            role = r.get("roleLabel", {}).get("value", "partner").lower()
            cid = f"c{len(mcf_docs[pid]['contacts'])}"
            org_entry = {"organization": org_name, "role": role}
            if "orgAddress" in r: org_entry["address"] = r["orgAddress"].get("value")
            if "orgCity" in r: org_entry["city"] = r["orgCity"].get("value")
            if "orgCountry" in r: org_entry["country"] = r["orgCountry"].get("value")
            if "longitude" in r: org_entry["longitude"] = r["longitude"].get("value")
            if "latitude" in r: org_entry["latitude"] = r["latitude"].get("value")
            mcf_docs[pid]["contacts"][cid] = org_entry

    return mcf_docs


def enrich_cordis_to_harvest_items(conn, projects: List[Dict[str, Any]], dry_run: bool = False) -> int:
    """Enriches projects via CORDIS SPARQL in-memory and writes MCF into harvest.items."""
    logger.info("\n--- PHASE 2: CORDIS SPARQL Enrichment directly into harvest.items ---")
    
    projects_by_grant = {str(p["grant_number"]).strip(): p for p in projects if p.get("grant_number")}
    grant_ids = list(projects_by_grant.keys())
    
    logger.info(f"Enriching {len(grant_ids)} projects with CORDIS SPARQL metadata...")
    total_stored = 0

    upsert_item_sql = """
        INSERT INTO harvest.items (
            identifier, identifiertype, uri, resultobject, resulttype,
            hash, source, itemtype, title, project
        ) VALUES (
            %(identifier)s, %(identifiertype)s, %(uri)s, %(resultobject)s, %(resulttype)s,
            %(hash)s, %(source)s, %(itemtype)s, %(title)s, %(project)s
        )
        ON CONFLICT (hash) DO UPDATE SET
            resultobject = EXCLUDED.resultobject,
            resulttype = EXCLUDED.resulttype;
    """

    for chunk in batched(grant_ids, SPARQL_BATCH_SIZE):
        # Query SPARQL in memory
        sparql_rows = run_cordis_sparql(chunk)
        mcf_docs = build_mcf_objects(sparql_rows, projects_by_grant)

        # Fallback for projects not found in CORDIS SPARQL (e.g. non-H2020 national projects)
        for gid in chunk:
            if gid not in mcf_docs:
                p = projects_by_grant[gid]
                mcf_docs[gid] = {
                    "mcf": {"version": "1.0"},
                    "metadata": {
                        "identifier": f"eucap_{gid}",
                        "hierarchylevel": "project",
                        "language": "eng",
                        "dataseturi": p.get("url") or p.get("official_website", "")
                    },
                    "identification": {
                        "title": p.get("title", ""),
                        "abstract": p.get("description", ""),
                        "keywords": {"default": {"keywords": p.get("keywords") or ["Soil"]}}
                    },
                    "contacts": {}
                }

        # Store in harvest.items
        with conn.cursor() as cur:
            for pid, mcf in mcf_docs.items():
                yaml_str = yaml.dump(mcf, sort_keys=False)
                hashcode = hashlib.md5(yaml_str.encode("utf-8")).hexdigest()
                local_p = projects_by_grant.get(pid, {})
                uri = local_p.get("cordis_url") or f"https://cordis.europa.eu/project/id/{pid}"

                values = {
                    "identifier": f"10.3030/{pid}",
                    "identifiertype": "doi",
                    "uri": uri,
                    "resultobject": yaml_str,
                    "resulttype": "yaml",
                    "hash": hashcode,
                    "source": "EU CAP Network",
                    "itemtype": "project",
                    "title": mcf.get("identification", {}).get("title", ""),
                    "project": pid
                }
                cur.execute(upsert_item_sql, values)
                total_stored += 1

        if not dry_run:
            conn.commit()

        logger.info(f"  ✓ Processed and committed batch of {len(mcf_docs)} projects to harvest.items")

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM harvest.items WHERE source = 'EU CAP Network' AND itemtype = 'project';")
        eucap_items = cur.fetchone()[0]

    logger.info(f"✓ All projects enriched into harvest.items (Total EU CAP Network project items: {eucap_items})")
    return total_stored


def main():
    parser = argparse.ArgumentParser(description="Unified EU CAP Network Harvester & In-Memory Enrichment.")
    parser.add_argument("--scrape", action="store_true", help="Live scrape from EU CAP Network website (default unless --seed-json is given)")
    parser.add_argument("--seed-json", default=None, help="Load projects from this JSON file instead of scraping")
    parser.add_argument("--skip-cordis", action="store_true", help="Skip CORDIS SPARQL enrichment into harvest.items")
    parser.add_argument("--dry-run", action="store_true", help="Run without committing database changes")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of projects to process")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Database host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Database port")
    parser.add_argument("--dbname", default=DEFAULT_DBNAME, help="Database name")
    parser.add_argument("--user", default=DEFAULT_USER, help="Database user")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Database password")
    args = parser.parse_args()

    print("=" * 65)
    print("UNIFIED EU CAP PROJECT HARVEST & IN-MEMORY CORDIS ENRICHMENT")
    print(f"Target DB:     {args.dbname} on {args.host}:{args.port}")
    print(f"Workflow:      EU CAP -> harvest.projects -> CORDIS SPARQL -> harvest.items")
    print(f"Mode:          {'DRY-RUN (No changes saved)' if args.dry_run else 'EXECUTE (Committing to DB)'}")
    print("=" * 65)

    conn = psycopg2.connect(
        host=args.host, port=args.port, dbname=args.dbname, user=args.user, password=args.password
    )

    try:
        # Step 1: Ensure database tables
        ensure_tables(conn)

        # Step 2: Acquire projects in memory
        # Clean repo: scrape live unless a seed file is passed explicitly with --seed-json
        # (the original silently preferred data/eucap_*.json when it existed).
        if args.seed_json and not args.scrape:
            json_file = Path(args.seed_json)
            logger.info(f"Loading seed projects from: {json_file}")
            with open(json_file, "r", encoding="utf-8") as f:
                raw_projects = json.load(f)
            pa_lookup = load_pa_lookup()
            projects = [resolve_project_identifiers(p, pa_lookup) for p in raw_projects]
        else:
            projects = live_scrape_eucap(max_count=args.limit)

        if args.limit:
            projects = projects[:args.limit]

        logger.info(f"Ready to process {len(projects)} projects.")

        # Step 3: Phase 1 — Ingest to harvest.projects
        ingest_to_harvest_projects(conn, projects, dry_run=args.dry_run)

        # Step 4: Phase 2 — In-memory CORDIS enrichment to harvest.items
        if not args.skip_cordis:
            enrich_cordis_to_harvest_items(conn, projects, dry_run=args.dry_run)

        if args.dry_run:
            conn.rollback()
            print("\n[DRY-RUN] Completed successfully. All transactions rolled back.")
        else:
            conn.commit()
            print("\n✓ SUCCESS: Pipeline completed and committed to database!")

    except Exception as e:
        conn.rollback()
        logger.error(f"Pipeline error: {e}")
        raise e
    finally:
        conn.close()


if __name__ == "__main__":
    main()
