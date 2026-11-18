#!/usr/bin/env python3
"""
harmonize_all_to_validate.py
-----------------------------
Generalised harmonizer: reads ALL records from harvest.items and writes
them into the relational validate schema, regardless of source or format.

Supports two payload formats stored in harvest.items.resultobject:
  1. Flat Solr JSON  -- all sources except EU CAP Network
     Keys: identifier, title, abstract, type, language, license, thumbnail,
           links, subjects, matched_subjects, persons, organizations,
           contact_persons, contact_organizations, view_contacts, view_authors,
           authors_suggest, projects, project_acronyms, european_funded,
           date, date_publication, date_creation, date_harvest, spatial, ...
  2. MCF YAML -- EU CAP Network and CORDIS project records (resulttype='yaml')
     Keys: mcf, metadata, identification, contacts, distribution

Entities populated:
  validate.sources              -> harvesting source registry
  validate.records              -> primary record, raw_metadata=JSONB
  validate.subjects             -> normalised keyword/subject labels
  validate.persons              -> author / contact persons
  validate.organizations        -> contact organisations
  validate.distributions        -> access links / URLs
  validate.projects             -> project acronyms
  validate.record_source        -> record <-> source junction
  validate.record_subject       -> record <-> subject junction
  validate.record_person        -> record <-> person junction
  validate.record_organization  -> record <-> organisation junction
  validate.record_project       -> record <-> project junction

Usage:
  # Dry-run (no DB writes):
  python harmonize_all_to_validate.py --dry-run

  # Commit all records:
  python harmonize_all_to_validate.py

  # Only a specific source:
  python harmonize_all_to_validate.py --source openaire

  # Limit records (useful for testing):
  python harmonize_all_to_validate.py --limit 500 --dry-run

  # Batch size (records per DB transaction, default 500):
  python harmonize_all_to_validate.py --batch-size 1000
"""

# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config  # noqa: E402,F401  (loads .env)
from common.sources import canonical_source, similar_sources, source_key  # noqa: E402
# --------------------------------------------------------------------------------------------
import os
import re
import sys
import uuid
import json
import logging
import argparse
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml
import psycopg2
from psycopg2.extras import Json, execute_values
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("harmonize_all.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("harmonize_all")

# ---------------------------------------------------------------------------
# Environment / DB defaults
# ---------------------------------------------------------------------------
# Environment is loaded by common.db (repo-root .env)

DEFAULT_HOST     = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST")
DEFAULT_PORT     = int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or 5432)
DEFAULT_DBNAME   = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB")
DEFAULT_USER     = os.getenv("DB_USER") or os.getenv("POSTGRES_USER")
DEFAULT_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")

URL_RE = re.compile(r"^https?://[^\s]+$")


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def is_valid_url(url: Any) -> bool:
    return bool(url and URL_RE.match(str(url).strip()))


def clean_and_parse_url(raw: Any) -> Optional[str]:
    """Clean, unquote, and validate any candidate URL."""
    if not raw:
        return None
    s = str(raw).strip()
    if "%" in s:
        try:
            s = urllib.parse.unquote(s).strip()
        except Exception:
            pass
    return s if is_valid_url(s) else None


