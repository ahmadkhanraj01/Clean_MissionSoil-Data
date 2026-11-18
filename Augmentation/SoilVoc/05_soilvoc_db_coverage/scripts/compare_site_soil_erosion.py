"""Compare the Knowledge Hub search for "soil erosion" (scraped CSVs) with stage. Read-only.

Usage: python Augmentation/SoilVoc/05_soilvoc_db_coverage/scripts/compare_site_soil_erosion.py [--out FILE]

Reads the two scrapes of https://msp-local.squarex.dk/knowledge-hub?q=soil+erosion, checks they hold the
same results, and matches them to validate.records by normalised title (the site shows no identifier).
Writes one row per record linked to the soil erosion branch (any status or link type):
  identifier, title, on_site         the record, and whether the site lists it
  direct_soil_erosion                linked to the `soil erosion` concept itself
  best_direct_link                   its link type and status on that concept
  branch_concepts                    all its concepts in the branch: name (link_type, status)
"""
import argparse
import collections
import csv
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, next(str(p) for p in Path(__file__).resolve().parents if (p / "paths.py").exists()))
from paths import ENV, T05, T05_OUT  # noqa: E402

import psycopg2  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

EROSION = "https://w3id.org/eusoilvoc#SoilErosion"
TITLE = "ecl-result-card__title-link"
SCRAPES = ["squarex website scraper.csv", "squarex-2026-11-05.csv"]
FIELDS = ["identifier", "title", "on_site", "direct_soil_erosion", "best_direct_link", "branch_concepts"]


def norm(s):
    return re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", s or "").lower()).strip()


def load(name):
    with open(T05 / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(T05_OUT / "soil_erosion_site_comparison.csv"))
    args = ap.parse_args()

    a, b = load(SCRAPES[0]), load(SCRAPES[1])
    shared = [c for c in a[0] if c in b[0]]
    diffs = sum(x[c] != y[c] for x, y in zip(a, b) for c in shared)
    print(f"scrapes: {len(a)} and {len(b)} rows; differences in the {len(shared)} shared columns: {diffs}")
    print(f"columns only in the first scrape: {[c for c in a[0] if c not in b[0]]}")

    e = dotenv_values(ENV)
    conn = psycopg2.connect(host=e["DB_HOST1"], port=e["DB_PORT1"], dbname=e["DB_NAME1"],
                            user=e["DB_USER1"], password=e["DB_PASSWORD1"], connect_timeout=15)
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        if cur.fetchone()[0] != "msp-kh-stage":
            raise SystemExit("not the stage DB")
        cur.execute("SELECT id::text, identifier, title FROM validate.records")
        records = {i: (ident, t) for i, ident, t in cur.fetchall()}
        cur.execute("""
            WITH RECURSIVE b AS (SELECT id, name FROM validate.soilvoc WHERE id = %s
                                 UNION ALL
                                 SELECT s.id, s.name FROM validate.soilvoc s JOIN b ON s.parent_id = b.id)
            SELECT rs.record_id::text, b.id, b.name, rs.link_type, rs.status
            FROM validate.record_soilvoc rs JOIN b ON b.id = rs.soilvoc_id""", (EROSION,))
        links = cur.fetchall()
    conn.close()

    branch = collections.defaultdict(list)
    for rid, sid, name, link_type, status in links:
        branch[rid].append((sid, name, link_type, status))
    direct = {rid for rid, ls in branch.items() if any(x[0] == EROSION for x in ls)}

    by_title = collections.defaultdict(list)
    for rid, (_, t) in records.items():
        by_title[norm(t)].append(rid)
    scraped = collections.Counter(norm(r[TITLE]) for r in a)

    shown, unresolved = set(), []
    for t, n in scraped.items():
        ids = by_title.get(t, [])
        in_branch = [i for i in ids if i in branch]
        if len(in_branch) == n:          # same number of cards as branch records with this title
            shown |= set(in_branch)
        else:
            unresolved.append((t, n, len(ids), len(in_branch)))
    print(f"site titles: {len(scraped)}, cards: {len(a)}; records resolved: {len(shown)}; unresolved titles: {unresolved}")

    rows = []
    for rid, ls in branch.items():
        d = [x for x in ls if x[0] == EROSION]
        rows.append({"identifier": records[rid][0], "title": " ".join(records[rid][1].split()),
                     "on_site": "yes" if rid in shown else "no",
                     "direct_soil_erosion": "yes" if d else "no",
                     "best_direct_link": f"{d[0][2]} ({d[0][3]})" if d else "",
                     "branch_concepts": "; ".join(sorted(f"{x[1]} ({x[2]}, {x[3]})" for x in ls))})
    rows.sort(key=lambda r: (r["on_site"], r["title"].lower(), r["identifier"]))
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"written: {args.out} ({len(rows)} rows)")
    print(f"branch records {len(branch)}, on site {len(shown)}, not on site {len(set(branch) - shown)}")
    print(f"linked to soil erosion itself: {len(direct)}; same set as the site: {direct == shown}; "
          f"direct not on site {len(direct - shown)}; on site not direct {len(shown - direct)}")
    print("direct links by type:", collections.Counter(
        (x[2], x[3]) for ls in branch.values() for x in ls if x[0] == EROSION).most_common())


if __name__ == "__main__":
    main()
