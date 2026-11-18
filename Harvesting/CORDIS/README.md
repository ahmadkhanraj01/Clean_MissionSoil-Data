# Harvesting/CORDIS

Enriches every project that has a grant number with its official metadata from the European Commission's CORDIS knowledge graph.

## `harvest_cordis_project_metadata.py` (pipeline step 4)

**Purpose:** reads all grant numbers from `harvest.projects` and queries the CORDIS SPARQL endpoint in batches of 10. Each project becomes an MCF YAML document (title, abstract, start/end dates, DOI `10.3030/<grant>`, partner organisations as `contacts`), which is stored in `harvest.items`.

| Direction | Source / target | Details |
|---|---|---|
| Input | `harvest.projects` | `grantnr` of every row where it is not empty |
| Input | `https://cordis.europa.eu/datalab/sparql` | EURIO ontology query per batch of 10 grant IDs |
| Output | `harvest.items` | one YAML item per project (`source='CORDIS'`, `resulttype='yaml'`, `itemtype='project'`) |
| Output | `harvest.sources` | registers `CORDIS` if it is missing |

**Database operations**

| Table | Operation | Columns | Conflict handling |
|---|---|---|---|
| `harvest.projects` | SELECT | `grantnr` (where not empty) | n/a |
| `harvest.sources` | SELECT, then INSERT if missing | `name, url, filter, type` | none |
| `harvest.items` | INSERT | `identifier, identifiertype, uri, resultobject, resulttype, hash, source, itemtype, title` | `ON CONFLICT DO NOTHING` (same MD5 hash = same YAML) |

One transaction per batch, committed after the batch.

**Run**
```bash
python Harvesting/CORDIS/harvest_cordis_project_metadata.py
```
There are no flags and no dry run.

> **Known issue on `msp-kh-stage`:** `harvest.sources` does not exist there. `hasSource()` then gets `None` back from `dbQuery` and the script stops with a `TypeError` before harvesting. Create the table or remove the `hasSource()` call before running it on stage.
