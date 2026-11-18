# vocab

Vocabulary files the SoilVoc tasks read. They were copied unchanged from the root of the `soil-vocabs` repo (2026-11-13). To update them, copy the newer files from soil-vocabs; do not edit them here.

| File | Purpose | Read by (path constant in `../paths.py`) |
|---|---|---|
| `SoilVoc.ttl` | The SoilVoc SKOS vocabulary (1,464 concepts) | task 04 `soilvoc_levels.py`, 05 `soilvoc_in_text.py` / `soilvoc_db_counts.py`, 07 `load_soilvoc.py` (`SOILVOC_TTL`) |
| `SoilVoc_concepts.csv` | SoilVoc concepts as a table (id, type, prefLabel, altLabel, definition, …; space-padded cells) | task 01 matching (`SOILVOC_CSV`) |
| `ontovocabs/` | Other soil vocabularies (AGROVOC, GEMET, GloSIS, ISO 11074, …) as CSV/TTL modules | task 01 matching reads every `*.csv` (`ONTOVOCABS`) |
| `uk2us.py` | UK → US spelling list (`uk_us`) | tasks 01, 03, 06 (`UK2US`) |

No DB access.
