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
├── console.py                    # Shared terminal display: -h screens, run headers, RESULT blocks
├── jpc.py                        # The jpc- commands: one short command per workflow step
├── pyproject.toml                # Installs the jpc- commands (python -m pip install -e .)
├── creds_template.py             # Credential template (see Setup below)
├── creds.py                      # Your local credentials (gitignored, you create this)
├── requirements.txt              # Python dependencies
│
├── aspace_csv_import/
│   ├── aspace_csv_import.py      # Main import script
│   ├── aspace_csv_export.py      # Export AV records to a CSV; --check, --fill-parents
│   ├── airtable_pull.py          # Save an Airtable view as a CSV (read-only)
│   ├── airtable_writeback.py     # Record a create run's results in Airtable
│   ├── check_mads.py             # Check which items are live in MADS (public DAMS delivery)
│   ├── check_extent_types.py     # Utility to validate extent types against ASpace
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
| `console.py` | Backend | Shared terminal display for every tool: the -h layout, argument-error screen, run header, RESULT block, saved-file lines and colors (`--no-color`). |
| `jpc.py` | Run via the `jpc-` commands | The short commands for each workflow step (`jpc-pull`, `jpc-check`, `jpc-fill`, `jpc-import`, `jpc-update`, `jpc-writeback`). Each runs one tool with that step's fixed flags; `jpc` lists them. |
| `pyproject.toml` | One-time setup | Installs the `jpc-` commands into the active environment. |
| `creds_template.py` | Reference only | Template showing required credential format. Do not edit directly. |
| `creds.py` | User creates/edits | Your local credentials file. You create this from the template. |
| `requirements.txt` | One-time setup | Python package dependencies. Run `pip install -r requirements.txt` once. |
| `aspace_csv_import.py` | Run via command line | Main script for importing CSV metadata to ArchivesSpace. |
| `aspace_csv_export.py` | Run via command line | Exports AV records to an import-shaped CSV in tree order with hierarchy and audit columns; `--mads-live` checks MADS; `--check` says which catalog numbers are in ArchivesSpace and whether an Airtable pull agrees; `--fill-parents` fills parent ref IDs. Read-only. |
| `airtable_pull.py` | Run via command line | Saves one Airtable view of `<<< ASpace_import >>>` as a CSV. Read-only. |
| `airtable_writeback.py` | Run via command line | After a production create run, records each created item's parent and `ASpace Item Record Created` = Yes in Airtable, after you confirm. |
| `check_mads.py` | Run via command line | Checks which catalog numbers are live in MADS (public URLs only). |
| `check_extent_types.py` | Run via command line | Troubleshooting: lists valid extent types in your ASpace instance. The import's dry run already checks formats. |
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

### 2. Install the `jpc-` commands

Once per machine, with the JPC_AV environment active, from this folder:

```bash
python -m pip install -e .
```

This puts `jpc`, `jpc-pull`, `jpc-check`, `jpc-fill`, `jpc-import`,
`jpc-update` and `jpc-writeback` into the environment: they exist whenever
`(JPC_AV)` is active. The `-e` (editable) matters - the commands run the
tools in this folder, so `git pull` keeps them current; reinstall only when a
command is added or renamed. **"command not found" means the JPC_AV
environment is not active, or this one-time install has not been done.**

### 3. Configure credentials

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

