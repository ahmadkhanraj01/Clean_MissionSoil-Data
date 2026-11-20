#!/usr/bin/env python3
"""
resolve_types_from_doi_registries.py  (pipeline step 42, runs between steps 17 and 18)
--------------------------------------------------------------------------------
Script version of notebook 05 (notebooks/05_doi_registry_type_resolution.ipynb).

For every row of data/msp_type_mismatches.csv (msp_type != ogc_type) it extracts the DOI,
asks Crossref and then DataCite which type the DOI is registered as, maps that to a common
class, and picks the side that agrees with the registry:
    msp / ogc   one side matches the registry (both match -> msp)
    neither     the registry answered, but neither side matches
    unresolved  no DOI, or no registry answer
Output: data/msp_type_mismatches_with_correct_type.csv (read by steps 18 and 19).

No database access. Calls are cached in data/registry_cache.json, so reruns are cheap.
Writes only local files, so the "dry run" is the real run.

    python Augmentation/Resource_Types/resolve_types_from_doi_registries.py
    python ... --email you@example.org --limit 50
--------------------------------------------------------------------------------
"""
# --- Clean_MissionSoil-Data bootstrap ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR  # noqa: E402
# ----------------------------------------

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote

import pandas as pd
import requests

DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>?#]+)", re.I)

CROSSREF = {
    "journal-article": "article", "proceedings-article": "conference",
    "book-chapter": "chapter", "book": "book", "monograph": "book",
    "edited-book": "book", "reference-book": "book", "dataset": "dataset",
    "report": "report", "report-component": "report", "dissertation": "thesis",
    "posted-content": "preprint", "other": "other", "peer-review": "other",
    "proceedings": "conference", "component": "other",
}
DATACITE = {
    "journalarticle": "article", "conferencepaper": "conference",
    "conferenceproceeding": "conference", "bookchapter": "chapter",
    "book": "book", "dataset": "dataset", "report": "report",
    "dissertation": "thesis", "preprint": "preprint", "software": "software",
    "text": "text", "audiovisual": "audiovisual", "image": "image",
    "model": "model", "collection": "collection", "event": "event",
    "interactiveresource": "interactive", "computationalnotebook": "notebook",
    "presentation": "presentation", "service": "service", "other": "other",
    "workflow": "software", "physicalobject": "other", "sound": "audiovisual",
}
LABEL = {
    "journal article": "article", "dataset": "dataset", "report": "report",
    "conference proceeding": "conference", "conference object": "conference",
    "book chapter": "chapter", "part of book or chapter of book": "chapter",
    "book": "book", "dissertation": "thesis", "preprint": "preprint",
    "software": "software", "text": "text", "audiovisual": "audiovisual",
    "image": "image", "model": "model", "collection": "collection",
    "event": "event", "interactive resource": "interactive",
    "computational notebook": "notebook", "presentation": "presentation",
    "service": "service", "other": "other", "data paper": "article",
}


def extract_doi(identifier):
    s = unquote(str(identifier))
    if s.startswith("oai:") or "youtu" in s or "vimeo" in s:
        return None
    m = DOI_RE.search(s)
    return m.group(1).rstrip(".,;)").lower() if m else None


def lookup(doi, session, email):
    """Crossref first, then DataCite. Returns (raw_type, class, source); source 'none' = not found."""
    hdr = {"User-Agent": "msp-type-check/1.0" + (f" (mailto:{email})" if email else "")}
    params = {"mailto": email} if email else {}
    for attempt in range(3):
        try:
            r = session.get(f"https://api.crossref.org/works/{doi}", params=params, headers=hdr, timeout=15)
            if r.status_code == 200:
                t = r.json().get("message", {}).get("type", "")
                return t, CROSSREF.get(t, "other"), "crossref"
            if r.status_code in (429, 503, 504):
                time.sleep(1 + attempt * 2)
                continue
            if r.status_code == 404:
                break
        except requests.RequestException:
            time.sleep(1)
    for attempt in range(3):
        try:
            r = session.get(f"https://api.datacite.org/dois/{doi}", headers=hdr, timeout=15)
            if r.status_code == 200:
                ty = r.json().get("data", {}).get("attributes", {}).get("types", {})
                t = ty.get("resourceTypeGeneral") or ty.get("citeproc") or ""
                return t, DATACITE.get(str(t).lower(), "other"), "datacite"
            if r.status_code in (429, 503, 504):
                time.sleep(1 + attempt * 2)
                continue
            if r.status_code == 404:
                break
        except requests.RequestException:
            time.sleep(1)
    return None, None, "none"


