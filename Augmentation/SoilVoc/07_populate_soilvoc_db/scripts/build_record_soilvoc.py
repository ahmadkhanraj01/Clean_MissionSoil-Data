"""Build the record-level SoilVoc dry run: one row per (record, SoilVoc concept). Read-only.

Usage: python Augmentation/SoilVoc/07_populate_soilvoc_db/scripts/build_record_soilvoc.py [--links Augmentation/SoilVoc/07_populate_soilvoc_db/outputs/dry_run_links.csv]
                                              [--out Augmentation/SoilVoc/07_populate_soilvoc_db/outputs/dry_run_record_soilvoc.csv]

Reads the subject-level matches (dry_run_links.csv, from build_soilvoc_links.py) and, from stage
(read-only), the record <-> subject links and validate.soilvoc. Writes the rows that
load_record_soilvoc.py puts into validate.record_soilvoc:

  record_id    the record
  soilvoc_id   the SoilVoc concept (validate.soilvoc.id, the SoilVoc URI)
  link_type    how it matched; if several subjects of the record give the same concept,
               the strongest: exact > synonym > translation > mapped > variant > broader > inside
  status       accepted = reviewed match; pending = a person still has to accept it
  soilvoc_name, level   for reading the file only (not loaded)
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path

import psycopg2
from dotenv import dotenv_values

import sys
sys.path.insert(0, next(str(p) for p in Path(__file__).resolve().parents if (p / "paths.py").exists()))
from paths import *  # noqa: E402,F401  (ROOT, CURATION, T0x_OUT, ...)
LINK_ORDER = ["exact", "synonym", "translation", "mapped", "variant", "broader", "inside"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--links", default=str(T07_OUT / "dry_run_links.csv"))
    ap.add_argument("--out", default=str(T07_OUT / "dry_run_record_soilvoc.csv"))
    args = ap.parse_args()

    links_by_subject = defaultdict(list)
    with open(args.links, newline="") as f:
        for l in csv.DictReader(f):
            links_by_subject[l["subject_id"]].append(
                (l["soilvoc_uri"], l["link_type"], l["reviewed"].strip().lower() == "true"))

    e = dotenv_values(ROOT / ".env")
    g = lambda k: e[k + "1"]  # stage only
    conn = psycopg2.connect(host=g("DB_HOST"), port=g("DB_PORT"), dbname=g("DB_NAME"),
                            user=g("DB_USER"), password=g("DB_PASSWORD"), connect_timeout=15)
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute("SELECT record_id::text, subject_id::text FROM validate.record_subject")
        rec_subjects = cur.fetchall()
        cur.execute("SELECT id, name, level FROM validate.soilvoc")
        soilvoc = {i: (n, l) for i, n, l in cur.fetchall()}
    conn.close()
    if not soilvoc:
        raise SystemExit("validate.soilvoc is empty: run load_soilvoc.py first")

    # (record, concept) -> [best link type, accepted?]
    pairs = {}
    for rid, sid in rec_subjects:
        for uri, lt, reviewed in links_by_subject.get(sid, ()):
            key = (rid, uri)
            cur_best = pairs.get(key)
            if cur_best is None:
                pairs[key] = [lt, reviewed]
                continue
            # accepted beats pending; then the stronger link type wins
            if (reviewed, -LINK_ORDER.index(lt)) > (cur_best[1], -LINK_ORDER.index(cur_best[0])):
                pairs[key] = [lt, reviewed]

    missing = {uri for _, uri in pairs if uri not in soilvoc}
    if missing:
        raise SystemExit(f"{len(missing)} concepts not in validate.soilvoc, e.g. {sorted(missing)[:3]}")

    rows = [{"record_id": rid, "soilvoc_id": uri, "link_type": lt,
             "status": "accepted" if ok else "pending",
             "soilvoc_name": soilvoc[uri][0], "level": soilvoc[uri][1] or ""}
            for (rid, uri), (lt, ok) in pairs.items()]
    rows.sort(key=lambda r: (r["record_id"], r["status"], LINK_ORDER.index(r["link_type"]), r["soilvoc_id"]))

    out = Path(args.out)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    acc = [r for r in rows if r["status"] == "accepted"]
    direct = [r for r in acc if r["link_type"] != "inside"]
    print(f"dry run written: {out.relative_to(ROOT)} ({len(rows)} rows)")
    print(f"  accepted rows {len(acc)}, pending rows {len(rows) - len(acc)}")
    print(f"  records with an accepted concept  : {len({r['record_id'] for r in acc})}")
    print(f"  records with a direct concept     : {len({r['record_id'] for r in direct})}")
    print(f"  records with a pending concept    : {len({r['record_id'] for r in rows if r['status'] == 'pending'})}")
    print(f"  concepts accepted                 : {len({r['soilvoc_id'] for r in acc})} "
          f"(direct only: {len({r['soilvoc_id'] for r in direct})})")


if __name__ == "__main__":
    main()
