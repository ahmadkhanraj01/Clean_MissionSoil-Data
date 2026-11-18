#!/usr/bin/env python3
"""
Enrich EU CAP Practice Abstracts JSON dataset.
Resolves missing project acronyms, grant numbers, project identifiers, and CORDIS URLs
for records where EU CAP Network did not display them in the HTML markup.
"""
# --- Clean_MissionSoil-Data bootstrap: repo root on sys.path, .env loaded by common.db ---
import sys as _sys, pathlib as _pl
_ROOT = next(p for p in _pl.Path(__file__).resolve().parents if (p / "common" / "db.py").is_file())
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
from common.db import DATA_DIR, get_connection, db_config  # noqa: E402,F401  (loads .env)
# --------------------------------------------------------------------------------------------


import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("enrich_eucap_practice_abstracts")

# Mapping for projects that had missing acronym and grant number
TITLE_BASED_ENRICHMENT: Dict[str, Dict[str, str]] = {
    "Effective Management of Pests and Harmful Alien Species - Integrated Solutions (EMPHASIS)": {
        "acronym": "EMPHASIS",
        "grant": "634179",
        "cordis": "https://cordis.europa.eu/project/id/634179"
    },
    "Accelerating Innovative practices for Spraying Equipment, Training and Advising in European agriculture through  mobilization  Agricultural Knowledge  Innovation Systems": {
        "acronym": "INNOSETA",
        "grant": "773864",
        "cordis": "https://cordis.europa.eu/project/id/773864"
    },
    "Innovation for Sustainable Sheep and Goat Production in Europe (iSAGE)": {
        "acronym": "iSAGE",
        "grant": "679302",
        "cordis": "https://cordis.europa.eu/project/id/679302"
    },
    "SuperPests 'Innovative tools for rational control of the most difficult-to manage pests (super pests) and the diseases they transmit'": {
        "acronym": "SuperPests",
        "grant": "773902",
        "cordis": "https://cordis.europa.eu/project/id/773902"
    },
    "HealthyFoodAfrica - Improving nutrition in Africa by strengthening the diversity, sustainability, resilience and connectivity of food systems": {
        "acronym": "HealthyFoodAfrica",
        "grant": "862776",
        "cordis": "https://cordis.europa.eu/project/id/862776"
    },
    "Field -testing and demonstration of digital and space based technologies with agroecological and organic practices in systemic innovation": {
        "acronym": "PestNu",
        "grant": "101037128",
        "cordis": "https://cordis.europa.eu/project/id/101037128"
    },
    "FoodE": {
        "acronym": "FoodE",
        "grant": "862663",
        "cordis": "https://cordis.europa.eu/project/id/862663"
    },
    "Mountain Valorisation Through Interconnectedness And Green Growth": {
        "acronym": "MOVING",
        "grant": "862739",
        "cordis": "https://cordis.europa.eu/project/id/862739"
    },
    "InnoVar: Next generation variety testing for improved cropping on European farmland": {
        "acronym": "InnoVar",
        "grant": "818144",
        "cordis": "https://cordis.europa.eu/project/id/818144"
    },
    "Safeguard - Safeguarding European wild pollinators": {
        "acronym": "Safeguard",
        "grant": "101003476",
        "cordis": "https://cordis.europa.eu/project/id/101003476"
    },
    "No Agricultural-Waste (NoAW)Innovative approaches to turn agricultural waste into ecological and economic assets": {
        "acronym": "NoAW",
        "grant": "688338",
        "cordis": "https://cordis.europa.eu/project/id/688338"
    },
    "SoilCare - Soil Care for profitable and sustainable crop production in Europe": {
        "acronym": "SoilCare",
        "grant": "677407",
        "cordis": "https://cordis.europa.eu/project/id/677407"
    },
    "Improving the stability of high-quality traits of berry indifferent environments and cultivation systems for thebenefit of European farmer/consumer": {
        "acronym": "GoodBerry",
        "grant": "679303",
        "cordis": "https://cordis.europa.eu/project/id/679303"
    },
    "MycoKey - Integrated and innovative key actions for mycotoxin management in the food and feed chain": {
        "acronym": "MycoKey",
        "grant": "678781",
        "cordis": "https://cordis.europa.eu/project/id/678781"
    },
    "Optimising bio-based fertilisers in agriculture - Providing a knowledge basis for new policies (LEX4BIO), Optimising the use of bio-based fertilizers in the EU": {
        "acronym": "LEX4BIO",
        "grant": "818309",
        "cordis": "https://cordis.europa.eu/project/id/818309"
    },
    "Integrated on-farm Aquaponics system for co-production of fish, halophyte vegetables, bioactive compounds and bioenergy": {
        "acronym": "AQUACOMBINE",
        "grant": "862834",
        "cordis": "https://cordis.europa.eu/project/id/862834"
    },
    "Giving Beekeeping Guidance by cOmputatiOnal-assisted Decision making (B-GOOD)": {
        "acronym": "B-GOOD",
        "grant": "817669",
        "cordis": "https://cordis.europa.eu/project/id/817669"
    },
    "Target-specific RNA-based bioprotectants for sustainable crop production in a changing climate": {
        "acronym": "BioProtect",
        "grant": "SusCrop-ERA-NET",
        "cordis": ""
    },
    "Transition paths to sUstainable legume-based systems in Europe (TRUE)": {
        "acronym": "TRUE",
        "grant": "727973",
        "cordis": "https://cordis.europa.eu/project/id/727973"
    },
    "IoF2020 - Internet of Food and Farm 2020": {
        "acronym": "IoF2020",
        "grant": "731884",
        "cordis": "https://cordis.europa.eu/project/id/731884"
    },
    "Best Practice Hens - Pilot Project on Best Practices for Alternative Egg Production Systems": {
        "acronym": "Best Practice Hens",
        "grant": "PP-1-2-2020",
        "cordis": ""
    },
    "Innovative concepts and technologies for ECOlogically sustainable NUTRIent management in agriculture aiming to prevent, mitigate and eliminate pollution in soils, water and air": {
        "acronym": "ECONUTRI",
        "grant": "101081858",
        "cordis": "https://cordis.europa.eu/project/id/101081858"
    },
    "Sustainable Plant Protection Transition: A Global Health Appoach (SPRINT)": {
        "acronym": "SPRINT",
        "grant": "862555",
        "cordis": "https://cordis.europa.eu/project/id/862555"
    },
    "Confronting Obesity: Co-creating policy with youth": {
        "acronym": "CO-CREATE",
        "grant": "774210",
        "cordis": "https://cordis.europa.eu/project/id/774210"
    },
    "FoodLAND - Food and Local, Agricultural and Nutritional Diversity": {
        "acronym": "FoodLAND",
        "grant": "862802",
        "cordis": "https://cordis.europa.eu/project/id/862802"
    }
}

