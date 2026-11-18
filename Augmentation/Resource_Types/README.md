# Augmentation/Resource_Types

Corrects `validate.records.resource_type` by comparing three sources: the MSP database, the SoilWise OGC catalogue, and the official DOI registries (Crossref / DataCite).

## Flow

```
SoilWise OGC API ──(15) fetch_soilwise_records ──► data/<Type>_records.json
validate.records ──(16) fetch_msp_kh_records ────► data/msp-kh-dev.json
                                                        │
data/OGC_records.json (notebook 01) ────────────────────┤
                                                        ▼
                             (17) compare_msp_vs_ogc_types ──► data/msp_type_mismatches.csv
                                                        │
                       notebook 05 (Crossref/DataCite check)
                                                        ▼
                            data/msp_type_mismatches_with_correct_type.csv
                                │                                    │
            (18) update_resource_types_from_ogc     (19) resolve_neither_and_unresolved
                                │                                    │
                                └────────► validate.records.resource_type ◄┘
```

Steps 18 and 19 are **dry run by default** (`--execute` to apply) and create a backup table first.

---

## `fetch_soilwise_records.py` (step 15)

**Purpose:** downloads OGC API – Features records for each resource type listed in `common/config.py` (`RECORD_TYPES`), 50 per page, with a short delay between pages.

| Direction | Source / target | Details |
|---|---|---|
| Input | `https://repository.soilwise-he.eu/cat/collections/metadata:main/items` (query param `type=<Type>`) | paginated |
| Output | `data/<Type>_records.json` | one file per type (e.g. `Dataset_records.json`) |

There are no database operations.
```bash
python Augmentation/Resource_Types/fetch_soilwise_records.py
```

---

## `fetch_msp_kh_records.py` (step 16)

**Purpose:** exports every record's identifier, title, abstract and resource type: the MSP side of the comparison.

| Direction | Table / file | Operation |
|---|---|---|
| Input | `validate.records` | SELECT `identifier, title, abstract, resource_type` ORDER BY identifier |
| Output | `data/msp-kh-dev.json` (or env `MSP_RECORDS_JSON`) | write file |

This is read-only on the DB. Verified on `msp-kh-stage`: 33,566 records exported.
```bash
python Augmentation/Resource_Types/fetch_msp_kh_records.py
```

---

## `compare_msp_vs_ogc_types.py` (step 17)

**Purpose:** matches each MSP record to an OGC feature, in this order:
1. identifier = OGC id
2. identifier found in the OGC link hrefs
3. same normalised title **and** the identifier in the links

It writes the rows where the MSP type differs from the OGC type.

| Direction | File | Details |
|---|---|---|
| Input | `data/msp-kh-dev.json` | from step 16 |
| Input | `data/OGC_records.json` | full OGC dump, built in `notebooks/01_soilwise_pipeline_and_reconciliation.ipynb` (not by step 15) |
| Output | `data/msp_type_mismatches.csv` | columns `identifier, title, msp_type, ogc_type, match_method` |

There are no database operations.
```bash
python Augmentation/Resource_Types/compare_msp_vs_ogc_types.py
```

---

## `update_resource_types_from_ogc.py` (step 18)

**Purpose:** for mismatches where the DOI registries confirm the **OGC** type is correct, sets that type in `validate.records`. Matching is strictly 1-to-1 on `identifier`. It prints the type distribution before and after.

| Direction | Table / file | Operation | Details |
|---|---|---|---|
| Input | `data/msp_type_mismatches_with_correct_type.csv` (`--csv`) | read file | produced by notebook 05 |
| Input | `<schema>.records` | SELECT | existence check, counts, type distribution |
| Backup | `<schema>.records_backup_<ts>` | CREATE TABLE AS SELECT * | with `--execute`, unless `--no-backup` |
| Output | `<schema>.records` | UPDATE | `SET resource_type, updated_at WHERE identifier = …` |

```bash
python Augmentation/Resource_Types/update_resource_types_from_ogc.py              # dry run
python Augmentation/Resource_Types/update_resource_types_from_ogc.py --execute
```
Flags: `--schema` (default `validate`), `--dbname` (default `.env`).

---

## `resolve_neither_and_unresolved.py` (step 19)

**Purpose:** decides the type for the leftover records with rules:
- **"neither"**: the registry type matched neither MSP nor OGC. Registry types are mapped (`JournalArticle` → Journal Article, `posted-content` → Preprint, …), and Zenodo `Text` is mapped by genre.
- **"unresolved"**: no DOI. EU portal `downloadPublic` URLs become `Report`, project deliverables become `Report`, and curated OGC types are accepted over a generic `Dataset`.

| Direction | Table / file | Operation | Details |
|---|---|---|---|
| Input | `--input-csv` (default `data/msp_type_mismatches_with_correct_type.csv`) | read file | |
| Input | `<schema>.records` | SELECT | `id, identifier, title, resource_type, url, updated_at` |
| Backup | `<schema>.records_backup_<ts>` | CREATE TABLE AS SELECT * | with `--execute`, unless `--no-backup` |
| Output | `<schema>.records` | UPDATE | `SET resource_type, updated_at = NOW() WHERE identifier = …` |
| Output | `--output-csv` (default `data/msp_type_mismatches_fully_resolved.csv`) | write file | the decisions made |

```bash
python Augmentation/Resource_Types/resolve_neither_and_unresolved.py                  # dry run
python Augmentation/Resource_Types/resolve_neither_and_unresolved.py --execute
python Augmentation/Resource_Types/resolve_neither_and_unresolved.py --identifier 10.5281/zenodo.123   # explain one record
```
Both step 18 and step 19 used to default `--dbname` to `msp-kh-dev`; they now use `.env`.
