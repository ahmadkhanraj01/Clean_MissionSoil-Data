# 04 SoilVoc hierarchy

**Purpose:** give every SoilVoc concept a level and a tree parent, and draw the hierarchy.
BFS from the 17 top concepts, children visited in lowercase label order; the first parent reached is the tree
parent. 1,215 concepts are in the tree (levels 1 to 8); 249 lab procedure codes are detached (level empty);
131 concepts have several parents. Task 07 loads exactly this tree into the DB.

**Run (file-only, no DB), from the repo root:**
```bash
python Augmentation/SoilVoc/04_soilvoc_hierarchy/scripts/soilvoc_levels.py Augmentation/SoilVoc/vocab/SoilVoc.ttl Augmentation/SoilVoc/04_soilvoc_hierarchy/outputs/soilvoc_keywords_by_level.csv
python Augmentation/SoilVoc/04_soilvoc_hierarchy/scripts/soilvoc_json.py Augmentation/SoilVoc/04_soilvoc_hierarchy/outputs/soilvoc_keywords_by_level.csv Augmentation/SoilVoc/04_soilvoc_hierarchy/outputs/soilvoc_hierarchy.json
python Augmentation/SoilVoc/04_soilvoc_hierarchy/scripts/soilvoc_mermaid.py Augmentation/SoilVoc/04_soilvoc_hierarchy/outputs/soilvoc_keywords_by_level.csv Augmentation/SoilVoc/04_soilvoc_hierarchy/outputs/soilvoc_hierarchy.md
```

## Files

- `scripts/soilvoc_levels.py`: reads `SoilVoc.ttl`; writes `soilvoc_keywords_by_level.csv`.
- `scripts/soilvoc_json.py`: reads the levels CSV; writes the JSON tree.
- `scripts/soilvoc_mermaid.py`: reads the levels CSV; writes Mermaid diagrams (32 diagrams).
- `outputs/soilvoc_keywords_by_level.csv`: one row per concept: URI, label, level, parent.
- `outputs/soilvoc_hierarchy.json`: the tree with parents, children and descendants. The reference that task 07 checks the DB against.
- `outputs/soilvoc_hierarchy.md`: the Mermaid charts.

Used by: 05, 06, 07.