# Mapping for projects that had an acronym but were missing grant number
ACRONYM_BASED_ENRICHMENT: Dict[str, Dict[str, str]] = {
    "ROSEWOOD4": {
        "grant": "862681",
        "cordis": "https://cordis.europa.eu/project/id/862681"
    },
    "LEGVALUE": {
        "grant": "727672",
        "cordis": "https://cordis.europa.eu/project/id/727672"
    },
    "MAGIC": {
        "grant": "727698",
        "cordis": "https://cordis.europa.eu/project/id/727698"
    },
    "PANACEA": {
        "grant": "773501",
        "cordis": "https://cordis.europa.eu/project/id/773501"
    },
    "MUSA": {
        "grant": "727624",
        "cordis": "https://cordis.europa.eu/project/id/727624"
    },
    "ROBUST": {
        "grant": "727988",
        "cordis": "https://cordis.europa.eu/project/id/727988"
    },
    "FUSILLI": {
        "grant": "101000717",
        "cordis": "https://cordis.europa.eu/project/id/101000717"
    },
    "BOND": {
        "grant": "774208",
        "cordis": "https://cordis.europa.eu/project/id/774208"
    },
    "PAPILLONS": {
        "grant": "101000249",
        "cordis": "https://cordis.europa.eu/project/id/101000249"
    },
    "STOP": {
        "grant": "774548",
        "cordis": "https://cordis.europa.eu/project/id/774548"
    },
    "AGRIFORVALOR": {
        "grant": "696394",
        "cordis": "https://cordis.europa.eu/project/id/696394"
    },
    "OPTAIN": {
        "grant": "862756",
        "cordis": "https://cordis.europa.eu/project/id/862756"
    },
    "NEXTFOOD": {
        "grant": "771738",
        "cordis": "https://cordis.europa.eu/project/id/771738"
    },
    "ENOUGH": {
        "grant": "101036588",
        "cordis": "https://cordis.europa.eu/project/id/101036588"
    },
    "UPSCALE": {
        "grant": "861998",
        "cordis": "https://cordis.europa.eu/project/id/861998"
    },
    "CAMELINA": {
        "grant": "PRIMA-4CE-MED",
        "cordis": "https://4cemed.eu"
    },
    "NovIGRain": {
        "grant": "101000663",
        "cordis": "https://cordis.europa.eu/project/id/101000663"
    },
    "MINAGRIS": {
        "grant": "101000407",
        "cordis": "https://cordis.europa.eu/project/id/101000407"
    },
    "UNTWIST": {
        "grant": "862524",
        "cordis": "https://cordis.europa.eu/project/id/862524"
    },
    "SUREFISH": {
        "grant": "PRIMA-1933",
        "cordis": "https://surefish.eu"
    },
    "SUSBIND": {
        "grant": "792061",
        "cordis": "https://cordis.europa.eu/project/id/792061"
    },
    "SHEALTHY": {
        "grant": "817936",
        "cordis": "https://cordis.europa.eu/project/id/817936"
    },
    "CAPSELLA": {
        "grant": "688813",
        "cordis": "https://cordis.europa.eu/project/id/688813"
    },
    "BIOFECTOR": {
        "grant": "312117",
        "cordis": "https://cordis.europa.eu/project/id/312117"
    },
    "SIMWOOD": {
        "grant": "613762",
        "cordis": "https://cordis.europa.eu/project/id/613762"
    },
    "FOWARIM": {
        "grant": "692103",
        "cordis": "https://cordis.europa.eu/project/id/692103"
    }
}


