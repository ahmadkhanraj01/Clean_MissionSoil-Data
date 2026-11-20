"""
compute_crossborder.py  (Clean_MissionSoil-Data pipeline step 40, stage "spatial")

Copied from K2X/polygons/compute_crossborder.py (2026-11-20). Changes in this copy:
  - DB settings come from the repo .env through common/db.py (DB_*1 or DB_*), and
    MSP_READ_ONLY=1 makes every session read-only, as for the other steps.
  - Data files live in ./data: countries_europe45.geojson, regions/NOR.geojson (the only
    regions file that patches a country), and optionally the GISCO file.
  - The GISCO file is read only by the scopes that use it (hybrid/world/europe/eu27),
    so the default europe45 scope runs without it.

Work out how many countries each validate.records.spatial bounding box
covers, and whether it is cross-border. See PLAN_crossborder_spatial.md.

Countries counted depend on --scope:
  europe45 (default) ONLY the 45 countries of the supplied countries.geojson (Norway patched
         from regions/NOR.geojson). Records with no such country get no row.
  hybrid Europe from the supplied countries.geojson (45 countries,
         data/countries_europe45.geojson) + the rest of the world from GISCO.
         GISCO entries are trimmed to what lies outside those 45 countries.
  geojson45 only the 45 European countries in the supplied countries.geojson
         (data/countries_europe45.geojson). Land outside them is ignored.
  world  every country/territory in the GISCO file, anywhere on Earth
         (Africa, Greenland, Russia, Antarctica, ...). Nothing is clipped.
  europe 44 European countries (no RU/TR); overseas parts clipped to EUROPE_WINDOW
  eu27   EU members only; overseas parts clipped to EUROPE_WINDOW

Counting rule for a rectangular bbox (points/lines count every country touched):
  1. National bbox match: if the bbox overlaps a country's own bbox with
     IoU >= --iou, the extent IS that country -> 1 country.
  2. Otherwise a country counts when
       share  = its land in bbox / all scoped land in bbox    >= --share
     or
       inside = its land in bbox / its total land             >= --inside
       and share >= --floor
  crossborders = number_of_countries > 1

Usage:
    python compute_crossborder.py --dry-run                    # read-only, nothing written
    python compute_crossborder.py --dry-run --scope eu27
    python compute_crossborder.py --dry-run --csv out.csv      # per-record results

    python compute_crossborder.py                              # create table if needed + upsert

Writing is one transaction: CREATE TABLE IF NOT EXISTS, upsert every record,
delete rows from older runs, verify counts; any failure rolls everything back.
Re-run after each harvest/import (idempotent).
"""

# --- Clean_MissionSoil-Data bootstrap ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import db_config  # noqa: E402  (loads <repo>/.env)
# ----------------------------------------

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import geopandas as gpd
import pandas as pd
import psycopg2
import shapely
from shapely.geometry import LineString, Point, box

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
# GISCO CNTR_RG_01M_2020 (Eurostat, 1:1M, 62 MB). Not in git; only the hybrid/world/europe/eu27
# scopes need it. Copy it from K2X/polygons/data/ or download it from Eurostat GISCO.
DEFAULT_COUNTRIES = DATA / "CNTR_RG_01M_2020_4326.geojson"
# Country borders supplied as JSON (copy of "geojson_data 1/geojson_data/countries.geojson"):
# 45 European countries, properties {name, code (ISO3)}
GEOJSON45 = DATA / "countries_europe45.geojson"
EQUAL_AREA = 6933
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?")

# Mainland Europe + Atlantic/Mediterranean islands (Azores, Iceland, Cyprus, Malta).
# Drops Canaries, Madeira, French overseas departments, Svalbard.
EUROPE_WINDOW = box(-32.0, 34.0, 45.0, 72.0)

# GISCO CNTR_ID codes (note EL = Greece, UK = United Kingdom)
EU27 = {"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU",
        "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK"}
