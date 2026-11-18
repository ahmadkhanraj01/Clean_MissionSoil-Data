#!/usr/bin/env python3
"""
EU-FarmBook contributions harvester: for every project already ingested into
`harvest.projects` (by harvest_eufarmbook_projects.py), visits that project's
Contributions tab on EU-FarmBook, collects every contribution, opens each
contribution's detail page, and extracts structured fields.

Inserts contributions DIRECTLY into `harvest.items` — no JSON files at any stage.
Projects are loaded from harvest.projects table (DB), not from any file.

Usage:
  # Scrape all projects and insert contributions directly to DB:
  python harvest_eufarmbook_contributions.py

  # Scrape only first N projects (useful for testing):
  python harvest_eufarmbook_contributions.py --max-projects 3

  # Show the browser window (for debugging selectors):
  python harvest_eufarmbook_contributions.py --no-headless
"""

# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config  # noqa: E402,F401  (loads .env)
# --------------------------------------------------------------------------------------------
import sys, os, time, re, json, argparse, hashlib, requests
from pathlib import Path
from datetime import datetime
from common.database import dbInit
from psycopg2.extras import execute_values


BASE_URL = "https://eufarmbook.eu"
CONTRIB_LINK_RE = re.compile(r"/en/contributions/([a-f0-9]{16,})")
PROJECT_LINK_RE = re.compile(r"/en/projects/([a-f0-9]{16,})")

SOURCE_NAME = "EUFARMBOOK"

INSERT_SQL = """
    INSERT INTO harvest.items
        (identifier, identifiertype, uri, resultobject, resulttype,
         itemtype, title, source, project, date, hash)
    VALUES %s
    ON CONFLICT (hash) DO UPDATE SET
        resultobject = EXCLUDED.resultobject,
        resulttype   = EXCLUDED.resulttype
"""


def to_schema_org(contrib: dict) -> dict:
    """
    Convert a raw EU-FarmBook contribution dict into a schema.org-shaped JSON
    object. process.py routes resulttype='schema.org' to
    import_metadata('schema-org', txt), which expects this shape.
    """
    authors = contrib.get("authors") or []
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
        "contentUrl": contrib.get("file_type_link"),
        "about":      contrib.get("purpose"),
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

    return {k: v for k, v in schema.items() if v not in (None, [], "")}


def insert_contributions_to_db(contributions: list) -> int:
    """
    Batch-insert a list of raw contribution dicts into harvest.items
    as schema.org JSON in a single DB round-trip.
    Returns the number of rows inserted/updated.
    """
    rows = []
    for contrib in contributions:
        identifier = contrib.get("identifier") or contrib.get("doi", "")
        if not identifier:
            continue

        schema_obj = to_schema_org(contrib)
        h = hashlib.md5(f"{identifier}{SOURCE_NAME}".encode()).hexdigest()

        rows.append((
            identifier,
            "eufarmbook_id",
            contrib.get("doi"),
            json.dumps(schema_obj, ensure_ascii=False),  # resultobject
            "schema.org",                                # resulttype
            contrib.get("resource_type") or "contribution",  # itemtype
            contrib.get("title"),
            SOURCE_NAME,
            contrib.get("project_grantnr"),              # links to parent project
            contrib.get("creation_date"),
            h,
        ))

    if not rows:
        return 0

    conn = dbInit()
    cur = conn.cursor()
    execute_values(cur, INSERT_SQL, rows)
    conn.commit()
    conn.close()
    return len(rows)



