# JPC ArchivesSpace AV Tools

Python scripts for managing audiovisual archival objects in ArchivesSpace for the Johnson Publishing Company collection.

## Overview

This repository contains the tools for the Johnson Publishing Company Archive (JPCA) audiovisual collection processing. They create, update, export and check records in ArchivesSpace and support the ingest workflow of assets to the Smithsonian DAMS.

1. **aspace_csv_import** — Creates and updates item-level archival objects from CSV metadata
2. **aspace_csv_export** — Exports AV records to an import-shaped CSV (round trip / audit), optionally checking MADS
3. **check_mads** — Reports which items are live in MADS, the public DAMS delivery
4. **aspace_rename_directories** — Processes digitized video files, extracts runtime, and updates ArchivesSpace records

## Directory Structure

```
aspace_jpc_av/
├── README.md                     # This file
├── aspace_client.py              # Shared ArchivesSpace API client (used by both scripts)
├── creds_template.py             # Credential template (see Setup below)
├── creds.py                      # Your local credentials (gitignored, you create this)
├── requirements.txt              # Python dependencies
│
├── aspace_csv_import/
│   ├── aspace_csv_import.py      # Main import script
│   ├── aspace_csv_export.py      # Export AV records to an import-shaped CSV (round trip)
│   ├── check_mads.py             # Check which items are live in MADS (public DAMS delivery)
│   ├── check_extent_types.py     # Utility to validate extent types against ASpace
│   ├── csv_utils.py              # CSV validation and parent checks
│   ├── sheet_rules.py            # The sheet contract: column names + validation rules (imported, never run)
│   ├── README.md                 # Detailed usage documentation
│   └── docs/
│       ├── CSV_TO_ASPACE_MAPPING.md   # Field mapping reference
│       ├── EXAMPLE_MAPPING.md         # Example CSV to JSON mappings
│       └── POTENTIAL_MAPPINGS.md      # Unmapped fields for future use
│
└── aspace_rename_directories/
    ├── aspace-rename-directories.py  # Main processing script
    └── README.md                     # Detailed usage documentation
```

### File Descriptions

More detailed descriptions of each file and usage in directory-specific README.md files.

| File | User Interaction | Description |
|------|------------------|-------------|
| `aspace_client.py` | Backend | Shared API client: credentials loading, one keep-alive session, login/logout, retries, verified lookups, and scope-locked writes. Both main scripts build on it. |
| `creds_template.py` | Reference only | Template showing required credential format. Do not edit directly. |
| `creds.py` | User creates/edits | Your local credentials file. You create this from the template. |
| `requirements.txt` | One-time setup | Python package dependencies. Run `pip install -r requirements.txt` once. |
| `aspace_csv_import.py` | Run via command line | Main script for importing CSV metadata to ArchivesSpace. |
| `aspace_csv_export.py` | Run via command line | Exports AV records to an import-shaped CSV in tree order with hierarchy and audit columns; `--mads-live` checks MADS. |
| `check_mads.py` | Run via command line | Checks which catalog numbers are live in MADS (public URLs only). |
| `check_extent_types.py` | Run via command line | Utility to check valid extent types in your ASpace instance. |
| `csv_utils.py` | Run via command line | Validates a CSV and checks parent ref_ids before import. |
| `sheet_rules.py` | Backend | The sheet contract: column names and the validation rules every tool applies. |
| `docs/*.md` | Reference | Field-mapping contract, a worked example, and the unmapped-column analysis. |
| `aspace-rename-directories.py` | Run via command line | Main script for processing video directories. |

### Logs and Reports

Every tool writes its reports to its own folder:

- **aspace_csv_import** — `~/aspace_import_reports/`: log, CSV and JSON receipts, and `import_records_*.json` (the records as stored after the run)
- **aspace_csv_export** — `~/aspace_import_reports/` (export CSVs)
- **check_mads** — `~/aspace_mads_reports/`
- **aspace_rename_directories** — `~/aspace_rename_reports/`

