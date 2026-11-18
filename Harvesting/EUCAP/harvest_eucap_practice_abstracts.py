#!/usr/bin/env python3
"""
harvest_eucap_practice_abstracts.py

Harvests Practice Abstracts from the EU CAP Network portal for Horizon 2020 and Horizon Europe projects.
Source URL: https://eu-cap-network.ec.europa.eu/projects/search_en?f[0]=main_funding_source%3Ah2020&f%5B1%5D=main_funding_source%3Ahorizon_eu

Enriches Practice Abstracts with authoritative Project Acronym, Grant Agreement Number,
and Identifier from the database (harvest.projects / eufarmbook_projects.json).

Features:
- Rotating User-Agent headers to avoid FPFIS bot-fingerprint blocks.
- Incremental saving & auto-resume (skips already-harvested projects).
- Polite sequential crawling with jitter to avoid CloudFront 429 WAF blocks.
- Smart 30s cooldown if a 429 is ever encountered.
"""

# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config  # noqa: E402,F401  (loads .env)
# --------------------------------------------------------------------------------------------
import asyncio
import argparse
import json
import logging
import os
import random
import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from tqdm import tqdm
import psycopg2

# Environment is loaded by common.db (repo-root .env)
SCRIPT_DIR = Path(__file__).resolve().parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

BASE_URL = "https://eu-cap-network.ec.europa.eu"
SEARCH_URL = (
    f"{BASE_URL}/projects/search_en"
    "?f%5B0%5D=main_funding_source%3Ah2020&f%5B1%5D=main_funding_source%3Ahorizon_eu"
)
DEFAULT_OUTPUT_PATH = DATA_DIR / "eu_cap_practice_abstracts.json"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0"
]


def get_headers() -> Dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    }


def clean_text(s: str) -> str:
    """Normalize text for fuzzy matching by removing punctuation and extra whitespace."""
    if not s:
        return ""
    return re.sub(r"[^a-zA-Z0-9]", "", s).lower()


def load_db_projects() -> List[Dict[str, str]]:
    """
    Loads project records (code, grantnr, title, funding) from the database
    or fallback JSON file.
    """
    projects: List[Dict[str, str]] = []
    
    host = os.environ.get("POSTGRES_HOST") or os.environ.get("DB_HOST")
    port = os.environ.get("POSTGRES_PORT") or os.environ.get("DB_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB") or os.environ.get("DB_NAME")
    user = os.environ.get("POSTGRES_USER") or os.environ.get("DB_USER")
    password = os.environ.get("POSTGRES_PASSWORD") or os.environ.get("DB_PASSWORD")

    if host and dbname and user:
        try:
            logger.info(f"Connecting to database {dbname} on {host}:{port} to load projects...")
            conn = psycopg2.connect(
                host=host,
                port=port,
                dbname=dbname,
                user=user,
                password=password,
                connect_timeout=10
            )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT code, grantnr, title, funding, website "
                    "FROM harvest.projects "
                    "WHERE coalesce(grantnr, '') != '' OR coalesce(code, '') != '';"
                )
                for r in cur.fetchall():
                    code = (r[0] or "").strip()
                    grantnr = (r[1] or "").strip()
                    title = (r[2] or "").strip()
                    funding = (r[3] or "").strip()
                    website = (r[4] or "").strip()
                    if code or grantnr:
                        projects.append({
                            "code": code,
                            "grantnr": grantnr,
                            "title": title,
                            "funding": funding,
                            "website": website
                        })
            conn.close()
            logger.info(f"Loaded {len(projects)} projects from harvest.projects table.")
            return projects
        except Exception as e:
            logger.warning(f"Failed to query database for projects: {e}. Trying fallback JSON...")

    # eufarmbook_projects.json is no longer produced (EU-FarmBook harvesters write to the DB);
    # kept only as an optional manual fallback in <repo>/data.
    fallback_paths = [
        DATA_DIR / "eufarmbook_projects.json"
    ]
    for p in fallback_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    code = (item.get("cordis_acronym") or item.get("title") or "").strip()
                    grantnr = (item.get("grant_number") or item.get("grant_id") or "").strip()
                    title = (item.get("title") or "").strip()
                    if code or grantnr:
                        projects.append({
                            "code": code,
                            "grantnr": grantnr,
                            "title": title,
                            "funding": item.get("project_type", ""),
                            "website": item.get("project_website", "")
                        })
                logger.info(f"Loaded {len(projects)} projects from fallback JSON: {p}")
                return projects
            except Exception as e:
                logger.warning(f"Error reading fallback file {p}: {e}")

    logger.warning("No projects could be loaded from DB or fallback files.")
    return projects


