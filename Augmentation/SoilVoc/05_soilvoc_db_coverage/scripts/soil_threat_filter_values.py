"""Soil-threat filter values with their record counts, for the PO to review. Read-only on stage.

Usage: python Augmentation/SoilVoc/05_soilvoc_db_coverage/scripts/soil_threat_filter_values.py [--out FILE]

One row per level 2 concept under `soil threats`, plus a row for records tagged only `soil threats`:
  soilvoc_id, name       the concept
  concepts_in_branch     concepts the value covers (stored tree, validate.soilvoc.parent_id)
  records                records on the branch: stored parent, accepted, no inside-keyword matches
  records_all_parents    same, following every SKOS parent (task 07 multi_parent_concepts.csv)
  records_with_inside    same as records, plus inside-keyword matches
  note                   why a value needs a decision
A record can have several threats, so the rows do not add up to the total.
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path
import sys
sys.path.insert(0, next(str(p) for p in Path(__file__).resolve().parents if (p / "paths.py").exists()))
from paths import ENV, T05_OUT, T07_OUT  # noqa: E402

import psycopg2  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

ROOT_ID = "https://w3id.org/eusoilvoc#SoilThreats"
FIELDS = ["soilvoc_id", "name", "concepts_in_branch", "records", "records_all_parents", "records_with_inside", "note"]


def branch(start, children):
    seen, stack = {start}, [start]
    while stack:
        for c in children[stack.pop()]:
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return seen


def union(ids, by_concept):
    out = set()
    for i in ids:
        out |= by_concept[i]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(T05_OUT / "soil_threat_filter_values.csv"))
    args = ap.parse_args()

    e = dotenv_values(ENV)
    conn = psycopg2.connect(host=e["DB_HOST1"], port=e["DB_PORT1"], dbname=e["DB_NAME1"],
                            user=e["DB_USER1"], password=e["DB_PASSWORD1"], connect_timeout=15)
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        if cur.fetchone()[0] != "msp-kh-stage":
            raise SystemExit("not the stage DB")
        cur.execute("SELECT id, name, parent_id FROM validate.soilvoc")
        concepts = cur.fetchall()
        cur.execute("SELECT record_id::text, soilvoc_id, link_type FROM validate.record_soilvoc "
                    "WHERE status = 'accepted'")
        links = cur.fetchall()
        cur.execute("SELECT count(*) FROM validate.records")
        n_records = cur.fetchone()[0]
    conn.close()

    names = {i: n for i, n, _ in concepts}
    tree, full = defaultdict(set), defaultdict(set)
    for i, _, p in concepts:
        if p:
            tree[p].add(i)
            full[p].add(i)
    with open(T07_OUT / "multi_parent_concepts.csv", newline="") as f:
        for r in csv.DictReader(f):
            for p in r["all_parents"].split(" | "):
                full[p.strip()].add(r["uri"])

    strict, accepted = defaultdict(set), defaultdict(set)
    for rid, sid, link_type in links:
        accepted[sid].add(rid)
        if link_type != "inside":
            strict[sid].add(rid)

    rows = []
    for t in tree[ROOT_ID]:
        b_tree, b_full = branch(t, tree), branch(t, full)
        n = len(union(b_tree, strict))
        n_full = len(union(b_full, strict))
        extra = sorted(names[x] for x in b_full - b_tree if strict[x])
        note = ""
        if not n:
            note = "no records, hide"
        elif n_full > n:
            note = "undercounted: all parents adds " + ", ".join(extra)
        rows.append({"soilvoc_id": t, "name": names[t], "concepts_in_branch": len(b_tree), "records": n,
                     "records_all_parents": n_full, "records_with_inside": len(union(b_tree, accepted)), "note": note})
    rows.sort(key=lambda r: (-r["records"], r["name"]))

    kids = tree[ROOT_ID]
    kids_tree = set().union(*(branch(t, tree) for t in kids))
    kids_full = set().union(*(branch(t, full) for t in kids))
    any_tree, any_full = union(kids_tree, strict), union(kids_full, strict)
    rows.append({"soilvoc_id": ROOT_ID, "name": "soil threats (general)", "concepts_in_branch": 1,
                 "records": len(strict[ROOT_ID] - any_tree), "records_all_parents": len(strict[ROOT_ID] - any_full),
                 "records_with_inside": len(accepted[ROOT_ID] - union(kids_tree, accepted)),
                 "note": "tagged only soil threats: no specific value returns these"})

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    any_root = any_tree | strict[ROOT_ID]
    print(f"written: {args.out} ({len(rows)} rows)")
    print(f"records with a specific value: {len(any_tree)} ({len(any_tree) / n_records:.1%} of {n_records}), "
          f"all parents {len(any_full)}")
    print(f"including soil threats itself: {len(any_root)} ({len(any_root) / n_records:.1%}), "
          f"all parents {len(any_full | strict[ROOT_ID])}")


if __name__ == "__main__":
    main()
