"""Load record_soilvoc and the noise marks into stage (schema validate).

Usage: python Augmentation/SoilVoc/07_populate_soilvoc_db/scripts/load_record_soilvoc.py [--db 1]
                                             [--records Augmentation/SoilVoc/07_populate_soilvoc_db/outputs/dry_run_record_soilvoc.csv]
                                             [--noise Augmentation/SoilVoc/07_populate_soilvoc_db/outputs/noise_subjects.csv]

SoilVoc is linked to records: validate.record_soilvoc (record_id, soilvoc_id, link_type, status,
run_id, classified_at), with foreign keys to validate.records and validate.soilvoc.
Stage only (msp-kh-stage); dev is never written.

One transaction (rolled back on any error):
  1. refuses to run if the DB is not msp-kh-stage
  2. checks every soilvoc_id is in validate.soilvoc and every record is in validate.records
  3. backs up subjects (id, label, vocabulary_name) -> validate.subjects_pre_soilvoc_backup_<ts>
  4. replaces all rows of record_soilvoc (run_id = this run)
  5. subjects.vocabulary_name: 'noise' for the noise list, nothing else is marked
     (never touches subjects.label or subjects.uri)
"""
import argparse
import csv
from datetime import datetime
from pathlib import Path

import psycopg2
from dotenv import dotenv_values
from psycopg2.extras import execute_values

import sys
sys.path.insert(0, next(str(p) for p in Path(__file__).resolve().parents if (p / "paths.py").exists()))
from paths import *  # noqa: E402,F401  (ROOT, CURATION, T0x_OUT, ...)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", choices=("1",), default="1",
                    help="1=stage (msp-kh-stage, schema validate). Dev is never written.")
    ap.add_argument("--records", default=str(T07_OUT / "dry_run_record_soilvoc.csv"))
    ap.add_argument("--noise", default=str(T07_OUT / "noise_subjects.csv"))
    args = ap.parse_args()

    with open(args.records, newline="") as f:
        rows = list(csv.DictReader(f))
    with open(args.noise, newline="") as f:
        noise_ids = [n["subject_id"] for n in csv.DictReader(f)]

    e = dotenv_values(ROOT / ".env")
    g = lambda k: e[k + args.db]
    conn = psycopg2.connect(host=g("DB_HOST"), port=g("DB_PORT"), dbname=g("DB_NAME"),
                            user=g("DB_USER"), password=g("DB_PASSWORD"), connect_timeout=15)
    conn.autocommit = False
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = ts.replace("_", "-")
    rep = {}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            if cur.fetchone()[0] != "msp-kh-stage":
                raise RuntimeError("not the stage DB: refusing to write")
            cur.execute("SELECT id FROM validate.soilvoc")
            ids = {i for (i,) in cur.fetchall()}
            if not ids:
                raise RuntimeError("validate.soilvoc is empty: run load_soilvoc.py first")
            unknown = {r["soilvoc_id"] for r in rows} - ids
            if unknown:
                raise RuntimeError(f"{len(unknown)} soilvoc_id not in validate.soilvoc, e.g. {sorted(unknown)[:3]}")
            cur.execute("SELECT id::text FROM validate.records")
            records = {r for (r,) in cur.fetchall()}
            missing = {r["record_id"] for r in rows} - records
            if missing:
                raise RuntimeError(f"{len(missing)} records not in validate.records, e.g. {sorted(missing)[:3]}")

            btable = f"validate.subjects_pre_soilvoc_backup_{ts}"
            cur.execute(f"CREATE TABLE {btable} AS SELECT id, label, vocabulary_name FROM validate.subjects")

            cur.execute("DELETE FROM validate.record_soilvoc")
            execute_values(cur, """
                INSERT INTO validate.record_soilvoc (record_id, soilvoc_id, link_type, status, run_id)
                VALUES %s""",
                [(r["record_id"], r["soilvoc_id"], r["link_type"], r["status"], run_id) for r in rows],
                template="(%s::uuid, %s, %s, %s, %s)", page_size=1000)

            cur.execute("UPDATE validate.subjects SET vocabulary_name = NULL "
                        "WHERE vocabulary_name IN ('SoilVoc', 'noise')")
            cur.execute("UPDATE validate.subjects SET vocabulary_name = 'noise' "
                        "WHERE id = ANY(%s::uuid[])", (noise_ids,))

            cur.execute("""SELECT COUNT(*),
                                  COUNT(*) FILTER (WHERE status = 'pending'),
                                  COUNT(DISTINCT record_id) FILTER (WHERE status = 'accepted'),
                                  COUNT(DISTINCT record_id) FILTER (WHERE status = 'accepted'
                                                                   AND link_type <> 'inside'),
                                  COUNT(DISTINCT soilvoc_id) FILTER (WHERE status = 'accepted')
                           FROM validate.record_soilvoc""")
            (rep["rows"], rep["pending"], rep["records"], rep["direct"], rep["concepts"]) = cur.fetchone()
            cur.execute("SELECT vocabulary_name, COUNT(*) FROM validate.subjects "
                        "WHERE vocabulary_name IS NOT NULL GROUP BY 1")
            rep["vocab"] = dict(cur.fetchall())
            cur.execute("SELECT COUNT(*) FROM validate.record_subject rs JOIN validate.subjects s "
                        "ON s.id = rs.subject_id WHERE s.vocabulary_name = 'noise'")
            rep["noise_uses"] = cur.fetchone()[0]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"LOADED into msp-kh-stage.validate.record_soilvoc (run {run_id})")
    print(f"  {rep['rows']} rows ({rep['pending']} pending): {rep['records']} records with an accepted "
          f"concept, {rep['direct']} with a direct one, {rep['concepts']} concepts")
    print(f"  subjects.vocabulary_name: {rep['vocab']} (noise used {rep['noise_uses']} times)")
    print(f"  backup: {btable}")


if __name__ == "__main__":
    main()
