"""
solr_schema_mapper.py
--------------------------------------------------------------------------------
Crosswalk / mapper to convert raw SoilWise Solr documents into standardized
Schema.org (JSON-LD) objects without losing any field data.
--------------------------------------------------------------------------------
"""

import re
import html
import json
import urllib.parse
from typing import Dict, Any, Tuple, List, Optional, Set


# Shared with clean_stage_subjects.py; see common/text_cleaning.py
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from common.text_cleaning import VALID_2_CHAR_KEYWORDS, clean_keyword_text  # noqa: E402,F401


def clean_project_name(raw_val: Any) -> Optional[str]:
    """Decodes raw JSON strings and strips noise from project names."""
    if not raw_val:
        return None
    if isinstance(raw_val, dict):
        val = raw_val.get("acronym") or raw_val.get("code") or raw_val.get("title") or raw_val.get("grantnr") or ""
        return clean_project_name(val)
    s = str(raw_val).strip()
    if not s or s.lower() in ("-", "–", "none", "null", "n/a", "unknown"):
        return None
    if s.startswith("{") and s.endswith("}"):
        try:
            pdict = json.loads(s)
            val = pdict.get("acronym") or pdict.get("code") or pdict.get("title") or pdict.get("grantnr") or ""
            return clean_project_name(val)
        except Exception:
            return None
    if "{" in s or "}" in s or len(s) < 2:
        return None
    return s


def extract_source(doc: Dict[str, Any]) -> str:
    """Extract authoritative primary source from Solr document sources list."""
    sources = doc.get("sources")
    if sources:
        if isinstance(sources, list) and len(sources) > 0:
            return str(sources[0]).lower().strip()
        elif isinstance(sources, str) and sources.strip():
            return sources.lower().strip()
    return "unknown"


def extract_identifier_and_type(doc: Dict[str, Any]) -> Tuple[str, str]:
    raw_id = doc.get("identifier")
    if isinstance(raw_id, list):
        raw_id = raw_id[0] if raw_id else ""
    raw_id = str(raw_id or "").strip()

    clean_id = raw_id
    for prefix in ['https://doi.org/', 'http://doi.org/', 'https://dx.doi.org/', 'http://dx.doi.org/', 'doi:']:
        if clean_id.lower().startswith(prefix):
            clean_id = clean_id[len(prefix):].strip()

    if clean_id.startswith("10.") or "/10." in clean_id:
        return clean_id, "doi"
    elif raw_id.startswith("http://") or raw_id.startswith("https://"):
        return raw_id, "uri"
    elif raw_id:
        return raw_id, "id"
    else:
        doc_id = str(doc.get("id") or "")
        return doc_id, "id"


def extract_uri(doc: Dict[str, Any], identifier: str) -> str:
    links = doc.get("links")
    if links and isinstance(links, list):
        for lk in links:
            if isinstance(lk, dict) and lk.get("url"):
                u = str(lk["url"])
                if "%" in u:
                    try:
                        u = urllib.parse.unquote(u).strip()
                    except Exception:
                        pass
                if u.startswith("http"):
                    return u
            elif isinstance(lk, str):
                try:
                    parsed = json.loads(lk)
                    if isinstance(parsed, dict) and parsed.get("url"):
                        u = str(parsed["url"])
                        if "%" in u:
                            try:
                                u = urllib.parse.unquote(u).strip()
                            except Exception:
                                pass
                        if u.startswith("http"):
                            return u
                except Exception:
                    s = lk.strip()
                    if "%" in s:
                        try:
                            s = urllib.parse.unquote(s).strip()
                        except Exception:
                            pass
                    if s.startswith("http"):
                        return s

    if identifier and (identifier.startswith("10.") or "/" in identifier):
        return f"https://doi.org/{identifier}"
    return f"https://catalogue.soilwise-he.eu/search-api/solr/search?id={identifier}"


