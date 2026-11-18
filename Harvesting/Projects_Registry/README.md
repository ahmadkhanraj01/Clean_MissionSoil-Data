# Harvesting/Projects_Registry

Builds the seed list of EU-funded soil projects. Other harvesters read `harvest.projects` to know which projects to fetch.

## `harvest_esdac_projects.py` (pipeline step 1)

**Purpose:** scrapes two public project lists and upserts every project into `harvest.projects`:
- the ESDAC "EU-funded projects" table: acronym, title, grant number from the CORDIS link
- the Mission Soil Platform "funded projects" page: acronym, funding call, project website, grant number from the CORDIS link

| Direction | Source / target | Details |
|---|---|---|
| Input | `https://esdac.jrc.ec.europa.eu/projects/Eufunded/Eufunded.html` | HTML table rows |
| Input | `https://mission-soil-platform.ec.europa.eu/project-hub/funded-projects-under-mission-soil` | HTML table rows; only projects with a numeric CORDIS grant number |
| Output | `harvest.projects` | one row per project |

**Database operations**

| Table | Operation | Columns | Conflict handling |
|---|---|---|---|
| `harvest.projects` | INSERT (ESDAC rows) | `code, title, grantnr, source='esdac'` | `ON CONFLICT (grantnr, code) DO UPDATE SET title` |
| `harvest.projects` | INSERT (Mission Soil rows) | `code, funding, website, grantnr, source='Mission soil'` | `ON CONFLICT (grantnr, code) DO UPDATE SET website, funding` |

No reads from the DB. No deletes. The table must already exist with the unique index `(code, grantnr)` (the DDL is in the script's comment).

**Run**
```bash
python Harvesting/Projects_Registry/harvest_esdac_projects.py
```
There are no flags and no dry run: it writes as it goes. Each insert is its own connection and commit (`common.database.dbQuery`). A failed row is printed and skipped.
