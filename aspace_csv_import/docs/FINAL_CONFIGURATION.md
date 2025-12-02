# Final Script Configuration - All Changes Applied

## ✅ All Requested Changes Have Been Made:

### 1. **Duration (Content TRT)** → COMMENTED OUT in aspace_csv_import.py
- Handled by `aspace-rename-directories.py` during DAMS ingest workflow
- Extracts exact runtime from .mkv files via mediainfo (format: hh:mm:ss)
- Maps to: Scope and Contents note > Defined List (note_definedlist) > "Duration" item

### 2. **EJS Season/Episode** → COMMENTED OUT in aspace_csv_import.py
- No longer creates General Notes from these fields
- Data is ignored during import
- Could potentially map to Scope and Contents note (note_definedlist) in the future

### 3. **Container Type** → CHANGED TO "AV Case"
- Was: "box"
- Now: "AV Case" (matching ArchivesSpace dropdown)

### 4. **Instance Type** → CHANGED TO "Moving Images (Video)"
- Was: "moving_images"  
- Now: "Moving Images (Video)" (matching ArchivesSpace dropdown)

### 5. **Parent RefID** → NOW REQUIRED
- If "ASpace Parent RefID" column is blank → **CRITICAL ERROR**
- Row will be skipped with error message
- No orphan items will be created

## Current Active Mappings (aspace_csv_import.py):

### From CSV → To ArchivesSpace:

| CSV Column | ArchivesSpace Field | Status |
|------------|-------------------|---------|
| CATALOG_NUMBER | component_id, container indicator | ✅ Active |
| TITLE | title (falls back to catalog number if empty) | ✅ Active |
| Creation or Recording Date | dates[creation] | ✅ Active |
| Edit Date | dates[modified] | ✅ Active |
| Broadcast Date | dates[broadcast] | ✅ Active |
| Original Format | extent_type (must match dropdown) | ✅ Active |
| ASpace Parent RefID | parent.ref | ✅ REQUIRED |
| DESCRIPTION | Scope & Contents note | ✅ Active |
| ~~Content TRT~~ | ~~Scope & Contents note~~ | ❌ Commented out - handled by `aspace-rename-directories.py` during DAMS ingest |
| ~~EJS Season~~ | ~~General Note~~ | ❌ Commented out - could use note_definedlist |
| ~~EJS Episode~~ | ~~General Note~~ | ❌ Commented out - could use note_definedlist |
| ~~ORIGINAL_MEDIA_TYPE~~ | ~~physical_details~~ | ❌ Commented out - could use `extent.physical_details` or phystech note |

## Critical Validation Rules:

1. **CATALOG_NUMBER** must exist (row skipped if missing)
2. **ASpace Parent RefID** must exist (CRITICAL ERROR if missing)
3. **Original Format** must match ArchivesSpace dropdown exactly (CRITICAL ERROR if not)
4. **Component ID** must be unique (no duplicates allowed)
5. **Parent object** must exist in ArchivesSpace (error if not found)

## Fixed Values:

- **Level:** "item"
- **Published:** true
- **Resource:** /repositories/2/resources/7
- **Extent portion:** "whole"
- **Extent number:** "1"
- **Container type:** "AV Case"
- **Instance type:** "Moving Images (Video)"

## Workflow

### Prerequisites

1. **Python environment** with `requests` package installed
   ```bash
   pip install -r requirements.txt
   ```

2. **CSV file prepared** with all required columns (see mapping above)

3. **ArchivesSpace credentials** with appropriate permissions

### Step 1: Validate CSV Structure

Check that your CSV has the correct columns and valid data:

```bash
python csv_utils.py validate your_file.csv
```

This checks for:
- Required columns present
- No duplicate CATALOG_NUMBERs
- Valid date formats
- Missing required fields

**Output:** `~/aspace_import_reports/csv_validation/validation_report_*.json`

### Step 2: Verify Parent RefIDs Exist

Confirm all parent archival objects exist in ArchivesSpace:

```bash
python csv_utils.py parents your_file.csv -u username -p 'password'
```

**Critical:** All parent ref_ids must exist before import. Items cannot be created as orphans.

**Output:** `~/aspace_import_reports/parent_lookups/parent_lookup_*.csv`

### Step 3: Verify Extent Types (Optional)

Check that "Original Format" values match ArchivesSpace dropdown exactly:

```bash
python check_extent_types.py your_file.csv -u username -p 'password'
```

**Output:** `valid_extent_types.txt` (list of valid values from your ArchivesSpace instance)

### Step 4: Dry Run

Test the import without creating any records:

```bash
python aspace_csv_import.py -n -f your_file.csv -u username -p 'password'
```

Review the output carefully. All rows should show "Would create archival object" with no errors.

**Output:** `import_reports/import_report_*.csv` and `import_reports/import_report_*.json`

### Step 5: Run Actual Import

Once dry run is successful, run the actual import:

```bash
python aspace_csv_import.py -f your_file.csv -u username -p 'password'
```

**Duplicate Handling Options:**
| Flag | Behavior |
|------|----------|
| (default) | Skip records with existing component_id |
| `--update-existing` | Update existing records with CSV data |
| `--fail-on-duplicate` | Stop entire import on first duplicate |

### Step 6: Verify in ArchivesSpace

1. Log into ArchivesSpace staff interface
2. Navigate to the resource (/repositories/2/resources/7)
3. Verify created items appear under correct parent objects
4. Spot-check a few records for correct field mapping

### Step 7: Review Reports

Check the generated reports for any issues:

- **Log file:** `import_reports/csv_import_*.log` - Detailed processing log
- **CSV report:** `import_reports/import_report_*.csv` - Row-by-row status
- **JSON report:** `import_reports/import_report_*.json` - Complete data for analysis

### Post-Import: DAMS Ingest Workflow

After digitization, run `aspace-rename-directories.py` to:
1. Extract exact duration from .mkv files via mediainfo
2. Add Duration to Scope and Contents note (as Defined List)
3. Rename directories to include ASpace ref_id

---

## Quick Reference

```bash
# Validate CSV
python csv_utils.py validate file.csv

# Check parents exist
python csv_utils.py parents file.csv -u USER -p 'PASS'

# Dry run
python aspace_csv_import.py -n -f file.csv -u USER -p 'PASS'

# Actual import
python aspace_csv_import.py -f file.csv -u USER -p 'PASS'

# Import with update mode
python aspace_csv_import.py -f file.csv -u USER -p 'PASS' --update-existing
```

## Ready to Import!