Setting `logs_dir` in `creds.py` moves them all under one parent, each tool in its own subfolder (`import_reports/`, `export_reports/`, `mads_reports/`, `rename_reports/`). Log files include the exact command run, timestamps, actions taken, and any errors encountered.

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

Your `creds.py` declares one entry per ArchivesSpace instance you can access:

```python
environments = {
    "sandbox": {
        "baseURL": "https://your-sandbox-api-url.org",
        "user": "your_username",
        "password": "your_password",
        "repo_id": "your_repository_id",      # differs between instances!
        "resource_id": "your_resource_id",    # differs between instances!
        "staff_url": "https://your-sandbox-staff-url.org",  # optional: clickable report links
    },
    # add a "production" entry only if you have production access
}
```

How the scripts pick the target:

- **One entry configured** — used automatically, nothing to type. If you only
  have sandbox access, production is unreachable from your machine.
- **Several entries configured** — every run must say which target with
  `--env sandbox` or `--env production`. There is no default, so a forgotten
  flag is a hard error, never a silent write to the wrong instance. Every run
  prints and logs a `Target:` line naming the instance it touched.

(Legacy flat `creds.py` files — top-level `baseURL`/`user`/etc. — still work
and are treated as a single `production` environment.)

Ask your ArchivesSpace administrator if you don't know these values.

## Scripts

### aspace_csv_import

Creates or updates archival objects in ArchivesSpace from CSV metadata. Handles titles, dates, extents, notes, and container instances. Every run states its mode (`--create-records` or `--update-only`); strict `--create-records` and `--update-only` preflight every row before writing anything, while `--skip-duplicates` processes rows individually.

```bash
cd aspace_csv_import
python3 aspace_csv_import.py --create-records -f data.csv --dry-run
```

See [aspace_csv_import/README.md](aspace_csv_import/README.md) for full documentation.

### aspace_csv_export

The reverse of the importer: exports AV records to an import-shaped CSV with audit columns (ref ID, Warnings, Level, Depth, Path, URI, staff link, MADS URL, created/modified) for round-trip editing with `--update-only` or as an audit report. Rows come out in tree order (`--list` keeps list order), so `--level all` reads like the ArchivesSpace tree. Read-only.

```bash
cd aspace_csv_import
python3 aspace_csv_export.py --level item --mads-live
```

### check_mads

Reports which catalog numbers are live in MADS (the public DAMS delivery). Public URLs only; ArchivesSpace is never contacted.

```bash
cd aspace_csv_import
python3 check_mads.py numbers.txt
```

Both are documented in [aspace_csv_import/README.md](aspace_csv_import/README.md).

### aspace_rename_directories

Processes digitized video directories to extract runtime from MKV files via `mediainfo`, update ArchivesSpace records with duration (added as a Defined List subnote to the Physical Characteristics and Technical Requirements note) and physical details, and rename directories with ref_ids.

```bash
cd aspace_rename_directories
python3 aspace-rename-directories.py -d /path/to/videos --dry-run
```

See [aspace_rename_directories/README.md](aspace_rename_directories/README.md) for full documentation.

## Workflow

Typical usage order:

1. **CSV Import** — Create archival objects from catalog metadata (validate, check parents and formats, dry run, real run)
2. **Directory Processing** — After digitization, extract runtime and update records; folders gain the ref ID
3. **DAMS ingest** — Outside these tools; MADS publishes the item within about a day
4. **Export / MADS check** — Any time: pull records to a CSV for auditing or round-trip edits, and see which items are live in MADS

## Environments

Every ArchivesSpace tool supports sandbox and production (`check_mads.py` talks only to the public MADS site and takes no environment). `creds.py` holds an `environments` dict with one entry per instance; with one configured it is selected automatically, with several every run must pass `--env NAME` (there is no default). The environment is chosen once per run, before anything connects.