EFTA = {"CH", "IS", "LI", "NO"}
CANDIDATES_NO_TR = {"AL", "BA", "MD", "ME", "MK", "RS", "UA"}
OTHER_EUROPE = {"UK", "AD", "MC", "SM", "VA", "BY", "XK"}
SCOPES = {
    "hybrid": "hybrid",   # Europe from the supplied countries.geojson, rest of the world from GISCO
    "europe45": "europe45",  # ONLY the 45 countries of the supplied countries.geojson (Norway patched); nothing else counts
    "geojson45": "file",  # every country in the supplied countries.geojson (45), no clipping
    "world": None,  # all countries, no clipping
    "eu27": EU27,
    "europe": EU27 | EFTA | CANDIDATES_NO_TR | OTHER_EUROPE,  # excludes RU, TR (transcontinental)
}


def connect(read_only: bool):
    """Connection from the repo .env (common/db.py). PGOPTIONS from MSP_READ_ONLY=1 still applies."""
    opts = "-c default_transaction_read_only=on" if read_only else None
    return psycopg2.connect(**db_config(), options=opts)


# GISCO NAME_ENGL -> short common international English name (reviewed 2026-11-19)
RENAMES = {
    "Russian Federation": "Russia",
    "United Republic of Tanzania": "Tanzania",
    "Viet nam": "Vietnam",
    "Myanmar/Burma": "Myanmar",
    "Us Virgin Islands": "United States Virgin Islands",
    "Faroes": "Faroe Islands",
    "Sint-Maarten": "Sint Maarten",
    "Jammu Kashmir": "Jammu and Kashmir",
    "Cape Verde": "Cabo Verde",
    # names used in the supplied countries.geojson
    "Czech Republic": "Czechia",
    "Luxemburg": "Luxembourg",
    "Macedonia, the former Yugoslav Republic of": "North Macedonia",
    "Moldova, Republic of": "Moldova",
    "Republic of Serbia": "Serbia",
    "Vatican": "Vatican City",
}


def tidy_name(name: str) -> str:
    """Short common English name: explicit RENAMES, then GISCO capitalisation quirks ('Côte D’Ivoire')."""
    if name in RENAMES:
        return RENAMES[name]
    for bad, good in ((" The ", " the "), (" Da ", " da "), ("Mcdonald", "McDonald"), ("D’Ivoire", "d'Ivoire"),
                      ("Hala'Ib", "Hala'ib")):
        name = name.replace(bad, good)
    return name


def to_names(counted, m, names):
    """Codes -> output: (countries JSON [{"code","name"}], country_shares JSON keyed by name)."""
    js = json.dumps({names[c]: {"share": round(s, 4), "inside": round(i, 4)}
                     for c, (s, i) in sorted(m.items(), key=lambda kv: -kv[1][0])}, ensure_ascii=False)
    return json.dumps([{"code": c, "name": names[c]} for c in counted], ensure_ascii=False), js


def read_country_file(path: Path, scope) -> gpd.GeoDataFrame:
    """Read a GISCO or supplied-JSON country file -> GeoDataFrame(code, name, geometry) in EPSG:4326."""
    raw = gpd.read_file(path)
    if raw.crs is not None and raw.crs.to_epsg() != 4326:
        raw = raw.to_crs(4326)
    geom = raw.geometry.make_valid().values
    if "CNTR_ID" not in raw.columns:  # supplied JSON format: properties {name, code}
        if not {"name", "code"} <= set(raw.columns):
            sys.exit(f"Unknown country file format: {path} (columns {list(raw.columns)})")
        raw = raw.assign(CNTR_ID=raw["code"], ISO3_CODE=raw["code"], NAME_ENGL=raw["name"])
        if scope not in (None, "file"):
            sys.exit("--scope europe/eu27 only work with the GISCO file")
        scope = None
    if scope is not None:  # European scopes: filter and clip overseas parts
        keep = raw["CNTR_ID"].isin(scope).values
        missing = scope - set(raw["CNTR_ID"])
        if missing:
            print(f"WARNING: scope codes not in country file: {sorted(missing)}")
        raw, geom = raw[keep], shapely.intersection(geom[keep], EUROPE_WINDOW)
    code = raw["ISO3_CODE"].where(raw["ISO3_CODE"].fillna("") != "", raw["CNTR_ID"])
    names = [tidy_name(n) for n in raw["NAME_ENGL"].values]
    gdf = gpd.GeoDataFrame({"code": code.values, "name": names}, geometry=geom, crs=4326)
    return gdf[~gdf.geometry.is_empty].reset_index(drop=True)


