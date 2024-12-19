# Update Video Metadata and Append ArchivesSpace Reference IDs to Directory Names

This Python script is designed to automate two critical tasks for handling digitized audiovisual (AV) assets from the JPC archive:

1. **Appending ArchivesSpace Reference IDs to Directory Names**:
   - Matches each AV directory with a corresponding archival object in ArchivesSpace using a unique identifier.
   - Appends the `ref_id` from ArchivesSpace to the directory name for seamless tracking.

2. **Updating Runtime in ArchivesSpace**:
   - Extracts the runtime of the `.mkv` video file within each directory.
   - Updates the `dimensions` field in the `extents` module of the associated archival object in ArchivesSpace with the runtime in `hh:mm:ss` format.

## How It Works

The script identifies directories containing digitized AV assets by their naming convention (e.g., `JPC_AV_00001`). Each directory is expected to contain an `.mkv` file alongside metadata or related files. The script performs the following steps for each directory:

1. **Search for Archival Object in ArchivesSpace**:
   - Uses the directory name as a keyword to locate the corresponding archival object.
   - If found, retrieves the `ref_id` and `archival_object_id`.

2. **Extract Runtime of `.mkv` File**:
   - Uses the `mediainfo` command-line tool to extract the duration of the `.mkv` file in `hh:mm:ss` format.

3. **Update the Archival Object**:
   - Updates the `dimensions` field in the `extents` module of the archival object to include the video runtime.

4. **Rename the Directory**:
   - Appends the retrieved `ref_id` to the directory name.

## Directory Structure Before Processing

```
JPC_AV_00001
├── JPC_AV_00001.mkv
├── JPC_AV_00001_2024-02-07_checksums.md5
├── JPC_AV_00001_qc_metadata
│   ├── JPC_AV_00001_2024_02_08_fixity.txt
│   ├── JPC_AV_00001_exiftool_output.txt
│   ├── JPC_AV_00001_ffprobe_output.txt
│   ├── JPC_AV_00001_mediaconch_output.csv
│   └── JPC_AV_00001_mediainfo_output.txt
└── JPC_AV_00001_vrecord_metadata
    ├── JPC_AV_00001.framemd5
    ├── JPC_AV_00001.mkv.qctools.mkv
    ├── JPC_AV_00001_QC_output_graphs.jpeg
    ├── JPC_AV_00001_capture_options.log
    └── JPC_AV_00001_vrecord_input.log
```

## Directory Structure After Processing

```
JPC_AV_00001_refid_b645fa3ffd01ad7364c9658f83fdceda
├── JPC_AV_00001.mkv
├── JPC_AV_00001_2024-02-07_checksums.md5
├── JPC_AV_00001_qc_metadata
│   ├── JPC_AV_00001_2024_02_08_fixity.txt
│   ├── JPC_AV_00001_exiftool_output.txt
│   ├── JPC_AV_00001_ffprobe_output.txt
│   ├── JPC_AV_00001_mediaconch_output.csv
│   └── JPC_AV_00001_mediainfo_output.txt
└── JPC_AV_00001_vrecord_metadata
    ├── JPC_AV_00001.framemd5
    ├── JPC_AV_00001.mkv.qctools.mkv
    ├── JPC_AV_00001_QC_output_graphs.jpeg
    ├── JPC_AV_00001_capture_options.log
    └── JPC_AV_00001_vrecord_input.log
```

## Preparing to Run the Script

### Prerequisites

1. **Install Dependencies**:
   - Python 3.6 or higher.
   - Required Python packages:
     - `requests`
     - `pymediainfo`
     - `colorama`
     - `authenticate` (custom module).
   - Ensure the `mediainfo` CLI tool is installed and accessible in your system's PATH.

2. **Configure ArchivesSpace API Credentials**:
   - Open the `creds_template.py` file in a text editor.
   - Fill in the following fields:
     ```python
     baseURL="https://api-aspace.best-archive-ever.org"
     user="your_username"
     password="your_password"
     ```
   - Save the file as `creds.py` in the same directory.

### Input Directory

- Navigate to the root directory containing the directories you wish to process.

## Running the Script

1. Open a terminal or command prompt.
2. Navigate to the root directory containing the target directories.
3. Run the script using Python:
   ```
   python3 <path-to-script>/aspace-video-update.py
   ```

## Example Log Output

The script logs all actions, including successes and errors. Example:

```
2024-12-20 15:30:25,123 [INFO] Login successful!
===============================================================================
2024-12-20 15:30:26,456 [INFO] Processing directory: JPC_AV_00001
2024-12-20 15:30:26,789 [INFO] Archival Object ID: 12345, RefID: b645fa3ffd01ad7364c9658f83fdceda
2024-12-20 15:30:27,101 [INFO] Extracted duration: 01:15:42 for file: JPC_AV_00001.mkv
2024-12-20 15:30:28,567 [INFO] Archival object updated successfully!
2024-12-20 15:30:29,123 [INFO] Directory renamed to: JPC_AV_00001_refid_b645fa3ffd01ad7364c9658f83fdceda
===============================================================================
2024-12-20 15:30:30,456 [INFO] Logout successful!
```

## Notes

- The script assumes each directory has a unique identifier (e.g., `JPC_AV_00001`) that matches exactly one archival object in ArchivesSpace. If multiple matches exist, the script logs a warning and skips renaming that directory.
- No changes are made to the contents of the directories or files; only the directory name is modified.
- If runtime extraction or API updates fail, the script logs the error and proceeds to the next directory.

## Troubleshooting

- **Error: `mediainfo` not found**:
  - Ensure `mediainfo` is installed and added to your system's PATH.

- **Multiple matches for a directory**:
  - Ensure identifiers are unique in ArchivesSpace.
  - Refine the ArchivesSpace query logic in the script if needed.

- **API Authentication Issues**:
  - Verify the `creds.py` file is configured correctly.
  - Ensure your ArchivesSpace account has necessary permissions.

