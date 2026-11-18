"""One place for every path used by the SoilVoc task scripts.

Copied from soil-vocabs/tasks/paths.py. In Clean_MissionSoil-Data:
  ROOT     = the repo root (the folder with common/db.py and .env)
  SOILVOC  = Augmentation/SoilVoc (this folder: tasks 01, 03-07 + curation; task 02, the LLM
             extraction, was not used and is not copied)
  VOCAB    = Augmentation/SoilVoc/vocab (SoilVoc.ttl, SoilVoc_concepts.csv, ontovocabs/, uk2us.py,
             copied from the root of the soil-vocabs repo)

Scripts do:  import sys; from pathlib import Path
             sys.path.insert(0, next(str(p) for p in Path(__file__).resolve().parents if (p / "paths.py").exists()))
             from paths import ROOT, ...
"""
import os
from pathlib import Path

# Same switch as common/db.py: MSP_READ_ONLY=1 makes every PostgreSQL session of these
# scripts read-only (they connect with psycopg2 directly, not through common.db).
if os.environ.get("MSP_READ_ONLY", "").strip().lower() in ("1", "true", "yes", "on"):
    _opt = "-c default_transaction_read_only=on"
    if _opt not in os.environ.get("PGOPTIONS", ""):
        os.environ["PGOPTIONS"] = (os.environ.get("PGOPTIONS", "") + " " + _opt).strip()

TASKS = SOILVOC = Path(__file__).resolve().parent            # Augmentation/SoilVoc
ROOT = next(p for p in SOILVOC.parents if (p / "common" / "db.py").is_file())   # repo root (holds .env)
ENV = ROOT / ".env"

VOCAB = SOILVOC / "vocab"
SOILVOC_TTL = VOCAB / "SoilVoc.ttl"
SOILVOC_CSV = VOCAB / "SoilVoc_concepts.csv"
ONTOVOCABS = VOCAB / "ontovocabs"
UK2US = VOCAB / "uk2us.py"

CURATION = SOILVOC / "curation"          # hand-edited inputs shared by several tasks

T01 = SOILVOC / "01_subjects_vs_soilvoc"
T03 = SOILVOC / "03_stage_vs_dev"
T04 = SOILVOC / "04_soilvoc_hierarchy"
T05 = SOILVOC / "05_soilvoc_db_coverage"
T06 = SOILVOC / "06_keyword_cleaning"
T07 = SOILVOC / "07_populate_soilvoc_db"

T01_OUT, T03_OUT, T04_OUT = (t / "outputs" for t in (T01, T03, T04))
T05_OUT, T06_OUT, T07_OUT = (t / "outputs" for t in (T05, T06, T07))
T07_DOCS = T07 / "docs"
CMP_SCRIPT = T01 / "scripts" / "compare_subjects_to_soilvoc.py"   # imported as a helper by tasks 03 and 06