def load_projects_from_db():
    """Load all EU-FarmBook projects from harvest.projects table."""
    conn = dbInit()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT code, grantnr, website
            FROM harvest.projects
            WHERE source = 'EU-FarmBook'
              AND coalesce(website, '') != ''
            ORDER BY grantnr
        """)
        rows = cur.fetchall()
    conn.close()

    projects = [
        {
            "title":        r[0],
            "grant_number": r[1],
            "eufarmbook_url": r[2],
        }
        for r in rows
    ]
    print(f"Loaded {len(projects)} EU-FarmBook projects from harvest.projects")
    return projects


def scrape_eufarmbook_contributions(projects, max_projects=None, headless=True):
    """Live harvest: for each project, collect + parse all its contributions."""
    from playwright.sync_api import sync_playwright
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    def safe_content(page):
        for _ in range(5):
            try:
                return page.content()
            except Exception:
                time.sleep(0.5)
        return page.content()

    def wait_past_anubis(page, timeout_s=30, expect_text=None):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            content = safe_content(page)
            if "Protected by EU-FarmBook BotStopper" not in content and "Anubis" not in content:
                if expect_text is None or expect_text in content:
                    return True
            time.sleep(0.8)
        return False

    def values_after_label(soup, label):
        """Find a label like 'AUTHORS' / 'PURPOSE' by visible text and
        return ALL following values as a list. Handles both cases:
        - multiple separate tagged elements (like Keywords)
        - one comma-separated text node (e.g. "Andrea Marescotti, Matteo
          Mengoni, Giovanni Belletti") which gets split into a real list."""
        node = soup.find(string=re.compile(rf"^\s*{re.escape(label)}\s*$", re.I))
        if not node:
            return []
        label_tag = node.find_parent(["div", "span", "dt", "p"]) or node.parent
        container = label_tag.find_next_sibling() if label_tag else None
        if not container:
            return []
        raw_values = [v.strip() for v in container.stripped_strings if v.strip()]
        # split any comma-separated entries into individual values
        values = []
        for v in raw_values:
            values.extend([part.strip() for part in v.split(",") if part.strip()])
        return values

    def text_after_label(soup, label):
        """Single-value convenience wrapper around values_after_label."""
        vals = values_after_label(soup, label)
        return vals[0] if vals else None

    def one_or_list(values):
        """Per request: single value stays a plain string, multiple values
        become a list."""
        if not values:
            return None
        if len(values) == 1:
            return values[0]
        return values
    def get_view_button_link(page):
        """
        The 'View document' / 'View slideshow/presentation' / 'View image'
        button is JS-driven (no static href in the DOM) - so instead of
        parsing HTML, we click it and capture where it actually navigates:
        either a new browser tab opens (most common for file viewers), or
        the current page's URL changes in place.
        """
        try:
            btn = page.locator(
                "button:has-text('View'), a:has-text('View')"
            ).first
            if btn.count() == 0:
                return None
 
            context = page.context
            before_url = page.url
 
            try:
                with context.expect_page(timeout=5000) as new_page_info:
                    btn.click(timeout=5000)
                new_page = new_page_info.value
                new_page.wait_for_load_state("domcontentloaded", timeout=10000)
                link = new_page.url
                new_page.close()
                return link
            except Exception:
                # no new tab opened - maybe it navigated the same tab instead
                page.wait_for_timeout(1500)
                after_url = page.url
                if after_url != before_url:
                    link = after_url
                    page.go_back(wait_until="domcontentloaded", timeout=10000)
                    return link
        except Exception:
            pass
        return None
    all_contributions = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36")
        )

        projects_to_process = projects[:max_projects] if max_projects else projects

        for pi, proj in enumerate(projects_to_process, 1):
            proj_url = proj.get("eufarmbook_url") or proj.get("website") or ""
            proj_title = proj.get("title") or proj.get("code") or proj_url
            if not proj_url:
                continue
            contributions_url = proj_url.rstrip('/') + '/contributions'
            project_contributions = []  # per-project batch for direct DB insert
            print(f"[{pi}/{len(projects_to_process)}] Project: {proj_title}")

            try:
                page.goto(contributions_url, wait_until="domcontentloaded", timeout=30000)
                wait_past_anubis(page)
            except Exception as e:
                print(f"  Failed to open contributions page: {e}")
                continue

            links = set()
            stable_rounds = 0
            while stable_rounds < 3:
                soup = BeautifulSoup(safe_content(page), "html.parser")
                before = len(links)
                for a in soup.find_all("a", href=True):
                    m = CONTRIB_LINK_RE.search(a["href"])
                    if m:
                        links.add(urljoin(BASE_URL, "/en/contributions/" + m.group(1)))
                if len(links) == before:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                page.mouse.wheel(0, 3000)
                time.sleep(1.0)

            print(f"  Found {len(links)} contributions")

            for ci, link in enumerate(sorted(links), 1):
                try:
                    page.goto(link, wait_until="domcontentloaded", timeout=30000)
                    wait_past_anubis(page)
                    soup = BeautifulSoup(safe_content(page), "html.parser")

                    contrib_id = link.rstrip('/').split('/')[-1]

                    # Get file URL directly from the REST API
                    file_type_link = None
                    try:
                        api_resp = requests.get(
                            f"{BASE_URL}/api/contributions/{contrib_id}",
                            headers={"User-Agent": "Mozilla/5.0"},
                            timeout=10
                        )
                        if api_resp.ok:
                            api_text = api_resp.text
                            # extract files[].src S3 URL from Next.js escaped JSON
                            src_matches = re.findall(r'https://ugent-dict-farmbook[^ "\\]+', api_text)
                            if src_matches:
                                file_type_link = src_matches[0]
                    except Exception as api_err:
                        print(f"    API call failed for {contrib_id}: {api_err}")

                    h1 = soup.find("h1")
                    title = h1.get_text(strip=True) if h1 else None

                    desc_heading = soup.find(
                        string=re.compile(r"^\s*Detail description\s*$", re.I))
                    description = None
                    if desc_heading:
                        # Collect text from every sibling paragraph/element
                        # after the heading, stopping once we hit the next
                        # section heading (e.g. an image, or the info panel).
                        # This handles descriptions split across multiple
                        # <p> tags instead of just one.
                        heading_tag = desc_heading.find_parent(["h1", "h2", "h3", "h4"])
                        parts = []
                        if heading_tag:
                            for sib in heading_tag.find_next_siblings():
                                if sib.name in ["h1", "h2", "h3", "h4"]:
                                    break
                                if sib.name == "img":
                                    break
                                txt = sib.get_text(" ", strip=True)
                                if txt:
                                    parts.append(txt)
                                # stop once we've collected a reasonable
                                # amount and hit a non-text container (like
                                # the image gallery below the description)
                                if sib.find("img"):
                                    break
                        description = " ".join(parts).strip() or None

                    project_name = None
                    proj_link_tag = soup.find("a", href=PROJECT_LINK_RE)
                    if proj_link_tag:
                        project_name = proj_link_tag.get_text(strip=True)
                    project_id = proj.get("grant_id")
                    project_grantnr=proj.get("grant_number")

                    location = text_after_label(soup, "LOCATION")
                    language = text_after_label(soup, "ORIGIN LANGUAGE")
                    creation_date = text_after_label(soup, "CREATED ON")
                    authors = values_after_label(soup, "AUTHORS")
                    purpose = values_after_label(soup, "PURPOSE")

                    file_type = text_after_label(soup, "FILE TYPE")
                    license_ = text_after_label(soup, "LICENSE")

                    keywords = []
                    kw_heading = soup.find(string=re.compile(r"^\s*KEYWORDS\s*$", re.I))
                    if kw_heading:
                        kw_container = kw_heading.find_next(["div", "ul"])
                        if kw_container:
                            keywords = [
                                t.strip() for t in kw_container.stripped_strings
                                if t.strip()
                            ]

                    file_type_link = None
                    file_url_pattern = re.compile(
                        r"(s3\.ugent\.be|knowledge-object|\.pdf($|\?)|\.docx?($|\?)|"
                        r"\.pptx?($|\?)|\.mp4($|\?)|\.jpg($|\?)|\.jpeg($|\?)|\.png($|\?))",
                        re.I)
                    candidates = []
                    for tag in soup.find_all(["a", "button"]):
                        for attr in ["href", "data-href", "data-url", "data-file",
                                     "data-src", "data-download-url"]:
                            val = tag.get(attr)
                            if val:
                                candidates.append(val)
                    for val in candidates:
                        if file_url_pattern.search(val):
                            file_type_link = urljoin(BASE_URL, val)
                            break
                    if not file_type_link:
                        for a_tag in soup.find_all("a", href=True):
                            if "download" in a_tag.get_text(" ", strip=True).lower():
                                file_type_link = urljoin(BASE_URL, a_tag["href"])
                                break
 
                    # Fallback: the "View document"/"View slideshow"/"View image"
                    # button has no static href - it's JS-driven. Actually click
                    # it and capture where it navigates.
                    if not file_type_link:
                        file_type_link = get_view_button_link(page)


                    item = {
                        "identifier": contrib_id,
                        "doi": link,
                        "title": title,
                        "description": description,
                        "location": location,
                        "language": language,
                        "keywords": keywords,
                        "creation_date": creation_date,
                        "authors": authors,
                        "purpose": purpose,
                        "resource_type": file_type,
                        "file_type_link": file_type_link,
                        "license": license_,
                        "source": SOURCE_NAME,
                        "project": project_name or proj_title,
                        "project_id": project_id,
                        "project_grantnr": project_grantnr,
                    }
                    all_contributions.append(item)
                    project_contributions.append(item)
                    print(f"    [{ci}/{len(links)}] {title}")

                except Exception as e:
                    print(f"    Error on {link}: {e}")

                time.sleep(1.0)

            # --- Insert this project's contributions directly to DB ---
            if project_contributions:
                n_inserted = insert_contributions_to_db(project_contributions)
                print(f"  ✅ Inserted {n_inserted}/{len(project_contributions)} contributions to harvest.items")

        browser.close()

    total = len(all_contributions)
    print(f"Done! Scraped {total} contributions, all inserted directly to harvest.items.")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape EU-FarmBook contributions and insert directly into harvest.items (no JSON).")
    parser.add_argument("--max-projects", type=int, default=None,
                        help="Max number of projects to scrape (for testing)")
    parser.add_argument("--no-headless", dest="headless", action="store_false", default=True,
                        help="Show the browser window (useful for debugging selectors)")
    args = parser.parse_args()

    projects = load_projects_from_db()
    if not projects:
        print("No EU-FarmBook projects found in harvest.projects. Run harvest_eufarmbook_projects.py first.")
        sys.exit(1)
    scrape_eufarmbook_contributions(projects, max_projects=args.max_projects, headless=args.headless)