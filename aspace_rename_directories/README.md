# ArchivesSpace Directory Processing Script

## Overview

This script automates two tasks for digitized AV assets from the JPC Archive:

1. **Updates ArchivesSpace records** with duration and physical details extracted from or confirmed by the digitized `.mkv` file.
2. **Renames directories** to append the ArchivesSpace `ref_id` for tracking and DAMS ingest.

## What It Does

For each `JPC_AV_*` directory, the script:

1. Searches ArchivesSpace for the archival object matching the directory's Component Unique Identifier (e.g., `JPC_AV_00001`).
2. Extracts the runtime of the `.mkv` file using `mediainfo`.
3. Updates the ArchivesSpace record:
   - Adds Duration as a Defined List subnote to the Physical Characteristics and Technical Requirements note (appended to any existing text subnotes, or creates a new phystech note if none exists).
   - Sets `physical_details` on all extents to `SD video, color, sound`.
4. Renames the directory to append `_refid_<ref_id>`.

## Directory Structure

**Before:**
```
JPC_AV_00001/
├── JPC_AV_00001.mkv
├── JPC_AV_00001_2024-02-07_checksums.md5
├── JPC_AV_00001_qc_metadata/
└── JPC_AV_00001_vrecord_metadata/
```

**After:**
```
JPC_AV_00001_refid_b645fa3ffd01ad7364c9658f83fdceda/
├── JPC_AV_00001.mkv
├── JPC_AV_00001_2024-02-07_checksums.md5
├── JPC_AV_00001_qc_metadata/
└── JPC_AV_00001_vrecord_metadata/
```

## Prerequisites

- Python 3.6 or higher
- `mediainfo` CLI tool installed and on your system PATH
- Required Python packages:
  ```bash
  pip install requests pymediainfo colorama
  ```
- `creds.py` configured at the repository root (see Installation)

## Installation

1. Copy the credentials template and add your credentials:
   ```bash
   cp creds_template.py creds.py
   ```

2. Edit `creds.py`:
   ```python
   baseURL = "https://api-aspace.jpcarchive.org"
   user = "your_username"
   password = "your_password"
   repo_id = 2
   resource_id = 7
   logs_dir = ""  # Optional: set to override default log location
   ```

   **Important:** Add `creds.py` to `.gitignore`.

## Usage

```bash
# Process all JPC_AV_* subdirectories in a folder
python3 aspace-rename-directories.py -d /path/to/videos

# Process specific directories directly
python3 aspace-rename-directories.py --single /path/to/JPC_AV_00001
python3 aspace-rename-directories.py --single /path/to/JPC_AV_00001 /path/to/JPC_AV_00002

# Dry run — preview changes without making them
python3 aspace-rename-directories.py -d /path/to/videos --dry-run

# Update ASpace records only, skip directory renaming
python3 aspace-rename-directories.py -d /path/to/videos --no-rename

# Rename directories only, skip ASpace record updates
python3 aspace-rename-directories.py -d /path/to/videos --no-update

# Also rename .mkv files to include ref_id
python3 aspace-rename-directories.py -d /path/to/videos --rename-mkv

# Enable debug logging
python3 aspace-rename-directories.py -d /path/to/videos --verbose
```

## Command-Line Options

| Option | Description |
|--------|-------------|
| `-d, --directory PATH` | Target directory containing `JPC_AV_*` subdirectories **(required unless `--single`)** |
| `--single PATH [PATH ...]` | Process specific directories directly (not their subdirectories) |
| `-n, --dry-run` | Preview changes without executing |
| `--no-rename` | Update ArchivesSpace only; skip directory renaming |
| `--no-update` | Rename directories only; skip ArchivesSpace record updates |
| `--rename-mkv` | Also rename `.mkv` files to include `ref_id` |
| `-v, --verbose` | Enable debug-level logging |

## ArchivesSpace Updates

### Duration
Added as a Defined List subnote to the Physical Characteristics and Technical Requirements (`phystech`) note:

```json
{
  "jsonmodel_type": "note_definedlist",
  "items": [
    {
      "jsonmodel_type": "note_definedlist_item",
      "label": "Duration",
      "value": "01:15:42"
    }
  ]
}
```

If a phystech note already exists (e.g., created during CSV import with transfer notes), Duration is appended to it. If no phystech note exists, one is created. The operation is idempotent — re-running removes and rewrites the Duration entry without duplicating it.

### Physical Details
Set on all extents:
```json
{
  "physical_details": "SD video, color, sound"
}
```

> **Note:** This hardcoded value is correct for most JPCA AV material. For tapes that deviate from the standard (BW, silent, HD), update the Physical Details field manually in ArchivesSpace after running the script.

## Logs

Written to `~/aspace_rename_reports/` by default. Override by setting `logs_dir` in `creds.py`.

```
~/aspace_rename_reports/rename_YYYYMMDD_HHMMSS.log
```

## Example Log Output

```
2024-12-20 15:30:25,123 [INFO] Successfully authenticated with ArchivesSpace
===============================================================================

2024-12-20 15:30:26,456 [INFO] Processing directory: JPC_AV_00001
2024-12-20 15:30:26,789 [INFO] Found archival object with Component Unique Identifier 'JPC_AV_00001'
2024-12-20 15:30:26,790 [INFO] RefID: b645fa3ffd01ad7364c9658f83fdceda, Archival Object ID: 12345
2024-12-20 15:30:27,101 [INFO] Extracted runtime: 01:15:42 for file: JPC_AV_00001.mkv
2024-12-20 15:30:27,200 [INFO] Found existing Physical Characteristics and Technical Requirements note - adding Duration defined list
2024-12-20 15:30:27,201 [INFO] Added Duration defined list to Physical Characteristics and Technical Requirements note: 01:15:42
2024-12-20 15:30:27,202 [INFO] Set physical_details to 'SD video, color, sound' on 1 extent(s)
2024-12-20 15:30:28,567 [INFO] Archival object updated successfully!
2024-12-20 15:30:29,123 [INFO] Directory renamed to: JPC_AV_00001_refid_b645fa3ffd01ad7364c9658f83fdceda

===============================================================================

2024-12-20 15:30:30,456 [INFO] Processing complete!
2024-12-20 15:30:30,457 [INFO] Processing Time: 00:00:05
```

## Notes

- The script matches directories to ArchivesSpace records using the Component Unique Identifier field (`component_id`), not a general keyword search. Each identifier must be unique.
- If multiple matches are found for a directory, the script logs a warning and uses the first result.
- If `.mkv` extraction or API updates fail for a directory, the script logs the error and moves on to the next directory.
- Directories already containing `_refid_` in their name are skipped.
- Authentication is always required, even when using `--no-update`, because the ArchivesSpace lookup for `ref_id` is needed for renaming.

## Troubleshooting

| Error | Solution |
|-------|----------|
| `mediainfo` not found | Install `mediainfo` and ensure it is on your system PATH |
| Authentication failed | Check `creds.py` credentials and ArchivesSpace URL |
| No archival object found | Verify the Component Unique Identifier exists in ArchivesSpace |
| Multiple matches found | Ensure identifiers are unique in ArchivesSpace |