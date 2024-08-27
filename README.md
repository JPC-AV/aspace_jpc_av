# Append an ASpace Reference ID to Directory Names

This script appends a reference ID (ref_id) from ArchivesSpace (ASpace) to the names of folders that contain digitized video files. It identifies folders by matching a unique identifier, which is both the folder name and the filename of the digitized content, with an archival object record in ASpace. This identifier is also physically marked on the tape and the case of the corresponding audiovisual (AV) object in the JPC archive.

In detail, each AV object is linked to an archival object record in ASpace, where the identifier in the directory name matches the identifier in the corresponding archival object record within ASpace. The script performs a keyword search in ASpace; when it finds an archival object with an identifier matching that of a directory, it retrieves the ref_id for that archival object and appends it to the directory name. The contents of the directory, including the video file and any other files, remain unchanged.

**The indifier structure is: JPC_AV_00001**

## Directory Structure Before Renaming:

```
JPC_AV_01660
├── JPC_AV_01660.mkv
├── JPC_AV_01660_2024-02-07_checksums.md5
├── JPC_AV_01660_qc_metadata
│   ├── JPC_AV_01660_2024_02_08_fixity.txt
│   ├── JPC_AV_01660_exiftool_output.txt
│   ├── JPC_AV_01660_ffprobe_output.txt
│   ├── JPC_AV_01660_mediaconch_output.csv
│   └── JPC_AV_01660_mediainfo_output.txt
└── JPC_AV_01660_vrecord_metadata
    ├── JPC_AV_01660.framemd5
    ├── JPC_AV_01660.mkv.qctools.mkv
    ├── JPC_AV_01660_QC_output_graphs.jpeg
    ├── JPC_AV_01660_capture_options.log
    └── JPC_AV_01660_vrecord_input.log
```
Upon successfully finding the matching ASpace archival object, the script will rename the directory to include the ASpace ref_id.

## Preparing to Run the Script

Before running the script, you must provide your ASpace API credentials:

1. open the `creds_template.py` in your favorite text editor. 
1. fill in the three needed fields: "baseURL", "user", and "password" as shown below:
    -   baseURL=""https://api-aspace.best-archive-ever.org" "
    -   user="prince"
    -   password="rosebud"
1. Save this file as `creds.py` in the same directory as `creds_template.py`. The `authenticate.py` script will look for the `creds.py` file to import the credentials.

## Running the Script

1. Navigate to the directory containing the directories you wish to rename by appending the ASpace ref_id.
1. Run the `aspace-rename-directory.py` script from within the directory that contains the target directories, like so:

`python3 <path-to-your-local-script>/aspace-rename-directories.py JPC_AV_01660`

## Example Output:

1. After running the script, the directory will be renamed to include the ASpace ref_id, as shown below:
```
JPC_AV_01660_refid_b645fa3ffd01ad7364c9658f83fdceda
├── JPC_AV_01660.mkv
├── JPC_AV_01660_2024-02-07_checksums.md5
├── JPC_AV_01660_qc_metadata
│   ├── JPC_AV_01660_2024_02_08_fixity.txt
│   ├── JPC_AV_01660_exiftool_output.txt
│   ├── JPC_AV_01660_ffprobe_output.txt
│   ├── JPC_AV_01660_mediaconch_output.csv
│   └── JPC_AV_01660_mediainfo_output.txt
└── JPC_AV_01660_vrecord_metadata
    ├── JPC_AV_01660.framemd5
    ├── JPC_AV_01660.mkv.qctools.mkv
    ├── JPC_AV_01660_QC_output_graphs.jpeg
    ├── JPC_AV_01660_capture_options.log
    └── JPC_AV_01660_vrecord_input.log
```

This updated structure keeps the directory's original contents intact and while adding the ArchivesSpace reference ID (ref_id) into the directory name. When importing the video file, the Smithsonian Digital Asset Management System (DAMS) will extract the ref_id from the file's parent directory to include it in the DAMS record. This will facilitate correct identification and tracking of the file further down stream.

**Note**: *Currently, the script relies on a basic keyword search assuming that JPC identifiers are unique to individual archival objects. However, if these identifiers appear in multiple archival objects, this approach may not be sufficient. In such cases, the script's search strategy can be refined to specifically target the "Child Indicator" field where the identifier is located*
