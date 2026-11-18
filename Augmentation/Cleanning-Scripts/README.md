# Augmentation/Cleanning-Scripts

Cleans the harmonized `validate` layer before it is migrated to `metadata`. Run after `Harmonize/`.

| Step | Script | Changes | Default mode |
|---|---|---|---|
| 12 | `clean_stage_subjects.py` | `validate.subjects`, `validate.record_subject` | dry run (`--commit` to apply) |
| 13 | `clean_record_languages.py` | `validate.records.language` | dry run (`--commit` to apply) |
| 14 | `clean_and_deduplicate_kh_dev.py` | `validate.records` + all junctions + distributions | **writes** (`--dry-run` to test) |

`Language Column Data Cleanup .md` is the original SQL write-up that `clean_record_languages.py` is built from.

---

## `clean_stage_subjects.py` (step 12)

**Purpose:** standardises the keyword taxonomy. Each subject label goes through `common/text_cleaning.clean_keyword_text`:
- drops pure numbers, dates, URLs and meaningless 2-letter tokens (scientific ones like `pH` and `Zn` are kept)
- strips classification prefixes (`01 natural sciences` → `natural sciences`) and HTML
- splits `;`-bundled labels into separate subjects

Duplicates are merged, and every record is re-linked to the canonical subject.

| Direction | Table | Operation | Details |
|---|---|---|---|
| Input | `validate.subjects` | SELECT | `id, label` |
| Input | `validate.record_subject` | SELECT | `record_id, subject_id` |
| Backup | `validate.subjects_backup_<ts>`, `validate.record_subject_backup_<ts>` | CREATE TABLE AS SELECT * | only with `--commit` |
| Output | `validate.subjects` | INSERT | new subjects produced by splitting |
| Output | `validate.subjects` | UPDATE | `label` set to the cleaned text |
| Output | `validate.record_subject` | **TRUNCATE**, then INSERT | the whole junction table is rebuilt from the cleaned links |
| Output | `validate.subjects` | DELETE | subjects that were pure noise or merged away |

Everything runs in one transaction, rolled back on error and in dry-run mode.

```bash
python Augmentation/Cleanning-Scripts/clean_stage_subjects.py            # dry run: projected summary
python Augmentation/Cleanning-Scripts/clean_stage_subjects.py --commit
```
Verified read-only on `msp-kh-stage`: 19,282 subjects and 102,270 links, net change 0.

> **Known issue:** a real term is also affected by the prefix stripping: `'4 per 1000" initiative'` → `'per 1000" initiative'`.

---

## `clean_record_languages.py` (step 13)

**Purpose:** gives `records.language` one standard form, as a full English name.
1. **Normalise:** codes and spellings become names (`en`/`eng`/`enc` → `English`, `fr`/`fra` → `French`, `deu` → `German`, `und` → `Undetermined`, …). Values that are already full names are **kept**. NULL, `''`, `'null'`, hashes and URLs become `'Unknown'`.
2. **Recover** (optional): rows still `'Unknown'` / NULL / `''` get their language from a CSV `identifier,language`. Rows that already have a language are skipped, so a rerun resumes where the last one stopped.

| Direction | Source / table | Operation | Details |
|---|---|---|---|
| Input | `<schema>.records` | SELECT | `language, count(*)` grouped; `identifier, language` for the CSV rows |
| Input | `--recovered-csv` file (e.g. `data/language_recovered.csv`) | read file | columns `identifier, language` |
| Backup | `<schema>.records_lang_backup_<ts>` | CREATE TABLE AS SELECT `identifier, language` | only with `--commit` |
| Output | `<schema>.records` | UPDATE | `SET language` per distinct raw value (step 1) |
| Output | `<schema>.records` | UPDATE … FROM (VALUES …) | `SET language WHERE language IS NULL OR IN ('', 'Unknown')` (step 2) |

`<schema>` defaults to `DB_SCHEMA` from `.env`, which is `validate`. Both steps run in one transaction.

```bash
python Augmentation/Cleanning-Scripts/clean_record_languages.py                     # dry run
python Augmentation/Cleanning-Scripts/clean_record_languages.py --recovered-csv data/language_recovered.csv
python Augmentation/Cleanning-Scripts/clean_record_languages.py --commit [--recovered-csv …]
```
Verified read-only on `msp-kh-stage`: 31 distinct values, 0 to change (already cleaned).
Nothing in the repo produces `language_recovered.csv`; it has to be supplied.

---

## `clean_and_deduplicate_kh_dev.py` (step 14)

**Purpose:** merges clusters of duplicate records listed in a review file. For each cluster:
1. The winner gets any fields it lacks from the losers.
2. All of the losers' links (sources, persons, organisations, subjects, projects, distributions) are re-pointed to the winner.
3. The losers are deleted.

At the end it prints an audit of what was merged and the final counts.

| Direction | Source / table | Operation | Details |
|---|---|---|---|
| Input | `data/detected_duplicates_for_review.json` (or env `DUPLICATES_JSON`) | read file | clusters with `recommended_winner_record` and its duplicates |
| Backup | `records_backup_<ts>`, `record_source_backup_<ts>` | CREATE TABLE AS SELECT * | skipped with `--dry-run` |
| Output | `records` | UPDATE | `SET <missing fields> WHERE id = winner` |
| Output | `record_source`, `record_person`, `record_organization`, `record_subject`, `record_project` | INSERT … SELECT | copy the loser's links to the winner · `ON CONFLICT (record_id, …) DO NOTHING` |
| Output | `distributions` | UPDATE | `SET record_id = winner WHERE record_id = loser` |
| Output | `records` | **DELETE** | `WHERE id = loser` |
| Check | `records`, junctions, `distributions` | SELECT count | verification after a real run |

Table names are unqualified. The connection pins `search_path` to `DB_SCHEMA` from `.env` (default `validate`).

```bash
python Augmentation/Cleanning-Scripts/clean_and_deduplicate_kh_dev.py --dry-run
python Augmentation/Cleanning-Scripts/clean_and_deduplicate_kh_dev.py
```
> Without `--dry-run` it **writes and deletes immediately**. The duplicates JSON is not produced by any script in this repo.
