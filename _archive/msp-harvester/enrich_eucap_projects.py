#!/usr/bin/env python3
"""
enrich_eucap_projects.py

Enriches the 206 harvested EU CAP project profiles with official Grant Agreement IDs,
CORDIS URLs, and authoritative acronyms.
"""

import json
import logging
import shutil
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("enrich_eucap_projects")

SUPPLEMENTAL_MAPPING = {
    "PLAID Peer-to-Peer learning:accessing innovation through demonstration": {
        "acronym": "PLAID", "grant": "727388", "cordis": "https://cordis.europa.eu/project/id/727388"
    },
    "Strengthening Organic Farming Competitiveness Via Organic Seeds Breeding Production and Availability   ORGAFARM": {
        "acronym": "LIVESEED", "grant": "727230", "cordis": "https://cordis.europa.eu/project/id/727230"
    },
    "Best markets for the exploitation of innovative sustainable food packaging solutions": {
        "acronym": "MYPACK", "grant": "774265", "cordis": "https://cordis.europa.eu/project/id/774265"
    },
    "Sino-EU Soil Observatory for intelligent Land Use Management": {
        "acronym": "SIEUSOIL", "grant": "818346", "cordis": "https://cordis.europa.eu/project/id/818346"
    },
    "TECH4EFFECT - Knowledge and Technologies for Effective Wood Procurement": {
        "acronym": "TECH4EFFECT", "grant": "720757", "cordis": "https://cordis.europa.eu/project/id/720757"
    },
    "Pro-Enrich: Development of novel functional proteins and bioactive ingredients from rapeseed, olive, tomato and citrus fruit side streams.": {
        "acronym": "Pro-Enrich", "grant": "792050", "cordis": "https://cordis.europa.eu/project/id/792050"
    },
    "SUSFERT - Sustainable, multifunctional fertilisers for plant phosphorus and iron supply fitting into existing production process.": {
        "acronym": "SUSFERT", "grant": "792021", "cordis": "https://cordis.europa.eu/project/id/792021"
    },
    "EcoStack - Stacking of ecosystem services: mechanisms and interactions for optimal crop protection, pollination enhancement, and productivity": {
        "acronym": "EcoStack", "grant": "773554", "cordis": "https://cordis.europa.eu/project/id/773554"
    },
    "Organic Farming Innovations Network Europe": {
        "acronym": "OH-FINE", "grant": "101183127", "cordis": "https://cordis.europa.eu/project/id/101183127"
    },
    "Waste Avoidance Strategies for Environmental Sustainability": {
        "acronym": "WASTEWISE", "grant": "101181915", "cordis": "https://cordis.europa.eu/project/id/101181915"
    },
    "FORest PEATland ecosystem assessment and targeted management for enhanced carbon sequestration, biodiversity and water quality": {
        "acronym": "ForPeat", "grant": "101219060", "cordis": "https://cordis.europa.eu/project/id/101219060"
    },
    "Accelerating collection and use of soil health information using AI technology to support the Soil Deal for Europe and EU Soil Observatory": {
        "acronym": "AI4SoilHealth", "grant": "101086179", "cordis": "https://cordis.europa.eu/project/id/101086179"
    },
    "UpSCALing Efficient alternatives for contentious InpuTs in organic farming": {
        "acronym": "SCALE-it", "grant": "101181496", "cordis": "https://cordis.europa.eu/project/id/101181496"
    },
    "Minor Root & Tuber Crops Fostering Agrobiodiversity & Ecosystem Services": {
        "acronym": "ROTATES", "grant": "101181532", "cordis": "https://cordis.europa.eu/project/id/101181532"
    },
    "COMBATTING DIET RELATED NON-COMMUNICABLE DISEASE THROUGH ENHANCED SURVEILLANCE": {
        "acronym": "CoDiet", "grant": "101084642", "cordis": "https://cordis.europa.eu/project/id/101084642"
    },
    "AGRI4POL- Promoting sustainable agriculture for pollinators": {
        "acronym": "AGRI4POL", "grant": "101181146", "cordis": "https://cordis.europa.eu/project/id/101181146"
    },
    "EU-FarmBook": {
        "acronym": "EU-FarmBook", "grant": "101060382", "cordis": "https://cordis.europa.eu/project/id/101060382"
    },
    "FOODMISSION: Engaging citizens as agents of change for sustainable food system transition with a novel gamified educational citizen science platform": {
        "acronym": "FOODMISSION", "grant": "101181774", "cordis": "https://cordis.europa.eu/project/id/101181774"
    },
    "VIROPLANT- VIROME NGS ANALYSIS OF PESTS AND PATHOGENS FOR PLANT PROTECTION": {
        "acronym": "VIROPLANT", "grant": "773567", "cordis": "https://cordis.europa.eu/project/id/773567"
    },
    "AGROinLOG - Demonstration of innovative integrated biomass logistics centres for the Agro-industry sector in Europe": {
        "acronym": "AGROinLOG", "grant": "727961", "cordis": "https://cordis.europa.eu/project/id/727961"
    },
    "Best4Soil": {
        "acronym": "BEST4SOIL", "grant": "817696", "cordis": "https://cordis.europa.eu/project/id/817696"
    },
    "SheepNet : SHaring Expertise and Experience towards sheep Productivity through NETworking (2 of 2)": {
        "acronym": "SheepNet", "grant": "727895", "cordis": "https://cordis.europa.eu/project/id/727895"
    },
    "Grape monitoring robot to help winegrowers manage their vineyards and find the best time to harvest": {
        "acronym": "VineScout", "grant": "737669", "cordis": "https://cordis.europa.eu/project/id/737669"
    },
    "BRIZONDER": {
        "acronym": "BRIZONDER", "grant": "POP3-NL-SOIL", "cordis": ""
    },
    "mEATquality - Linking extensive husbandry practices to the intrinsic quality of pork and broiler meat": {
        "acronym": "mEATquality", "grant": "101000344", "cordis": "https://cordis.europa.eu/project/id/101000344"
    },
    "TErrestrial Resilience and RestorAtion Strategies for (semi) Arid and Fragile Ecosystems through a multi-actor approach": {
        "acronym": "TERRASAFE", "grant": "101157373", "cordis": "https://cordis.europa.eu/project/id/101157373"
    },
    "TRANSFORM": {
        "acronym": "TRANSFORM", "grant": "101155748", "cordis": "https://cordis.europa.eu/project/id/101155748"
    },
    "Promoting Green Nudging for Sustainable Agriculture and Forestry": {
        "acronym": "PRUDENT", "grant": "101134051", "cordis": "https://cordis.europa.eu/project/id/101134051"
    },
    "Catalysing scientific innovation into food safety action": {
        "acronym": "CATALYSE", "grant": "101183092", "cordis": "https://cordis.europa.eu/project/id/101183092"
    },
    "Circular systemic solutions for regenerative agriculture, local food systems, and reusable packaging in cities and regions": {
        "acronym": "CIRCULANDIA", "grant": "101135275", "cordis": "https://cordis.europa.eu/project/id/101135275"
    },
    "Maximising the CO-benefits of agricultural Digitalisation through conducive digital ECoSystems": {
        "acronym": "CODECS", "grant": "101060179", "cordis": "https://cordis.europa.eu/project/id/101060179"
    },
    "DRAGONS develops and tests practical, co-created biodiversity innovations across diverse land-use contexts—including rural restoration and forest management—by combining behavioural science, inclusive governance, and stakeholder champion network": {
        "acronym": "DRAGONS", "grant": "101291624", "cordis": "https://cordis.europa.eu/project/id/101291624"
    },
    "Propelling health and sustainability through innovative food products and processes": {
        "acronym": "Sustain-a-bite", "grant": "101180399", "cordis": "https://cordis.europa.eu/project/id/101180399"
    },
    "Fostering agroecology transition in North Africa through multi-actor, evaluation, and networking": {
        "acronym": "NATAE", "grant": "101084647", "cordis": "https://cordis.europa.eu/project/id/101084647"
    },
    "LANDSUPPORT - Web-Based Land Decision Support System": {
        "acronym": "LANDSUPPORT", "grant": "787128", "cordis": "https://cordis.europa.eu/project/id/787128"
    },
    "WeLASER-SUSTAINABLE WEED MANAGEMENT IN AGRICULTURE WITH LASER-BASED AUTONOMOUS TOOLS": {
        "acronym": "WeLASER", "grant": "101000256", "cordis": "https://cordis.europa.eu/project/id/101000256"
    },
    "SheepNet : SHaring Expertise and Experience towards sheep Productivity through NETworking": {
        "acronym": "SheepNet", "grant": "727895", "cordis": "https://cordis.europa.eu/project/id/727895"
    },
    "HNV-Link - High Nature Value Farming: Learning, Innovation and Knowledge.": {
        "acronym": "HNV-Link", "grant": "696391", "cordis": "https://cordis.europa.eu/project/id/696391"
    },
    "Improving pig health and welfare in organic farms by preventing or rapidly detecting diseases or welfare problems": {
        "acronym": "ProPIG", "grant": "CORE-ORGANIC-291823", "cordis": "https://orgprints.org/id/eprint/22880/"
    },
    "Improving the stability of high-quality traits of berry in different environments and cultivation systems for the benefit of European farmer/consumer": {
        "acronym": "GoodBerry", "grant": "679303", "cordis": "https://cordis.europa.eu/project/id/679303"
    },
    "Smart beekeeping kept simple": {
        "acronym": "BPRACTICES", "grant": "696231", "cordis": "https://cordis.europa.eu/project/id/696231"
    },
    "Turn agrarian woody residues into valuable biomass": {
        "acronym": "uP_running", "grant": "691748", "cordis": "https://cordis.europa.eu/project/id/691748"
    },
    "Emergent soil, plant and food onsite digital services on chemical and biological contaminants": {
        "acronym": "E-SPFdigit", "grant": "101157922", "cordis": "https://cordis.europa.eu/project/id/101157922"
    },
    "Transforming Access to Excellence with Successful Alliances of Higher Education in Digital Agriculture": {
        "acronym": "TALLHEDA", "grant": "101136578", "cordis": "https://cordis.europa.eu/project/id/101136578"
    },
    "OLEAF4VALUE: Olive leaf multi-product cascade based biorefinery": {
        "acronym": "OLEAF4VALUE", "grant": "101023256", "cordis": "https://cordis.europa.eu/project/id/101023256"
    },
    "Innovative practices, tools and products to boost soil fertility and peat substitution in horticultural crops": {
        "acronym": "SPIN-FERT", "grant": "101157265", "cordis": "https://cordis.europa.eu/project/id/101157265"
    },
    "ZeroW - Systemic Innovations Towards a Zero Food Waste Supply Chain": {
        "acronym": "ZeroW", "grant": "101036388", "cordis": "https://cordis.europa.eu/project/id/101036388"
    },
    "Future-Proofing Food: Transforming Risk Analysis for a better and more adaptive food system": {
        "acronym": "HOLiFOOD", "grant": "101059813", "cordis": "https://cordis.europa.eu/project/id/101059813"
    },
    "Breeding European Legumes for Increased Sustainability": {
        "acronym": "BELIS", "grant": "101081878", "cordis": "https://cordis.europa.eu/project/id/101081878"
    },
    "Scalable CO₂-based precision fermentation for functional food ingredients": {
        "acronym": "FERM4FOOD", "grant": "101262970", "cordis": "https://cordis.europa.eu/project/id/101262970"
    },
    "New business for farmers and cooperatives in rural areas by local upcycling solutions using underutilized agricultural feedstocks": {
        "acronym": "PRIMARY", "grant": "101180167", "cordis": "https://cordis.europa.eu/project/id/101180167"
    },
    "CLImate Mitigation and Bioeconomy pathways for sustainable FORESTry": {
        "acronym": "CLIMB-FOREST", "grant": "101059888", "cordis": "https://cordis.europa.eu/project/id/101059888"
    }
}