def parse_date(val: Any) -> Optional[datetime]:
    """Parse any date-like value to a UTC-aware datetime."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    s = str(val).strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m", "%Y",
    ):
        try:
            dt = datetime.strptime(s[: len(fmt)], fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    m = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", s)
    if m:
        return datetime(
            int(m.group(1)),
            int(m.group(2) or 1),
            int(m.group(3) or 1),
            tzinfo=timezone.utc,
        )
    return None


def clean_project_name(raw_val: Any, grant_map: Optional[Dict[str, str]] = None) -> Optional[str]:
    """
    Decodes raw JSON strings, strips noise, and resolves numeric grant IDs to clean acronyms.
    Never returns raw serialized JSON text (e.g. '{"title": ...}').
    """
    if not raw_val:
        return None

    if isinstance(raw_val, dict):
        val = raw_val.get("acronym") or raw_val.get("code") or raw_val.get("title") or raw_val.get("grantnr") or ""
        return clean_project_name(val, grant_map)

    s = str(raw_val).strip()
    if not s or s.lower() in ("-", "–", "none", "null", "n/a", "unknown"):
        return None

    # Handle stringified JSON (e.g. '{"title":..., "acronym":"SED-RUNS", "grantnr":"101033236"}')
    if s.startswith("{") and s.endswith("}"):
        try:
            pdict = json.loads(s)
            val = pdict.get("acronym") or pdict.get("code") or pdict.get("title") or pdict.get("grantnr") or ""
            return clean_project_name(val, grant_map)
        except Exception:
            return None

    # If it's a numeric grant number, resolve to acronym if known
    if grant_map and s in grant_map:
        return grant_map[s].strip()

    # Discard leftover JSON artifacts or invalid project names
    if "{" in s or "}" in s or len(s) < 2:
        return None

    return s


def as_list(val: Any) -> List:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        return [val] if val.strip() else []
    return [val]


def first_str(val: Any) -> Optional[str]:
    if isinstance(val, str):
        return val.strip() or None
    if isinstance(val, list):
        for item in val:
            s = first_str(item)
            if s:
                return s
    if isinstance(val, dict):
        for v in val.values():
            s = first_str(v)
            if s:
                return s
    return None


def deduplicate_batch(batch: List[Tuple], key_indices: Tuple) -> List[Tuple]:
    seen: Set = set()
    out: List[Tuple] = []
    for row in batch:
        key = tuple(row[i] for i in key_indices)
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


# ---------------------------------------------------------------------------
# Parsed record container
# ---------------------------------------------------------------------------

class ParsedRecord:
    __slots__ = (
        "identifier", "title", "abstract", "resource_type", "language",
        "license_text", "thumbnail", "url", "pub_date", "creation_date",
        "updated_date", "harvest_date", "temporal_start", "temporal_end",
        "spatial", "subjects", "persons", "organizations", "links",
        "project_acronyms", "raw", "distributions",
    )

    def __init__(self):
        self.identifier: str = ""
        self.title: str = "Untitled"
        self.abstract: Optional[str] = None
        self.resource_type: str = "Unknown"
        self.language: str = "en"
        self.license_text: Optional[str] = None
        self.thumbnail: Optional[str] = None
        self.url: Optional[str] = None
        self.pub_date: Optional[datetime] = None
        self.creation_date: Optional[datetime] = None
        self.updated_date: Optional[datetime] = None
        self.harvest_date: Optional[datetime] = None
        self.temporal_start: Optional[datetime] = None
        self.temporal_end: Optional[datetime] = None
        self.spatial: Optional[str] = None
        self.subjects: List[str] = []
        self.persons: List[str] = []
        self.organizations: List[str] = []
        self.links: List[str] = []
        self.distributions: List[Tuple[str, str, str]] = []  # (name, format, url)
        self.project_acronyms: List[str] = []
        self.raw: Dict = {}


# ---------------------------------------------------------------------------
# Payload parsers
# ---------------------------------------------------------------------------

def parse_solr_json(row, grant_map: Optional[Dict[str, str]] = None) -> Optional[ParsedRecord]:
    """
    Parse a harvest.items row whose resultobject is the flat Solr/harvest JSON.
    All sources except EU CAP Network produce this format.
    """
    ident, id_type, uri, robj, rtype, doiobj, source, ins_date, item_type, \
        title_col, lang_col, date_col, project_col = row

    try:
        data: Dict = json.loads(robj) if robj else {}
    except Exception as e:
        logger.warning(f"[{source}] JSON parse error for {ident}: {e}")
        return None

    p = ParsedRecord()
    p.raw = data

    p.identifier    = (first_str(data.get("identifier")) or ident or "").strip()
    p.title         = (first_str(data.get("title")) or title_col or "Untitled").strip()
    p.abstract      = first_str(data.get("abstract"))
    p.resource_type = first_str(data.get("type")) or item_type or "Unknown"
    p.language      = first_str(data.get("language")) or lang_col or "en"
    p.license_text  = first_str(data.get("license"))
    thumb = first_str(data.get("thumbnail"))
    p.thumbnail     = clean_and_parse_url(thumb)
    p.harvest_date  = parse_date(ins_date) or datetime.now(timezone.utc)
    p.spatial       = first_str(data.get("spatial"))

    p.pub_date       = parse_date(data.get("date_publication") or data.get("date") or date_col)
    p.creation_date  = parse_date(data.get("date_creation")) or p.pub_date
    p.updated_date   = parse_date(data.get("date_revision"))
    p.temporal_start = parse_date(data.get("temporal_start"))
    p.temporal_end   = parse_date(data.get("temporal_end"))

    # Links / Distributions
    distributions_list: List[Tuple[str, str, str]] = []
    links_raw: List[str] = []
    seen_urls: Set[str] = set()

    for lval in as_list(data.get("links")):
        link_dict = {}
        if isinstance(lval, dict):
            link_dict = lval
        elif isinstance(lval, str):
            s = lval.strip()
            if s.startswith("{") and s.endswith("}"):
                try:
                    link_dict = json.loads(s)
                except Exception:
                    link_dict = {"url": s}
            else:
                link_dict = {"url": s}

        raw_url = link_dict.get("url") or link_dict.get("href") or link_dict.get("link") or ""
        clean_url = clean_and_parse_url(raw_url)
        if clean_url and clean_url not in seen_urls:
            seen_urls.add(clean_url)
            name = link_dict.get("name") or "Access link"
            fmt = link_dict.get("format") or "URL"
            distributions_list.append((str(name)[:255], str(fmt)[:100], clean_url))
            links_raw.append(clean_url)

    p.distributions = distributions_list
    p.links = links_raw
    if clean_and_parse_url(uri):
        p.url = clean_and_parse_url(uri)
    elif links_raw:
        p.url = links_raw[0]
    elif clean_and_parse_url(p.identifier):
        p.url = clean_and_parse_url(p.identifier)

    # Subjects
    seen_subj: Set[str] = set()
    for field in ("subjects", "matched_subjects"):
        for raw_s in as_list(data.get(field)):
            s = str(raw_s).strip()
            if s and len(s) > 2 and s.lower() not in seen_subj:
                seen_subj.add(s.lower())
                p.subjects.append(s)

    # Persons
    seen_pers: Set[str] = set()
    for field in ("persons", "view_authors", "authors_suggest", "contact_persons"):
        for raw_p in as_list(data.get(field)):
            name = str(raw_p).strip()
            if name and len(name) > 1 and name.lower() not in seen_pers:
                seen_pers.add(name.lower())
                p.persons.append(name)

    # Organizations
    seen_org: Set[str] = set()
    for field in ("organizations", "contact_organizations"):
        for raw_o in as_list(data.get(field)):
            org = str(raw_o).strip()
            if org and len(org) > 1 and org.lower() not in seen_org:
                seen_org.add(org.lower())
                p.organizations.append(org)

    # Projects
    seen_proj: Set[str] = set()
    for field in ("project_acronyms", "projects"):
        for raw_pr in as_list(data.get(field)):
            c_name = clean_project_name(raw_pr, grant_map)
            if c_name and c_name.lower() not in seen_proj:
                seen_proj.add(c_name.lower())
                p.project_acronyms.append(c_name)
    if project_col:
        c_col = clean_project_name(project_col, grant_map)
        if c_col and c_col.lower() not in seen_proj:
            seen_proj.add(c_col.lower())
            p.project_acronyms.append(c_col)

    return p


def parse_schema_org(row, grant_map: Optional[Dict[str, str]] = None) -> Optional[ParsedRecord]:
    """
    Parse a harvest.items row whose resultobject is Schema.org JSON-LD.
    """
    ident, id_type, uri, robj, rtype, doiobj, source, ins_date, item_type, \
        title_col, lang_col, date_col, project_col = row

    try:
        data: Dict = json.loads(robj) if isinstance(robj, str) else (robj or {})
    except Exception as e:
        logger.warning(f"[{source}] Schema.org JSON parse error for {ident}: {e}")
        return None

    if not isinstance(data, dict):
        return None

    p = ParsedRecord()
    p.raw = data

    p.identifier    = (data.get("identifier") or data.get("@id") or ident or "").strip()
    p.title         = (data.get("name") or data.get("title") or title_col or "Untitled").strip()
    p.abstract      = first_str(data.get("description"))
    p.resource_type = first_str(data.get("additionalType")) or first_str(data.get("@type")) or item_type or "Dataset"
    p.language      = first_str(data.get("inLanguage")) or lang_col or "en"
    p.license_text  = first_str(data.get("license"))
    thumb           = first_str(data.get("thumbnailUrl")) or first_str(data.get("image"))
    p.thumbnail     = clean_and_parse_url(thumb)
    p.harvest_date  = parse_date(ins_date) or datetime.now(timezone.utc)
    p.spatial       = first_str(data.get("spatialCoverage"))

    p.pub_date      = parse_date(data.get("datePublished") or date_col)
    p.creation_date = parse_date(data.get("dateCreated")) or p.pub_date
    p.updated_date  = parse_date(data.get("dateModified"))

    # Temporal
    temp = data.get("temporalCoverage")
    if temp and isinstance(temp, str) and "/" in temp:
        parts = temp.split("/")
        p.temporal_start = parse_date(parts[0])
        p.temporal_end   = parse_date(parts[1])
    else:
        p.temporal_start = parse_date(temp)

    # Distributions
    distributions_list: List[Tuple[str, str, str]] = []
    links_raw: List[str] = []
    seen_urls: Set[str] = set()

    for d in as_list(data.get("distribution")):
        if isinstance(d, dict):
            raw_url = d.get("contentUrl") or d.get("url") or ""
            clean_url = clean_and_parse_url(raw_url)
            if clean_url and clean_url not in seen_urls:
                seen_urls.add(clean_url)
                name = d.get("name") or "Data Download"
                fmt = d.get("encodingFormat") or d.get("format") or "URL"
                distributions_list.append((str(name)[:255], str(fmt)[:100], clean_url))
                links_raw.append(clean_url)
        elif isinstance(d, str):
            clean_url = clean_and_parse_url(d)
            if clean_url and clean_url not in seen_urls:
                seen_urls.add(clean_url)
                distributions_list.append(("Data Download", "URL", clean_url))
                links_raw.append(clean_url)

    if data.get("contentUrl"):
        clean_url = clean_and_parse_url(data.get("contentUrl"))
        if clean_url and clean_url not in seen_urls:
            seen_urls.add(clean_url)
            distributions_list.append(("Direct File Link", "URL", clean_url))
            links_raw.append(clean_url)

    p.distributions = distributions_list
    p.links = links_raw

    # URL / Landing page
    target_url = clean_and_parse_url(data.get("url")) or clean_and_parse_url(uri)
    if target_url:
        p.url = target_url
    elif links_raw:
        p.url = links_raw[0]
    elif clean_and_parse_url(p.identifier):
        p.url = clean_and_parse_url(p.identifier)

    # Keywords / Subjects
    seen_subj: Set[str] = set()
    for raw_s in as_list(data.get("keywords")):
        s = str(raw_s).strip()
        if s and len(s) > 2 and s.lower() not in seen_subj:
            seen_subj.add(s.lower())
            p.subjects.append(s)

    # Authors / Persons
    seen_pers: Set[str] = set()
    for raw_p in as_list(data.get("author")) + as_list(data.get("creator")):
        if isinstance(raw_p, dict):
            name = str(raw_p.get("name") or "").strip()
        else:
            name = str(raw_p).strip()
        if name and len(name) > 1 and name.lower() not in seen_pers:
            seen_pers.add(name.lower())
            p.persons.append(name)

    # Organizations / Publishers
    seen_org: Set[str] = set()
    for raw_o in as_list(data.get("publisher")):
        if isinstance(raw_o, dict):
            org = str(raw_o.get("name") or "").strip()
        else:
            org = str(raw_o).strip()
        if org and len(org) > 1 and org.lower() not in seen_org:
            seen_org.add(org.lower())
            p.organizations.append(org)

    # Projects / Funding
    seen_proj: Set[str] = set()
    for raw_pr in as_list(data.get("funder")) + as_list(data.get("isPartOf")) + as_list(data.get("project_acronyms")):
        c_name = clean_project_name(raw_pr, grant_map)
        if c_name and c_name.lower() not in seen_proj:
            seen_proj.add(c_name.lower())
            p.project_acronyms.append(c_name)
    if project_col:
        c_col = clean_project_name(project_col, grant_map)
        if c_col and c_col.lower() not in seen_proj:
            seen_proj.add(c_col.lower())
            p.project_acronyms.append(c_col)

    return p


def parse_mcf_yaml(row, grant_map: Optional[Dict[str, str]] = None) -> Optional[ParsedRecord]:
    """
    Parse a harvest.items row whose resultobject is MCF YAML (EU CAP Network).
    """
    ident, id_type, uri, robj, rtype, doiobj, source, ins_date, item_type, \
        title_col, lang_col, date_col, project_col = row

    try:
        mcf: Dict = yaml.safe_load(robj) if robj else {}
    except Exception as e:
        logger.warning(f"[{source}] YAML parse error for {ident}: {e}")
        return None

    if not isinstance(mcf, dict) or "identification" not in mcf:
        logger.warning(f"[{source}] MCF YAML missing 'identification' for {ident}")
        return None

    p = ParsedRecord()
    p.raw = mcf

    mid   = mcf.get("identification", {})
    mmeta = mcf.get("metadata", {})

    p.identifier    = ident.strip()
    p.title         = (first_str(mid.get("title")) or title_col or "Untitled").strip()
    p.abstract      = first_str(mid.get("abstract"))
    p.resource_type = first_str(mmeta.get("hierarchylevel")) or item_type or "Project"
    p.language      = first_str(mmeta.get("language")) or lang_col or "en"
    lic = mid.get("license")
    if isinstance(lic, dict):
        p.license_text = lic.get("url") or lic.get("name")
    else:
        p.license_text = first_str(lic)
    p.harvest_date  = parse_date(ins_date) or datetime.now(timezone.utc)

    # Temporal extents
    temporal_list = mid.get("extents", {}).get("temporal", [{}])
    temporal = temporal_list[0] if temporal_list else {}
    p.temporal_start = parse_date(temporal.get("begin"))
    p.temporal_end   = parse_date(temporal.get("end"))
    p.pub_date       = p.temporal_start

    dates = mmeta.get("dates", {}) or {}
    p.creation_date = parse_date(dates.get("creation")) or p.pub_date
    p.updated_date  = parse_date(dates.get("revision"))

    spatial_list = mid.get("extents", {}).get("spatial", [])
    if spatial_list:
        p.spatial = str(spatial_list[0].get("bbox", ""))

    # URL / links from distribution
    web_url = mcf.get("distribution") or {}
    p.url = clean_and_parse_url(uri)
    seen_urls: Set[str] = set()
    for dkey, dval in (web_url or {}).items():
        if isinstance(dval, dict):
            candidate = dval.get("url")
            clean_url = clean_and_parse_url(candidate)
            if clean_url and clean_url not in seen_urls:
                seen_urls.add(clean_url)
                d_name = dval.get("name") or ("Official Website" if dkey == "www" else "Access Link")
                d_fmt = dval.get("format") or "HTML"
                p.distributions.append((str(d_name)[:255], str(d_fmt)[:100], clean_url))
                p.links.append(clean_url)
                if not p.url:
                    p.url = clean_url

    # Subjects from keywords
    seen_subj: Set[str] = set()
    for kw_block in (mid.get("keywords") or {}).values():
        for kw in as_list((kw_block or {}).get("keywords")):
            s = first_str(kw) or ""
            if s and len(s) > 2 and s.lower() not in seen_subj:
                seen_subj.add(s.lower())
                p.subjects.append(s)

    # Persons + Orgs from contacts
    contacts = mcf.get("contacts", {}) or {}
    seen_pers: Set[str] = set()
    seen_org: Set[str] = set()
    for c in contacts.values():
        name = (c.get("individualname") or c.get("name") or "").strip()
        if name and name.lower() not in seen_pers:
            seen_pers.add(name.lower())
            p.persons.append(name)
        org = (c.get("organization") or "").strip()
        if org and org.lower() not in seen_org:
            seen_org.add(org.lower())
            p.organizations.append(org)

    # Projects
    seen_proj: Set[str] = set()
    for ai in (mmeta.get("additional_identifiers") or []):
        if ai.get("scheme") == "acronym" and ai.get("identifier"):
            c_name = clean_project_name(ai["identifier"], grant_map)
            if c_name and c_name.lower() not in seen_proj:
                seen_proj.add(c_name.lower())
                p.project_acronyms.append(c_name)
    if project_col:
        c_col = clean_project_name(project_col, grant_map)
        if c_col and c_col.lower() not in seen_proj:
            seen_proj.add(c_col.lower())
            p.project_acronyms.append(c_col)

    return p


# ---------------------------------------------------------------------------
# Harmonizer class
# ---------------------------------------------------------------------------

class Harmonizer:
    def __init__(self, conn, dry_run: bool = False):
        self.conn    = conn
        self.cur     = conn.cursor()
        self.dry_run = dry_run

        # In-memory caches: entity_name.lower() -> UUID str
        self.sources_cache:  Dict[str, str] = {}   # source_key(canonical name) -> UUID
        self.source_names:   Set[str] = set()      # names as stored, for typo warnings
        self.records_cache:  Dict[str, str] = {}
        self.subjects_cache: Dict[str, str] = {}
        self.persons_cache:  Dict[str, str] = {}
        self.orgs_cache:     Dict[str, str] = {}
        self.projects_cache: Dict[str, str] = {}
        self.grant_to_acronym: Dict[str, str] = {}

    # --- Cache bootstrap ----------------------------------------------------

    def load_caches(self) -> None:
        logger.info("Loading existing entity caches from validate schema...")

        # Sources are keyed by their canonical name (common/sources.py), so
        # "Data.Europa.EU", "https://data.europa.eu/" and listed aliases such as
        # "data.erupa.eu" all resolve to the one data.europa.eu row. If the DB
        # already holds a variant row too, the row named canonically wins.
        self.cur.execute("SELECT name, id FROM validate.sources;")
        for name, sid in self.cur.fetchall():
            key = source_key(canonical_source(name))
            if key not in self.sources_cache or source_key(name) == key:
                self.sources_cache[key] = str(sid)
            self.source_names.add(name.strip())

        self.cur.execute("SELECT identifier, id FROM validate.records;")
        for ident, rid in self.cur.fetchall():
            self.records_cache[ident.strip()] = str(rid)

        self.cur.execute("SELECT label, id FROM validate.subjects WHERE label IS NOT NULL;")
        for label, sid in self.cur.fetchall():
            self.subjects_cache[label.strip().lower()] = str(sid)

        self.cur.execute("SELECT name, id FROM validate.persons WHERE name IS NOT NULL;")
        for name, pid in self.cur.fetchall():
            self.persons_cache[name.strip().lower()] = str(pid)

        self.cur.execute("SELECT name, id FROM validate.organizations WHERE name IS NOT NULL;")
        for name, oid in self.cur.fetchall():
            self.orgs_cache[name.strip().lower()] = str(oid)

        self.cur.execute("SELECT name, id FROM validate.projects WHERE name IS NOT NULL;")
        for name, pid in self.cur.fetchall():
            self.projects_cache[name.strip().lower()] = str(pid)

        # Preload grantnr -> acronym code from harvest.projects
        try:
            self.cur.execute("SELECT grantnr, code FROM harvest.projects WHERE grantnr IS NOT NULL AND code IS NOT NULL;")
            for gnr, code in self.cur.fetchall():
                if gnr and code:
                    self.grant_to_acronym[str(gnr).strip()] = str(code).strip()
            logger.info(f"  Loaded {len(self.grant_to_acronym)} grant-to-acronym project mappings from harvest.projects.")
        except Exception as e:
            logger.warning(f"Could not load grant-to-acronym mappings: {e}")

        logger.info(
            f"  Cached: {len(self.sources_cache)} sources | {len(self.records_cache)} records | "
            f"{len(self.subjects_cache)} subjects | {len(self.persons_cache)} persons | "
            f"{len(self.orgs_cache)} orgs | {len(self.projects_cache)} projects"
        )

    # --- Core batch processing ----------------------------------------------

    def harmonize_batch(self, rows: List[Tuple], source_name: str) -> Dict[str, int]:
        """Process one page of harvest.items rows and flush to DB."""

        new_sources:  Dict[str, Tuple[str, str]] = {}
        new_subjects: Dict[str, Tuple[str, str]] = {}
        new_persons:  Dict[str, Tuple[str, str]] = {}
        new_orgs:     Dict[str, Tuple[str, str]] = {}
        new_projects: Dict[str, Tuple[str, str]] = {}

        records_batch:        List[Tuple] = []
        distributions_batch:  List[Tuple] = []
        record_source_batch:  List[Tuple] = []
        record_subject_batch: List[Tuple] = []
        record_person_batch:  List[Tuple] = []
        record_org_batch:     List[Tuple] = []
        record_project_batch: List[Tuple] = []
        skipped = 0

        # Ensure source entity (one row per source, whatever the spelling: see common/sources.py)
        s_clean = canonical_source(source_name)
        s_key = source_key(s_clean)
        if s_clean != source_name.strip():
            logger.info(f"  Source '{source_name}' -> canonical '{s_clean}'")
        if s_key in self.sources_cache:
            source_id = self.sources_cache[s_key]
        else:
            look_alike = similar_sources(s_clean, self.source_names)
            if look_alike:
                logger.warning(
                    f"  New source '{s_clean}' looks like existing {look_alike}. If it is the same "
                    f"source, add it to common/source_aliases.json and rerun."
                )
            source_id = str(uuid.uuid4())
            self.sources_cache[s_key] = source_id
            self.source_names.add(s_clean)
            new_sources[s_key] = (source_id, s_clean)

        for row in rows:
            rtype = row[4]
            if rtype == "yaml":
                p = parse_mcf_yaml(row, self.grant_to_acronym)
            elif rtype == "schema.org":
                p = parse_schema_org(row, self.grant_to_acronym)
            else:
                p = parse_solr_json(row, self.grant_to_acronym)

            if p is None or not p.identifier:
                skipped += 1
                continue

            # Record UUID
            rec_uuid = self.records_cache.get(p.identifier) or str(uuid.uuid4())
            self.records_cache[p.identifier] = rec_uuid

            records_batch.append((
                rec_uuid, p.identifier, p.title, p.abstract,
                p.resource_type, p.license_text, p.language, p.thumbnail,
                p.pub_date, p.creation_date, p.updated_date,
                p.harvest_date, p.spatial, p.temporal_start, p.temporal_end,
                p.url, Json(p.raw), "pending",
            ))

            record_source_batch.append((str(uuid.uuid4()), rec_uuid, source_id))

            # Distributions (links)
            seen_links: Set[str] = set()
            for d_name, d_fmt, link_url in p.distributions:
                if link_url not in seen_links:
                    seen_links.add(link_url)
                    distributions_batch.append((
                        str(uuid.uuid4()), rec_uuid, d_name, d_fmt, link_url,
                    ))

            # Subjects
            for label in p.subjects:
                clabel = label.strip()
                if not clabel or len(clabel) <= 1:
                    continue
                k = clabel.lower()
                if k in self.subjects_cache:
                    sid = self.subjects_cache[k]
                else:
                    sid = str(uuid.uuid4())
                    self.subjects_cache[k] = sid
                    new_subjects[k] = (sid, clabel)
                record_subject_batch.append((str(uuid.uuid4()), rec_uuid, sid))

            # Persons
            for name in p.persons:
                cname = name.strip()
                if not cname or len(cname) <= 1:
                    continue
                k = cname.lower()
                if k in self.persons_cache:
                    pid = self.persons_cache[k]
                else:
                    pid = str(uuid.uuid4())
                    self.persons_cache[k] = pid
                    new_persons[k] = (pid, cname)
                record_person_batch.append((str(uuid.uuid4()), rec_uuid, pid))

            # Organizations
            for name in p.organizations:
                cname = name.strip()
                if not cname or len(cname) <= 1:
                    continue
                k = cname.lower()
                if k in self.orgs_cache:
                    oid = self.orgs_cache[k]
                else:
                    oid = str(uuid.uuid4())
                    self.orgs_cache[k] = oid
                    new_orgs[k] = (oid, cname)
                record_org_batch.append((str(uuid.uuid4()), rec_uuid, oid))

            # Projects
            for name in p.project_acronyms:
                cname = name.strip()
                if not cname:
                    continue
                k = cname.lower()
                if k in self.projects_cache:
                    prid = self.projects_cache[k]
                else:
                    prid = str(uuid.uuid4())
                    self.projects_cache[k] = prid
                    new_projects[k] = (prid, cname)
                record_project_batch.append((str(uuid.uuid4()), rec_uuid, prid))

        # ---- DB writes (in foreign key dependency order) ----
        counts: Dict[str, int] = {"skipped": skipped}

        # 1. Parent entities
        if new_sources:
            execute_values(self.cur, """
                INSERT INTO validate.sources (id, name) VALUES %s
                ON CONFLICT (name) DO NOTHING;
            """, list(new_sources.values()), page_size=500)
            counts["new_sources"] = len(new_sources)

        if new_subjects:
            execute_values(self.cur, """
                INSERT INTO validate.subjects (id, label) VALUES %s;
            """, list(new_subjects.values()), page_size=500)
            counts["new_subjects"] = len(new_subjects)

        if new_persons:
            execute_values(self.cur, """
                INSERT INTO validate.persons (id, name) VALUES %s;
            """, list(new_persons.values()), page_size=500)
            counts["new_persons"] = len(new_persons)

        if new_orgs:
            execute_values(self.cur, """
                INSERT INTO validate.organizations (id, name) VALUES %s;
            """, list(new_orgs.values()), page_size=500)
            counts["new_organizations"] = len(new_orgs)

        if new_projects:
            execute_values(self.cur, """
                INSERT INTO validate.projects (id, name) VALUES %s
                ON CONFLICT (name) DO NOTHING;
            """, list(new_projects.values()), page_size=500)
            counts["new_projects"] = len(new_projects)

        # 2. Main records table (deduplicate within batch to prevent CardinalityViolation)
        if records_batch:
            unique_records = list({r[1]: r for r in records_batch}.values())
            execute_values(self.cur, """
                INSERT INTO validate.records (
                    id, identifier, title, abstract, resource_type,
                    license, language, thumbnail,
                    publication_date, resource_creation_date, resource_updated_date,
                    harvest_date, spatial, temporal_start, temporal_end,
                    url, raw_metadata, approval_status
                ) VALUES %s
                ON CONFLICT (identifier) DO UPDATE SET
                    title                  = EXCLUDED.title,
                    abstract               = EXCLUDED.abstract,
                    resource_type          = EXCLUDED.resource_type,
                    license                = EXCLUDED.license,
                    language               = EXCLUDED.language,
                    thumbnail              = EXCLUDED.thumbnail,
                    publication_date       = EXCLUDED.publication_date,
                    resource_creation_date = EXCLUDED.resource_creation_date,
                    resource_updated_date  = EXCLUDED.resource_updated_date,
                    harvest_date           = EXCLUDED.harvest_date,
                    spatial                = EXCLUDED.spatial,
                    temporal_start         = EXCLUDED.temporal_start,
                    temporal_end           = EXCLUDED.temporal_end,
                    url                    = EXCLUDED.url,
                    raw_metadata           = EXCLUDED.raw_metadata,
                    updated_at             = NOW();
            """, unique_records, page_size=500)
            counts["records"] = len(unique_records)

        # 3. Junction tables & child entities
        if record_source_batch:
            uq = deduplicate_batch(record_source_batch, (1, 2))
            execute_values(self.cur, """
                INSERT INTO validate.record_source (id, record_id, source_id)
                VALUES %s ON CONFLICT (record_id, source_id) DO NOTHING;
            """, uq, page_size=500)
            counts["record_source"] = len(uq)

        if distributions_batch:
            uq = deduplicate_batch(distributions_batch, (1, 4))
            execute_values(self.cur, """
                INSERT INTO validate.distributions (id, record_id, name, format, access_url)
                VALUES %s;
            """, uq, page_size=500)
            counts["distributions"] = len(uq)

        if record_subject_batch:
            uq = deduplicate_batch(record_subject_batch, (1, 2))
            execute_values(self.cur, """
                INSERT INTO validate.record_subject (id, record_id, subject_id)
                VALUES %s ON CONFLICT (record_id, subject_id) DO NOTHING;
            """, uq, page_size=500)
            counts["record_subject"] = len(uq)

        if record_person_batch:
            uq = deduplicate_batch(record_person_batch, (1, 2))
            execute_values(self.cur, """
                INSERT INTO validate.record_person (id, record_id, person_id)
                VALUES %s ON CONFLICT (record_id, person_id) DO NOTHING;
            """, uq, page_size=500)
            counts["record_person"] = len(uq)

        if record_org_batch:
            uq = deduplicate_batch(record_org_batch, (1, 2))
            execute_values(self.cur, """
                INSERT INTO validate.record_organization (id, record_id, organization_id)
                VALUES %s ON CONFLICT (record_id, organization_id) DO NOTHING;
            """, uq, page_size=500)
            counts["record_organization"] = len(uq)

        if record_project_batch:
            uq = deduplicate_batch(record_project_batch, (1, 2))
            execute_values(self.cur, """
                INSERT INTO validate.record_project (id, record_id, project_id)
                VALUES %s ON CONFLICT (record_id, project_id) DO NOTHING;
            """, uq, page_size=500)
            counts["record_project"] = len(uq)

        return counts

    # --- Main run loop ------------------------------------------------------

    def run(
        self,
        source_filter: Optional[str] = None,
        limit: Optional[int] = None,
        batch_size: int = 500,
        missing_only: bool = False,
    ) -> None:
        self.load_caches()

        if source_filter:
            self.cur.execute(
                "SELECT DISTINCT source FROM harvest.items "
                "WHERE lower(source)=lower(%s) ORDER BY source;",
                (source_filter,),
            )
        else:
            self.cur.execute(
                "SELECT DISTINCT source FROM harvest.items ORDER BY source;"
            )
        sources = [r[0] for r in self.cur.fetchall()]
        logger.info(f"\nSources to process: {sources}\n")

        grand_totals: Dict[str, int] = {}

        for src in sources:
            logger.info(f"\n{'='*60}\n  Source: [{src}]\n{'='*60}")

            if missing_only:
                self.cur.execute("""
                    SELECT h.identifier
                    FROM harvest.items h
                    LEFT JOIN validate.records v ON h.identifier = v.identifier
                    WHERE v.id IS NULL AND h.source = %s
                    ORDER BY h.insert_date ASC, h.identifier ASC;
                """, (src,))
            else:
                self.cur.execute("""
                    SELECT identifier
                    FROM harvest.items
                    WHERE source = %s
                    ORDER BY insert_date ASC, identifier ASC;
                """, (src,))
            target_ids = [r[0] for r in self.cur.fetchall()]
            if limit:
                target_ids = target_ids[:limit]

            total_src = len(target_ids)
            logger.info(f"  Records to process: {total_src:,}")

            if total_src == 0:
                logger.info(f"  [{src}] Already up-to-date. 0 records to harmonize.")
                continue

            src_totals: Dict[str, int] = {}

            for offset in range(0, total_src, batch_size):
                chunk_ids = target_ids[offset : offset + batch_size]
                self.cur.execute("""
                    SELECT
                        identifier, identifiertype, uri, resultobject, resulttype,
                        doimetadata, source, insert_date, itemtype,
                        title, language, date, project
                    FROM harvest.items
                    WHERE identifier = ANY(%s);
                """, (chunk_ids,))
                rows = self.cur.fetchall()
                if not rows:
                    break

                batch_num = offset // batch_size + 1
                logger.info(
                    f"  Batch {batch_num}: rows {offset+1}–{offset+len(rows)}"
                )

                # Snapshot caches before batch to restore if batch fails
                cache_snapshot = (
                    dict(self.sources_cache),
                    dict(self.records_cache),
                    dict(self.subjects_cache),
                    dict(self.persons_cache),
                    dict(self.orgs_cache),
                    dict(self.projects_cache),
                )

                self.cur.execute("SAVEPOINT batch_sp;")
                try:
                    counts = self.harmonize_batch(rows, src)
                    if not self.dry_run:
                        self.cur.execute("RELEASE SAVEPOINT batch_sp;")
                        self.conn.commit()
                        logger.info(f"  Committed — {counts}")
                    else:
                        self.cur.execute("RELEASE SAVEPOINT batch_sp;")
                        logger.info(f"  [DRY-RUN] Validated batch — {counts}")
                except Exception as e:
                    logger.error(
                        f"  Batch error [{src}] offset={offset}: {e}", exc_info=True
                    )
                    self.cur.execute("ROLLBACK TO SAVEPOINT batch_sp;")
                    (
                        self.sources_cache,
                        self.records_cache,
                        self.subjects_cache,
                        self.persons_cache,
                        self.orgs_cache,
                        self.projects_cache,
                    ) = cache_snapshot
                    continue

                for k, v in counts.items():
                    src_totals[k] = src_totals.get(k, 0) + v

            logger.info(f"\n  [{src}] DONE — {src_totals}")
            for k, v in src_totals.items():
                grand_totals[k] = grand_totals.get(k, 0) + v

        # Summary
        print("\n" + "=" * 65)
        print("  HARMONIZATION SUMMARY")
        print("=" * 65)
        print(f"  Mode      : {'DRY-RUN (will rollback)' if self.dry_run else 'EXECUTED & committed'}")
        print(f"  Source    : {source_filter or 'ALL'}")
        for k, v in grand_totals.items():
            print(f"  {k:<28}: {v:>10,}")

        print("\n  --- validate schema counts (in-transaction) ---")
        with self.conn.cursor() as vc:
            for tbl in ("records", "sources", "subjects", "persons",
                        "organizations", "projects",
                        "record_source", "record_subject", "record_person",
                        "record_organization", "record_project", "distributions"):
                vc.execute(f"SELECT count(*) FROM validate.{tbl};")
                print(f"  validate.{tbl:<25}: {vc.fetchone()[0]:>10,}")

        if self.dry_run:
            self.conn.rollback()
            print("\n  [DRY-RUN] Rolled back entire transaction — database is untouched.")
        print("=" * 65)

    def populate_distributions(self, batch_size: int = 1000) -> None:
        """
        Fast dedicated sync: extracts and writes distributions for all records
        already in validate.records.
        """
        logger.info("\nPopulating validate.distributions from harvest.items...")

        with self.conn.cursor() as cur:
            cur.execute("SELECT identifier, id FROM validate.records;")
            rec_map = {r[0]: str(r[1]) for r in cur.fetchall()}
        logger.info(f"Loaded {len(rec_map):,} validate.records mappings.")

        logger.info("Truncating validate.distributions for clean sync...")
        with self.conn.cursor() as cur:
            cur.execute("TRUNCATE validate.distributions;")
        self.conn.commit()

        # Get list of sources to iterate cleanly source-by-source
        with self.conn.cursor() as cur:
            cur.execute("SELECT DISTINCT source FROM harvest.items WHERE source IS NOT NULL ORDER BY source;")
            sources = [r[0] for r in cur.fetchall()]

        total_dists = 0
        insert_cur = self.conn.cursor()

        for src in sources:
            logger.info(f"Processing distributions for source: {src}...")
            with self.conn.cursor() as read_cur:
                read_cur.execute("""
                    SELECT identifier, identifiertype, uri, resultobject, resulttype,
                           doimetadata, source, insert_date, itemtype,
                           title, language, date, project
                    FROM harvest.items
                    WHERE source = %s AND resultobject IS NOT NULL;
                """, (src,))

                batch: List[Tuple] = []
                while True:
                    rows = read_cur.fetchmany(batch_size)
                    if not rows:
                        break

                    for row in rows:
                        rtype = row[4]
                        if rtype == "yaml":
                            p = parse_mcf_yaml(row)
                        elif rtype == "schema.org":
                            p = parse_schema_org(row)
                        else:
                            p = parse_solr_json(row)
                        if not p or not p.identifier:
                            continue

                        rec_id = rec_map.get(p.identifier)
                        if not rec_id:
                            continue

                        seen: Set[str] = set()
                        for d_name, d_fmt, d_url in p.distributions:
                            if d_url not in seen:
                                seen.add(d_url)
                                batch.append((str(uuid.uuid4()), rec_id, d_name, d_fmt, d_url))

                    if len(batch) >= 2000:
                        execute_values(insert_cur, """
                            INSERT INTO validate.distributions (id, record_id, name, format, access_url)
                            VALUES %s;
                        """, batch, page_size=1000)
                        self.conn.commit()
                        total_dists += len(batch)
                        logger.info(f"  [{src}] Inserted {len(batch):,} distributions (total: {total_dists:,})...")
                        batch = []

                if batch:
                    execute_values(insert_cur, """
                        INSERT INTO validate.distributions (id, record_id, name, format, access_url)
                        VALUES %s;
                    """, batch, page_size=1000)
                    self.conn.commit()
                    total_dists += len(batch)
                    logger.info(f"  [{src}] Inserted remaining {len(batch):,} distributions (total: {total_dists:,})...")

        insert_cur.close()
        logger.info(f"\n✓ Finished populating distributions: {total_dists:,} rows committed.")

        with self.conn.cursor() as vc:
            vc.execute("SELECT count(*) FROM validate.distributions;")
            print(f"\n  Final validate.distributions count: {vc.fetchone()[0]:,}\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generalised harmonizer: harvest.items -> validate schema.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run",            action="store_true",
                        help="Validate without committing to DB")
    parser.add_argument("--source",             default=None,
                        help="Process only this source name (case-insensitive)")
    parser.add_argument("--limit",              type=int, default=None,
                        help="Max records per source (for testing)")
    parser.add_argument("--batch-size",         type=int, default=500,
                        help="Records per DB transaction (default 500)")
    parser.add_argument("--missing-only",       action="store_true",
                        help="Only process records not yet present in validate.records")
    parser.add_argument("--sync-distributions", action="store_true",
                        help="Fast dedicated sync of validate.distributions for all records")
    parser.add_argument("--host",               default=DEFAULT_HOST)
    parser.add_argument("--port",               type=int, default=DEFAULT_PORT)
    parser.add_argument("--dbname",             default=DEFAULT_DBNAME)
    parser.add_argument("--user",               default=DEFAULT_USER)
    parser.add_argument("--password",           default=DEFAULT_PASSWORD)
    args = parser.parse_args()

    print("=" * 65)
    print("  GENERALISED HARMONIZER: harvest.items -> validate schema")
    print(f"  Target DB  : {args.dbname} @ {args.host}:{args.port}")
    print(f"  Source     : {args.source or 'ALL'}")
    print(f"  Mode       : {'DRY-RUN (no writes)' if args.dry_run else 'EXECUTE (commit)'}")
    print(f"  Scope      : {'SYNC DISTRIBUTIONS ONLY' if args.sync_distributions else ('MISSING RECORDS ONLY' if args.missing_only else 'ALL RECORDS')}")
    print(f"  Batch size : {args.batch_size}")
    print("=" * 65 + "\n")

    try:
        conn = psycopg2.connect(
            host=args.host, port=args.port, dbname=args.dbname,
            user=args.user, password=args.password,
        )
        conn.autocommit = False
    except Exception as e:
        logger.error(f"DB connection failed: {e}")
        sys.exit(1)

    try:
        h = Harmonizer(conn, dry_run=args.dry_run)
        if args.sync_distributions:
            h.populate_distributions(batch_size=args.batch_size)
        else:
            h.run(
                source_filter=args.source,
                limit=args.limit,
                batch_size=args.batch_size,
                missing_only=args.missing_only,
            )
    except Exception as e:
        conn.rollback()
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
