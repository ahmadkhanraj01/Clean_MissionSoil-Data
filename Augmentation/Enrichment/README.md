# Augmentation/Enrichment

Fills gaps in harvested records using external registries, **before** they are harmonized.

## `enrich_missing_abstracts.py` (pipeline step 8)

**Purpose:** finds `harvest.items` records that have a DOI but no abstract. It asks **Crossref → DataCite → OpenAlex**, in that order, for the abstract. Crossref JATS XML is stripped, and OpenAlex's inverted index is rebuilt into text. The abstract is then written back into the record's JSON. Requests run in a small thread pool (`--workers`, default 3).

| Direction | Source / target | Details |
|---|---|---|
| Input | `harvest.items` | rows with `identifiertype='doi'`, `resulttype` in (`schema.org`, `json`), and an empty `abstract` in `resultobject` |
| Input | `api.crossref.org`, `api.datacite.org`, `api.openalex.org` | one lookup per DOI |
| Output | `harvest.items` | `resultobject` with the abstract added |

**Database operations**

| Table | Operation | Columns | Details |
|---|---|---|---|
| `harvest.items` | SELECT | `hash, identifier, source, resultobject` | filtered as above, optional `--source`, `--limit` |
| `harvest.items` | UPDATE (batch, `execute_values`) | `SET resultobject, insert_date = NOW()` | `WHERE hash = …` |

```bash
python Augmentation/Enrichment/enrich_missing_abstracts.py --dry-run --limit 100   # fetches, writes nothing
python Augmentation/Enrichment/enrich_missing_abstracts.py --source openaire --workers 5
```

Changes from the original:
- It used to be hard-wired to `msp-kh-dev`; it now uses `.env`.
- It used to crash on YAML items (CORDIS / EU CAP have `identifiertype='doi'` but YAML payloads). It now only reads JSON payloads. This was verified read-only on `msp-kh-stage`: 0 records currently need an abstract.
