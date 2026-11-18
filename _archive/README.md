# _archive

Unchanged copies of scripts from `MissionSoil-Data` (branch `mahnoor`) that are **not part of the active pipeline**. They are kept for reference only and still use the old imports, paths and env names, so they will not run from here as-is.

| File | Original location | What it did | Tables / files | Why archived |
|---|---|---|---|---|
| `msp-harvester/insert_eufarmbook_to_harvest.py` | `msp-harvester/` | Loaded EU-FarmBook projects + contributions from JSON | reads `eufarmbook_projects.json`, `eufarmbook_contributions2.json` → INSERT `harvest.items` (`ON CONFLICT (hash) DO UPDATE`) | The EU-FarmBook harvesters now write to the DB directly |
| `msp-harvester/insert_missing_projects_to_harvest.py` | `msp-harvester/` | One-off gap fill for 8 named EU-FarmBook projects | JSON → INSERT `harvest.items` (schema.org) | One-off |
| `msp-harvester/enrich_eucap_projects.py` | `msp-harvester/` | Added grant IDs / CORDIS URLs to the 206-project EU CAP JSON | reads/writes `data/eucap_projects_not_in_msp_testing.json` | Folded into `Harvesting/EUCAP/harvest_eucap_projects.py` |
| `msp-harvester/insert_eucap_projects_to_harvest.py` | `msp-harvester/` | Loaded that JSON into `harvest.projects`; `--copy-testing-base` copied 341 projects from `msp-testing` | INSERT `harvest.projects` (`ON CONFLICT (code, grantnr) DO UPDATE`) | Replaced by `harvest_eucap_projects.py` |
| `msp-harvester/convert_harvest_to_schema_org.py` | `msp-harvester/` | One-off: converted old `resulttype='json'` Solr rows to schema.org | SELECT / UPDATE `harvest.items` | Solr harvester now writes schema.org directly |
| `msp-harvester/citation2doi.py` | `msp-harvester/utils/` | Citation string → DOI via Crossref (hard-coded `file.csv`) | CSV in, stdout out | Standalone tool, unused |
| `src/backfill_metadata_organizations.py` | `src/scripts/` | Repaired CORDIS partner orgs lost by an old `contacts`/`contact` bug | reads `harvest.items`, `metadata.records` → INSERT `metadata.organization`, `metadata.contact_in_record` | Bug fixed in the current harmonizer |
| `src/migrate_metadata_to_kh_dev.py` | `src/scripts/` | Cross-DB copy `msp-testing.metadata` → `msp-kh-dev` | reads `metadata.*`, `harvest.*` in source DB → writes target DB | Old two-database setup |
| `src/analyze_person_org_relations.py` | `src/scripts/` | Counted person/organisation cardinalities in local Solr dumps | reads `data/*solrData.json` | Ad-hoc analysis |
| `src/insert_normalized_ultra.py`, `src/queries.py`, `src/connection.py` | `src/db/` | Two-pass batch insert of `merged.json` into the old un-prefixed normalised schema | writes `records`, `persons`, `organizations`, `subjects`, … (no schema) | Replaced by the `validate` schema; connection code merged into `common/db.py` |
| `msp-md-harmonization/process.py` | `msp-md-harmonization/src/` | pygeometa harmonizer `harvest.vw_unique_harvest_items` → `metadata.*` | reads `harvest.vw_unique_harvest_items`, writes `metadata.records`, `records_processed`, `records_failed`, … | Replaced by `Harmonize/` (validate path) |
