import os

# Base directory: Clean_MissionSoil-Data (repo root)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Data directory path
DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_PATH = os.path.join(DATA_DIR, "Oct22_solrData.json")

SEARCH_URL = "https://catalogue.soilwise-he.eu/search-api/solr/search"
CATALOGUE_ITEMS_URL = "https://repository.soilwise-he.eu/cat/collections/metadata:main/items"


# ==============================================================================
# CONFIGURATION SETTINGS FOR FETCHING RECORDS
# ==============================================================================
# List of record types to fetch one by one in a loop.
# Comment out or add types as needed.
RECORD_TYPES = [
    "Dataset",
    "Journal Article",
    "Report",
    "Service",
    "Project",
    "Software",
    "Education and Training Material",
    "Best Practices",
    "Policy Document",
    "Scientific",
    "Interview",
    "Conference Proceeding",
    "Computational Notebook",
    "Text",
    "Data Paper",
    # "Other",  # (Already done)
]

# Request parameters
PAGE_LIMIT = 50       # Max supported by server is 50
REQUEST_DELAY = 0.2   # Seconds to wait between pagination requests
# ==============================================================================