SLIVER_KM2 = 50  # GISCO leftovers smaller than this are border slivers, not territory
# Supplied regions/<ISO3>.geojson (from K2X/polygons/geojson_data 1/geojson_data/regions). Only
# NOR.geojson is copied: it is the only one that patches a country (the others are smaller than
# 1.2 x the country outline, so they change nothing). Add more files here to patch more countries.
REGIONS_DIR = DATA / "regions"


def read_regions(path: Path):
    """Union of all NUTS regions in a supplied regions/<ISO3>.geojson, skipping mislabelled
    Turkish regions (TR*) that appear in the BGR and GRC files."""
    r = gpd.read_file(path)
    r = r[~r["id"].astype(str).str.startswith("TR")]
    return shapely.union_all(r.geometry.make_valid().values)


def hybrid_countries(europe_path: Path, world_path: Path, europe_only: bool = False):
    """Europe from the supplied JSON (authoritative), the rest of the world from GISCO.

    Each GISCO entry keeps only what lies OUTSIDE the supplied European countries.
    A leftover is kept if it is a real territory (>= half its original area, e.g.
    Gibraltar, Faroe Islands) or a part >= SLIVER_KM2 (e.g. French Guiana); thin
    slivers caused by the two datasets drawing borders slightly differently are dropped.
    Returns (gdf, report).
    """
    eu = read_country_file(europe_path, "file")
    to_km2 = lambda geoms: gpd.GeoSeries(geoms, crs=4326).to_crs(EQUAL_AREA).area.values / 1e6
    report = {"kept_whole": 0, "trimmed": [], "dropped": [], "patched": []}
    # Patch countries whose outline in countries.geojson is incomplete, using the supplied
    # regions/<ISO3>.geojson (e.g. NOR in countries.geojson is only Svalbard + Jan Mayen).
    for i, row in eu.iterrows():
        rf = REGIONS_DIR / f"{row['code']}.geojson"
        if not rf.exists():
            continue
        reg = read_regions(rf)
        reg_km2, own_km2 = to_km2([reg])[0], to_km2([row.geometry])[0]
        if reg_km2 > 1.2 * own_km2:
            eu.at[i, "geometry"] = shapely.union_all([row.geometry, reg])
            report["patched"].append(f"{row['name']} {own_km2:,.0f} -> {to_km2([eu.at[i, 'geometry']])[0]:,.0f} km² (from regions file)")
    if europe_only:  # only the countries of the supplied file, no GISCO pieces at all
        report["kept_whole"] = 0
        return gpd.GeoDataFrame(eu, geometry="geometry", crs=4326), report
    if not world_path.exists():
        sys.exit(f"Scope 'hybrid' needs the GISCO file: {world_path} (see DEFAULT_COUNTRIES)")
    world = read_country_file(world_path, None)
    eu_union = shapely.union_all(eu.geometry.values)
    eu_names = dict(zip(eu["code"], eu["name"]))
    hits = set(world.sindex.query(eu_union, predicate="intersects"))
    parts = []
    for i, row in world.iterrows():
        if i not in hits and row["code"] not in eu_names:
            parts.append((row["code"], row["name"], row.geometry)); report["kept_whole"] += 1
            continue
        rest = row.geometry.difference(eu_union)
        pieces = [p for p in getattr(rest, "geoms", [rest]) if p.geom_type == "Polygon" and not p.is_empty]
        areas = to_km2(pieces) if pieces else []
        if row["code"] in eu_names:
            # one of the 45: inside Europe the supplied outline wins; keep only overseas parts
            keep = [p for p in pieces if not p.intersects(EUROPE_WINDOW)]
        elif sum(areas) < 0.5 * to_km2([row.geometry])[0]:
            keep = []  # mostly covered by the supplied countries (e.g. Svalbard is in NOR)
        else:
            keep = [p for p, a in zip(pieces, areas) if a >= SLIVER_KM2 or sum(areas) < 10 * SLIVER_KM2]
        if not keep:
            report["dropped"].append(row["name"]); continue
        name = eu_names.get(row["code"], row["name"])  # e.g. French overseas parts stay "France"
        parts.append((row["code"], name, shapely.MultiPolygon(keep) if len(keep) > 1 else keep[0]))
        report["trimmed"].append(f"{name} ({to_km2(keep).sum():,.0f} km² kept)")
    out = gpd.GeoDataFrame([{"code": c, "name": n} for c, n, _ in parts],
                           geometry=[g for _, _, g in parts], crs=4326)
    out = pd.concat([eu, out], ignore_index=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=4326), report


