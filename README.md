# JPC ArchivesSpace AV Tools

Python scripts for managing audiovisual archival objects in ArchivesSpace for the Johnson Publishing Company collection.

## Overview

This repository contains two scripts that work together for the Johnson Publishing Company Archive (JPCA) audiovisual collection processing. They create and update records in ArchivesSpace and support the ingest workflow of assets to the Smithsonian DAMS.

1. **aspace_csv_import** — Creates item-level archival objects from CSV metadata
2. **aspace_rename_directories** — Processes digitized video files, extracts runtime, and updates ArchivesSpace records

## Directory Structure

```
aspace_jpc_av/
├── README.md                     # This file
├── creds_template.py             # Credential template (see Setup below)
├── creds.py                      # Your local credentials (gitignored, you create this)
├── requirements.txt              # Python dependencies
│
├── aspace_csv_import/
│   ├── aspace_csv_import.py      # Main import script
│   ├── check_extent_types.py     # Utility to validate extent types against ASpace
│   ├── csv_utils.py              # CSV helper functions
│   ├── README.md                 # Detailed usage documentation
│   └── docs/
│       ├── CSV_TO_ASPACE_MAPPING.md   # Field mapping reference
│       ├── EXAMPLE_MAPPING.md         # Example CSV to JSON mappings
│       ├── POTENTIAL_MAPPINGS.md      # Unmapped fields for future use
│       ├── WORKFLOW.md                # Process documentation
│       └── archive/                   # Legacy reference files
│           ├── config_sample.py
│           └── run_examples.sh
│
└── aspace_rename_directories/
    ├── aspace-rename-directories.py  # Main processing script
    └── README.md                     # Detailed usage documentation
```

### File Descriptions

More detailed descriptions of each file and usage in directory-specific README.md files.

| File | User Interaction | Description |
|------|------------------|-------------|
| `creds_template.py` | Reference only | Template showing required credential format. Do not edit directly. |
| `creds.py` | User creates/edits | Your local credentials file. You create this from the template. |
| `requirements.txt` | One-time setup | Python package dependencies. Run `pip install -r requirements.txt` once. |
| `aspace_csv_import.py` | Run via command line | Main script for importing CSV metadata to ArchivesSpace. |
| `check_extent_types.py` | Run via command line | Utility to check valid extent types in your ASpace instance. |
| `csv_utils.py` | Backend | Helper functions used by the import script. |
| `docs/*.md` | Reference | Documentation for field mappings and workflows. |
| `aspace-rename-directories.py` | Run via command line | Main script for processing video directories. |

### Logs and Reports

Both scripts generate logs and reports:

- **aspace_csv_import** creates logs and reports in `~/aspace_import_reports/`
- **aspace_rename_directories** outputs to the terminal (use `--verbose` for detailed logging)

Log files include timestamps, actions taken, and any errors encountered.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

**Important:** The repository does not contain a `creds.py` file for security reasons. You must create one locally.

After cloning or pulling this repository to your local machine:

1. Open the `creds_template.py` file to see the required format
2. Create a **new file** called `creds.py` in the same directory (the repo root)
3. Copy the contents of `creds_template.py` into your new `creds.py` file
4. Fill in your actual credentials in `creds.py`

**Do NOT edit `creds_template.py` directly.** If you accidentally commit your credentials to GitHub, they will be exposed publicly. The `creds.py` file is listed in `.gitignore` so it will not be tracked or uploaded.

Your `creds.py` should look like this (with your actual values):

```python
baseURL = "https://your-aspace-api-url.org"
user = "your_username"
password = "your_password"
repo_id = "your_repository_id"
resource_id = "your_resource_id"
```

Ask your ArchivesSpace administrator if you don't know these values.

## Scripts

### aspace_csv_import

Creates archival objects in ArchivesSpace from CSV metadata. Handles titles, dates, extents, notes, and container instances.

```bash
cd aspace_csv_import
python3 aspace_csv_import.py -f data.csv --dry-run
```

See [aspace_csv_import/README.md](aspace_csv_import/README.md) for full documentation.

### aspace_rename_directories

Processes digitized video directories to extract runtime from MKV files, update ArchivesSpace records with duration and physical details, and rename directories with ref_ids.

```bash
cd aspace_rename_directories
python3 aspace-rename-directories.py -d /path/to/videos --dry-run
```

See [aspace_rename_directories/README.md](aspace_rename_directories/README.md) for full documentation.

## Workflow

Typical usage order:

1. **CSV Import** — Create archival objects from catalog metadata
2. **Directory Processing** — After digitization, extract runtime and update records

## Environments

Both scripts support sandbox and production environments. Update your local `creds.py` with the appropriate `baseURL` and `resource_id` for your target environment.