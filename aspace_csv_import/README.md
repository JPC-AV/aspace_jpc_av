# ArchivesSpace CSV Import Script

## Overview

This script imports item-level archival objects from CSV files into ArchivesSpace. It's specifically designed for the Johnson Publishing Company (JPC) audiovisual collection but can be adapted for other collections.

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Related Documentation](#related-documentation)
- [Authentication](#authentication)
- [CSV File Format](#csv-file-format)
- [Quick Start](#quick-start)
- [Command-Line Options](#command-line-options)
- [Modes](#modes)
  - [Create (--create-records)](#create---create-records)
  - [Create, skipping existing (--skip-duplicates)](#create-skipping-existing---skip-duplicates)
  - [Update (--update-only)](#update---update-only)
  - [Update-only (narrow CSV)](#update-only-narrow-csv)
- [Output](#output)
- [Field Mapping](#field-mapping)
- [Validation](#validation)
- [Reports](#reports)
- [Utility Scripts](#utility-scripts)
- [Recommended Workflow](#recommended-workflow)
  - [Full import (create)](#full-import-create)
  - [Update-only workflow (narrow CSV)](#update-only-workflow-narrow-csv)
- [Troubleshooting](#troubleshooting)
- [Version History](#version-history)
- [License](#license)

## Features

- **Bulk Import**: Create multiple archival objects from CSV data
- **Parent Hierarchy**: Attach items to existing parent objects using ref_ids
- **Comprehensive Metadata**: Import titles, dates, extents, and notes
- **Smart Update Mode**: Detects actual changes before updating (shows what changed)
- **Explicit Modes**: Every run states its intent - `--create-records` or `--update-only`; strict create and update-only preflight every row before writing anything
- **Colorized Output**: Clean, color-coded terminal output with status indicators
- **Change Detection**: Only updates records when data actually differs
- **Error Handling**: Robust error handling with retry logic
- **Reporting**: Generates CSV, JSON, and log file reports
- **Dry Run Mode**: Test imports without creating records

## Prerequisites

- Python 3.8 or higher
- Access to ArchivesSpace with appropriate permissions
- Required Python packages:
  ```bash
  pip install requests
  ```

## Installation

1. Clone the repository (the tools depend on files at two levels):

   **Repository root** (`aspace_jpc_av/`):
   - `aspace_client.py` - the shared ArchivesSpace client every tool imports (required)
   - `creds_template.py` - credentials template; your `creds.py` copy lives here too
   - `requirements.txt`

   **This folder** (`aspace_jpc_av/aspace_csv_import/`):
   - `aspace_csv_import.py` - Main import script
   - `aspace_csv_export.py` - Export to an import-shaped CSV (round trip, audit columns, `--mads-live`)
   - `check_mads.py` - MADS liveness checker (public URLs; never touches ArchivesSpace)
   - `csv_utils.py` - CSV validation utilities
   - `check_extent_types.py` - Extent type checker
   - `sheet_rules.py` - The sheet contract: column names and the shared validation rules (imported by the others)

2. Set up credentials **at the repository root**:
   ```bash
   cd aspace_jpc_av
   cp creds_template.py creds.py
   # Edit creds.py with your username and password (see Authentication below)
   ```
   `creds.py` is already listed in `.gitignore`.

3. Run the tools **from this folder** - every command in this document assumes it:
   ```bash
   cd aspace_csv_import
   ```

## Related Documentation

- **docs/CSV_TO_ASPACE_MAPPING.md** - The field contract: what each column becomes on create, what `--update-only` changes, what the rename tool adds
- **docs/POTENTIAL_MAPPINGS.md** - The sheet columns that are not imported, and where they could go
- **docs/EXAMPLE_MAPPING.md** - One row followed from the sheet to the record and through the rename tool

## Authentication

### Method 1: Credentials File (Preferred)

Copy the template and add your credentials. Both files live at the
**repository root**, one level above this folder:
```bash
cp ../creds_template.py ../creds.py
```

Edit `../creds.py` - credentials live inside the `environments` dict, one
entry per ArchivesSpace instance (the template ships with the sandbox
filled in and production commented out):
```python
environments = {
    "sandbox": {
        "baseURL": "https://api-jpcsb.as.atlas-sys.com",
        "user": "your_username",
        "password": "your_password",
        "repo_id": "2",
        "resource_id": "7",
        "staff_url": "https://staff-jpcsb.as.atlas-sys.com",
    },
}
```

With one environment configured it is selected automatically; with several,
every run must say which with `--env NAME` (there is no default - a
forgotten flag can never mean production).

`creds.py` is already in `.gitignore`; never commit or share it.

Then run without credential flags:
```bash
python aspace_csv_import.py --create-records -f your_file.csv
```

### Method 2: Command-Line Arguments

Pass credentials directly (useful for testing or one-off runs):
```bash
python aspace_csv_import.py --create-records -f your_file.csv -u username -p 'password'
```

**Note:** If your password contains special characters (`&`, `!`, `#`, etc.), wrap it in single quotes.

**Caution:** Passing the password with `-p` exposes it to your shell history and process listings. Prefer creds.py.

Command-line arguments override creds.py settings.

## CSV File Format

**Create runs (`--create-records`) require all nine column headers below to
be present** - the "Required" column describes whether each *cell* may be
left blank, not whether the column may be omitted. Only `--update-only`
accepts a narrow sheet (`CATALOG_NUMBER` plus just the columns to change).

| Column | Description | Value required? | Example |
|--------|-------------|----------|---------|
| CATALOG_NUMBER | Component Unique Identifier | Yes | JPC_AV_00012 |
| ASpace Title | Item title | No* | Ebony/Jet Celebrity Showcase |
| Creation or Recording Date | Creation date (M/D/YYYY or M/D/YY, or ISO YYYY-MM-DD / YYYY-MM / YYYY) | No | 8/1/1982 |
| Edit Date | Edit/modified date (same formats) | No | 8/2/1982 |
| Broadcast Date | Broadcast date (same formats) | No | 9/1/1982 |
| Original Format | Physical format (must match dropdown when set or changed; an unchanged stored term round-trips under `--update-only`) | No* | 2 inch videotape |
| ASpace Parent RefID | Parent object's ref_id | Yes for create; ignored by `--update-only` | abc123def456 |
| ASpace Scope and Contents Note | Scope and contents | No | Pilot episode featuring... |
| ASpace PhysTech Note | Physical characteristics / playback notes | No | Slight ringing present... |

**Date range:** every date you set or change must fall within **1940–2020**, the span of the AV material - anything outside is rejected as a typo. **Two-digit years** (`11/2/93`) are therefore unambiguous: `40`–`99` are 19xx, `00`–`20` are 20xx, and `21`–`39` are rejected (impossible in either century). The same sheet parses identically in any year. Day-first dates are never accepted. One exception: `--update-only` preserves a stored date outside the range as long as the sheet leaves it unchanged (an exported legacy value round-trips; the export flags it for you), but refuses to *change* a date to an out-of-range value.

*If no title is provided, the catalog number will be used. If no format is provided the record is created without an extent - every item should have one, but the importer does not insist.

**Note:** The CSV contains 80+ columns, but only 9 are actively mapped. See **docs/POTENTIAL_MAPPINGS.md** for analysis of unmapped fields.

## Quick Start

```bash
# Set up credentials (one time) - at the repository root, one level up
cp ../creds_template.py ../creds.py
# Edit ../creds.py with your username and password (see Authentication)

# Run commands (with creds.py configured):
python aspace_csv_import.py --create-records -n -f your_file.csv   # Dry run
python aspace_csv_import.py --create-records -f your_file.csv      # Create records
python aspace_csv_import.py --update-only -f your_file.csv         # Update existing

# Or use command-line credentials:
python aspace_csv_import.py --create-records -f your_file.csv -u username -p 'password'

# With several environments in creds.py, every command that contacts
# ArchivesSpace (the importer, csv_utils.py --parents, check_extent_types.py,
# aspace_csv_export.py) needs --env. csv_utils.py --validate is local, and
# check_mads.py only talks to the public MADS site - neither needs --env.
python aspace_csv_import.py --env sandbox --create-records -n -f your_file.csv
```

## Command-Line Options

```
Mode (required - choose one):
  --create-records      Create records; aborts before writing if ANY row already exists
  --update-only         Update existing records (narrow or full CSV); never creates

Options:
  -h, --help            Show help message
  -n, --dry-run         Preview - no ArchivesSpace writes of any kind (no creates, no updates)
  -f FILE, --file FILE  CSV file to import
  -u USERNAME           ArchivesSpace username
  -p PASSWORD           ArchivesSpace password
  --skip-duplicates     With --create-records: create new rows, skip existing ones
  --env NAME            Target environment from creds.py (required when several are configured)
  --no-color            Disable colored output
```

## Modes

A mode is required: every run states whether it makes new records or changes
existing ones. Strict `--create-records` and `--update-only` both preflight
every row before writing anything, and their aborts are mirror images -
create aborts if a catalog number EXISTS, update-only aborts if one DOESN'T.
A preflight abort means nothing was written, so fixing the sheet and
rerunning is safe. (`--skip-duplicates` is the exception: it is a single
pass with no preflight, and a runtime API failure mid-run in any mode can
still leave earlier rows written - the report and non-zero exit say so.) In
every mode a lookup that fails or matches multiple records is refused - the
preflighting modes abort the run, `--skip-duplicates` errors that row and
moves on: an unverifiable answer is never permission to write.

### Create (--create-records)
```bash
python aspace_csv_import.py --create-records -f file.csv
```
- For sheets where every row is genuinely new
- Preflights every row first - catalog number verifiably new, parent
  exists, format valid, container indicator unambiguous; if ANY row fails,
  the whole run aborts before anything is written (the report lists every
  problem row, with links)
- A clean, careful run: no silent skips hiding a surprise

### Create, skipping existing (--skip-duplicates)
```bash
python aspace_csv_import.py --create-records --skip-duplicates -f file.csv
```
- For mixed sheets: creates the new rows, skips ones that already exist
- Existing records are never touched (changing them is --update-only's job)
- First half of the mixed-sheet workflow: create with --skip-duplicates,
  wait a minute for the search index, then --update-only for the changes

### Update (--update-only)
```bash
python aspace_csv_import.py --update-only -f file.csv
```
- NEVER creates records: every catalog number must already exist, or the
  whole run aborts before writing anything (a typo'd number can't silently
  become a new record)
- Works with a full sheet or a narrow one (CATALOG_NUMBER + just the
  columns to change); absent columns are left untouched
- Detects what fields have changed; only updates if data differs
- Shows "unchanged" for records with no differences and displays what
  changed (title, dates, extents, description)
- Mixed sheet with genuinely new records? Run
  `--create-records --skip-duplicates` first (new rows created, existing
  skipped), wait a minute for the search index, then --update-only for
  the changes

### Update-only (narrow CSV)
```bash
python aspace_csv_import.py --update-only -f titles_only.csv
```
- Accepts a narrow CSV: `CATALOG_NUMBER` plus just the column(s) to change
  (e.g. only `ASpace Title`) — the other mapped columns may be omitted entirely
  and are left untouched
- **Never creates records.** Every catalog number is resolved to exactly one
  existing record *before anything is written*; if any row matches zero
  records (e.g. a typo'd barcode) or multiple records, the entire run aborts
  with no writes
- Prints which columns the run will update and which it will leave alone
- `ASpace Parent RefID` is not required (updates never use it)

## Output

The script provides colorized terminal output:

```
ArchivesSpace CSV Import
────────────────────────────────────────────────────────────
  Target: SANDBOX (https://api-jpcsb.as.atlas-sys.com, repo 2, resource 7)
  File: your_file.csv
  Mode: update-only (never creates)

[>] Connecting to https://api-jpcsb.as.atlas-sys.com...
[OK] Authenticated
[>] Extent vocabulary loaded only if a row changes a format (update-only)

────────────────────────────────────────────────────────────
PROCESSING RECORDS
────────────────────────────────────────────────────────────
[>] Resolving 3 catalog number(s) before writing anything...
[~] JPC_AV_00468 - Updated: title, description - Ref ID 7e228513...
  [>] title: Old Title --> New Title
  [>] description: Old desc... --> New desc...
[=] JPC_AV_00471 - No changes needed - Ref ID 2d2aba84...
[~] JPC_AV_00472 - Updated: dates - Ref ID bc814158...
  [>] dates: {'creation': None} --> {'creation': '1987-01-29'}

────────────────────────────────────────────────────────────
IMPORT SUMMARY
────────────────────────────────────────────────────────────
  Total Rows:    3
  Updated:       2
  Unchanged:     1

  Mode: update-only (never creates)

  Reports: ~/aspace_import_reports/
  Records (as stored in ASpace): import_records_20260910_140212_71021.json (records: 3 of 3, containers: 3 of 3 captured)
```

(A `--create-records` run lists `[+] ... Created successfully - Ref ID ...` lines instead; `--skip-duplicates` is the only mode that mixes `[+]` and `[-]` lines.)

### Status Symbols
- `[+]` Green - Created new record
- `[~]` Blue - Updated existing record
- `[=]` Gray - No changes needed
- `[-]` Yellow - Skipped
- `[X]` Red - Error
- `[!]` Yellow - Warning
- `[>]` Cyan - Info
- `[OK]` Green - Success

## Field Mapping

### What Gets Imported

| CSV Column | ArchivesSpace Field | Notes |
|------------|-------------------|-------|
| CATALOG_NUMBER | `component_id` | Component Unique Identifier |
| CATALOG_NUMBER | `top_container.indicator` | Container indicator (no barcode) |
| ASpace Title | `title` | Falls back to CATALOG_NUMBER if empty |
| Creation or Recording Date | `dates[]` (label: creation) | Converted to YYYY-MM-DD; partial YYYY or YYYY-MM kept as-is |
| Edit Date | `dates[]` (label: Edited) | Converted to YYYY-MM-DD; partial values kept as-is |
| Broadcast Date | `dates[]` (label: broadcast) | Converted to YYYY-MM-DD; partial values kept as-is |
| Original Format | `extent_type` | Must match ASpace dropdown exactly when set or changed; an unchanged stored term round-trips under `--update-only` |
| ASpace Scope and Contents Note | Scope and Contents note | Multipart note with text subnote |
| ASpace PhysTech Note | Physical Characteristics note | Playback/quality issues (phystech) |
| ASpace Parent RefID | `parent.ref` | **Required** - links to parent object |

### Fixed Values
| Field | Value |
|-------|-------|
| Level | item |
| Published | true |
| Container Type | AV Case |
| Instance Type | Moving Images (Video) |
| Extent Portion | whole |
| Extent Number | 1 |

### Duration (Handled Separately)

Duration is **not** imported by `aspace_csv_import.py`. Instead, `aspace-rename-directories.py` extracts exact runtime from `.mkv` files after digitization and adds a Defined List subnote to the record's **Physical Characteristics and Technical Requirements (phystech) note** (preserving the note's text) containing:
- Label: "Duration"
- Value: hh:mm:ss format (e.g., "01:23:45")

This provides more accurate duration data than CSV estimates.

### What Update Mode Changes
When using `--update-only`:
- ✅ Title
- ✅ Dates (merged by label — a supplied date replaces only the same-label date; others are preserved)
- ✅ Extents (format type — on records with zero or one extent, and only the type changes; everything else on the extent is kept; multi-extent records are never collapsed, and changing one errors the row)
- ✅ Scope & Contents notes (the first note that carries text: its first text paragraph is replaced; other paragraphs and extra same-type notes preserved)
- ✅ PhysTech notes (same rule; the Duration defined list and extra same-type notes preserved)

What it preserves:
- ❌ Component ID
- ❌ Parent relationship
- ❌ Instances/containers

**Blank cells:** a blank CSV cell leaves the existing ArchivesSpace value
untouched — updates can replace values but never clear them. Deletions are
done in ArchivesSpace directly.

## Validation

The script validates:
1. **Required fields**: CATALOG_NUMBER always; ASpace Parent RefID for create runs (critical error if missing; ignored by `--update-only`)
2. **Extent types**: Must match ArchivesSpace dropdown exactly when a format is being set or changed (critical error if not); an unchanged stored term - even a retired one - round-trips under `--update-only`
3. **Parent existence**: Parent ref_id must exist in ArchivesSpace (create runs; `--update-only` never re-parents)
4. **Duplicate detection**: Checks component_id before creating

## Reports

Generated in `~/aspace_import_reports/` by default. Setting `logs_dir` in
creds.py moves them to `<logs_dir>/import_reports/`; the other tools' folders
sit beside it as siblings directly under `<logs_dir>` (`export_reports/`,
`mads_reports/`, `rename_reports/`).

Files (the stamp is `YYYYMMDD_HHMMSS_<pid>`; the `<pid>` is the process
ID - the number macOS assigns to each running program, unique for the life
of that run - so two runs started in the same second never share a name,
and any report can be matched to the run that wrote it):

- `csv_import_<stamp>.log` - detailed log: target, the exact command, every lookup and write
- `import_report_<stamp>.csv` - the receipt: one row per input row with status, message, URI, ref ID, staff link, and every mapped column; row 1 is a `# command | target | time` provenance line, like the exports
- `import_report_<stamp>.json` - the same receipt plus a summary block (counts, mode, environment, command, snapshot completeness) and per-row change details
- `import_records_<stamp>.json` - the records as ArchivesSpace holds them after the run, read back after each write (archival object plus its top container), keyed by catalog number; not written for dry runs

## Utility Scripts

### csv_utils.py
Validate CSV before import:
```bash
python csv_utils.py --validate your_file.csv
python csv_utils.py --parents your_file.csv
python csv_utils.py --validate your_file.csv --update-only   # narrow update CSV
```

### check_extent_types.py
Check valid extent types:
```bash
python check_extent_types.py
python check_extent_types.py your_file.csv  # Validate CSV values
```

### aspace_csv_export.py
The reverse of the importer: pull AV records into an import-shaped CSV
(same columns, plus ref ID, Warnings, Level, Depth, Path, URI, staff link,
MADS URL and created/modified audit fields) for round-trip editing with
`--update-only`, or as an audit report. Read-only.
```bash
python aspace_csv_export.py --level item                    # every item-level record
python aspace_csv_export.py --level all                     # the whole hierarchy, every level
python aspace_csv_export.py --parent REFID                  # direct children of one record
python aspace_csv_export.py --list numbers.txt              # exactly these catalog numbers
python aspace_csv_export.py --level item --mads-live        # add a 'MADS live' column
```
Rows are written in tree order (a parent immediately followed by its
children, siblings as the staff interface orders them), so `--level all`
reads like the ArchivesSpace tree; `--list` keeps the order of the list. `Level` is the record's level, `Depth`
its distance from the top (0 for a series; an ephemera item under a tape is
one deeper than the tape), and `Path` its ancestors joined with ` > ` -
which survives sorting and filtering, and tells you in words which record
the `ASpace Parent RefID` points at. `--update-only` ignores all three, so
delete them or leave them.

**Filling parent ref IDs.** Before a create run, the exporter can fill a
sheet's empty `ASpace Parent RefID` column for you:
```bash
python aspace_csv_export.py --fill-parents your_file.csv
```
The sheet needs `CATALOG_NUMBER`, `ASpace Parent RefID`, `EJS Episode` (`4006`,
or `9` for Celebrity Showcase) and `ASpace File Type` (`Edited`, `Promo`, ...).
Each row gets the ref ID of that file record under that episode, plus a
`Path` showing where it will land and a `Parent Note`. A cell is filled only
when exactly one record matches; otherwise it stays blank and the note says
why (no such episode, the episode has no Promo record, multiple matching file records).
Normalized episode keys must be unique across the selected AV resource:
a duplicate is a fatal error (exit code 1), names both conflicting records,
and stops the entire run without writing a CSV. The check uses the sheet
lookup rules: case and surrounding whitespace are ignored, and numeric
forms normalize (`Episode 09`, `Episode 9` and `Episode 9.0` conflict).
Duplicate non-episode subseries titles, such as `Season 1` or `Cosmetics`,
do not block filling; this is not a resource-wide subseries naming policy.
A value already in the sheet is never replaced. `Raw` rows are always left
for a person, because a tape in a multi-tape set goes under that set's own
file record. The result is a new file (name it with `-o`; yours is never
edited) and it is the file the rest of the workflow uses. Exit code 2 means
some rows still need a parent.
`--list` accepts a plain text file (one number per line) or any CSV with a
`CATALOG_NUMBER` column. Files land in `~/aspace_import_reports/` by default
(`<logs_dir>/export_reports/` when `logs_dir` is set) with a `# command`
provenance line as row 1 (every reader in the toolset skips it).

### check_mads.py
Check which catalog numbers are live in MADS (the public DAMS delivery).
Public URLs only - ArchivesSpace is never contacted.
```bash
python check_mads.py numbers.txt          # or any CSV with a CATALOG_NUMBER column
```
Writes `CATALOG_NUMBER, MADS URL, MADS live, Checked` to `~/aspace_mads_reports/`
by default (`<logs_dir>/mads_reports/` when `logs_dir` is set).
`MADS live` is `Yes`, `No`, `check failed`, or `invalid catalog number` -
the last two are never evidence of absence.

## Recommended Workflow

### Full import (create)

1. **Fill parent ref_ids** *(if the sheet's `ASpace Parent RefID` column is blank)*
   ```bash
   python aspace_csv_export.py --fill-parents your_file.csv -o your_file_filled.csv
   ```
   Every later step uses the filled file. Rows the tool left blank (listed
   on the console and in its `Parent Note` column) must be filled by hand
   first - the validator rejects a blank parent on a create run. If the
   parents are already filled and you skip this step, use your original
   filename throughout.

2. **Validate CSV**
   ```bash
   python csv_utils.py --validate your_file_filled.csv
   ```

3. **Check parent ref_ids exist**
   ```bash
   python csv_utils.py --parents your_file_filled.csv
   ```

4. **Verify extent types**
   ```bash
   python check_extent_types.py your_file_filled.csv
   ```

5. **Dry run**
   ```bash
   python aspace_csv_import.py --create-records -n -f your_file_filled.csv
   ```

6. **Run import**
   ```bash
   python aspace_csv_import.py --create-records -f your_file_filled.csv
   ```

7. **Verify in ArchivesSpace**

> **Rerunning after a run that created records:** wait a minute or two before
> rerunning. The duplicate check uses ArchivesSpace's search index, which is
> updated on a short delay (typically under a minute) — a record created
> seconds ago may not be findable yet, and an immediate rerun could create a
> duplicate. Normal human-paced reruns are unaffected.

### Update-only workflow (narrow CSV)

For updating existing records from a narrow CSV (`CATALOG_NUMBER` plus just
the column(s) to change — e.g. titles only). Never creates records; no parent
ref_ids needed.

1. **Validate CSV**
   ```bash
   python csv_utils.py --validate your_file.csv --update-only
   ```

2. **Verify extent types** *(only if you intend to CHANGE `Original Format`)*
   ```bash
   python check_extent_types.py your_file.csv
   ```
   An exported sheet may carry a retired term on an unchanged record; the
   importer accepts it as long as the format itself isn't being changed, so
   the checker's "INVALID" for such a value is not a blocker.

3. **Dry run** — check the `will update:` / `Left untouched:` scope lines and
   the proposed `old --> new` changes
   ```bash
   python aspace_csv_import.py --update-only -n -f your_file.csv
   ```

4. **Run the update**
   ```bash
   python aspace_csv_import.py --update-only -f your_file.csv
   ```

5. **Verify in ArchivesSpace**

Every row is resolved and preflighted before anything is written — if any
catalog number matches zero or multiple records, or a row would hit a guard
(invalid extent type, multi-extent or multi-date conflict), the entire run
aborts with no writes.

## Troubleshooting

### Common Errors

| Error | Solution |
|-------|----------|
| "Authentication failed" | Check username/password in creds.py |
| "Parent not found" | Verify parent ref_id exists in ASpace |
| "Missing Parent RefID" | Add parent ref_id to CSV (required field) |
| "Invalid extent type" | Check Original Format matches ASpace dropdown exactly |

## Version History

- **v3.0** (2026): Safety hardening + update-only mode
  - New `--update-only` mode: narrow CSVs (CATALOG_NUMBER + columns to
    change), never creates records, resolves and preflights every row
    before anything is written — any predictable problem aborts the run
    with zero writes
  - Fail-closed everywhere: duplicate/parent/container lookups verify exact
    matches within the AV resource and abort on failure instead of guessing;
    failed report writes fail the run (exit 3)
  - Write safety: retries limited to reads (a timed-out POST is never blindly
    retried); top containers are reused by indicator and cleaned up if the
    record creation is definitively rejected
  - Update mode applies only detected changes — unchanged dates, extents,
    and notes keep their richer nested metadata (date expressions/certainty,
    extent physical_details, note labels and Duration defined lists);
    multi-extent and multi-same-label-date records are never collapsed
  - Blank CSV cells mean "leave the existing value alone"; day-first dates
    (13/02/2024) are rejected as malformed
  - Column names renamed (ASpace Title, ASpace Scope and Contents Note) and
    centralized in sheet_rules.py — future renames are a one-line edit
  - `csv_utils.py --validate --update-only` for narrow CSVs; docs corrected
    and expanded (ToC, workflows, real status symbols)

- **v2.0** (2024): Major update
  - Colorized terminal output
  - Smart change detection in update mode
  - "Unchanged" status for records with no differences
  - Cleaner output formatting
  - Credentials file support (creds.py)
  - Removed noisy logging from console
  - Added `--no-color` flag

- **v1.0** (2024): Initial release
  - Basic CSV import functionality
  - Parent hierarchy support
  - Three duplicate modes
  - Comprehensive error handling

## License

This script is provided as-is for archival processing purposes.
