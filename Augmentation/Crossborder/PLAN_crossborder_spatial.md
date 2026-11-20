# Cross-border spatial extents: `validate.record_crossborder`

**Goal:** For each record in `validate.records` that has a `spatial` value, work out how many of the **45 European countries in the supplied `countries.geojson`** that extent covers, and flag it as cross-border when it covers more than one. Records whose extent touches none of the 45 get no row.

**Target DB:** `msp-kh-stage`, schema `validate` (connection settings from `DB_*1` in `.env`)

**Script:** `polygons/compute_crossborder.py`

**Status (2026-11-19):** ✅ Built. The current run is `crossborder_20261119_143357`, scope `europe45`: **4,010 rows, 1,558 of them cross-border (39%)**. The previous run (all countries worldwide, scope `hybrid`) had 4,853 rows and 1,727 cross-border; the 843 records outside the 45 countries were removed. `countries` is JSON, `[{"code": "IND", "name": "India"}]`, so it can feed an API.

---

## 1. What the source data looks like

| Fact | Value |
|---|---|
| `records` rows | 33,566 |
| Rows with `spatial` | **4,857** (14%), of which **1,018** are distinct values |
| Column type | `text`, **not** geometry |
| Format | Always a WKT bounding box `POLYGON((minx miny, maxx miny, maxx maxy, minx maxy, minx miny))`, lon/lat in EPSG:4326 |
| PostGIS on the server | **Not installed and not available.** All spatial work runs in Python (shapely 2.1 and geopandas 1.1). |

**How the script handles awkward values:**

| Case | Records | Handling |
|---|---:|---|
| `minx > maxx` (longitudes swapped) | 35 | Normalised with `min()`/`max()` |
| Zero-area box: a point or a line | 110 / 38 | Intersected as a point or line. Every country it touches counts. |
| Placeholder `POLYGON((0 0, 0 0, …))` | 4 | **Skipped**, no row written |
| Box touching none of the 45 countries (sea, Africa, Asia, the Americas…) | 843 | **No row** (with `--scope europe45`, the default) |

## 2. Country boundaries

**Default scope `europe45` (since 2026-11-19): only the 45 countries of the supplied file count.**

| Item | Value |
|---|---|
| Borders from | The supplied `countries.geojson` (`polygons/data/countries_europe45.geojson`, a copy of `geojson_data 1/geojson_data/countries.geojson`). No GISCO data is used. |
| Codes | ISO3, as in the file (`DEU`, `ROU`…) |
| Outlines | Repaired with `make_valid`, since 19 of the 45 are invalid |
| Land outside the 45 | Ignored. A box over Africa that also reaches Spain counts Spain only; a box touching none of the 45 gets no row. |
| Shares | `share` is computed among the 45 only, so it can differ from the world run |

**Norway is incomplete in `countries.geojson`:** its outline is only Svalbard and Jan Mayen (62,088 km²). It is rebuilt from the supplied `regions/NOR.geojson` (386,924 km², mainland included).

Six names in the supplied file are mapped to our naming rule:

| `countries.geojson` | Used |
|---|---|
| Czech Republic | Czechia |
| Luxemburg | Luxembourg |
| Macedonia, the former Yugoslav Republic of | North Macedonia |
| Moldova, Republic of | Moldova |
| Republic of Serbia | Serbia |
| Vatican | Vatican City |

**Other scopes (kept in the script, not used by the current run):**
- **`hybrid`** (the previous run): the supplied file for Europe, GISCO `CNTR_RG_01M_2020_4326` (Eurostat 1:1M, `polygons/data/CNTR_RG_01M_2020_4326.geojson`) for the rest of the world. GISCO is used for the 45 only for overseas parts (French Guiana, Réunion, Madeira). Other GISCO entries are trimmed to what lies outside the 45, and entries mostly covered by the file, such as Svalbard, are dropped. Kosovo is its own country.
- **`world`**: GISCO only, 257 entries, nothing clipped.

