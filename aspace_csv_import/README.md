# ArchivesSpace CSV Import Script

## Overview

This script imports item-level archival objects from CSV files into ArchivesSpace. It's specifically designed for the Johnson Publishing Company (JPC) audiovisual collection but can be adapted for other collections.

## Features

- **Bulk Import**: Create multiple archival objects from CSV data
- **Parent Hierarchy**: Attach items to existing parent objects using ref_ids
- **Comprehensive Metadata**: Import titles, dates, extents, and notes
- **Smart Update Mode**: Detects actual changes before updating (shows what changed)
- **Flexible Duplicate Handling**: Three modes - skip, update, or fail
- **Colorized Output**: Clean, color-coded terminal output with status indicators
- **Change Detection**: Only updates records when data actually differs
- **Error Handling**: Robust error handling with retry logic
- **Reporting**: Generates CSV, JSON, and log file reports
- **Dry Run Mode**: Test imports without creating records

## Prerequisites

- Python 3.6 or higher
- Access to ArchivesSpace with appropriate permissions
- Required Python packages:
  ```bash
  pip install requests
  ```

## Installation

1. Clone or download the script files:
   - `aspace_csv_import.py` - Main import script
   - `creds_template.py` - Credentials template
   - `csv_utils.py` - CSV validation utilities
   - `check_extent_types.py` - Extent type checker

2. Set up credentials:
   ```bash
   cp creds_template.py creds.py
   # Edit creds.py with your username and password
   # Add creds.py to .gitignore
   ```

## Related Documentation

- **CSV_TO_ASPACE_MAPPING.md** - Detailed field mapping from CSV columns to ArchivesSpace fields
- **POTENTIAL_MAPPINGS.md** - Analysis of unmapped CSV fields and future mapping possibilities
- **EXAMPLE_MAPPING.md** - Example showing CSV row transformed to ArchivesSpace JSON

## Authentication

### Method 1: Credentials File (Preferred)

Copy the template and add your credentials:
```bash
cp creds_template.py creds.py
```

Edit `creds.py`:
```python
user = "your_username"
password = "your_password_here"
```

**Important:** Add `creds.py` to your `.gitignore` to avoid exposing credentials!

Then run without credential flags:
```bash
python aspace_csv_import.py -f your_file.csv
```

### Method 2: Command-Line Arguments

Pass credentials directly (useful for testing or one-off runs):
```bash
python aspace_csv_import.py -f your_file.csv -u username -p 'password'
```

**Note:** If your password contains special characters (`&`, `!`, `#`, etc.), wrap it in single quotes.

Command-line arguments override creds.py settings.

## CSV File Format

The CSV should have the following columns:

| Column | Description | Required | Example |
|--------|-------------|----------|---------|
| CATALOG_NUMBER | Component Unique Identifier | Yes | JPC_AV_00012 |
| TITLE | Item title | No* | Ebony/Jet Celebrity Showcase |
| Creation or Recording Date | Creation date (M/D/YYYY) | No | 8/1/1982 |
| Edit Date | Edit/modified date (M/D/YYYY) | No | 8/2/1982 |
| Broadcast Date | Broadcast date (M/D/YYYY) | No | 9/1/1982 |
| Original Format | Physical format (must match dropdown) | Yes | 2 inch videotape |
| ASpace Parent RefID | Parent object's ref_id | Yes | abc123def456 |
| DESCRIPTION | Scope and contents | No | Pilot episode featuring... |

*If no title is provided, the catalog number will be used

**Note:** The CSV contains 80+ columns, but only 8 are actively mapped. See **POTENTIAL_MAPPINGS.md** for analysis of unmapped fields.

## Quick Start

```bash
# Set up credentials (one time)
cp creds_template.py creds.py
# Edit creds.py with your username and password

# Run commands (with creds.py configured):
python aspace_csv_import.py -n -f your_file.csv              # Dry run
python aspace_csv_import.py -f your_file.csv                 # Create records
python aspace_csv_import.py --update-existing -f your_file.csv  # Update existing

# Or use command-line credentials:
python aspace_csv_import.py -f your_file.csv -u username -p 'password'
```

## Command-Line Options

```
Options:
  -h, --help            Show help message
  -n, --dry-run         Test mode - no records created
  -f FILE, --file FILE  CSV file to import
  -u USERNAME           ArchivesSpace username
  -p PASSWORD           ArchivesSpace password
  --no-color            Disable colored output

Duplicate Handling (choose one):
  --skip-duplicates     Skip existing records (DEFAULT)
  --update-existing     Update existing records if data changed
  --fail-on-duplicate   Stop import on first duplicate
```

## Duplicate Handling Modes

### Skip (Default)
```bash
python aspace_csv_import.py -f file.csv
```
- Skips records that already exist
- Creates only new records
- Safe for re-running imports

### Update
```bash
python aspace_csv_import.py --update-existing -f file.csv
```
- Detects what fields have changed
- Only updates if data differs
- Shows "unchanged" for records with no differences
- Displays what changed (title, dates, extents, description)

