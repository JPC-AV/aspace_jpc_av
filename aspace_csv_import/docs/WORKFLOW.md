# CSV Import Workflow

## Prerequisites

1. **Python environment** with `requests` package installed
   ```bash
   pip install -r requirements.txt
   ```

2. **Credentials configured** - copy `creds_template.py` to `creds.py` and add your credentials

3. **CSV file prepared** with required columns:
   - `CATALOG_NUMBER` (required, must be unique)
   - `ASpace Parent RefID` (required)
   - `Original Format` (required, must match ASpace dropdown)
   - `TITLE`, `DESCRIPTION`, dates (optional)

## Step 1: Validate CSV Structure

Check that your CSV has correct columns and valid data:

```bash
python csv_utils.py validate your_file.csv
```

**Output:** `~/aspace_import_reports/csv_validation/validation_report_*.json`

## Step 2: Verify Parent RefIDs Exist

Confirm all parent archival objects exist in ArchivesSpace:

```bash
python csv_utils.py parents your_file.csv
```

**Critical:** All parent ref_ids must exist before import. Items cannot be created as orphans.

**Output:** `~/aspace_import_reports/parent_lookups/parent_lookup_*.csv`

## Step 3: Verify Extent Types (Optional)

Check that "Original Format" values match ArchivesSpace dropdown:

```bash
python check_extent_types.py your_file.csv
```

**Output:** `valid_extent_types.txt`

## Step 4: Dry Run

Test the import without creating any records:

```bash
python aspace_csv_import.py -n -f your_file.csv
```

Review the output. All rows should show `+` (would create) with no errors.

## Step 5: Run Actual Import

```bash
python aspace_csv_import.py -f your_file.csv
```

**Duplicate Handling Options:**

| Flag | Behavior |
|------|----------|
| (default) | Skip records with existing component_id |
| `--update-existing` | Update existing records if data changed |
| `--fail-on-duplicate` | Stop entire import on first duplicate |

## Step 6: Verify in ArchivesSpace

1. Log into ArchivesSpace staff interface
2. Navigate to the resource
3. Verify items appear under correct parent objects
4. Spot-check records for correct field mapping

## Step 7: Review Reports

Check generated reports in `~/aspace_import_reports/`:

- `csv_import_*.log` - Detailed processing log
- `import_report_*.csv` - Row-by-row status
- `import_report_*.json` - Complete data for analysis

## Post-Import: DAMS Ingest Workflow

After digitization, run `aspace-rename-directories.py` to:
1. Extract exact duration from .mkv files via mediainfo
2. Add Duration to Scope and Contents note
3. Rename directories to include ASpace ref_id

---

## Quick Reference

```bash
# Validate CSV
python csv_utils.py validate file.csv

# Check parents exist
python csv_utils.py parents file.csv

# Dry run
python aspace_csv_import.py -n -f file.csv

# Actual import
python aspace_csv_import.py -f file.csv

# Import with update mode
python aspace_csv_import.py -f file.csv --update-existing
```
