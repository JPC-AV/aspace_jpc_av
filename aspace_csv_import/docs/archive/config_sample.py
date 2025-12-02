# ArchivesSpace CSV Import Configuration
# Copy this file to 'config.py' and customize for your needs

# ==============================
# ARCHIVESSPACE CONNECTION
# ==============================
ASPACE_URL = "https://api-aspace.jpcarchive.org"
ASPACE_USERNAME = "your_username"  # REPLACE
ASPACE_PASSWORD = "your_password"  # REPLACE

# ==============================
# TARGET LOCATION
# ==============================
REPO_ID = "2"          # Repository ID
RESOURCE_ID = "7"      # Resource ID where items will be created

# ==============================
# PROCESSING OPTIONS
# ==============================
DRY_RUN = True         # Set to False to actually create records
BATCH_SIZE = 10        # Number of records to process before pausing
RETRY_ATTEMPTS = 3     # Number of retries for failed API calls
RETRY_DELAY = 2        # Seconds between retries

# ==============================
# CSV COLUMN MAPPING
# ==============================
# Map your CSV columns to script variables
CSV_COLUMNS = {
    "catalog_number": "CATALOG_NUMBER",
    "title": "TITLE",
    "creation_date": "Creation or Recording Date",
    "edit_date": "Edit Date",
    "broadcast_date": "Broadcast Date",
    "season": "EJS Season",
    "episode": "EJS Episode",
    "format": "Original Format",
    "parent_ref_id": "ASpace Parent RefID",
    "duration": "Content TRT",
    "description": "DESCRIPTION",
    "media_type": "ORIGINAL_MEDIA_TYPE"
}

# ==============================
# DEFAULT VALUES
# ==============================
DEFAULTS = {
    "level": "item",                    # Archival object level
    "publish": True,                    # Publish by default
    "extent_portion": "whole",          # Default extent portion
    "extent_number": "1",               # Default extent number
    "extent_type": "videocassettes",   # Default extent type
    "instance_type": "moving_images"    # Default instance type
}

# ==============================
# FIELD VALIDATION RULES
# ==============================
REQUIRED_FIELDS = [
    "CATALOG_NUMBER"  # Fields that must have values
]

UNIQUE_FIELDS = [
    "CATALOG_NUMBER"  # Fields that must be unique in ArchivesSpace
]

# ==============================
# DATE FORMATS
# ==============================
# Formats to try when parsing dates from CSV
DATE_FORMATS = [
    "%m/%d/%Y",  # 8/1/1982
    "%m/%d/%y",  # 8/1/82
    "%Y-%m-%d",  # 2023-08-01
    "%Y/%m/%d",  # 2023/08/01
    "%d/%m/%Y"   # 01/08/2023 (European)
]