### Fail
```bash
python aspace_csv_import.py --fail-on-duplicate -f file.csv
```
- Stops entire import on first duplicate
- Use when duplicates indicate data problems

## Output

The script provides colorized terminal output:

```
ArchivesSpace CSV Import
────────────────────────────────────────────────────────────
  File: your_file.csv
  Mode: update

→ Connecting to ArchivesSpace...
✓ Authenticated
→ Loaded 37 valid extent types

────────────────────────────────────────────────────────────
PROCESSING RECORDS
────────────────────────────────────────────────────────────
+ JPC_AV_00463 - Created successfully
↻ JPC_AV_00468 - Updated: title, description
  → title: Old Title → New Title
  → description: Old desc... → New desc...
= JPC_AV_00471 - No changes needed
○ JPC_AV_00472 - Duplicate - skipped

────────────────────────────────────────────────────────────
IMPORT SUMMARY
────────────────────────────────────────────────────────────
  Total Rows:    4
  Created:       1
  Updated:       1
  Unchanged:     1
  Skipped:       1

  Mode: update

  Reports: ~/aspace_import_reports/
```

### Status Symbols
- `+` Green - Created new record
- `↻` Blue - Updated existing record
- `=` Gray - No changes needed
- `○` Yellow - Skipped
- `✗` Red - Error

## Field Mapping

### What Gets Imported

| CSV Column | ArchivesSpace Field | Notes |
|------------|-------------------|-------|
| CATALOG_NUMBER | `component_id` | Component Unique Identifier |
| CATALOG_NUMBER | `top_container.indicator` | Container indicator (no barcode) |
| TITLE | `title` | Falls back to CATALOG_NUMBER if empty |
| Creation or Recording Date | `dates[]` (label: creation) | Converted to YYYY-MM-DD |
| Edit Date | `dates[]` (label: Edited) | Converted to YYYY-MM-DD |
| Broadcast Date | `dates[]` (label: broadcast) | Converted to YYYY-MM-DD |
| Original Format | `extent_type` | Must match ASpace dropdown exactly |
| DESCRIPTION | Scope and Contents note | Multipart note with text subnote |
| _TRANSFER_NOTES | Physical Characteristics note | Playback/quality issues (phystech) |
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

Duration is **not** imported by `aspace_csv_import.py`. Instead, `aspace-rename-directories.py` extracts exact runtime from `.mkv` files during DAMS ingest and creates an ODD note with a Defined List containing:
- Label: "Duration"
- Value: hh:mm:ss format (e.g., "01:23:45")

This provides more accurate duration data than CSV estimates.

### What Update Mode Changes
When using `--update-existing`:
- ✅ Title
- ✅ All dates
- ✅ Extents (format type)
- ✅ Scope & Contents notes

What it preserves:
- ❌ Component ID
- ❌ Parent relationship
- ❌ Instances/containers

## Validation

The script validates:
1. **Required fields**: CATALOG_NUMBER, ASpace Parent RefID (critical error if missing)
2. **Extent types**: Must match ArchivesSpace dropdown exactly (critical error if not)
3. **Parent existence**: Parent ref_id must exist in ArchivesSpace
4. **Duplicate detection**: Checks component_id before creating

## Reports

Generated in `~/aspace_import_reports/` directory:

- `csv_import_YYYYMMDD_HHMMSS.log` - Detailed log file
- `import_report_YYYYMMDD_HHMMSS.csv` - Row-by-row results
- `import_report_YYYYMMDD_HHMMSS.json` - Complete JSON data

## Utility Scripts

### csv_utils.py
Validate CSV before import:
```bash
python csv_utils.py validate your_file.csv
python csv_utils.py parents your_file.csv
python csv_utils.py clean your_file.csv
```

### check_extent_types.py
Check valid extent types:
```bash
python check_extent_types.py
python check_extent_types.py your_file.csv  # Validate CSV values
```

## Recommended Workflow

1. **Validate CSV**
   ```bash
   python csv_utils.py validate your_file.csv
   ```

2. **Check parent ref_ids exist**
   ```bash
   python csv_utils.py parents your_file.csv
   ```

3. **Verify extent types**
   ```bash
   python check_extent_types.py your_file.csv
   ```

4. **Dry run**
   ```bash
   python aspace_csv_import.py -n -f your_file.csv
   ```

5. **Run import**
   ```bash
   python aspace_csv_import.py -f your_file.csv
   ```

6. **Verify in ArchivesSpace**

## Troubleshooting

### Common Errors

| Error | Solution |
|-------|----------|
| "Authentication failed" | Check username/password in creds.py |
| "Parent not found" | Verify parent ref_id exists in ASpace |
| "Missing Parent RefID" | Add parent ref_id to CSV (required field) |
| "Invalid extent type" | Check Original Format matches ASpace dropdown exactly |

## API Configuration

The script connects to:
- **API URL**: https://api-aspace.jpcarchive.org
- **Repository ID**: 2
- **Resource ID**: 7

## Version History

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
