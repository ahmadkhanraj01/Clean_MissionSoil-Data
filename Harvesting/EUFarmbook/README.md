# Harvesting/EUFarmbook

EU-FarmBook (eufarmbook.eu) hosts Horizon 2020 / Horizon Europe agricultural projects and their contributions: documents, videos and practice material. Both scripts drive a headless Chromium with Playwright and get past the site's Anubis bot check.

Setup: `pip install playwright && playwright install chromium`

Run order: **projects first**, then contributions. The contributions harvester reads the projects from the DB.

---

## `harvest_eufarmbook_projects.py` (pipeline step 2)

**Purpose:** lists all Horizon 2020 and Horizon Europe projects on EU-FarmBook. For each one it takes the best grant ID it can find (DOI `10.3030/<grant>`, then the CORDIS URL, then a fallback) and upserts the project into `harvest.projects`.

| Direction | Source / target | Details |
|---|---|---|
| Input | `https://eufarmbook.eu/en/projects` | project cards and detail pages |
| Output | `harvest.projects` | `source='EU-FarmBook'`; `website` = the project's EU-FarmBook URL |

**Database operations**

| Table | Operation | Columns | Conflict handling |
|---|---|---|---|
| `harvest` (schema) | CREATE SCHEMA IF NOT EXISTS | n/a | n/a |
| `harvest.projects` | CREATE TABLE / UNIQUE INDEX IF NOT EXISTS | `idx_hrv_prj_grant_code (code, grantnr)` | n/a |
| `harvest.projects` | INSERT (batch, `execute_values`) | `code, title, funding, website, grantnr, source` | `ON CONFLICT (grantnr, code) DO UPDATE` |

**Run**
```bash
python Harvesting/EUFarmbook/harvest_eufarmbook_projects.py              # all projects
python Harvesting/EUFarmbook/harvest_eufarmbook_projects.py --max 5      # first 5 (testing)
python Harvesting/EUFarmbook/harvest_eufarmbook_projects.py --no-headless   # show the browser
```
There is no dry run.

---

## `harvest_eufarmbook_contributions.py` (pipeline step 5)

**Purpose:** for every EU-FarmBook project in `harvest.projects`, opens its Contributions tab and then each contribution page. It extracts title, description, type, language, authors, dates, file links and keywords, converts each contribution to schema.org JSON, and inserts it into `harvest.items`. Inserts happen per project, in one round-trip.

| Direction | Source / target | Details |
|---|---|---|
| Input | `harvest.projects` | rows with `source='EU-FarmBook'` and a non-empty `website` |
| Input | `https://eufarmbook.eu/en/contributions/<id>` | contribution detail pages |
| Output | `harvest.items` | `source='EUFARMBOOK'`, `resulttype='schema.org'`, `itemtype` = contribution type (default `contribution`), `project` = grant number |

**Database operations**

| Table | Operation | Columns | Conflict handling |
|---|---|---|---|
| `harvest.projects` | SELECT | `code, grantnr, website` where `source='EU-FarmBook'` | n/a |
| `harvest.items` | INSERT (batch per project) | `identifier, identifiertype, uri, resultobject, resulttype, itemtype, title, source, project, date, hash` | `ON CONFLICT (hash) DO UPDATE SET resultobject, resulttype` |

**Run**
```bash
python Harvesting/EUFarmbook/harvest_eufarmbook_contributions.py
python Harvesting/EUFarmbook/harvest_eufarmbook_contributions.py --max-projects 3
python Harvesting/EUFarmbook/harvest_eufarmbook_contributions.py --no-headless
```
There is no dry run. The `project` column links each contribution to its project, so the harmonizer can fill `validate.record_project`.