def match_project_with_db(
    acronym: str,
    title: str,
    existing_grant: str,
    db_projects: List[Dict[str, str]]
) -> Optional[Dict[str, str]]:
    """
    Matches scraped project against authoritative DB projects using multiple strategies:
    1. By existing grant number
    2. By exact acronym
    3. By acronym word occurring inside title
    4. By clean title substring match
    """
    if not db_projects:
        return None

    norm_acronym = acronym.strip().upper() if acronym else ""

    if existing_grant:
        for p in db_projects:
            if p["grantnr"] == existing_grant:
                return p

    if norm_acronym:
        for p in db_projects:
            if p["code"].strip().upper() == norm_acronym:
                return p

    for p in db_projects:
        p_code = p["code"].strip()
        if p_code and len(p_code) >= 3:
            if re.search(r"\b" + re.escape(p_code) + r"\b", title, re.IGNORECASE):
                return p

    c_title = clean_text(title)
    if len(c_title) > 15:
        for p in db_projects:
            c_p_title = clean_text(p["title"])
            if len(c_p_title) > 15:
                if c_p_title in c_title or c_title in c_p_title:
                    return p

    return None


async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    retries: int = 5
) -> Optional[str]:
    """
    Fetches URL with rotating User-Agent and smart rate-limit aware backoff.
    """
    for attempt in range(1, retries + 1):
        headers = get_headers()
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 429:
                cooldown = 15.0 + random.uniform(1.0, 5.0)
                logger.warning(
                    f"FPFIS 429 Rate Limit for {url}. "
                    f"Switching User-Agent and waiting {cooldown:.1f}s (attempt {attempt}/{retries})..."
                )
                await asyncio.sleep(cooldown)
                continue
            elif resp.status_code == 404:
                logger.warning(f"404 Not Found: {url}")
                return None
            else:
                logger.warning(f"HTTP {resp.status_code} for {url} (attempt {attempt}/{retries})")
        except Exception as e:
            logger.warning(f"Error fetching {url}: {e} (attempt {attempt}/{retries})")
        
        await asyncio.sleep(2.0 * attempt)
    return None


async def discover_project_urls(
    client: httpx.AsyncClient,
    max_pages: Optional[int] = None,
    max_projects: Optional[int] = None,
    page_delay: float = 0.8
) -> List[str]:
    """
    Crawls search result pagination to discover project URLs.
    """
    logger.info("Discovering Horizon 2020 and Horizon Europe projects from EU CAP Network...")
    
    first_page_html = await fetch_with_retry(client, f"{SEARCH_URL}&page=0")
    if not first_page_html:
        raise RuntimeError("Failed to fetch initial search page.")

    soup = BeautifulSoup(first_page_html, "html.parser")
    
    last_page = 0
    for a in soup.find_all("a", href=True):
        match = re.search(r"page=(\d+)", a["href"])
        if match:
            p_num = int(match.group(1))
            if p_num > last_page and "social-media" not in a["href"]:
                last_page = p_num

    total_pages = last_page + 1
    logger.info(f"Detected {total_pages} total search pages (page 0 to page {last_page}).")

    if max_pages is not None:
        total_pages = min(total_pages, max_pages)

    if max_projects is not None:
        needed_pages = (max_projects + 9) // 10
        total_pages = min(total_pages, needed_pages)

    logger.info(f"Will query {total_pages} search listing page(s)...")

    project_slugs: List[str] = []
    seen = set()

    for p in range(total_pages):
        page_url = f"{SEARCH_URL}&page={p}"
        html = first_page_html if p == 0 else await fetch_with_retry(client, page_url)
        if not html:
            continue

        page_soup = BeautifulSoup(html, "html.parser")
        main = page_soup.find("main") or page_soup
        for a in main.find_all("a", href=True):
            href = a["href"]
            if (
                href.startswith("/projects/")
                and not href.startswith("/projects/search")
                and not href.startswith("/projects/practice")
                and href.endswith("_en")
            ):
                if href not in seen:
                    seen.add(href)
                    project_slugs.append(href)
                    if max_projects is not None and len(project_slugs) >= max_projects:
                        break

        if max_projects is not None and len(project_slugs) >= max_projects:
            break

        if p < total_pages - 1:
            await asyncio.sleep(page_delay + random.uniform(0.1, 0.3))

    logger.info(f"Discovered {len(project_slugs)} project URLs.")
    return project_slugs