def solr_to_schema_org(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transforms a SoilWise Solr dictionary into a comprehensive Schema.org (JSON-LD) object.
    Preserves all descriptive fields, distributions, authors, subjects, and affiliations.
    """
    # 1. Resource Type mapping
    raw_type = doc.get("type")
    if isinstance(raw_type, list):
        raw_type = raw_type[0] if raw_type else "Dataset"
    raw_type_str = str(raw_type or "").lower().strip()

    if "pub" in raw_type_str or "art" in raw_type_str or "paper" in raw_type_str or "report" in raw_type_str:
        schema_type = "ScholarlyArticle"
    elif "soft" in raw_type_str or "code" in raw_type_str:
        schema_type = "SoftwareSourceCode"
    elif "proj" in raw_type_str:
        schema_type = "ResearchProject"
    elif "data" in raw_type_str or "dataset" in raw_type_str:
        schema_type = "Dataset"
    else:
        schema_type = "CreativeWork"

    # 2. Identifiers and URIs
    identifier, id_type = extract_identifier_and_type(doc)
    uri = extract_uri(doc, identifier)

    # 3. Title & Abstract
    title = doc.get("title")
    if isinstance(title, list):
        title = title[0] if title else ""
    title = str(title or "").strip()

    abstract = doc.get("abstract")
    if isinstance(abstract, list):
        abstract = abstract[0] if abstract else ""
    abstract = str(abstract or "").strip()

    # 4. Distributions / DataDownload Links
    distributions: List[Dict[str, str]] = []
    links = doc.get("links") or []
    if not isinstance(links, list):
        links = [links]

    seen_urls = set()
    for lk in links:
        link_dict = {}
        if isinstance(lk, dict):
            link_dict = lk
        elif isinstance(lk, str):
            s = lk.strip()
            if s.startswith("{") and s.endswith("}"):
                try:
                    link_dict = json.loads(s)
                except Exception:
                    link_dict = {"url": s}
            else:
                link_dict = {"url": s}

        raw_url = link_dict.get("url") or link_dict.get("href") or link_dict.get("link") or ""
        if "%" in raw_url:
            try:
                raw_url = urllib.parse.unquote(raw_url).strip()
            except Exception:
                pass
        raw_url = raw_url.strip()

        if raw_url and raw_url.startswith("http") and raw_url not in seen_urls:
            seen_urls.add(raw_url)
            name = link_dict.get("name") or "Access link"
            fmt = link_dict.get("format") or "URL"
            distributions.append({
                "@type": "DataDownload",
                "name": str(name)[:255],
                "encodingFormat": str(fmt)[:100],
                "contentUrl": raw_url
            })

    # 5. Keywords (Subjects & Matched Subjects)
    keywords: List[str] = []
    seen_kw = set()
    for kf in ("subjects", "matched_subjects"):
        raw_kws = doc.get(kf) or []
        if isinstance(raw_kws, str):
            raw_kws = [raw_kws]
        for k in raw_kws:
            for cleaned in clean_keyword_text(str(k)):
                if cleaned.lower() not in seen_kw:
                    seen_kw.add(cleaned.lower())
                    keywords.append(cleaned)

    # 6. Authors / Persons
    authors: List[Dict[str, str]] = []
    seen_auth = set()
    for af in ("persons", "view_authors", "authors_suggest", "contact_persons"):
        raw_auths = doc.get(af) or []
        if isinstance(raw_auths, str):
            raw_auths = [raw_auths]
        for a in raw_auths:
            a_str = str(a).strip()
            if a_str and len(a_str) > 1 and a_str.lower() not in seen_auth:
                seen_auth.add(a_str.lower())
                authors.append({"@type": "Person", "name": a_str})

    # 7. Organizations / Publishers
    publishers: List[Dict[str, str]] = []
    seen_org = set()
    for of in ("organizations", "contact_organizations"):
        raw_orgs = doc.get(of) or []
        if isinstance(raw_orgs, str):
            raw_orgs = [raw_orgs]
        for o in raw_orgs:
            o_str = str(o).strip()
            if o_str and len(o_str) > 1 and o_str.lower() not in seen_org:
                seen_org.add(o_str.lower())
                publishers.append({"@type": "Organization", "name": o_str})

    # 8. Projects / Funding
    projects: List[Dict[str, str]] = []
    seen_prj = set()
    for pf in ("project_acronyms", "projects", "project"):
        raw_prjs = doc.get(pf) or []
        if isinstance(raw_prjs, str):
            raw_prjs = [raw_prjs]
        for pr in raw_prjs:
            c_name = clean_project_name(pr)
            if c_name and c_name.lower() not in seen_prj:
                seen_prj.add(c_name.lower())
                projects.append({"@type": "ResearchProject", "name": c_name})

    # 9. Dates
    date_pub = doc.get("date_publication") or doc.get("date")
    if isinstance(date_pub, list):
        date_pub = date_pub[0] if date_pub else None
    date_created = doc.get("date_creation")
    if isinstance(date_created, list):
        date_created = date_created[0] if date_created else None
    if not date_created:
        date_created = date_pub
    date_modified = doc.get("date_revision")
    if isinstance(date_modified, list):
        date_modified = date_modified[0] if date_modified else None

    # 10. Spatial and Temporal Coverage
    spatial = doc.get("spatial")
    if isinstance(spatial, list):
        spatial = spatial[0] if spatial else None
    temp_start = doc.get("temporal_start")
    if isinstance(temp_start, list):
        temp_start = temp_start[0] if temp_start else None
    temp_end = doc.get("temporal_end")
    if isinstance(temp_end, list):
        temp_end = temp_end[0] if temp_end else None

    temporal_coverage = None
    if temp_start and temp_end:
        temporal_coverage = f"{temp_start}/{temp_end}"
    elif temp_start:
        temporal_coverage = str(temp_start)
    elif temp_end:
        temporal_coverage = str(temp_end)

    # 11. License, Language & Thumbnail
    license_str = doc.get("license")
    if isinstance(license_str, list):
        license_str = license_str[0] if license_str else None
    lang_str = doc.get("language")
    if isinstance(lang_str, list):
        lang_str = lang_str[0] if lang_str else None
    thumb = doc.get("thumbnail")
    if isinstance(thumb, list):
        thumb = thumb[0] if thumb else None
    if thumb and "%" in thumb:
        try:
            thumb = urllib.parse.unquote(thumb).strip()
        except Exception:
            pass

    schema = {
        "@context": "https://schema.org",
        "@type": schema_type,
        "identifier": identifier,
        "@id": uri or identifier,
        "name": title or "Untitled",
        "description": abstract or None,
        "url": uri or None,
        "inLanguage": lang_str or "en",
        "license": license_str or None,
        "thumbnailUrl": thumb or None,
        "datePublished": date_pub or None,
        "dateCreated": date_created or None,
        "dateModified": date_modified or None,
        "keywords": keywords or None,
        "distribution": distributions or None,
        "author": authors or None,
        "publisher": publishers or None,
        "funder": projects or None,
        "spatialCoverage": spatial or None,
        "temporalCoverage": temporal_coverage or None,
        "additionalType": raw_type or None,
    }

    return {k: v for k, v in schema.items() if v not in (None, [], "")}
