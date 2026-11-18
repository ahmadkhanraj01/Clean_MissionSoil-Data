# Soil-threat filter values and record coverage

Stage DB `msp-kh-stage`, schema `validate`, load run `20261103-160240`. Counted on 5 November 2026. Read-only; dev not touched.

## Output

**11 filter values, 10 with records. They cover 808 of 33,566 records (2.4%).** With the 75 records tagged only `soil threats`, the total is 883 (2.6%). That is 14.9% of the 5,914 records with a direct SoilVoc match.

Counts are accepted matches without inside-keyword matches, including narrower concepts.

### Records per filter value

A record can have several threats, so the rows add up to more than the total.

```text
soil pollution           | 392 ########################################
soil degradation         | 234 ########################
soil erosion             | 227 #######################
soil compaction          | 115 ############
soil sealing             |  80 ########
soil biodiversity loss   |  36 ####
soil acidification       |  31 ###
soil organic carbon loss |  20 ##
soil nutrient loss       |  15 ##
waterlogging             |  14 #
soil deficiencies        |   0 
-------------------------+
soil threats (general)   |  75 ########
```

### Coverage

```text
all records                         33566  100.0%  |##################################################|
with a direct SoilVoc match          5914   17.6%  |#########                                         |
with any soil threat                  883    2.6%  |#                                                 |
with a specific filter value          808    2.4%  |#                                                 |
```

### The filter values in SoilVoc

```text
soil threats  (level 1, 883 records in total)
|-- soil pollution           392 records, 22 concepts
|-- soil degradation         234 records,  7 concepts
|-- soil erosion             227 records, 20 concepts
|-- soil compaction          115 records,  1 concept
|-- soil sealing              80 records,  3 concepts
|-- soil biodiversity loss    36 records,  1 concept
|-- soil acidification        31 records,  1 concept
|-- soil organic carbon loss  20 records,  1 concept
|-- soil nutrient loss        15 records,  3 concepts
|-- waterlogging              14 records,  1 concept
`-- soil deficiencies          0 records,  2 concepts
```

### All values

CSV: [`../outputs/soil_threat_filter_values.csv`](../outputs/soil_threat_filter_values.csv)

| Filter value | Concepts | Records | All parents | With inside-keyword matches | Note |
|---|---:|---:|---:|---:|---|
| soil pollution | 22 | 392 | 392 | 407 |  |
| soil degradation | 7 | 234 | 345 | 234 | undercounted: all parents adds soil compaction, soil salinization, soil sealing |
| soil erosion | 20 | 227 | 227 | 236 |  |
| soil compaction | 1 | 115 | 115 | 115 |  |
| soil sealing | 3 | 80 | 80 | 80 |  |
| soil biodiversity loss | 1 | 36 | 36 | 36 |  |
| soil acidification | 1 | 31 | 31 | 31 |  |
| soil organic carbon loss | 1 | 20 | 20 | 20 |  |
| soil nutrient loss | 3 | 15 | 15 | 15 |  |
| waterlogging | 1 | 14 | 14 | 14 |  |
| soil deficiencies | 2 | 0 | 0 | 0 | no records, hide |
| soil threats (general) | 1 | 75 | 75 | 78 | tagged only soil threats: no specific value returns these |

- **Records:** uses the one parent stored in `soilvoc.parent_id`.
- **All parents:** follows every parent in SoilVoc. Only soil degradation changes. Across all values, 808 becomes 814 and 883 becomes 889.
- **With inside-keyword matches:** also counts terms found inside longer keywords. The 883 total becomes 908.

### Gaps

```text
soil degradation, stored parent ............ 234 records
                                              |
    + soil compaction    (115 records)  -.    |  stored directly under soil threats
    + soil sealing       ( 80 records)  -+->  |  stored directly under soil threats
    + soil salinization  ( 69 records)  -'    |  stored under soil chemical processes
                                              v
