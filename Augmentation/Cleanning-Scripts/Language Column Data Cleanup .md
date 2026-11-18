# Language Column Data Cleanup Report

This document outlines the SQL queries used to explore, standardize, and permanently update the messy data found within the `language` column of the `public.records` table.

## 1. Initial Data Exploration
Before cleaning the data, it is important to understand the scope of the inconsistencies. 

**Function:** This query generates a simple list of all unique values currently existing in the `language` column.
```sql
SELECT DISTINCT language
FROM public.records;
```

**Function:** This query lists each unique value alongside its frequency, sorted from most frequent to least frequent. This is useful for identifying the most common anomalies (like 'und' or blank strings).
```sql
SELECT language, COUNT(*) AS count
FROM public.records
GROUP BY language
ORDER BY count DESC;
```

## 2. Filtering Out Anomalies (View Only)
Once data quality issues (like URLs, hashes, and literal 'null' strings) were identified, we created a query to view the data without the noise.

**Function:** This query returns the counts of languages while actively filtering out nulls, empty spaces, the literal string 'null', and long erroneous strings (like hashes or URLs) by checking the character length.
```sql
SELECT language, COUNT(*) AS count
FROM public.records
WHERE language IS NOT NULL 
  AND TRIM(language) != ''
  AND LOWER(language) != 'null'
  AND LENGTH(language) <= 15
GROUP BY language
ORDER BY count DESC;
```

## 3. Testing the Data Transformation
To safely map the inconsistent values (like 2-letter codes, 3-letter codes, and full words) to standard names, we built a `CASE` statement. 

**Function:** This query acts as a translation layer. It groups the messy data into clean, standardized buckets and counts them to ensure the logic works correctly before modifying the actual database. It safely catches unexpected values in an 'Unknown' bucket.
```sql
SELECT 
  CASE
     WHEN LOWER(language) IN ('en', 'eng', 'enc') THEN 'English'
     WHEN LOWER(language) IN ('fr', 'fra') THEN 'French'
     WHEN LOWER(language) = 'sk' THEN 'Slovak'
     WHEN LOWER(language) = 'nn' THEN 'Norwegian Nynorsk'
     WHEN LOWER(language) = 'bg' THEN 'Bulgarian'
     WHEN LOWER(language) = 'fi' THEN 'Finnish'
     WHEN LOWER(language) IN ('cat', 'ca', 'http://publications.europa.eu/resource/authority/language/cat') THEN 'Catalan'
     WHEN LOWER(language) = 'glg' THEN 'Galician'
     WHEN LOWER(language) = 'hr' THEN 'Croatian'
     WHEN LOWER(language) = 'cs' THEN 'Czech'
     WHEN LOWER(language) = 'lt' THEN 'Lithuanian'
     WHEN LOWER(language) IN ('sv', 'swedish') THEN 'Swedish'
     WHEN LOWER(language) = 'ro' THEN 'Romanian'
     WHEN LOWER(language) = 'de' THEN 'German'
     WHEN LOWER(language) = 'nl' THEN 'Dutch'
     WHEN LOWER(language) = 'sl' THEN 'Slovenian'
     WHEN LOWER(language) = 'et' THEN 'Estonian'
     WHEN LOWER(language) = 'ar' THEN 'Arabic'
     WHEN LOWER(language) = 'pt' THEN 'Portuguese'
     WHEN LOWER(language) = 'hu' THEN 'Hungarian'
     WHEN LOWER(language) = 'el' THEN 'Greek'
     WHEN LOWER(language) = 'pl' THEN 'Polish'
     WHEN LOWER(language) = 'it' THEN 'Italian'
     WHEN LOWER(language) = 'lv' THEN 'Latvian'
     WHEN LOWER(language) = 'es' THEN 'Spanish'
     WHEN LOWER(language) = 'da' THEN 'Danish'
     WHEN LOWER(language) = 'bzj' THEN 'Belize Kriol'
     WHEN LOWER(language) = 'ekk' THEN 'Estonian (Standard)'
     WHEN LOWER(language) IN ('und', 'indeterminado') THEN 'Undetermined'
     WHEN LOWER(language) = 'other' THEN 'Other'
     WHEN language IS NULL OR TRIM(language) = '' OR LOWER(language) = 'null' THEN 'Unknown'
     ELSE 'Unknown'
  END AS clean_language,
  COUNT(*) AS count
FROM public.records
GROUP BY clean_language
ORDER BY count DESC;
```

## 4. Applying Permanent Fixes
After verifying that the `CASE` statement accurately translated the raw data, the logic was applied directly to the table.

**Function:** This `UPDATE` statement permanently replaces the existing data in the `language` column with the standardized names defined in the `CASE` statement. **Note: This alters the raw table data.**
```sql
UPDATE public.records
SET language = CASE
   WHEN LOWER(language) IN ('en', 'eng', 'enc') THEN 'English'
   WHEN LOWER(language) IN ('fr', 'fra') THEN 'French'
   WHEN LOWER(language) = 'sk' THEN 'Slovak'
   WHEN LOWER(language) = 'nn' THEN 'Norwegian Nynorsk'
   WHEN LOWER(language) = 'bg' THEN 'Bulgarian'
   WHEN LOWER(language) = 'fi' THEN 'Finnish'
   WHEN LOWER(language) IN ('cat', 'ca', 'http://publications.europa.eu/resource/authority/language/cat') THEN 'Catalan'
   WHEN LOWER(language) = 'glg' THEN 'Galician'
   WHEN LOWER(language) = 'hr' THEN 'Croatian'
   WHEN LOWER(language) = 'cs' THEN 'Czech'
   WHEN LOWER(language) = 'lt' THEN 'Lithuanian'
   WHEN LOWER(language) IN ('sv', 'swedish') THEN 'Swedish'
   WHEN LOWER(language) = 'ro' THEN 'Romanian'
   WHEN LOWER(language) = 'de' THEN 'German'
   WHEN LOWER(language) = 'nl' THEN 'Dutch'
   WHEN LOWER(language) = 'sl' THEN 'Slovenian'
   WHEN LOWER(language) = 'et' THEN 'Estonian'
   WHEN LOWER(language) = 'ar' THEN 'Arabic'
   WHEN LOWER(language) = 'pt' THEN 'Portuguese'
   WHEN LOWER(language) = 'hu' THEN 'Hungarian'
   WHEN LOWER(language) = 'el' THEN 'Greek'
   WHEN LOWER(language) = 'pl' THEN 'Polish'
   WHEN LOWER(language) = 'it' THEN 'Italian'
   WHEN LOWER(language) = 'lv' THEN 'Latvian'
   WHEN LOWER(language) = 'es' THEN 'Spanish'
   WHEN LOWER(language) = 'da' THEN 'Danish'
   WHEN LOWER(language) = 'bzj' THEN 'Belize Kriol'
   WHEN LOWER(language) = 'ekk' THEN 'Estonian (Standard)'
   WHEN LOWER(language) IN ('und', 'indeterminado') THEN 'Undetermined'
   WHEN LOWER(language) = 'other' THEN 'Other'
   WHEN language IS NULL OR TRIM(language) = '' OR LOWER(language) = 'null' THEN 'Unknown'
   ELSE 'Unknown'
END;
```