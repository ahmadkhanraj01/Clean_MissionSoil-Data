# curation: hand-edited inputs

CSV and JSON files that people edit and the scripts read. They decide how keywords are matched, translated and
cleaned. They are shared by tasks 01, 03, 06 and 07, so they live in one place (`paths.CURATION`).

| File | Purpose | Read by |
|---|---|---|
| `keyword_decisions.csv` | Manual keyword -> SoilVoc term decisions (e.g. `boden` -> soil) | 01, 03, 06 |
| `keyword_translations.csv` | Manual keyword translations to English | 06 |
| `translated_labels.json` | Multilingual SoilVoc labels (from soilwise-he/metadata-augmentation) | 01, 06 |
| `translated_review.csv` | Review of the machine translations | people |
| `stoplist.csv` | Words that are never a SoilVoc match (generic words) | 01, 03, 06 |
| `path_qualifiers.csv` | Qualifiers like "classification" stripped from path-like keywords | 01, 03, 06 |
| `category_labels.csv` | SDG, OECD and HAL category labels (noise) | 06 |
| `keyword_kinds.csv` | Kind of each keyword (term, code, portal tag, ...) | 06 |
| `inside_keyword_review.csv` | Review of 866 "term inside a longer keyword" pairs (50 same, 706 narrower, 72 wrong, 38 unclear); written by task 06 | 07 |
| `review_sheet.csv` | Older review sheet of undecided keywords (task 01 output). The current sheet is in task 07 outputs | people |
| `soilvoc_new_terms.csv` | Proposed new SoilVoc terms | people |
| `soilvoc_synonym_candidates.csv` | Proposed synonyms and broader links | people |
| `new_term_groups.csv` | Groups of the proposed new terms | people |
