# ArchivesSpace CSV Import Script

## Overview

This script imports item-level archival objects from CSV files into ArchivesSpace. It's specifically designed for the Johnson Publishing Company (JPC) audiovisual collection but can be adapted for other collections.

## Features

- **Bulk Import**: Create multiple archival objects from CSV data
- **Parent Hierarchy**: Attach items to existing parent objects using ref_ids
- **Comprehensive Metadata**: Import titles, dates, extents, notes, and instances
- **Flexible Duplicate Handling**: Three modes for handling existing records (skip, update, or fail)
- **Error Handling**: Robust error handling with retry logic
- **Reporting**: Generates CSV, JSON, and log file reports
- **Dry Run Mode**: Test imports without creating records
- **Batch Processing**: Process records in batches to avoid overwhelming the API

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
   - `config_sample.py` - Sample configuration file

2. Create your configuration:
   ```bash
   cp config_sample.py config.py
   ```

3. Edit `config.py` with your ArchivesSpace credentials and settings

## CSV File Format

The CSV should have the following columns:

| Column | Description | Required | Example |
|--------|-------------|----------|---------|
| CATALOG_NUMBER | Component Unique Identifier | Yes | JPC_AV_00012 |
| TITLE | Item title | No* | Ebony/Jet Celebrity Showcase |
| Creation or Recording Date | Creation date (M/D/YYYY) | No | 8/1/1982 |
| Edit Date | Edit/modified date (M/D/YYYY) | No | 8/2/1982 |
| Broadcast Date | Broadcast date (M/D/YYYY) | No | 9/1/1982 |
| EJS Season | Season information | No** | Celebrity Showcase |
| EJS Episode | Episode information | No** | Episode 1 |
| Original Format | Physical format (must match dropdown) | Yes | 2 inch videotape |
| ASpace Parent RefID | Parent object's ref_id | Yes | abc123def456 |
| Content TRT | Duration in minutes | No | 38 |
| DESCRIPTION | Scope and contents | No | Pilot episode featuring... |
| ORIGINAL_MEDIA_TYPE | Detailed media type | No** | 2 inch videotape, 3M |

*If no title is provided, the catalog number will be used
**Currently not used/commented out in mapping

## Configuration

Edit the script's configuration section or use command-line arguments:

```python
# ArchivesSpace API Configuration
ASPACE_URL = "https://your-aspace.edu"
ASPACE_USERNAME = "your_username"  # Or use -u flag
ASPACE_PASSWORD = "your_password"  # Or use -p flag

# Repository and Resource Configuration
REPO_ID = "2"
RESOURCE_ID = "7"

# Processing Options
BATCH_SIZE = 10  # Records per batch
```

Or use command-line arguments to override:
```bash
python aspace_csv_import.py -u myusername -p mypassword -f myfile.csv
```

## Usage

### Command-Line Options

```bash
python aspace_csv_import.py [options]

Options:
  -h, --help            Show help message
  -n, --dry-run         Perform a dry run without creating records (test mode)
  -f FILE, --file FILE  CSV file to import (default: JPCA-AV_SOURCE-ASpace_CSV_exoort.csv)
  -u USERNAME           ArchivesSpace username (overrides script setting)
  -p PASSWORD           ArchivesSpace password (overrides script setting)
  
Duplicate Handling (choose one):
  --skip-duplicates     Skip records with duplicate component_id (DEFAULT)
  --update-existing     Update existing records when component_id already exists
  --fail-on-duplicate   Stop entire import if duplicate component_id is found
```

### Duplicate Component ID Handling

The script provides three different ways to handle records when a component_id (CATALOG_NUMBER) already exists in ArchivesSpace:

#### 1. Skip Duplicates (DEFAULT)
```bash
python aspace_csv_import.py  # Default behavior
# Or explicitly:
python aspace_csv_import.py --skip-duplicates
```
- **Behavior**: Skips rows with existing component_ids and continues processing
- **Use when**: You want to import only NEW records and leave existing ones untouched
- **Result**: Shows as "Skipped" in summary

#### 2. Update Existing Records
```bash
python aspace_csv_import.py --update-existing
```
- **Behavior**: Updates existing records with data from CSV
- **Updates**: Title, dates, extents, notes
- **Preserves**: Parent relationship, instances, component_id
- **Use when**: You want to refresh metadata for existing records
- **Result**: Shows as "Updated" in summary

#### 3. Fail on Duplicate (Strict Mode)
```bash
python aspace_csv_import.py --fail-on-duplicate
```
- **Behavior**: STOPS entire import immediately on first duplicate
- **Use when**: Duplicates indicate a data problem that needs investigation
- **Result**: Import terminates with error status

#### Testing Duplicate Modes
Always test with dry run first:
```bash
# Test skip mode
python aspace_csv_import.py -n

# Test update mode
python aspace_csv_import.py -n --update-existing

# Test strict mode
python aspace_csv_import.py -n --fail-on-duplicate
```

#### What Gets Updated
When using `--update-existing`, these fields are replaced:
- ✅ Title
- ✅ All dates (creation, edit, broadcast)
- ✅ All extents (format type, physical details)
- ✅ Scope & Contents notes

These fields are preserved:
- ❌ Component ID
- ❌ Parent relationship
- ❌ Resource relationship
- ❌ Instances/containers

#### Choosing the Right Mode

| Scenario | Recommended Mode |
|----------|-----------------|
| Fresh import of new data | `--skip-duplicates` (default) |
| Updating metadata for existing records | `--update-existing` |
| Data integrity is critical | `--fail-on-duplicate` |
| Mixed new and existing records | `--skip-duplicates` or `--update-existing` |
| Testing/debugging | Use `-n` with any mode to preview |

### Basic Usage