class Countries:
    def __init__(self, gdf: gpd.GeoDataFrame):
        self.gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)
        self.sindex = self.gdf.sindex
        self.names = dict(zip(self.gdf["code"], self.gdf["name"]))
        self.full_area = self.gdf.to_crs(EQUAL_AREA).area.groupby(self.gdf["code"].values).sum().to_dict()
        # each country's own bbox: whole (clipped) country and its largest part
        self.bboxes, self.main = {}, {}
        for c, grp in self.gdf.groupby("code"):
            g = shapely.union_all(grp.geometry.values)
            main = max(getattr(g, "geoms", [g]), key=lambda p: p.area)
            self.bboxes[c] = [box(*g.bounds), box(*main.bounds)]
            self.main[c] = main
        # mainland (largest part) area, so remote parts (Svalbard, French overseas) don't hide a covered mainland
        codes = list(self.main)
        self.main_area = dict(zip(codes, gpd.GeoSeries([self.main[c] for c in codes], crs=4326).to_crs(EQUAL_AREA).area))

    def measure(self, geom) -> dict:
        """{code: (share, inside)} for every scoped country the geometry touches."""
        idx = self.sindex.query(geom, predicate="intersects")
        if len(idx) == 0:
            return {}
        hit = self.gdf.iloc[idx]
        if geom.geom_type != "Polygon":
            codes = sorted(set(hit["code"]))
            return {c: (round(1 / len(codes), 4), 1.0) for c in codes}
        clipped = gpd.GeoSeries(shapely.intersection(hit.geometry.values, geom), crs=4326).to_crs(EQUAL_AREA)
        areas = Counter()
        for c, a in zip(hit["code"], clipped.area):
            areas[c] += a
        land = sum(areas.values())
        if land <= 0:  # touches only along a border line
            return {c: (round(1 / len(areas), 4), 0.0) for c in areas}
        found = [c for c, a in areas.items() if a > 0]
        main_in = gpd.GeoSeries(shapely.intersection([self.main[c] for c in found], geom), crs=4326).to_crs(EQUAL_AREA).area
        # inside = the larger of: share of the whole country, share of its mainland.
        # Rounded to the 4 decimals that are stored, so the rule re-applied to country_shares
        # always gives the same answer (no 0.09996 -> "0.1" edge cases).
        return {c: (round(areas[c] / land, 4), round(max(areas[c] / self.full_area[c], mi / self.main_area[c]), 4))
                for c, mi in zip(found, main_in)}

    def national_match(self, geom, codes, iou_min: float):
        if geom.geom_type != "Polygon":
            return None
        best, best_c = 0.0, None
        for c in codes:
            for bb in self.bboxes[c]:
                u = geom.union(bb).area
                v = geom.intersection(bb).area / u if u else 0
                if v > best:
                    best, best_c = v, c
        return best_c if best >= iou_min else None


def parse_bbox(wkt: str):
    """Return (geometry, flags) or (None, reason)."""
    nums = [float(n) for n in NUM_RE.findall(wkt)]
    if len(nums) < 4 or len(nums) % 2:
        return None, "unparseable"
    xs, ys = nums[0::2], nums[1::2]
    if any(abs(x) > 180 for x in xs) or any(abs(y) > 90 for y in ys):
        return None, "out_of_range"
    if all(v == 0 for v in nums):
        return None, "placeholder_0_0"
    flags = []
    if xs[0] > xs[1]:
        flags.append("swapped_lon")
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    if minx == maxx and miny == maxy:
        flags.append("point")
        return Point(minx, miny), flags
    if minx == maxx or miny == maxy:
        flags.append("line")
        return LineString([(minx, miny), (maxx, maxy)]), flags
    return box(minx, miny, maxx, maxy), flags