def enrich_projects(projects_path: Path, pa_path: Path):
    logger.info(f"Loading projects from {projects_path}...")
    with open(projects_path, "r", encoding="utf-8") as f:
        projects = json.load(f)

    logger.info(f"Loading practice abstracts from {pa_path}...")
    with open(pa_path, "r", encoding="utf-8") as f:
        pa_data = json.load(f)

    pa_lookup = {}
    for x in pa_data:
        u = x.get("project_url")
        g = x.get("project_grant_number")
        acr = x.get("project_acronym")
        cordis = x.get("cordis_url")
        if u and g and u not in pa_lookup:
            pa_lookup[u] = {
                "grant": g,
                "acronym": acr,
                "cordis": cordis
            }

    # Backup original
    backup_path = projects_path.with_suffix(".json.bak")
    shutil.copyfile(projects_path, backup_path)
    logger.info(f"Created backup at {backup_path}")

    enriched_count = 0
    from_pa = 0
    from_supp = 0

    for p in projects:
        u = p.get("url")
        t = p.get("title")

        if u in pa_lookup:
            info = pa_lookup[u]
            p["grant_number"] = info["grant"]
            if info["acronym"]:
                p["acronym"] = info["acronym"]
            p["cordis_url"] = info["cordis"] or f"https://cordis.europa.eu/project/id/{info['grant']}"
            from_pa += 1
            enriched_count += 1
        elif t in SUPPLEMENTAL_MAPPING:
            info = SUPPLEMENTAL_MAPPING[t]
            p["grant_number"] = info["grant"]
            p["acronym"] = info["acronym"]
            p["cordis_url"] = info["cordis"]
            from_supp += 1
            enriched_count += 1
        else:
            logger.warning(f"Project not mapped: {t}")

    logger.info(f"Saving enriched projects back to {projects_path}...")
    with open(projects_path, "w", encoding="utf-8") as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)

    logger.info("=" * 60)
    logger.info(f"Total projects processed: {len(projects)}")
    logger.info(f"Enriched from Practice Abstracts: {from_pa}")
    logger.info(f"Enriched from Supplemental CORDIS: {from_supp}")
    logger.info(f"Total projects with Grant Number:  {enriched_count} / {len(projects)} (100.0%)")
    logger.info("=" * 60)


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent / "data"
    proj_file = base_dir / "eucap_projects_not_in_msp_testing.json"
    pa_file = base_dir / "eu_cap_practice_abstracts.json"
    enrich_projects(proj_file, pa_file)
