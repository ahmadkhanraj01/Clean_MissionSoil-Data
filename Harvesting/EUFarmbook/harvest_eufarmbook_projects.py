#!/usr/bin/env python3
"""
EU-FarmBook project harvester: Ingests Horizon Europe & Horizon 2020 projects
from EU-FarmBook DIRECTLY into the `harvest.projects` database table.
No intermediate JSON files — all data goes straight to DB.

Works seamlessly with:
  1. harvest_eufarmbook_projects.py        -> ingests all projects into harvest.projects
  2. harvest_cordis_project_metadata.py     -> enriches projects with CORDIS SPARQL metadata into harvest.items
  3. harvest_eufarmbook_contributions.py   -> harvests EU-FarmBook contributions directly into harvest.items

Usage:
  # Scrape live from EU-FarmBook and insert directly to DB:
  python harvest_eufarmbook_projects.py

  # Scrape only first N projects (for testing):
  python harvest_eufarmbook_projects.py --max 5

  # Show the browser window (for debugging selectors):
  python harvest_eufarmbook_projects.py --no-headless
"""

# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config  # noqa: E402,F401  (loads .env)
# --------------------------------------------------------------------------------------------
import sys, os, time, re, json, argparse
from pathlib import Path
from common.database import dbInit, dbQuery
from psycopg2.extras import execute_values

GRANT_NUM_RE = re.compile(r"10\.3030/(\d+)")
PROJECT_LINK_RE = re.compile(r"/en/projects/([a-f0-9]{16,})")
BASE_URL = "https://eufarmbook.eu"
PROJECTS_URL = "https://eufarmbook.eu/en/projects"


def ensure_table():
    """Ensure harvest schema and projects table exist."""
    dbQuery("""
    CREATE SCHEMA IF NOT EXISTS harvest;
    CREATE TABLE IF NOT EXISTS harvest.projects (
        code character varying(99) NOT NULL,
        title text,
        funding character varying(99),
        website character varying(99),
        grantnr character varying(99) NOT NULL,
        source character varying(99)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_hrv_prj_grant_code ON harvest.projects (code, grantnr);
    """, hasoutput=False)


def get_best_grant(p):
    """
    Extract the most accurate CORDIS grant number.
    Handles:
      1. '10.3030/101000918'
      2. Plain numeric IDs: '101156076'
      3. Numeric IDs in CORDIS URL: 'https://cordis.europa.eu/project/id/227161'
      4. Known project corrections (e.g. BIKE -> 952872, LANDMARK -> 635201)
      5. Fallback for projects with '-' on EU-FarmBook (eufb-<hash>) so all 341 are preserved.
    """
    code = (p.get("title") or "").strip()
    gid = (p.get("grant_id") or "").strip()
    clink = (p.get("cordis_link") or "").strip()
    url = (p.get("eufarmbook_url") or "").strip()

    if code == "BIKE":
        return "952872"
    if "LANDMARK" in code:
        return "635201"

    # Pattern 1: 10.3030/(\d+)
    m1 = re.search(r"10\.3030/(\d+)", gid)
    if m1:
        return m1.group(1)

    # Pattern 2: Direct numeric grant_id
    m2 = re.search(r"^\d+$", gid)
    if m2:
        return m2.group(0)

    # Pattern 3: CORDIS link contains project id
    m3 = re.search(r"/project/id/(\d+)", clink)
    if m3:
        return m3.group(1)

    # Pattern 4: Fallback to EU-FarmBook project hash if EU-FarmBook displays '-'
    m4 = re.search(r"/projects/([a-f0-9]{10,})", url)
    if m4:
        return f"eufb-{m4.group(1)[:12]}"

    return None


def batch_insert_projects(projects):
    """Fast batch insert/update into harvest.projects in a single network round-trip."""
    rows = []
    for p in projects:
        code = (p.get("title") or "").strip()[:99]
        title = (p.get("subtitle") or p.get("title") or "").strip()
        funding = (p.get("project_type") or "")[:99]
        website = (p.get("project_website") or "")[:99]
        grantnr = get_best_grant(p)

        if code and grantnr:
            rows.append((code, title, funding, website, grantnr, 'EU-FarmBook'))

    if not rows:
        return 0

    sql = """
        INSERT INTO harvest.projects
        (code, title, funding, website, grantnr, source)
        VALUES %s
        ON CONFLICT (grantnr, code)
        DO UPDATE SET
            title = EXCLUDED.title,
            funding = EXCLUDED.funding,
            website = EXCLUDED.website,
            source = EXCLUDED.source
    """

    conn = dbInit()
    cur = conn.cursor()
    execute_values(cur, sql, rows)
    conn.commit()
    conn.close()

    return len(rows)