def classify(geom, m: dict, C: Countries, a):
    """Return (countries sorted by share, method)."""
    if not m:
        return [], "no_land"
    if geom.geom_type != "Polygon":
        return sorted(m, key=lambda c: -m[c][0]), geom.geom_type.lower()
    nat = C.national_match(geom, m.keys(), a.iou)
    if nat:
        return [nat], "national_bbox"
    counted = [c for c, (s, i) in m.items() if s >= a.share or (i >= a.inside and s >= a.floor)]
    return sorted(counted, key=lambda c: -m[c][0]), "share_rule"


DDL = """
CREATE TABLE IF NOT EXISTS __SCHEMA__.record_crossborder (
    id                  uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id           uuid         NOT NULL UNIQUE
                                     REFERENCES __SCHEMA__.records(id) ON DELETE CASCADE,
    spatial             text         NOT NULL,
    crossborders        boolean      NOT NULL,
    number_of_countries smallint     NOT NULL,
    countries           jsonb        NOT NULL DEFAULT '[]',
    method              text         NOT NULL,
    country_shares      jsonb        NOT NULL DEFAULT '{}',
    scope               text         NOT NULL,
    run_id              text         NOT NULL,
    created_at          timestamptz  NOT NULL DEFAULT now(),
    updated_at          timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT record_crossborder_count_ck CHECK (number_of_countries = jsonb_array_length(countries)),
    CONSTRAINT record_crossborder_flag_ck  CHECK (crossborders = (number_of_countries > 1))
);
CREATE INDEX IF NOT EXISTS record_crossborder_crossborders_idx ON __SCHEMA__.record_crossborder (crossborders);
CREATE INDEX IF NOT EXISTS record_crossborder_ncountries_idx   ON __SCHEMA__.record_crossborder (number_of_countries);
COMMENT ON TABLE __SCHEMA__.record_crossborder IS
  'Per record: how many countries records.spatial (a bbox) covers (see scope column; default europe45 = only the 45 countries of countries.geojson). Built by Clean_MissionSoil-Data Augmentation/Crossborder/compute_crossborder.py.';
COMMENT ON COLUMN __SCHEMA__.record_crossborder.countries IS 'JSON array [{"code": ISO3, "name": full name}] of the countries counted, largest share of bbox land first';
COMMENT ON COLUMN __SCHEMA__.record_crossborder.created_at IS 'When the row was first inserted; never changed by re-runs';
COMMENT ON COLUMN __SCHEMA__.record_crossborder.method IS 'national_bbox | share_rule | point | linestring | no_land';
COMMENT ON COLUMN __SCHEMA__.record_crossborder.country_shares IS
  'Every scoped country touched, keyed by name: share = its land / all scoped land in bbox, inside = its land in bbox / its total land';
"""

# older tables stored countries as text[]; convert to jsonb [{code,name}] (idempotent)
MIGRATE = """
DO $$
BEGIN
  IF (SELECT data_type FROM information_schema.columns WHERE table_schema = '__SCHEMA__'
        AND table_name = 'record_crossborder' AND column_name = 'countries') = 'ARRAY' THEN
    ALTER TABLE __SCHEMA__.record_crossborder DROP CONSTRAINT record_crossborder_count_ck;
    ALTER TABLE __SCHEMA__.record_crossborder DROP COLUMN countries;
    ALTER TABLE __SCHEMA__.record_crossborder ADD COLUMN countries jsonb NOT NULL DEFAULT '[]';
    ALTER TABLE __SCHEMA__.record_crossborder ADD CONSTRAINT record_crossborder_count_ck
      CHECK (number_of_countries = jsonb_array_length(countries)) NOT VALID;  -- validated after the upsert
  END IF;
END $$;
"""


def ddl(schema: str) -> str:
    """CREATE TABLE/INDEX/COMMENT statements for <schema>.record_crossborder (FK to <schema>.records)."""
    assert schema.isidentifier()
    return DDL.replace("__SCHEMA__", schema) + MIGRATE.replace("__SCHEMA__", schema)