def decide(row):
    reg = row["registry_class"]
    if not isinstance(reg, str) or not row["doi"]:
        return pd.Series({"correct_type": "", "correct_side": "unresolved"})
    msp_ok = LABEL.get(str(row["msp_type"]).strip().lower()) == reg
    ogc_ok = LABEL.get(str(row["ogc_type"]).strip().lower()) == reg
    if ogc_ok and not msp_ok:
        return pd.Series({"correct_type": row["ogc_type"], "correct_side": "ogc"})
    if msp_ok:  # only msp, or both
        return pd.Series({"correct_type": row["msp_type"], "correct_side": "msp"})
    return pd.Series({"correct_type": "", "correct_side": "neither"})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--infile", default=str(DATA_DIR / "msp_type_mismatches.csv"))
    ap.add_argument("--outfile", default=str(DATA_DIR / "msp_type_mismatches_with_correct_type.csv"))
    ap.add_argument("--cache", default=str(DATA_DIR / "registry_cache.json"))
    ap.add_argument("--email", default=os.environ.get("CROSSREF_EMAIL", ""),
                    help="contact address for the Crossref polite pool (or set CROSSREF_EMAIL)")
    ap.add_argument("--workers", type=int, default=4, help="parallel lookups (be polite)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N rows")
    a = ap.parse_args()

    if not os.path.exists(a.infile):
        raise SystemExit(f"Input not found: {a.infile} (run steps 15-17 first)")
    df = pd.read_csv(a.infile, skipinitialspace=True)
    df.columns = df.columns.str.strip()
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()
    if a.limit:
        df = df.head(a.limit).copy()
    df["doi"] = df["identifier"].map(extract_doi)

    cache = json.load(open(a.cache)) if os.path.exists(a.cache) else {}
    todo = sorted(d for d in df["doi"].dropna().unique() if d not in cache or (cache.get(d) and cache[d][2] == "none"))
    print(f"{len(df)} rows | {df['doi'].notna().sum()} with DOI | {len(todo)} lookups to do ({len(cache)} cached)")

    sess = requests.Session()

    def work(d):
        time.sleep(0.1)
        return d, lookup(d, sess, a.email)

    if todo:
        try:
            with ThreadPoolExecutor(a.workers) as ex:
                it = ex.map(work, todo)
                try:  # progress bar if tqdm is installed
                    from tqdm import tqdm
                    it = tqdm(it, total=len(todo), desc="DOI lookups", unit="doi")
                except ImportError:
                    pass
                for i, (d, res) in enumerate(it, 1):
                    cache[d] = list(res)
                    if i % 200 == 0:
                        json.dump(cache, open(a.cache, "w"), indent=2)
        finally:
            json.dump(cache, open(a.cache, "w"), indent=2)

    df["registry_type"] = df["doi"].map(lambda d: (cache.get(d) or [None])[0] if d else None)
    df["registry_class"] = df["doi"].map(lambda d: (cache.get(d) or [None, None])[1] if d else None)
    df["registry_src"] = df["doi"].map(lambda d: (cache.get(d) or [None, None, "none"])[2] if d else "none")
    dec = df.apply(decide, axis=1)
    df["correct_type"], df["correct_side"] = dec["correct_type"], dec["correct_side"]

    df.drop(columns=["doi", "registry_class"]).to_csv(a.outfile, index=False)
    print("Saved", a.outfile)
    print(df["correct_side"].value_counts().to_string())


if __name__ == "__main__":
    main()