def parse_project_and_practice_abstracts(
    html: str,
    project_url: str,
    db_projects: List[Dict[str, str]]
) -> List[Dict[str, Any]]:
    """
    Parses a single project page for its project metadata and embedded Practice Abstracts,
    enriching missing grant and acronym fields from the database.
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Project Title
    h1 = soup.find("h1")
    project_title = ""
    if h1:
        en_h1 = h1.find(class_="js-lang")
        if en_h1:
            project_title = en_h1.get_text(strip=True)
        else:
            project_title = h1.get_text(strip=True)

    # 2. Project Acronym
    project_acronym = ""
    acronym_el = soup.find(string=re.compile(r"Project acronym", re.I))
    if acronym_el and acronym_el.find_parent("dt"):
        dd = acronym_el.find_parent("dt").find_next_sibling("dd")
        if dd:
            project_acronym = dd.get_text(strip=True)

    if not project_acronym and project_title:
        lead_m = re.match(r"^([A-Z][A-Z0-9\-_]{2,20})\b", project_title)
        tail_m = re.search(r"\b([A-Z][A-Z0-9\-_]{2,20})\s*[\".]*$", project_title)
        if lead_m:
            project_acronym = lead_m.group(1)
        elif tail_m:
            project_acronym = tail_m.group(1)

    # 3. Main Funding Source
    funding_source = ""
    funding_el = soup.find(string=re.compile(r"Main funding source", re.I))
    if funding_el and funding_el.find_parent("dt"):
        dd = funding_el.find_parent("dt").find_next_sibling("dd")
        if dd:
            funding_source = dd.get_text(strip=True)

    # 4. Project Identifier & Grant Agreement Number from page
    identifier = ""
    grant_number = ""
    id_match = re.search(r"Project identifier:\s*([^\s<]+)", html)
    if id_match:
        identifier = id_match.group(1).strip()
        grant_match = re.search(r"(?:HE|H2020)_(\d+)", identifier)
        if grant_match:
            grant_number = grant_match.group(1)

    # 5. CORDIS link
    cordis_url = ""
    cordis_a = soup.find("a", href=re.compile(r"cordis\.europa\.eu/project/id/(\d+)", re.I))
    if cordis_a:
        cordis_url = cordis_a["href"]
        if not grant_number:
            c_match = re.search(r"id/(\d+)", cordis_url)
            if c_match:
                grant_number = c_match.group(1)

    if not grant_number and identifier:
        m = re.search(r"(\d{6,9})", identifier)
        if m:
            grant_number = m.group(1)

    # 6. Enrich from Database
    db_match = match_project_with_db(project_acronym, project_title, grant_number, db_projects)
    if db_match:
        if not project_acronym:
            project_acronym = db_match["code"]
        if not grant_number:
            grant_number = db_match["grantnr"]
        if not identifier:
            identifier = db_match["grantnr"]
        if not cordis_url and grant_number:
            cordis_url = f"https://cordis.europa.eu/project/id/{grant_number}"
        if not funding_source and db_match.get("funding"):
            funding_source = db_match["funding"]

    # 7. Parse Practice Abstracts from accordions
    accordions = soup.find_all(class_="accordion-item")
    grouped: Dict[str, Dict[str, Any]] = {}

    for acc in accordions:
        acc_id = acc.get("id", "")
        if not acc_id:
            continue
        
        is_native = "js-lang-native" in acc.get("class", [])
        
        h5 = acc.find("h5")
        title = h5.get_text(strip=True) if h5 else ""

        body = acc.find(class_="accordion-body")
        text = ""
        pa_url = ""
        if body:
            a_link = body.find("a", href=re.compile(r"/projects/practice-abstracts/"))
            if a_link:
                pa_url = a_link["href"]
                if not pa_url.startswith("http"):
                    pa_url = BASE_URL + pa_url
                a_link.decompose()
            text = " ".join(body.get_text(separator=" ", strip=True).split())

        if acc_id not in grouped:
            grouped[acc_id] = {"id": acc_id, "pa_url": pa_url}

        if is_native:
            grouped[acc_id]["native_title"] = title
            grouped[acc_id]["native_abstract"] = text
        else:
            grouped[acc_id]["title"] = title
            grouped[acc_id]["abstract"] = text
            if pa_url:
                grouped[acc_id]["pa_url"] = pa_url

    # Convert grouped accordions into flat records
    abstracts: List[Dict[str, Any]] = []
    for acc_id, pa_data in grouped.items():
        title = pa_data.get("title") or pa_data.get("native_title", "")
        abstract = pa_data.get("abstract") or pa_data.get("native_abstract", "")
        if not title and not abstract:
            continue

        abstracts.append({
            "id": acc_id,
            "title": title,
            "abstract": abstract,
            "native_title": pa_data.get("native_title"),
            "native_abstract": pa_data.get("native_abstract"),
            "url": pa_data.get("pa_url") or "",
            "source": "EU-CAP-NETWORK",
            "resource_type": "practices abstract",
            "project_title": project_title,
            "project_acronym": project_acronym,
            "project_grant_number": grant_number,
            "project_identifier": identifier,
            "project_funding": funding_source,
            "project_url": project_url,
            "cordis_url": cordis_url
        })

    return abstracts


def load_existing_output(output_path: Path) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Loads existing harvested JSON file if present to support resuming."""
    if output_path.exists() and output_path.stat().st_size > 0:
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            seen_projects = set(item.get("project_url") for item in data if item.get("project_url"))
            logger.info(f"Resuming: found {len(data)} existing abstracts from {len(seen_projects)} projects in {output_path}")
            return data, seen_projects
        except Exception as e:
            logger.warning(f"Could not parse existing output file ({e}). Starting fresh.")
    return [], set()