UPSERT = """
INSERT INTO validate.record_crossborder
    (record_id, spatial, crossborders, number_of_countries, countries, method, country_shares, scope, run_id)
VALUES %s
ON CONFLICT (record_id) DO UPDATE SET
    spatial = EXCLUDED.spatial, crossborders = EXCLUDED.crossborders,
    number_of_countries = EXCLUDED.number_of_countries, countries = EXCLUDED.countries,
    method = EXCLUDED.method, country_shares = EXCLUDED.country_shares,
    scope = EXCLUDED.scope, run_id = EXCLUDED.run_id, updated_at = now()
"""


def write_db(rows, run_id):
    from psycopg2.extras import execute_values
    conn = connect(read_only=False)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(ddl("validate"))
            execute_values(cur, UPSERT, rows, page_size=1000,
                           template="(%s::uuid, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s)")
            # drop rows whose record lost its spatial value / was skipped / is from an older run
            cur.execute("DELETE FROM validate.record_crossborder WHERE run_id <> %s", (run_id,))
            deleted = cur.rowcount
            cur.execute("ALTER TABLE validate.record_crossborder VALIDATE CONSTRAINT record_crossborder_count_ck")
            cur.execute("""SELECT count(*), count(*) FILTER (WHERE crossborders),
                                  (SELECT count(*) FROM validate.records WHERE spatial IS NOT NULL)
                           FROM validate.record_crossborder""")
            n, n_cross, n_spatial = cur.fetchone()
            cur.execute("""SELECT count(*) FROM validate.record_crossborder rc
                           JOIN validate.records r ON r.id = rc.record_id
                           WHERE rc.spatial IS DISTINCT FROM r.spatial""")
            stale = cur.fetchone()[0]
            if n != len(rows) or stale:
                raise RuntimeError(f"verification failed: rows={n} expected={len(rows)} stale={stale}")
        print(f"\nCommitted run {run_id}: {n} rows ({n_cross} cross-border), removed {deleted} old rows. "
              f"Records with spatial: {n_spatial}, stale rows: {stale}.")
    finally:
        conn.close()


def bucket(n: int) -> str:
    return "0" if n == 0 else "1" if n == 1 else "2" if n == 2 else "3-5" if n <= 5 else "6-20" if n <= 20 else "21+"


