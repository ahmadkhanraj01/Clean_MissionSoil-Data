"""Records linked to a SoilVoc concept under `soil threats`, with concept and record details.

Usage: python Augmentation/SoilVoc/05_soilvoc_db_coverage/scripts/soil_threat_records.py [--out FILE]

Read-only on stage. One row per (record, concept) link in the soil-threats branch:
  soil_threat_value        level 2 concept under soil threats (the filter value); "soil threats"
                           on rows for the top concept itself (the record may also have other threats)
  soilvoc_id, name, level  the matched concept
  parent_id, parent_name   its stored parent (soilvoc.parent_id, one parent only)
  link_type, status        how it matched, accepted or pending
  record_id, identifier, title, abstract  the record (line breaks in title and abstract become spaces,
                           so every row is one line)
A record can match several concepts, so it appears once per concept.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, next(str(p) for p in Path(__file__).resolve().parents if (p / "paths.py").exists()))
from paths import ENV, T05_OUT  # noqa: E402

import psycopg2  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

ROOT_ID = "https://w3id.org/eusoilvoc#SoilThreats"
FIELDS = ["soil_threat_value", "soilvoc_id", "name", "level", "parent_id", "parent_name",
          "link_type", "status", "record_id", "identifier", "title", "abstract"]

SQL = """
WITH RECURSIVE tree AS (
    SELECT id, name, level, parent_id, id AS value_id, name AS value_name, 0 AS depth
    FROM validate.soilvoc
    WHERE id = %(root)s
  UNION ALL
    SELECT s.id, s.name, s.level, s.parent_id,
           CASE WHEN t.depth = 0 THEN s.id     ELSE t.value_id   END,
           CASE WHEN t.depth = 0 THEN s.name   ELSE t.value_name END,
           t.depth + 1
    FROM validate.soilvoc s
    JOIN tree t ON s.parent_id = t.id
)
SELECT t.value_name, t.id, t.name, t.level, t.parent_id, p.name,
       rs.link_type, rs.status, rs.record_id::text,
       r.identifier, r.title, r.abstract
FROM tree t
JOIN validate.record_soilvoc rs ON rs.soilvoc_id = t.id
JOIN validate.records           r  ON r.id = rs.record_id
LEFT JOIN validate.soilvoc      p  ON p.id = t.parent_id
ORDER BY t.value_name, t.level, r.identifier
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(T05_OUT / "soil_threat_records.csv"))
    args = ap.parse_args()

    e = dotenv_values(ENV)
    conn = psycopg2.connect(host=e["DB_HOST1"], port=e["DB_PORT1"], dbname=e["DB_NAME1"],
                            user=e["DB_USER1"], password=e["DB_PASSWORD1"], connect_timeout=15)
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        if cur.fetchone()[0] != "msp-kh-stage":
            raise SystemExit("not the stage DB")
        cur.execute(SQL, {"root": ROOT_ID})
        rows = cur.fetchall()
        cur.execute("SELECT count(*) FROM validate.records")
        n_records = cur.fetchone()[0]
    conn.close()

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for r in rows:
            w.writerow(r[:10] + tuple(" ".join((v or "").split()) for v in r[10:]))

    records = {r[8] for r in rows}
    accepted = {r[8] for r in rows if r[7] == "accepted" and r[6] != "inside"}
    print(f"written: {args.out} ({len(rows)} rows)")
    print(f"distinct records: {len(records)} of {n_records} ({len(records) / n_records:.1%}); "
          f"accepted without inside matches: {len(accepted)} ({len(accepted) / n_records:.1%})")
    for status in ("accepted", "pending"):
        print(f"  {status}: {sum(1 for r in rows if r[7] == status)} rows, "
              f"{len({r[8] for r in rows if r[7] == status})} records")
    print(f"  linked to the top concept 'soil threats' (may also have other threats): "
          f"{len({r[8] for r in rows if r[0] == 'soil threats'})} records")


if __name__ == "__main__":
    main()
