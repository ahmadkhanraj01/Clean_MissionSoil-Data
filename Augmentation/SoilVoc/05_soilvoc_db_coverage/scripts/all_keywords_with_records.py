"""Every keyword in the DB with the number of records that use it, alphabetically.

Usage: python Augmentation/SoilVoc/05_soilvoc_db_coverage/scripts/all_keywords_with_records.py [--out FILE]

Read-only on stage. One row per distinct subject label:
  keyword            the label as harvested (never changed)
  records            distinct records that use it
  vocabulary_name    'noise' when the keyword was marked as noise in task 07, else empty
Sorted alphabetically, case-insensitive.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, next(str(p) for p in Path(__file__).resolve().parents if (p / "paths.py").exists()))
from paths import ENV, T05_OUT  # noqa: E402

import psycopg2  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

SQL = """
SELECT s.label,
       COUNT(DISTINCT rs.record_id) AS records,
       CASE WHEN COUNT(DISTINCT COALESCE(s.vocabulary_name, '')) = 1
            THEN MAX(COALESCE(s.vocabulary_name, ''))
            ELSE 'mixed' END AS vocabulary_name
FROM validate.subjects s
JOIN validate.record_subject rs ON rs.subject_id = s.id
GROUP BY s.label
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(T05_OUT / "all_keywords_with_records.csv"))
    args = ap.parse_args()

    e = dotenv_values(ENV)
    conn = psycopg2.connect(host=e["DB_HOST1"], port=e["DB_PORT1"], dbname=e["DB_NAME1"],
                            user=e["DB_USER1"], password=e["DB_PASSWORD1"], connect_timeout=15)
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        if cur.fetchone()[0] != "msp-kh-stage":
            raise SystemExit("not the stage DB")
        cur.execute(SQL)
        rows = cur.fetchall()
        cur.execute("SELECT count(DISTINCT record_id) FROM validate.record_subject")
        used = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM validate.records")
        total = cur.fetchone()[0]
    conn.close()

    rows.sort(key=lambda r: (r[0].strip().lower(), r[0]))
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["keyword", "records", "vocabulary_name"])
        w.writerows(rows)

    noise = sum(1 for r in rows if r[2] == "noise")
    print(f"written: {args.out} ({len(rows)} keywords)")
    print(f"records with at least one keyword: {used} of {total} ({used / total:.1%}); "
          f"noise keywords: {noise}")


if __name__ == "__main__":
    main()