def main():
    ap = argparse.ArgumentParser(description="Detect cross-border spatial extents")
    ap.add_argument("--dry-run", action="store_true", help="read-only connection, nothing is written")
    ap.add_argument("--scope", choices=SCOPES, default="europe45")
    ap.add_argument("--iou", type=float, default=0.80, help="national bbox match threshold")
    ap.add_argument("--share", type=float, default=0.10)
    ap.add_argument("--inside", type=float, default=0.80)
    ap.add_argument("--floor", type=float, default=0.0, help="min share for the 'inside' branch")
    ap.add_argument("--countries-file", type=Path, default=None,
                    help="GISCO file used by hybrid/world/europe/eu27 (default data/CNTR_RG_01M_2020_4326.geojson)")
    ap.add_argument("--csv", type=Path, help="write per-record results to this CSV")
    a = ap.parse_args()
    t0 = time.time()
    if a.scope in ("hybrid", "europe45"):
        gdf, rep = hybrid_countries(GEOJSON45, a.countries_file or DEFAULT_COUNTRIES, a.scope == "europe45")
        print(f"Hybrid borders: {len(gdf)} pieces | GISCO kept whole: {rep['kept_whole']} | "
              f"trimmed to outside Europe: {len(rep['trimmed'])} | dropped (inside Europe): {len(rep['dropped'])}")
        print("  patched: " + ("; ".join(rep["patched"]) or "none"))
        print("  trimmed: " + "; ".join(rep["trimmed"]))
        print("  dropped: " + "; ".join(rep["dropped"]))
        C = Countries(gdf)
    else:
        if a.countries_file is None:
            a.countries_file = GEOJSON45 if a.scope == "geojson45" else DEFAULT_COUNTRIES
        C = Countries(read_country_file(a.countries_file, SCOPES[a.scope]))
    print(f"Scope '{a.scope}': {len(C.full_area)} countries  "
          f"rule: iou>={a.iou} | share>={a.share} | inside>={a.inside} & share>={a.floor}")

    conn = connect(read_only=True)
    with conn, conn.cursor() as cur:
        cur.execute("SHOW transaction_read_only")
        ro = cur.fetchone()[0]
        cur.execute("SELECT id::text, spatial FROM validate.records WHERE spatial IS NOT NULL")
        records = cur.fetchall()
    conn.close()
    print(f"DB session read-only: {ro}")

    by_spatial = {}
    for rid, sp in records:
        by_spatial.setdefault(sp, []).append(rid)
    print(f"Records with spatial: {len(records)}  distinct: {len(by_spatial)}")

    results, flag_counts, skipped = {}, Counter(), Counter()
    for sp, rids in by_spatial.items():
        geom, flags = parse_bbox(sp)
        if geom is None:
            skipped[flags] += len(rids)
            continue
        for f in flags:
            flag_counts[f] += len(rids)
        m = C.measure(geom)
        counted, method = classify(geom, m, C, a)
        if not counted:  # no country of the scope -> no row (e.g. a box over Africa when scope = europe45)
            skipped["no_country_in_scope"] += len(rids)
            continue
        results[sp] = (m, counted, method, flags)
    print("Normalised (records): " + ", ".join(f"{k}={v}" for k, v in sorted(flag_counts.items())))
    print("Skipped, not in table (records): " + (", ".join(f"{k}={v}" for k, v in skipped.items()) or "none"))

    n_rec = lambda sp: len(by_spatial[sp])
    b, meth, cross = Counter(), Counter(), 0
    for sp, (_, counted, method, _) in results.items():
        b[bucket(len(counted))] += n_rec(sp)
        meth[method] += n_rec(sp)
        cross += (len(counted) > 1) * n_rec(sp)
    total = sum(n_rec(sp) for sp in results)
    print(f"\nCross-border: {cross} of {total} records ({cross/total:.0%})")
    print("By number_of_countries: " + "  ".join(f"{k}: {b[k]}" for k in ["0", "1", "2", "3-5", "6-20", "21+"]))
    print("By method: " + "  ".join(f"{k}: {v}" for k, v in meth.most_common()))

    print("\nTop 20 extents by record count:")
    for sp in sorted(results, key=lambda s: -n_rec(s))[:20]:
        m, counted, method, _ = results[sp]
        nums = NUM_RE.findall(sp)
        shown = ",".join(counted[:10]) + ("…" if len(counted) > 10 else "")
        print(f"  {n_rec(sp):>4}  [{nums[0]},{nums[1]} → {nums[4]},{nums[5]}]  n={len(counted):<2} "
              f"{'CROSS' if len(counted) > 1 else '     '}  {method:<16} {shown}")

    print("\nTop 10 cross-border extents decided by the share rule (check these):")
    cands = [s for s, r in results.items() if r[2] == "share_rule" and len(r[1]) > 1]
    for sp in sorted(cands, key=lambda s: -n_rec(s))[:10]:
        m, counted, _, _ = results[sp]
        nums = NUM_RE.findall(sp)
        print(f"  {n_rec(sp):>4}  [{nums[0]},{nums[1]} → {nums[4]},{nums[5]}]  "
              + ", ".join(f"{c} {m[c][0]:.0%}/{m[c][1]:.0%}" for c in counted[:6]))

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["record_id", "spatial", "crossborders", "number_of_countries", "countries",
                        "method", "country_shares", "flags"])
            for sp, rids in by_spatial.items():
                if sp not in results:
                    continue
                m, counted, method, flags = results[sp]
                cnames, js = to_names(counted, m, C.names)
                for rid in rids:
                    w.writerow([rid, sp, len(counted) > 1, len(counted), cnames,
                                method, js, ";".join(flags)])
        print(f"\nCSV written: {a.csv}")

    if a.dry_run:
        print(f"\nDry run finished in {time.time()-t0:.1f}s. Nothing was written to the database.")
        return

    run_id = time.strftime("crossborder_%Y%m%d_%H%M%S")
    rows = []
    for sp, rids in by_spatial.items():
        if sp not in results:
            continue
        m, counted, method, _ = results[sp]
        cnames, js = to_names(counted, m, C.names)
        rows += [(rid, sp, len(counted) > 1, len(counted), cnames, method, js, a.scope, run_id) for rid in rids]
    write_db(rows, run_id)
    print(f"Finished in {time.time()-t0:.1f}s.")


if __name__ == "__main__":
    main()