def enrich_dataset(file_path: Path, backup: bool = True) -> Tuple[int, int, int]:
    """
    Enriches the dataset in-place.
    Returns (total_records, enriched_both_count, enriched_grant_count).
    """
    logger.info(f"Loading data from {file_path}...")
    with open(file_path, "r", encoding="utf-8") as f:
        records: List[Dict[str, Any]] = json.load(f)

    if backup:
        backup_path = file_path.with_suffix(".json.bak")
        logger.info(f"Creating backup at {backup_path}...")
        shutil.copyfile(file_path, backup_path)

    enriched_both_count = 0
    enriched_grant_count = 0

    for rec in records:
        title = (rec.get("project_title") or "").strip()
        acronym = (rec.get("project_acronym") or "").strip()
        grant = (rec.get("project_grant_number") or "").strip()

        # Case 1: Missing both acronym and grant
        if not acronym and not grant:
            info = TITLE_BASED_ENRICHMENT.get(title)
            if info:
                rec["project_acronym"] = info["acronym"]
                rec["project_grant_number"] = info["grant"]
                rec["project_identifier"] = info["grant"]
                if info.get("cordis") and not rec.get("cordis_url"):
                    rec["cordis_url"] = info["cordis"]
                enriched_both_count += 1
            else:
                logger.warning(f"No enrichment found for missing project title: {title}")

        # Case 2: Has acronym but missing grant
        elif acronym and not grant:
            info = ACRONYM_BASED_ENRICHMENT.get(acronym)
            if info:
                rec["project_grant_number"] = info["grant"]
                rec["project_identifier"] = info["grant"]
                if info.get("cordis") and not rec.get("cordis_url"):
                    rec["cordis_url"] = info["cordis"]
                enriched_grant_count += 1

    logger.info(f"Saving enriched dataset to {file_path}...")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    return len(records), enriched_both_count, enriched_grant_count


def main():
    parser = argparse.ArgumentParser(description="Enrich EU CAP Practice Abstracts JSON dataset")
    parser.add_argument(
        "--file",
        type=str,
        default=str(DATA_DIR / "eu_cap_practice_abstracts.json"),
        help="Path to JSON file to enrich"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating a backup copy"
    )
    args = parser.parse_args()

    target_file = Path(args.file).resolve()
    if not target_file.exists():
        logger.error(f"Target file does not exist: {target_file}")
        sys.exit(1)

    total, both_cnt, grant_cnt = enrich_dataset(target_file, backup=not args.no_backup)
    logger.info("=" * 60)
    logger.info(f"Successfully processed {total} records.")
    logger.info(f"Enriched records missing both acronym & grant: {both_cnt}")
    logger.info(f"Enriched records missing grant only:          {grant_cnt}")
    logger.info(f"Total enriched records:                        {both_cnt + grant_cnt}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
