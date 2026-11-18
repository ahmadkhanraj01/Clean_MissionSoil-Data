"""
common/text_cleaning.py
--------------------------------------------------------------------------------
Keyword / subject cleaner shared by:
  - Harvesting/Solar_API/solr_schema_mapper.py              (at harvest time)
  - Augmentation/Cleanning-Scripts/clean_stage_subjects.py  (on validate.subjects)

Copied verbatim from solr_schema_mapper.py on branch `mahnoor`; the copy in
clean_stage_subjects.py had the same logic and whitelist.
--------------------------------------------------------------------------------
"""
import re
import html
from typing import List, Set


VALID_2_CHAR_KEYWORDS = {
    "ph", "3d", "ai", "ec", "uv", "ca", "fe", "cu", "zn", "cd",
    "pb", "mg", "mn", "se", "al", "ni", "cr", "as", "k+", "h+"
}


def clean_keyword_text(raw_text: str) -> List[str]:
    """
    Cleans a raw subject label into a list of valid, standardized keywords.
    Strips numeric classification codes, unbundles semicolons, removes HTML,
    and discards noise numbers/symbols.
    """
    if not raw_text:
        return []

    # 1. Unescape HTML and remove HTML tags (e.g. <i>, <sub>)
    text = html.unescape(raw_text)
    text = re.sub(r"<[^>]+>", "", text)

    # 2. Split on semicolons if multiple keywords are bundled
    parts = [p.strip() for p in text.split(";") if p.strip()]

    cleaned_keywords: List[str] = []
    seen: Set[str] = set()

    for p in parts:
        # Strip bracketed repository prefixes like [info.info-it] or [shs.eco]
        p = re.sub(r"^\[[^\]]+\]\s*", "", p).strip()

        # Strip leading classification numbers (e.g. "0101 mathematics", "01 natural sciences", "3103.12 foo")
        p = re.sub(r"^[\d]+([.][\d]+)*\s+", "", p).strip()

        # Strip leading/trailing punctuation and quotes
        p = p.strip(" .,;:-_\"'`~")

        # Strip balanced outer wrapping brackets e.g. "(foo)" -> "foo", "[bar]" -> "bar"
        while (p.startswith("(") and p.endswith(")")) or (p.startswith("[") and p.endswith("]")) or (p.startswith("{") and p.endswith("}")):
            p = p[1:-1].strip(" .,;:-_\"'`~")

        # Discard if single char or has no alphabetic characters
        if len(p) <= 1 or not any(c.isalpha() for c in p):
            continue

        # Discard pure numbers / dots / slashes (e.g. '01', '02', '310', '37.4.3', '2300')
        if re.match(r"^[\d\s\-_./,]+$", p):
            continue

        # Discard URL artifacts or date patterns
        if p.startswith("http://") or p.startswith("https://") or re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}$", p):
            continue

        # Discard meaningless 2-char tokens unless in whitelisted scientific abbreviations
        if len(p) == 2 and p.lower() not in VALID_2_CHAR_KEYWORDS:
            continue

        if p.lower() not in seen:
            seen.add(p.lower())
            cleaned_keywords.append(p)

    return cleaned_keywords