GISCO details (only matter for the `hybrid` / `world` / `europe` / `eu27` scopes):
- There are **257 entries**: sovereign countries, dependent territories (Greenland, French Polynesia and others) and disputed areas (`XA`–`XV`).
- Country names are the short, common international name (`India`, `Sri Lanka`, `Iran`).
- Nine GISCO names were renamed (`RENAMES` in the script, reviewed 2026-11-19):

  | GISCO | Used |
  |---|---|
  | Russian Federation | Russia |
  | United Republic of Tanzania | Tanzania |
  | Viet nam | Vietnam |
  | Myanmar/Burma | Myanmar |
  | Us Virgin Islands | United States Virgin Islands |
  | Faroes | Faroe Islands |
  | Sint-Maarten | Sint Maarten |
  | Jammu Kashmir | Jammu and Kashmir |
  | Cape Verde | Cabo Verde |

  Capitalisation is fixed as well: `Côte D’Ivoire` → `Côte d'Ivoire`, `Tristan Da Cunha` → `Tristan da Cunha`, `The` → `the` mid-name, and `Mcdonald` → `McDonald`.
- **Taiwan is part of China** in GISCO, so there is no separate `TWN`.
- **France's overseas departments** count as France.

`--scope` chooses which countries are counted:

| Scope | Countries | Notes |
|---|---:|---|
| **`europe45`** (default, current run) | 45 | Only the supplied `countries.geojson` (Norway patched). Records touching none of them get no row. |
| `hybrid` | 257 | Supplied file for Europe, GISCO for the rest; records with no land get a row with 0 countries |
| `geojson45` | 45 | The supplied file exactly as it is (Norway is only Svalbard) |
| `world` | 257 | GISCO only, worldwide; nothing is clipped |
| `europe` | 44 | EU-27, EFTA, UK, candidate countries, Belarus and the microstates. No Russia or Turkey. Overseas parts are clipped to lon -32…45, lat 34…72. |
| `eu27` | 27 | EU members only, with the same clipping |

## 3. Counting rule

A bounding box is a rectangle, so a box drawn around one country nearly always clips its neighbours. Germany's own box, for example, touches 9 countries. Counting every country a box touches would therefore make almost every national dataset cross-border, so the script uses this rule:

