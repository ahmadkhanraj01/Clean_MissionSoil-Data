# data

Local input and output files. The folder is git-ignored (this README is the only file meant to be shared). All scripts find it through `common.db.DATA_DIR`.

| File | Written by | Read by |
|---|---|---|
| `eu_cap_practice_abstracts.json` | `Harvesting/EUCAP/harvest_eucap_practice_abstracts.py`; fixed in place by `enrich_eucap_practice_abstracts.py` (backup `.json.bak`) | `Harmonize/insert_eucap_practices.py`; `harvest_eucap_projects.py` (lookup) |
| `eufarmbook_projects.json` | nothing (old manual fallback) | `harvest_eucap_practice_abstracts.py`, only if the DB is unreachable |
| `<Type>_records.json` | `Augmentation/Resource_Types/fetch_soilwise_records.py` | not read by any script (manual analysis) |
| `OGC_records.json` | `notebooks/01_soilwise_pipeline_and_reconciliation.ipynb` (original repo) | `compare_msp_vs_ogc_types.py` |
| `msp-kh-dev.json` | `fetch_msp_kh_records.py` | `compare_msp_vs_ogc_types.py` |
| `msp_type_mismatches.csv` | `compare_msp_vs_ogc_types.py` | notebook 05 (registry check) |
| `msp_type_mismatches_with_correct_type.csv` | notebook 05 (original repo) | `update_resource_types_from_ogc.py`, `resolve_neither_and_unresolved.py` |
| `msp_type_mismatches_fully_resolved.csv` | `resolve_neither_and_unresolved.py` | not read by any script |
| `language_recovered.csv` | **nothing in the repo**; supply it | `clean_record_languages.py --recovered-csv` |
| `detected_duplicates_for_review.json` | **nothing in the repo**; supply it | `clean_and_deduplicate_kh_dev.py` |