How the scripts pick the target **when run directly** (the `jpc-` commands
default to production instead - see [Commands](#commands)):

- **One entry configured** — used automatically, nothing to type. If you only
  have sandbox access, production is unreachable from your machine.
- **Several entries configured** — every run must say which target with
  `--env sandbox` or `--env production`. There is no default, so a forgotten
  flag is a hard error, never a silent write to the wrong instance. Every run
  prints and logs a `Target:` line naming the instance it touched.

(Legacy flat `creds.py` files — top-level `baseURL`/`user`/etc. — still work
and are treated as a single `production` environment.)

Ask your ArchivesSpace administrator if you don't know these values.

## Commands

One short command per workflow step, runnable from any folder (see Setup).
Each runs one tool with that step's fixed flags filled in; the tools keep all
their own checks, PLANs and `yes` prompts. `jpc` lists them;
`jpc-STEP --help` shows what a step accepts.

| Command | Runs |
|---------|------|
| `jpc-pull --view NAME` | `airtable_pull.py NAME` |
| `jpc-check --file FILE [--output PATH]` | `aspace_csv_export.py --check FILE --env production` |
| `jpc-fill --file FILE` | `aspace_csv_export.py --fill-parents FILE --env production` |
| `jpc-import --file FILE [--dry-run] [--skip-duplicates]` | `aspace_csv_import.py --create-records --file FILE --env production` |
| `jpc-update --file FILE [--dry-run]` | `aspace_csv_import.py --update-only --file FILE --env production` |
| `jpc-writeback --report REPORT.json [--run] [--exclude-catalog NUM]...` | `airtable_writeback.py REPORT.json` |

- **Production by default** for the commands that talk to ArchivesSpace,
  shown before anything runs; add `--env sandbox` for the sandbox. (The tools
  themselves ask for `--env` every time.) Each command decides on its own, so
  a sandbox trial needs `--env sandbox` on **every** step - and a sandbox
  import never goes on to `jpc-writeback` (the write-back accepts production
  reports only). The Airtable commands take no `--env`.
- **Paths are read from the folder you are in.** Pasting the full path a
  tool printed ("Saved pulled CSV: ...") works from anywhere.
- **Only the flags listed**, in their long form: anything else - a short
  form (`-f`, `-n`), an abbreviation, `--file=x`, a repeated flag, a
  username or password, a flag for another step - is refused before anything
  runs, and the message says what to use instead.
- Each command prints the exact tool command it runs, then hands over: the
  tool's prompts, Ctrl-C and exit code are its own. The tools' own NEXT STEP
  lines keep printing the long commands, which always work too.
- Export, MADS and directory processing have no `jpc-` command yet; run
  those tools directly.

## Scripts

### aspace_csv_import

Creates or updates archival objects in ArchivesSpace from CSV metadata. Handles titles, dates, extents, notes, and container instances. Every run states its mode (`--create-records` or `--update-only`), checks every row first, and prints a plan of what it will create, skip, refuse or change; a real run writes only after you type `yes`, and a real create ends with the exact command to record the results in Airtable. A dry run (`-n`) shows the plan and writes nothing.

```bash
cd aspace_csv_import
python3 aspace_csv_import.py --create-records -f data.csv --dry-run
```

See [aspace_csv_import/README.md](aspace_csv_import/README.md) for full documentation.

### aspace_csv_export

The reverse of the importer: exports AV records to an import-shaped CSV with audit columns (ref ID, Warnings, Level, Depth, Path, URI, staff link, MADS URL, created/modified) for round-trip editing with `--update-only` or as an audit report. Rows come out in tree order (`--list` keeps list order), so `--level all` reads like the ArchivesSpace tree. `--check FILE` prints which catalog numbers are in ArchivesSpace and, given an Airtable pull, whether its parent and Item Record Created agree with ArchivesSpace. `--fill-parents FILE` fills a sheet's empty parent ref IDs from its `EJS Episode` and `ASpace File Type` columns, writing `FILE_ready.csv` and `FILE_review.csv` beside it. Read-only.

```bash
cd aspace_csv_import
python3 aspace_csv_export.py --level item --mads-live
```

### airtable_pull and airtable_writeback

`airtable_pull.py VIEW` saves one grid view of the Airtable `<<< ASpace_import >>>` table as a CSV (read-only). After a real production create run, `airtable_writeback.py REPORT.json --run` records the results in Airtable: each created row's parent and `ASpace Item Record Created` = Yes. It lists every change row by row and writes only after you type `yes`. Tokens go in `creds.py` as `airtable_pat_read_only` (all reads) and `airtable_pat_write` (writes only).

```bash
cd aspace_csv_import
python3 airtable_pull.py VIEW_NAME
python3 airtable_writeback.py <reports>/import_report_<stamp>.json --run
```

### check_mads

Reports which catalog numbers are live in MADS (the public DAMS delivery). Public URLs only; ArchivesSpace is never contacted.

```bash
cd aspace_csv_import
python3 check_mads.py numbers.txt
```

All of these are documented in [aspace_csv_import/README.md](aspace_csv_import/README.md).

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

Every ArchivesSpace tool supports sandbox and production (`check_mads.py` talks only to the public MADS site and takes no environment). `creds.py` holds an `environments` dict with one entry per instance. When running the tools directly: with one configured it is selected automatically, with several every run must pass `--env NAME` (there is no default). The `jpc-` commands differ: they use production unless `--env sandbox` is given, and show the environment before anything runs (see [Commands](#commands)). The environment is chosen once per run, before anything connects.