1. Place your CSV file in the same directory as the script
2. Run the script:
   ```bash
   # Dry run (test mode) - ALWAYS DO THIS FIRST
   python aspace_csv_import.py -n
   
   # Actual import (creates records, skips duplicates)
   python aspace_csv_import.py
   
   # Update existing records
   python aspace_csv_import.py --update-existing
   
   # Strict mode - stop on any duplicate
   python aspace_csv_import.py --fail-on-duplicate
   
   # Dry run with update mode
   python aspace_csv_import.py -n --update-existing
   
   # Import with credentials on command line
   python aspace_csv_import.py -u myusername -p mypassword
   ```

### Dry Run (Test Mode)

Always test with a dry run first:
```bash
python aspace_csv_import.py -n
```

This will:
- Validate all data
- Check for duplicates
- Show what would be created
- NOT create any records in ArchivesSpace

### Production Run

After successful dry run, run the actual import:
```bash
python aspace_csv_import.py
```

The script will create records in ArchivesSpace. Monitor the output for any errors.

## Workflow

1. **Authentication**: Script logs into ArchivesSpace
2. **Validation**: Each row is validated for:
   - Required fields (catalog number, parent ref_id)
   - Valid extent types (must match dropdown)
   - Duplicate component IDs (handled based on mode)
   - Parent object existence
3. **Object Processing**: Based on duplicate mode:
   - **New Records**: Creates archival object with metadata
   - **Existing Records**: Skips, updates, or fails based on flag
   - Creates top container using catalog number
   - Links to parent object (required)
4. **Reporting**: Generates three reports:
   - Log file with detailed processing information
   - CSV report with row-by-row results
   - JSON report with complete data

## Reports

The script generates three types of reports in the `import_reports` directory:

### 1. Log File
```
import_reports/csv_import_YYYYMMDD_HHMMSS.log
```
Detailed processing log with timestamps and error messages

### 2. CSV Report
```
import_reports/import_report_YYYYMMDD_HHMMSS.csv
```
Summary of each row's import status:
- row_number
- catalog_number
- title
- status:
  - `success` - New record created
  - `updated` - Existing record updated (--update-existing mode)
  - `skipped` - Row skipped (duplicate or missing data)
  - `error` - Failed to create/update
- message
- uri (of created/updated object)

### 3. JSON Report
```
import_reports/import_report_YYYYMMDD_HHMMSS.json
```
Complete import data in JSON format for programmatic analysis

## Data Mapping

### Dates
The script creates three types of dates:
- **Creation Date**: From "Creation or Recording Date" column (label: "creation")
- **Edit Date**: From "Edit Date" column (label: "modified")
- **Broadcast Date**: From "Broadcast Date" column (label: "broadcast")

Dates are converted from M/D/YYYY to YYYY-MM-DD format.

### Extents
Creates extent records with:
- **Portion**: "whole"
- **Number**: "1"
- **Type**: "videocassettes"
- **Physical Details**: From ORIGINAL_MEDIA_TYPE column
- **Container Summary**: From Original Format column

### Notes
Creates three types of notes:
1. **Scope and Contents** (multipart):
   - Description text
   - Duration information
2. **Physical Characteristics**: Original media details
3. **General Note**: Season/episode information

### Instances
Creates moving image instances with top containers where:
- **Indicator**: Catalog number (e.g., JPC_AV_00012)
- **Barcode**: Same as indicator
- **Type**: "box"

## Error Handling

### Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| "Authentication failed" | Wrong credentials | Check username/password |
| "Parent not found" | Invalid parent ref_id | Verify parent exists in ArchivesSpace |
| "Missing Parent RefID" | No parent specified | All items require parent objects |
| "Invalid extent type" | Original Format not in dropdown | Must match ArchivesSpace controlled vocabulary exactly |
| "Duplicate component ID" | Catalog number already exists | Handle based on mode - see below |
| "Session expired" | Long running import | Script auto-reconnects |

### Duplicate Component ID Handling

| Mode | When Duplicate Found | Result |
|------|---------------------|--------|
| `--skip-duplicates` (default) | Skips row, continues | Row marked as "skipped" |
| `--update-existing` | Updates existing record | Row marked as "updated" |
| `--fail-on-duplicate` | Stops entire import | Import terminates with error |

### Fatal Errors
The script will stop if:
- Cannot authenticate with ArchivesSpace
- CSV file is not found
- Missing Parent RefID (all items must have parents)
- Invalid extent type (must match dropdown exactly)
- Duplicate found with `--fail-on-duplicate` flag

## Performance Considerations

- **Batch Size**: Default is 10 records per batch with 1-second pause
- **API Rate Limiting**: Script includes retry logic with delays
- **Large Imports**: For >1000 records, consider:
  - Running during off-peak hours
  - Increasing batch delays
  - Splitting CSV into smaller files

## Troubleshooting

1. **Check the log file first** - Most issues are clearly logged
2. **Verify parent ref_ids** - Use ArchivesSpace search to confirm
3. **Test with small batches** - Start with 5-10 records
4. **Validate CSV encoding** - Should be UTF-8

## Customization

To adapt for other collections:

1. **Modify date labels**: Change in `create_date_objects()`
2. **Adjust extent types**: Update in `create_extent_objects()`
3. **Add custom notes**: Extend `create_notes()`
4. **Change instance types**: Modify `create_instances()`

## Support

For issues specific to the JPC collection, consult the development team.
For general ArchivesSpace API questions, see: https://archivesspace.github.io/archivesspace/api/

## Version History

- v1.0 (2024): Initial release for JPC audiovisual collection
  - Basic CSV import functionality
  - Parent hierarchy support
  - Comprehensive error handling

## License

This script is provided as-is for archival processing purposes.
