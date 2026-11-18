# Harvesting

Pulls records from external sources into the raw **`harvest`** schema. Nothing here touches `validate` or `metadata`.

| Table | What it holds | Key |
|---|---|---|
| `harvest.projects` | One row per research project (acronym `code`, `grantnr`, title, funding, website, `source`) | unique `(code, grantnr)` |
| `harvest.items` | One row per harvested record; the payload is in `resultobject` (`resulttype` = `yaml` or `schema.org`) | unique `hash` |
| `harvest.sources` | Source registry (used only by the CORDIS harvester) | `name` |

## Run order

`harvest.projects` must be filled first. Steps 4, 5 and 6 read it.

| Step | Folder | Script | Reads | Writes |
|---|---|---|---|---|
| 1 | `Projects_Registry/` | `harvest_esdac_projects.py` | ESDAC + Mission Soil Platform web pages | `harvest.projects` |
| 2 | `EUFarmbook/` | `harvest_eufarmbook_projects.py` | eufarmbook.eu | `harvest.projects` |
| 3 | `EUCAP/` | `harvest_eucap_projects.py` | EU CAP Network portal, CORDIS SPARQL | `harvest.projects`, `harvest.items` |
| 4 | `CORDIS/` | `harvest_cordis_project_metadata.py` | `harvest.projects`, CORDIS SPARQL | `harvest.items`, `harvest.sources` |
| 5 | `EUFarmbook/` | `harvest_eufarmbook_contributions.py` | `harvest.projects`, eufarmbook.eu | `harvest.items` |
| 6 | `EUCAP/` | `harvest_eucap_practice_abstracts.py` | `harvest.projects`, EU CAP Network portal | `data/eu_cap_practice_abstracts.json` |
| 7 | `Solar_API/` | `harvest_solr_records.py` | SoilWise Solr API | `harvest.items` |

Each subfolder's README lists every operation per table.

## What `harvest.items` contains after harvesting

| `source` | `resulttype` | `itemtype` | Written by |
|---|---|---|---|
| `CORDIS` | `yaml` (MCF) | `project` | step 4 |
| `EU CAP Network` | `yaml` (MCF) | `project` | step 3 |
| `EUFARMBOOK` | `schema.org` | contribution type (default `contribution`) | step 5 |
| primary Solr provider (`openaire`, `bonares`, `cordis`, `impact4soil`, …) | `schema.org` | from the record | step 7 |
