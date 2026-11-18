"""
Source-name normalisation for validate.sources.

One source must have one row in validate.sources, however a harvester spelled it.
canonical_source() maps every spelling to one canonical name:

  1. normalise: lower case, trim, drop http(s)://, www. and a trailing '/',
     collapse inner whitespace ("Data.Europa.EU ", "https://data.europa.eu/" -> "data.europa.eu")
  2. look the result up in common/source_aliases.json (typos and other names
     -> canonical name, e.g. "data.erupa.eu" -> "data.europa.eu")
  3. otherwise keep the name as given (trimmed)

similar_sources() finds existing names that look like a new one (for a warning);
it never merges anything by itself, because short names such as "eea" / "fao"
would give false matches. Add real variants to source_aliases.json instead.
"""
from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List

ALIASES_FILE = Path(__file__).resolve().parent / "source_aliases.json"


def source_key(name: str) -> str:
    """Comparison key: case, spaces, scheme, www. and trailing slash ignored."""
    s = (name or "").strip().lower()
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s)   # http://, https://
    s = re.sub(r"^www\.", "", s)
    s = s.rstrip("/")
    s = re.sub(r"\s+", " ", s)
    return s


@lru_cache(maxsize=1)
def _alias_map() -> Dict[str, str]:
    """key of every variant (and of the canonical name itself) -> canonical name."""
    if not ALIASES_FILE.is_file():
        return {}
    data = json.loads(ALIASES_FILE.read_text(encoding="utf-8"))
    out: Dict[str, str] = {}
    for canonical, variants in data.items():
        if canonical.startswith("_"):
            continue
        out[source_key(canonical)] = canonical
        for v in variants or []:
            k = source_key(v)
            if k in out and out[k] != canonical:
                raise ValueError(f"{ALIASES_FILE.name}: '{v}' is listed under both "
                                 f"'{out[k]}' and '{canonical}'")
            out[k] = canonical
    return out


def canonical_source(name: str) -> str:
    """Canonical name for a harvested source name (see module docstring)."""
    return _alias_map().get(source_key(name), (name or "").strip())


def similar_sources(name: str, existing: Iterable[str], cutoff: float = 0.85) -> List[str]:
    """Existing source names that look like `name` (possible unlisted typo)."""
    k = source_key(name)
    keys = {source_key(e): e for e in existing}
    keys.pop(k, None)
    return [keys[m] for m in difflib.get_close_matches(k, list(keys), n=3, cutoff=cutoff)]
