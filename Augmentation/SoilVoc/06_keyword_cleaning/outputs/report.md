# Cleaned subjects vs SoilVoc

Database `msp-kh-dev`, schema `validate` (read-only). Cleaning is done in CSV only; nothing is written to the DB.

## Result

- SoilVoc concepts used by records: **685 of 1464** (650 without 'broader' links)
- Records with a SoilVoc subject: **19158 of 38211 (50.1%)**, 58.5% of the 32732 records with subjects (18510 without 'broader' links)
- Before cleaning (exact labels only): 17983 records
- Including SoilVoc terms found inside longer keywords (weaker): 703 concepts, 20006 records (52.4%)

## Keywords

- Unique keywords before cleaning: 48685
- Unique keywords after cleaning: 46376
- SoilVoc: 1398 (exact 862, synonym 81, translation 177, variant 63, mapped 163, accents 9, broader 43)
- SoilVoc but ambiguous (more than one concept): 59
- SoilVoc term inside a longer keyword (weaker link): 2631
- Proposed new SoilVoc terms: 90
- Category labels (SDG goals, OECD fields of science, HAL domains, INSPIRE themes, portal tags): 183
- Noise: 1645
- Not yet classified: 40370

## Cleaning steps applied (keyword parts)

- separators: 6272
- SoilVoc term inside keyword: 2781
- split: 1980
- language (keyword_translations.csv): 1666
- brackets: 1476
- numbering: 704
- language/synonym (manual decision): 228
- classification-code: 220
- language (SoilVoc translated labels): 217
- OECD field of science: 152
- HAL domain: 131
- portal/metadata tag: 59
- SDG goal: 53
- INSPIRE theme: 48
- wrapper: 41
- project-prefix: 11
- camelcase: 1

## Not yet classified, by record language (unique keywords)

- en: 22174
- und: 9251
- eng: 3942
- rus: 702
- ukr: 399
- fr: 398
- jpn: 323
- nl: 303

## Top 40 not yet classified keywords (by records)

- and fisheries (6031)
- carbon (981)
- ecosystem (912)
- soil study (381)
- charcoal (302)
- oryza (299)
- individual sample (287)
- conservation of natural resources (203)
- manure (197)
- environmental restoration and remediation (174)
- hydrogen ion concentration (170)
- composting (163)
- triticum (159)
- wetlands (155)
- poaceae (154)
- mining (154)
- ecosystems (147)
- specimen (134)
- plant diseases (128)
- terrestrial section (125)
- date (122)
- education (119)
- core (111)
- time (103)
- biota (101)
- air pollutants (101)
- rivers (98)
- minerals (97)
- agricultural irrigation (97)
- desert climate (94)
- agronomy and crop science (90)
- environmental and earth sciences (86)
- plant culture (85)
- microbial community (84)
- decomposition (83)
- denitrification (82)
- bodennutzbarkeit (82)
- oxidative stress (82)
- soil microbiome (81)
- herbicides (81)

## Files

- `subjects_cleaned.csv`: one row per subject part: original, cleaned, English, language, steps, status, SoilVoc concept
- `record_soilvoc.csv`: one row per record and SoilVoc concept

Language is the translation's language when one was used, otherwise the most common language of the subject's records.