1. **Point or line:** every country it touches counts.
2. **National box match:** if the box overlaps a country's own bounding box with IoU ≥ 0.80, it **is** that country, and only that country counts. Two bounding boxes are tried for each country: the whole country and its largest part.
3. **Otherwise** a country counts when either:
   - **share** (the country's land in the box ÷ all land in the box) is at least **10%**, or
   - **inside** is at least **80%**. *inside* is the larger of two measures: the country's land in the box ÷ the country's total land, or the mainland's part in the box ÷ the whole mainland (the largest piece). The mainland measure stops remote parts from hiding a covered mainland. Without it, a Europe-wide box would drop Norway, because Svalbard lies outside the box, and drop France because of its overseas departments.

`share` and `inside` are rounded to the 4 decimals stored in `country_shares` *before* the rule is applied, so re-applying the rule to the stored values always gives the same answer.

`crossborders = number_of_countries > 1`. Areas are measured in equal-area EPSG:6933.

Options: `--iou`, `--share`, `--inside`, `--floor` (a minimum share for the *inside* branch, default 0), `--scope`, `--csv`, `--dry-run`.

## 4. Table, as built

```sql
CREATE TABLE validate.record_crossborder (
    id                  uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id           uuid         NOT NULL UNIQUE REFERENCES validate.records(id) ON DELETE CASCADE,
    spatial             text         NOT NULL,     -- copy of records.spatial at compute time
    crossborders        boolean      NOT NULL,
    number_of_countries smallint     NOT NULL,
    countries           jsonb        NOT NULL DEFAULT '[]',  -- [{"code":"IND","name":"India"}], largest share first
    method              text         NOT NULL,     -- national_bbox | share_rule | point | linestring
    country_shares      jsonb        NOT NULL DEFAULT '{}',  -- every touched country: {"share":…, "inside":…}
    scope               text         NOT NULL,
    run_id              text         NOT NULL,
    updated_at          timestamptz  NOT NULL DEFAULT now(),  -- same name as records.updated_at
    created_at          timestamptz  NOT NULL DEFAULT now(),  -- same name as records.created_at; never changed by re-runs
    CONSTRAINT record_crossborder_count_ck CHECK (number_of_countries = jsonb_array_length(countries)),
    CONSTRAINT record_crossborder_flag_ck  CHECK (crossborders = (number_of_countries > 1))
);
-- plus indexes on crossborders and number_of_countries
```

### Fields

| Field | Type | Purpose | Example |
|---|---|---|---|
| `id` | uuid | Row ID | `b77471dd-…` |
| `record_id` | uuid | Link to the record | `00102166-…` |
| `spatial` | text | The record's bounding box | `POLYGON((72.9 5.8, …))` |
| `crossborders` | boolean | More than one country? | `true` |
| `number_of_countries` | smallint | How many countries | `2` |
| `countries` | jsonb | Which countries (code + full name) | `[{"code":"ROU","name":"Romania"},{"code":"UKR","name":"Ukraine"}]` |
| `method` | text | How it was decided | `share_rule` |
| `country_shares` | jsonb | How much of the box each of the 45 countries covers (keyed by name) | `{"Romania": {"share": 0.87, "inside": 0.02}, …}` |
| `scope` | text | Which country borders were used | `europe45` |
| `run_id` | text | Which script run wrote the row | `crossborder_20261119_143357` |
| `updated_at` | timestamptz | When the row was last updated | `2026-11-19 05:53` |
| `created_at` | timestamptz | When the row was first added | `2026-11-18 11:57` |

#### What `country_shares` means

It lists **every one of the 45 countries the box touches**, with two numbers for each one:

- **`share`:** how much of the box's land (among the 45) belongs to this country.
- **`inside`:** how much of this country is inside the box.

Both numbers go from 0 to 1, so 0.5 means half and 1.0 means all of it.

**Example:** a box over Romania and Ukraine (a real row).

```json
{
  "Romania": {"share": 0.8716, "inside": 0.024},
  "Ukraine": {"share": 0.1284, "inside": 0.0014}
}
```

| Country | share | inside | Counted? | Why |
|---|---|---|---|---|
| Romania | 87% of the box | 2% of Romania | ✅ | Big share of the box (≥ 10%) |
| Ukraine | 13% of the box | 0.1% of Ukraine | ✅ | Share is at least 10% |

So `countries = [{"code":"ROU","name":"Romania"},{"code":"UKR","name":"Ukraine"}]`. A country that touches the box with less than 10% share and less than 80% inside stays in `country_shares` but not in `countries`, so you can see it was checked and left out.

**Why keep it:** you can check any result, or try a different threshold in SQL without running the script again.

### Tables

| Table | FK target | Rows | Status |
|---|---|---:|---|
| `validate.record_crossborder` | `validate.records(id)` | 4,010 | Populated by the script |
| `metadata.record_crossborder` | `metadata.records(id)` | 0 | **Empty**. Same columns (including the JSON `countries`), constraints and indexes, created 2026-11-19. Not filled by the script yet; it only writes to `validate`. |

Both tables come from the same DDL in the script (`ddl("validate")` and `ddl("metadata")`). They were created directly, **not through Alembic** (the schema's Alembic head is still `e3f8a1c92b47`).

**Refreshing:** run `python3 compute_crossborder.py` after each harvest or import. It is one transaction: create the table if needed (an older `text[]` `countries` column is converted to JSON), upsert every row, delete rows from older runs, then verify. Any failure rolls the whole thing back.

## 5. Results (scope `europe45`)

| | Rows | Cross-border |
|---|---:|---:|
| Before (all countries, `hybrid`) | 4,853 | 1,727 |
| **After (45 countries, `europe45`)** | **4,010** | **1,558 (39%)** |

| Countries | Records |
|---|---:|
| 1 | 2,452 |
| 2 | 366 |
| 3–5 | 311 |
| 6–20 | 86 |
| 21+ | 795 |
| 0 | none (those records get no row) |

The 843 removed records touch none of the 45 countries. 4 more records with the `0 0` placeholder were already skipped.

| Method | Records |
|---|---:|
| share_rule | 2,973 |
| national_bbox | 916 |
| point | 93 |
| linestring | 28 |

## 6. Verification (2026-11-19)

The Natural Earth and title checks below were done on the earlier worldwide run; the rule itself is unchanged.

| Check | Result |
|---|---|
| One row per record with `spatial` (excluding the 4 placeholders); no orphans, duplicates or out-of-date rows | ✅ |
| Same box always gives the same answer | ✅ 0 inconsistencies |
| Rule re-applied in SQL to the stored `country_shares` | ✅ 0 mismatches over 2,973 share_rule rows (europe45 run) |
| Every code in the table is one of the 45 in `countries.geojson`; no row has 0 countries | ✅ |
| Counted countries confirmed by Natural Earth 1:110m, an independent dataset | ✅ 99.98% (82,596 / 82,612). The misses are islands Natural Earth leaves out, or boxes within 0.02° of a border. |
| Countries holding ≥30% of a box (per Natural Earth) that appear in the result | 95%. Nearly all the misses are national box matches working as designed (e.g. Denmark's own box contains a lot of Sweden). |
| Titles naming one country: that country is in the result | ✅ 97.8% (1,010 / 1,033). The misses are mostly wrong boxes in the source data. |

**Known limitations:**
- **Microstates inside a region:** San Marino and the Vatican inside Italian regional boxes make those boxes cross-border.
- **Regional boxes spilling over a border:** Wallonia, Bavaria, Catalonia and Piemonte come out as 2–3 countries.
- **Countries inside a national box are dropped:** when a box matches a national box, a smaller country lying inside it is not counted. "Senegal and the Gambia" comes out as Senegal only, and "Syria and Lebanon" as Syria only.
- **Wrong boxes in the source data:** some boxes are wrong at the source.
  - Belgian soil-carbon maps have latitude and longitude swapped.
  - Iran maps carry Iraq's box.
  - Some Madagascar, Benin and Philippines studies carry Germany's box.

**Possible next fixes:**
1. Match against NUTS regional bounding boxes as well as national ones.
2. Ignore microstates below 0.5% of a box's land.
3. Within a national box match, still count countries that lie at least 80% inside the box and hold at least 3% of its land.
4. Detect swapped latitude/longitude.

---

## 7. The 45 countries

Source: `validate.record_crossborder`, run `crossborder_20261119_143357` (4,010 rows), scope `europe45`.

*Rows* is the number of records whose box counts the country. *Cross-border* is how many of those are flagged `crossborders = true`. *Only country* is how many have it as the single country.

| Code | Country | Rows | Cross-border | Only country |
|---|---|---:|---:|---:|
| DEU | Germany | 2,623 | 1,009 | 1,614 |
| ITA | Italy | 1,251 | 1,115 | 136 |
| FRA | France | 1,027 | 1,012 | 15 |
| ESP | Spain | 1,019 | 953 | 66 |
| BEL | Belgium | 982 | 958 | 24 |
| GRC | Greece | 940 | 930 | 10 |
| LUX | Luxembourg | 933 | 927 | 6 |
| CHE | Switzerland | 928 | 916 | 12 |
| AUT | Austria | 919 | 831 | 88 |
| NLD | Netherlands | 910 | 887 | 23 |
| SVN | Slovenia | 903 | 866 | 37 |
| SMR | San Marino | 884 | 884 | 0 |
| CZE | Czechia | 866 | 839 | 27 |
| PRT | Portugal | 859 | 852 | 7 |
| HUN | Hungary | 854 | 807 | 47 |
| POL | Poland | 851 | 832 | 19 |
| DNK | Denmark | 842 | 799 | 43 |
| AND | Andorra | 840 | 840 | 0 |
| GBR | United Kingdom | 840 | 805 | 35 |
| SWE | Sweden | 837 | 792 | 45 |
| MCO | Monaco | 836 | 836 | 0 |
| EST | Estonia | 828 | 806 | 22 |
| MDA | Moldova | 828 | 803 | 25 |
| SVK | Slovakia | 825 | 807 | 18 |
| BGR | Bulgaria | 819 | 812 | 7 |
| HRV | Croatia | 817 | 811 | 6 |
| LIE | Liechtenstein | 817 | 815 | 2 |
| VAT | Vatican City | 817 | 817 | 0 |
| ROU | Romania | 814 | 809 | 5 |
| BIH | Bosnia and Herzegovina | 813 | 813 | 0 |
| LVA | Latvia | 812 | 793 | 19 |
| MKD | North Macedonia | 810 | 810 | 0 |
| IRL | Ireland | 808 | 792 | 16 |
| SRB | Serbia | 807 | 807 | 0 |
| LTU | Lithuania | 806 | 792 | 14 |
| ALB | Albania | 805 | 805 | 0 |
| FIN | Finland | 804 | 788 | 16 |
| XKX | Kosovo | 802 | 802 | 0 |
| MNE | Montenegro | 801 | 801 | 0 |
| BLR | Belarus | 788 | 788 | 0 |
| NOR | Norway | 785 | 785 | 0 |
| UKR | Ukraine | 764 | 761 | 3 |
| ISL | Iceland | 752 | 717 | 35 |
| MLT | Malta | 604 | 600 | 4 |
| CYP | Cyprus | 570 | 564 | 6 |
