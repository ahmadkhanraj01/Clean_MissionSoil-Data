# common

Shared code imported by every script. Each script starts with a small bootstrap block. It finds this folder, puts the repo root on `sys.path` and imports `common.db`, which loads `.env`. So scripts work from any directory.

| File | Purpose | DB / file operations |
|---|---|---|
| `db.py` | Loads `<repo>/.env`. Normalises variable names: `DB_*`, `DB_*1` or `POSTGRES_*` all work, and both spellings are set afterwards. Provides `get_connection(dbname=None, search_path=None, **overrides)`, `db_config()`, `db_url()`, `default_schema()`, and `DATA_DIR` / `ROOT_DIR`. With `MSP_READ_ONLY=1` every connection is read-only (`PGOPTIONS=-c default_transaction_read_only=on`). | Reads `.env`. Opens connections; no queries itself |
| `database.py` | Helpers used by the harvesters (from `msp-harvester/utils/database.py`). `dbInit()` now uses `get_connection()`. | see below |
| `utils.py` | DOI / PID helpers: `doi_from_url`, `url_from_pid`, `pid_from_url`, `pid_type`, `is_doi`, and a generic `to_schema_org` field mapper | none |
| `text_cleaning.py` | `clean_keyword_text()` + `VALID_2_CHAR_KEYWORDS`: the keyword cleaner shared by the Solr mapper and `clean_stage_subjects.py` (one copy; the two originals were identical) | none |
| `sources.py` + `source_aliases.json` | `canonical_source(name)`: one name per source in `validate.sources`. Ignores case, spaces, `http(s)://`, `www.` and a trailing `/`, then maps the variants listed in `source_aliases.json` (e.g. `data.erupa.eu`, `https://data.europa.eu/` → `data.europa.eu`). `similar_sources()` finds look-alike names for a warning; it never merges by itself. Used by `Harmonize/harmonize_all_to_validate.py` | reads `source_aliases.json` |
| `config.py` | Data paths, SoilWise Solr / OGC URLs, `RECORD_TYPES`, `PAGE_LIMIT`, `REQUEST_DELAY` (used by `fetch_soilwise_records.py`) | none |
| `keyword_matching.py` | `matchCountryUri(label)` → EU country URI | reads `utils/country_data.json` (not in the repo; nothing imports this module at the moment) |

## `database.py` operations

| Function | Table | Operation |
|---|---|---|
| `dbQuery(sql, params, hasoutput)` | any | runs one statement on a new connection (SELECT returns rows; otherwise commits). On error it prints and returns `None` |
| `dbUQuery(sql)` | any | runs and commits one statement |
| `insQry(table, values, cur)` | any (e.g. `harvest.items`) | INSERT … `ON CONFLICT DO NOTHING` on an open cursor |
| `insertSQL(table, fields, values)` | any | INSERT … `ON CONFLICT DO NOTHING`, own connection |
| `insertRecord(...)` | `harvest.items`, `harvest.item_duplicates` | INSERT into both (not used by the current scripts) |
| `hasSource(label, ...)` | `harvest.sources` | SELECT, then INSERT if missing (used by the CORDIS harvester; the table does not exist on stage) |
| `reset(source)` | `harvest.items` | **DELETE** all items of one source (not called by any script) |