soil degradation, all parents .............. 345 records (overlaps removed)
```

- **General records:** 75 records are tagged only `soil threats`, so no specific value returns them.
- **Soil degradation:** shows 234 records, or 345 following all parents, because `parent_id` holds one parent.
- **Salinisation:** SoilVoc has `soil salinisation` (9 records) and `soil salinization` (69), 78 records in total, and neither is a filter value. `soil salinization` is outside the branch, and 6 of its records have no other threat.
- **Soil deficiencies:** has no records, so it should be hidden.
- **Keywords only:** these counts do not use titles or abstracts, and `review_sheet.csv` has 0 of 257 verdicts, so nobody has reviewed the matches yet.

## How the counts work

```text
validate.soilvoc                     validate.record_soilvoc           validate.records
+---------------+                    +--------------------+            +----------+
| id            |<-------------------| soilvoc_id         |    .------>| id       |
| name          |                    | record_id          |----'       +----------+
| parent_id --. |                    | link_type          |  <> 'inside'
+-------------|-+                    | status             |  = 'accepted'
      ^       |                      +--------------------+
      '-------'  walked down from each level 2 value
```

## Queries

The SQL below was run on stage and matches the CSV. It uses only the stored parent. The `all parents` column needs the parent list in `Augmentation/SoilVoc/07_populate_soilvoc_db/outputs/multi_parent_concepts.csv`, because the DB does not hold it, so only the script computes that column.

### Filter values and counts

```sql
WITH RECURSIVE branch AS (
    SELECT id AS value_id, name AS value_name, id AS concept_id
    FROM validate.soilvoc
    WHERE parent_id = 'https://w3id.org/eusoilvoc#SoilThreats'
    UNION ALL
    SELECT b.value_id, b.value_name, s.id
    FROM branch b
    JOIN validate.soilvoc s ON s.parent_id = b.concept_id
)
SELECT b.value_id   AS soilvoc_id,
       b.value_name AS name,
       COUNT(DISTINCT b.concept_id) AS concepts_in_branch,
       COUNT(DISTINCT rs.record_id) FILTER (WHERE rs.link_type <> 'inside') AS records,
       COUNT(DISTINCT rs.record_id) AS records_with_inside
FROM branch b
LEFT JOIN validate.record_soilvoc rs
       ON rs.soilvoc_id = b.concept_id AND rs.status = 'accepted'
GROUP BY b.value_id, b.value_name
ORDER BY records DESC, name;
```

### Totals

Returns 808, 75, 883 and 33,566.

```sql
WITH RECURSIVE branch AS (
    SELECT id FROM validate.soilvoc
    WHERE parent_id = 'https://w3id.org/eusoilvoc#SoilThreats'
    UNION ALL
    SELECT s.id FROM branch b JOIN validate.soilvoc s ON s.parent_id = b.id
),
specific AS (
    SELECT DISTINCT rs.record_id
    FROM validate.record_soilvoc rs
    JOIN branch b ON b.id = rs.soilvoc_id
    WHERE rs.status = 'accepted' AND rs.link_type <> 'inside'
),
parent_term AS (
    SELECT DISTINCT record_id
    FROM validate.record_soilvoc
    WHERE soilvoc_id = 'https://w3id.org/eusoilvoc#SoilThreats'
      AND status = 'accepted' AND link_type <> 'inside'
)
SELECT (SELECT COUNT(*) FROM specific) AS records_with_specific_value,
       (SELECT COUNT(*) FROM parent_term
         WHERE record_id NOT IN (SELECT record_id FROM specific)) AS records_general_only,
       (SELECT COUNT(*) FROM (SELECT record_id FROM specific
                              UNION SELECT record_id FROM parent_term) u) AS records_total,
       (SELECT COUNT(*) FROM validate.records) AS all_records;
```

## Script

Writes the CSV and prints the totals. Run it from the repo root:

```bash
python Augmentation/SoilVoc/05_soilvoc_db_coverage/scripts/soil_threat_filter_values.py
```

Source: [`../scripts/soil_threat_filter_values.py`](../scripts/soil_threat_filter_values.py)

```python
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
```
