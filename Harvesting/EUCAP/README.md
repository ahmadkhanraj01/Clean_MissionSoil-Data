# Harvesting/EUCAP

EU CAP Network (eu-cap-network.ec.europa.eu): Horizon 2020 / Horizon Europe projects and their **Practice Abstracts**, which are short farmer-oriented summaries. The portal sits behind CloudFront and rate-limits aggressively (HTTP 429), so the scripts crawl politely: one request at a time, jittered pauses, rotating User-Agents, and backoff with retry.

---

## `harvest_eucap_projects.py` (pipeline step 3)

**Purpose:** a single pipeline for EU CAP projects.
1. Scrapes the project pages: title, description, keywords (`a.chip--keyword`), website.
2. Resolves acronym, grant number and CORDIS URL. It uses the practice-abstracts JSON, if present, as a lookup, plus a built-in override table.
3. Upserts the projects into `harvest.projects`.
4. Queries CORDIS SPARQL for partner organisations, abstract, dates and locations.
5. Builds MCF YAML and upserts it into `harvest.items`.

| Direction | Source / target | Details |
|---|---|---|
| Input | EU CAP Network project search + detail pages | live scrape (default) |
| Input | `data/eu_cap_practice_abstracts.json` | optional lookup (project URL → grant / acronym / CORDIS) |
| Input | file passed with `--seed-json` | optional: use this project list instead of scraping |
| Input | `https://cordis.europa.eu/datalab/sparql` | partner and metadata enrichment (skip with `--skip-cordis`) |
| Output | `harvest.projects` | `source='EU CAP Network'`, plus `keywords`, `description`, `cordis_url` |
| Output | `harvest.items` | `source='EU CAP Network'`, `resulttype='yaml'`, `itemtype='project'` |

**Database operations**

| Table | Operation | Columns | Conflict handling |
|---|---|---|---|
| `harvest` (schema) | CREATE SCHEMA IF NOT EXISTS | n/a | n/a |
| `harvest.projects` | CREATE TABLE IF NOT EXISTS; ALTER TABLE ADD COLUMN IF NOT EXISTS `keywords text[]`, `description text`, `cordis_url text`; UNIQUE INDEX `(code, grantnr)` | n/a | n/a |
| `harvest.items` | CREATE TABLE IF NOT EXISTS; UNIQUE INDEX `(hash)` | n/a | n/a |
| `harvest.projects` | INSERT (batch) | `code, title, funding, website, grantnr, source, keywords, description, cordis_url` | `ON CONFLICT (code, grantnr) DO UPDATE SET title, funding, website, source, keywords, description, cordis_url` |
| `harvest.items` | INSERT | `identifier, identifiertype, uri, resultobject, resulttype, hash, source, itemtype, title, project` | `ON CONFLICT (hash) DO UPDATE SET resultobject, resulttype` |
| both | SELECT count(*) | verification counts at the end | n/a |

One transaction for the whole run. With `--dry-run` it is rolled back at the end.

**Run**
```bash
python Harvesting/EUCAP/harvest_eucap_projects.py --dry-run --limit 5   # test, rolls back
python Harvesting/EUCAP/harvest_eucap_projects.py                       # scrape + write
python Harvesting/EUCAP/harvest_eucap_projects.py --seed-json data/eucap_projects_not_in_msp_testing.json
python Harvesting/EUCAP/harvest_eucap_projects.py --skip-cordis
```

---

## `harvest_eucap_practice_abstracts.py` (pipeline step 6)

**Purpose:** crawls the EU CAP project search (Horizon 2020 + Horizon Europe filter), opens every project page, and collects its Practice Abstracts: title, abstract, topics, contacts and URL. Each abstract is matched to a project in `harvest.projects` by acronym, grant number or normalised title. Progress is saved after every project, so a rerun resumes where it stopped.

| Direction | Source / target | Details |
|---|---|---|
| Input | `harvest.projects` | `code, grantnr, title, funding, website` |
| Input | `data/eufarmbook_projects.json` | only as a manual fallback if the DB is unreachable |
| Input | EU CAP Network search + project pages | live crawl |
| Output | `data/eu_cap_practice_abstracts.json` (or `--output`) | list of abstracts with `project_acronym`, `project_grant_number`, `cordis_url` |

**Database operations**

| Table | Operation | Columns |
|---|---|---|
| `harvest.projects` | SELECT | `code, grantnr, title, funding, website` |

The script makes **no DB writes**; its output is a JSON file. `Harmonize/insert_eucap_practices.py` loads it into `validate`.

**Run**
```bash
python Harvesting/EUCAP/harvest_eucap_practice_abstracts.py
python Harvesting/EUCAP/harvest_eucap_practice_abstracts.py --max-pages 2 --max-projects 10 --delay 2.0
python Harvesting/EUCAP/harvest_eucap_practice_abstracts.py --output data/test_pa.json
```

---

## `enrich_eucap_practice_abstracts.py` (helper, run after step 6)

**Purpose:** fixes the practice-abstracts JSON in place. When EU CAP did not show a project's acronym or grant number, the script fills `project_acronym`, `project_grant_number`, `project_identifier` and `cordis_url` from a built-in title → project table.

| Direction | Source / target | Details |
|---|---|---|
| Input | `data/eu_cap_practice_abstracts.json` (or `--file`) | JSON list |
| Output | same file, rewritten | a backup is written first as `*.json.bak` (skip with `--no-backup`) |

There are **no database operations**.

**Run**
```bash
python Harvesting/EUCAP/enrich_eucap_practice_abstracts.py
python Harvesting/EUCAP/enrich_eucap_practice_abstracts.py --file data/other_pa.json --no-backup
```
There is no dry run, but the `.bak` copy lets you undo the change.