def scrape_eufarmbook(project_types=("Horizon 2020", "Horizon Europe"), max_projects=None, headless=True):
    """Live harvest from EU-FarmBook website using Playwright."""
    from playwright.sync_api import sync_playwright
    from bs4 import BeautifulSoup
    from urllib.parse import quote, urljoin

    def safe_content(page):
        for _ in range(5):
            try:
                return page.content()
            except Exception:
                time.sleep(0.5)
        return page.content()

    def wait_past_anubis(page, timeout_s=30):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            content = safe_content(page)
            if "Protected by EU-FarmBook BotStopper" not in content and "Anubis" not in content:
                if "Projects" in content:
                    return True
            time.sleep(0.8)
        return False

    listing_url = f"{PROJECTS_URL}?projectType={quote('_'.join(project_types))}"
    print(f"Connecting to EU-FarmBook: {listing_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(listing_url, wait_until="domcontentloaded", timeout=60000)
        wait_past_anubis(page)

        links = set()
        for page_num in range(1, 100):
            url = listing_url if page_num == 1 else f"{listing_url}&page={page_num}"
            print(f"Fetching listing page {page_num}...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            wait_past_anubis(page)

            soup = BeautifulSoup(safe_content(page), "html.parser")
            before = len(links)
            for a in soup.find_all("a", href=True):
                m = PROJECT_LINK_RE.search(a["href"])
                if m:
                    links.add(urljoin(BASE_URL, "/en/projects/" + m.group(1)))

            gained = len(links) - before
            print(f"Collected {len(links)} links (+{gained})")
            if gained == 0 or (max_projects and len(links) >= max_projects):
                break

        print(f"Extracting details for {len(links)} projects...")
        all_items = []
        for i, url in enumerate(sorted(links), 1):
            if max_projects and i > max_projects:
                break
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                wait_past_anubis(page)
                soup = BeautifulSoup(safe_content(page), "html.parser")

                h1 = soup.find("h1")
                code = h1.get_text(strip=True) if h1 else None
                nxt = h1.find_next(["p", "h2", "div"]) if h1 else None
                title = nxt.get_text(strip=True) if nxt else code

                grant_id = None
                grant_node = soup.find(string=re.compile(r"^\s*GRANT ID\s*$", re.I))
                if grant_node:
                    parent_text = grant_node.parent.find_next(string=True)
                    if parent_text:
                        grant_id = parent_text.strip()

                funding = "Horizon Europe"
                type_node = soup.find(string=re.compile(r"^\s*PROJECT TYPE\s*$", re.I))
                if type_node:
                    funding_text = type_node.parent.find_next(string=True)
                    if funding_text:
                        funding = funding_text.strip()

                website = None
                cordis_link = None
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    txt = a.get_text(strip=True).lower()
                    if "project website" in txt:
                        website = href
                    if "cordis" in txt or "cordis.europa.eu" in href:
                        cordis_link = href

                item = {
                    "eufarmbook_url": url,
                    "title": code,
                    "subtitle": title,
                    "project_type": funding,
                    "project_website": website,
                    "grant_id": grant_id,
                    "cordis_link": cordis_link
                }
                all_items.append(item)
                print(f"[{i}/{len(links)}] Parsed: {code}")
            except Exception as e:
                print(f"Error on {url}: {e}")

        browser.close()

    # Insert directly to DB — no JSON file
    count = batch_insert_projects(all_items)
    print(f"Done! Scraped {len(all_items)} projects, inserted {count} directly to harvest.projects.")
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape EU-FarmBook projects and insert directly into harvest.projects.")
    parser.add_argument("--max", type=int, default=None, help="Max projects to scrape (for testing)")
    parser.add_argument("--no-headless", dest="headless", action="store_false", default=True,
                        help="Show browser window (useful for debugging)")
    args = parser.parse_args()

    ensure_table()
    scrape_eufarmbook(max_projects=args.max, headless=args.headless)