def save_output(output_path: Path, data: List[Dict[str, Any]]):
    """Safely saves results to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    temp_path.replace(output_path)


async def crawl_all_projects_sequentially(
    project_slugs: List[str],
    db_projects: List[Dict[str, str]],
    output_path: Path,
    request_delay: float = 1.0
) -> List[Dict[str, Any]]:
    """
    Crawls project detail pages sequentially with polite delay and auto-resume.
    Saves incrementally to avoid any lost progress.
    """
    all_abstracts, seen_projects = load_existing_output(output_path)

    pending_slugs = []
    for slug in project_slugs:
        full_url = BASE_URL + slug if not slug.startswith("http") else slug
        if full_url not in seen_projects:
            pending_slugs.append(slug)

    logger.info(f"Projects to harvest: {len(pending_slugs)} (already harvested: {len(seen_projects)}).")

    if not pending_slugs:
        logger.info("All projects have already been harvested!")
        return all_abstracts

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for slug in tqdm(pending_slugs, desc="Crawling projects sequentially"):
            full_url = BASE_URL + slug if not slug.startswith("http") else slug
            
            html = await fetch_with_retry(client, full_url)
            if html:
                pas = parse_project_and_practice_abstracts(html, full_url, db_projects)
                if pas:
                    all_abstracts.extend(pas)
                save_output(output_path, all_abstracts)
            
            await asyncio.sleep(request_delay + random.uniform(0.1, 0.4))

    return all_abstracts


async def main_async(args):
    output_path = Path(args.output)

    # 1. Load project details from DB
    db_projects = load_db_projects()

    # 2. Discover EU CAP Network project URLs
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        slugs = await discover_project_urls(
            client,
            max_pages=args.max_pages,
            max_projects=args.max_projects
        )

    # 3. Crawl projects sequentially with polite delay & auto-resume
    logger.info(f"Crawling {len(slugs)} project pages with delay={args.delay}s (polite sequential mode)...")
    abstracts = await crawl_all_projects_sequentially(
        slugs,
        db_projects,
        output_path,
        request_delay=args.delay
    )

    logger.info(f"Harvest complete! Total practice abstracts in file: {len(abstracts)}")
    logger.info(f"Results saved to: {output_path}")

    # Summary statistics
    with_grant = sum(1 for a in abstracts if a.get("project_grant_number"))
    with_acronym = sum(1 for a in abstracts if a.get("project_acronym"))
    h2020_count = sum(1 for a in abstracts if "2020" in a.get("project_funding", ""))
    he_count = sum(1 for a in abstracts if "Horizon Europe" in a.get("project_funding", ""))
    
    logger.info(f"Summary:")
    logger.info(f"  Total Practice Abstracts: {len(abstracts)}")
    if abstracts:
        logger.info(f"  With Grant Agreement Number: {with_grant}/{len(abstracts)} ({with_grant/len(abstracts)*100:.1f}%)")
        logger.info(f"  With Project Acronym: {with_acronym}/{len(abstracts)} ({with_acronym/len(abstracts)*100:.1f}%)")
    logger.info(f"  Horizon 2020: {h2020_count}, Horizon Europe: {he_count}")


def main():
    parser = argparse.ArgumentParser(description="Harvest Practice Abstracts from EU CAP Network enriched with DB project details.")
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT_PATH),
        help=f"Path to output JSON file (default: {DEFAULT_OUTPUT_PATH})"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional limit on search pages to crawl."
    )
    parser.add_argument(
        "--max-projects",
        type=int,
        default=None,
        help="Optional limit on project pages to crawl (useful for testing)."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between requests (default: 1.0s)."
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
