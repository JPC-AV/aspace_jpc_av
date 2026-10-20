# ArchivesSpace Directory Processing Script

## Overview

This script automates two tasks for digitized AV assets from the JPC Archive:

1. **Updates ArchivesSpace records** with duration and physical details extracted from or confirmed by the digitized media file (`.mkv` by default; `--mp4` for optical-disc transfers).
2. **Renames directories** to append the ArchivesSpace `ref_id` for tracking and DAMS ingest.

## Two Ways to Run It

| | `jpc-rename` (everyday runs) | The tool run directly |
|---|---|---|
| Setup | The root README's [Setup](../README.md#setup), which installs the command | The same `creds.py`, plus `requests` (`pip install -r requirements.txt` in the repo root) |
| Where | Any folder | `python3 aspace-rename-directories.py ...` from this folder (`aspace_rename_directories/`) |
| Environment | Production unless you add `--env sandbox` | `--env NAME` is required when `creds.py` has several environments (no default); with one, it is used automatically |
| Input | `--directory PATH` | `-d PATH`, or `--single PATH [PATH ...]` |
| Options | `--dry-run`, `--mp4`, `--no-color`, `--env sandbox` | Every option below |

Either way, `mediainfo` must be installed (see Prerequisites), and
**`--env sandbox` changes only which ArchivesSpace is used**: a real sandbox
run still renames the real folders, with the sandbox records' ref IDs. Try
the sandbox only on disposable copies of the folders.

## What It Does

For each folder named exactly `JPC_AV_<digits>` directly inside the given folder (nothing deeper is searched), the script:

1. Resolves the directory's Component Unique Identifier (e.g., `JPC_AV_00001`) to exactly one verified ArchivesSpace record — each search candidate is fetched and must match the identifier exactly within the AV resource. Zero matches, multiple matches, or a failed search all fail the directory with a message saying which it was.
2. Extracts the runtime of the media file using `mediainfo`. The directory must contain exactly one media file of the selected format, named after the directory — zero, several, or a mismatched name fail the directory rather than guessing which file's runtime to record. (In `--mp4` mode the media lives in the `access_<name>/` subdirectory — see below.)
3. Updates the ArchivesSpace record **only if something changed** (otherwise it is counted as already correct and nothing is written):
   - Sets Duration in the Physical Characteristics and Technical Requirements note — existing Duration entries are updated in place (in every phystech note, preserving neighboring items), or a Defined List subnote is added if none exists.
   - Fills a **blank** `physical_details` with `SD video, color, sound` on single-extent records — existing values are never overwritten, so manual corrections survive reruns; multi-extent records are left for staff.
4. Renames the directory to append `_refid_<ref_id>`.

**A real run asks first.** Every folder is first worked out with reads
only (the record, the media file, the runtime, and what step 3 would
change). A PLAN then shows every change - each current and new Duration,
the physical details fill, the new folder name - and every refused folder
with its reason. Only `yes` writes; anything else, Ctrl-C at
the prompt included, cancels with nothing written and nothing renamed. Only
the planned folders are then processed, each read again just before it is
written and refused if its planned changes no longer match. A dry run
(`--dry-run`) shows each folder's outcome, leaves ArchivesSpace and folder
names unchanged, and saves a log.

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

- `mediainfo` CLI tool installed and on your system PATH - it reads the runtimes
- Everything else - Python, the `jpc-` commands, `requests` and `creds.py` - comes from the root README's [Setup](../README.md#setup)

## Installation

Follow the root README's [Setup](../README.md#setup): it installs
`jpc-rename` with the other `jpc-` commands and explains `creds.py`. For
direct runs, `creds.py` and `requests` are all the tool needs; it picks the
environment as described in [Two Ways to Run It](#two-ways-to-run-it).

## Usage

Everyday runs, from any folder (production unless you add `--env sandbox`):

```bash
# Dry run - each folder's outcome; ArchivesSpace and folder names unchanged
jpc-rename --directory /path/to/videos --dry-run

# Real run - the PLAN, then type yes
jpc-rename --directory /path/to/videos

# Optical-disc .mp4 transfers instead of .mkv
jpc-rename --directory /path/to/discs --mp4
```

The tool run directly, from this folder, naming the environment
(`--env sandbox` for the sandbox):

```bash
cd ~/github/jpc/aspace_jpc_av/aspace_rename_directories

# Process all JPC_AV_<digits> folders directly inside a folder
python3 aspace-rename-directories.py -d /path/to/videos --env production

# Process specific folders, named one by one
python3 aspace-rename-directories.py --single /path/to/JPC_AV_00001 /path/to/JPC_AV_00002 --env production

# Dry run
python3 aspace-rename-directories.py -d /path/to/videos --env production --dry-run

# Update ASpace records only, skip directory renaming
python3 aspace-rename-directories.py -d /path/to/videos --env production --no-rename

# Rename directories only, skip ASpace record updates
python3 aspace-rename-directories.py -d /path/to/videos --env production --no-update

# Also rename the media file to include ref_id (.mkv batches only)
python3 aspace-rename-directories.py -d /path/to/videos --env production --rename-media

# Enable debug logging
python3 aspace-rename-directories.py -d /path/to/videos --env production --verbose
```

## Command-Line Options

`jpc-rename` takes only `--directory`, `--dry-run`, `--mp4`, `--no-color` and
`--env sandbox`; the rest are for direct runs.

| Option | Description |
|--------|-------------|
| `-d, --directory PATH` | The folder holding the `JPC_AV_<digits>` folders (only those directly inside are processed) **(required unless `--single`)** |
| `--single PATH [PATH ...]` | Process specific directories directly (not their subdirectories) |
| `-n, --dry-run` | Preview changes without executing |
| `--mp4` | Process optical-disc `.mp4` transfers instead of the default `.mkv` (see below) |
| `--no-rename` | Update ArchivesSpace only; skip directory renaming |
| `--no-update` | Rename directories only; skip ArchivesSpace record updates |
| `--rename-media` | Also rename the media file to include `ref_id` (`.mkv` batches only; `--rename-mkv` is an alias). Refused for a folder whose checksum manifest (`.md5`/`.sha256`...) names the media file (or whose manifests could not be read) - renaming would orphan that entry |
| `-v, --verbose` | Show debug detail too |
| `--env NAME` | Target environment from `creds.py` (required when several are configured) |
| `--no-color` | Disable colored output |

One media format per run: the default is `.mkv` (vrecord digitizations); `--mp4` switches the run to optical-disc transfers. Future formats (`--wav`, `--mp3`) will follow the same pattern — audio formats will skip the `physical_details` fill, since the video default doesn't apply to them.

## Optical-Disc Transfers (`--mp4`)

`--mp4` processes the directory layout produced by [makeiso-video.py](https://github.com/JPC-AV/optical_disc_jpc_av):

```
JPC_AV_14180/
├── JPC_AV_14180.iso              # preservation image (untouched)
├── JPC_AV_14180.iso.log.txt
├── JPC_AV_14180_manifest.json
├── JPC_AV_14180_tree.txt
└── access_JPC_AV_14180/
    ├── JPC_AV_14180.mp4          # the access copy - runtime comes from here
    ├── JPC_AV_14180.mp4.log.txt
    └── JPC_AV_14180_access_manifest.json
```

- The runtime is extracted from `access_<name>/<name>.mp4`; the record update (Duration, `physical_details`) is identical to `.mkv` runs.
- **Only the top-level directory is renamed.** The manifests record the inner filenames and paths, so nothing inside the structure is ever renamed — `--rename-media` is rejected in `--mp4` mode.
- **Multi-title discs** (`<name>_title02.mp4`, `_title03.mp4`, ... beside or instead of `<name>.mp4`) have no single runtime. They are refused on every run - running again never finishes one - and handled by hand:
  1. Complete the record's work by hand in ArchivesSpace, following the manual (4.D.iv).
  2. Then rename just that folder with the tool run directly. `--no-update` skips **all** record updates (it reads no media file and writes nothing to the record), which is why the record work comes first; once renamed, the folder is excluded from later runs.
     ```bash
     cd ~/github/jpc/aspace_jpc_av/aspace_rename_directories
     python3 aspace-rename-directories.py --single /path/to/JPC_AV_14180 --no-update --mp4 --env production
     ```
     It checks the record, shows a PLAN with the new folder name and asks for `yes`.
- A directory without an `access_<name>/` subdirectory (incomplete transfer) is failed, not skipped.

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

If Duration entries already exist (in any phystech note), they are updated in place — other items in the same defined list (and any other phystech notes) are preserved. If none exists, a Duration defined list is appended to the existing phystech note, or a new phystech note is created. The operation is idempotent — re-running converges on the current runtime without duplicating entries.

### Physical Details
Filled when the record has a **single extent** whose `physical_details` is blank:
```json
{
  "physical_details": "SD video, color, sound"
}
```

> **Note:** This default is correct for most JPCA AV material. For tapes that deviate from the standard (BW, silent, HD), set the Physical Details field manually in ArchivesSpace — the script only fills blanks and never overwrites an existing value, so manual corrections survive reruns. On records with multiple extents the script leaves all blanks alone (it can't tell which extent describes the video carrier), so fill those manually too.

## Output

The screen opens with what the run will do. A real run then shows the
PLAN and asks; after `yes` it shows each folder's steps under WRITING and
ends with the result:

```
Update ArchivesSpace and rename AV folders
------------------------------------------------------------
  Target:  PRODUCTION (https://api-aspace.jpcarchive.org, repo 2, resource 7)
  Input:   /Volumes/Drive/one_inch
  Mode:    update ArchivesSpace records + rename folders
  Media:   .mkv  (JPC_AV_00001/JPC_AV_00001.mkv)

[>] Successfully authenticated with ArchivesSpace
[>] Found 53 directories to process

------------------------------------------------------------
PLAN - what this run will change (nothing written yet)
------------------------------------------------------------

  JPC_AV_00001
    update   Duration (none) -> 01:15:42
    rename   folder -> JPC_AV_00001_refid_b645fa3ffd01ad7364c9658f83fdceda
...
  JPC_AV_04144
    refused  2 media files found (JPC_AV_04144.mkv, JPC_AV_04144_v2.mkv) - expected exactly one - left as it is

  Records:  50 to update, 2 already up to date (not rewritten)
  Folders:  52 to rename
  Refused:  1 (left as they are - see the PLAN)

  About to write to ArchivesSpace (PRODUCTION) and rename folders

  Type yes to go ahead, anything else to cancel: yes

------------------------------------------------------------
WRITING
------------------------------------------------------------

JPC_AV_00001
  [>] RefID: b645fa3ffd01ad7364c9658f83fdceda, Archival Object ID: 12345
  [>] Extracted runtime: 01:15:42 for file: JPC_AV_00001.mkv
  [OK] ArchivesSpace record updated: Duration -> 01:15:42
  [OK] Directory renamed to: JPC_AV_00001_refid_b645fa3ffd01ad7364c9658f83fdceda
...
------------------------------------------------------------
FOLDERS
------------------------------------------------------------
  Targets selected      53
  Done                  52
  Failed                 1

------------------------------------------------------------
CHANGES MADE
------------------------------------------------------------
  ArchivesSpace records updated      50
  Folders renamed                    52
  Records already correct (not rewritten)       2

------------------------------------------------------------
NEEDS ATTENTION
------------------------------------------------------------
  JPC_AV_04144  failed
      JPC_AV_04144: 2 media files found (JPC_AV_04144.mkv, JPC_AV_04144_v2.mkv) - expected exactly one. Skipping.

  Saved log:  /Users/you/aspace_rename_reports/rename_20260930_101500_48213.log
```

**FOLDERS** puts every target in exactly one line, so they add up to
*Targets selected*:

| Line | Meaning |
|------|---------|
| Done | Every requested step succeeded |
| Already up to date | Every requested step needed no change (only possible with `--no-rename`) |
| Partly done | Some changes were made and kept, others were not - e.g. the record was updated but the folder could not be renamed |
| Failed | No requested change was confirmed and kept. Preparation or cleanup leftovers may remain; check NEEDS ATTENTION before rerunning |
| Outcome unknown | A step's result is uncertain - an update whose reply was lost, or a rename that reported an error but may have landed |
| Not reached (the run stopped) | The run stopped - Ctrl-C or an unexpected error - before this target was processed |

**CHANGES MADE** counts only confirmed changes that were kept (a media
rename that was rolled back is not counted). **NEEDS ATTENTION** names each
target that did not finish, what was done, the problem, and any manual fix
(e.g. "Rename it back to ... before rerunning"). A folder rename that
reports an error but may have landed is *Outcome unknown*, and nothing is
rolled back: NEEDS ATTENTION gives both possible folder locations - and,
with `--rename-media`, the media file's old and new names - to check before
rerunning. For *Partly done* and
*Outcome unknown*: inspect the named paths and resolve the reported problem
before rerunning. A run that finishes processing exits 1 if any target
failed, is partly done or has an unknown outcome. Ctrl-C exits 130.

A dry run (`-n`) has no PLAN and no prompt: it shows each folder's
outcome - *Would update ArchivesSpace record*, *Would rename directory* -
and a result that says *Would be done*. ArchivesSpace and folder names stay
unchanged, and the log is saved.

RESULT appears after folder processing. A run cancelled at the prompt shows
none - it says nothing was written or renamed - and a run stopped by a login
problem or a missing folder shows the error and no RESULT.

**Exit codes:** `0` every folder done or already up to date (or none found);
`1` some folders refused, failed, partly done or of unknown outcome - or the
run stopped before writing (a `creds.py` or login problem, a missing folder,
or cancelled at the prompt), or writing the log failed after it opened
(below); `2` an argument was rejected, nothing done; `130` interrupted with
Ctrl-C (see below).

### Log file

A run writes a log to `~/aspace_rename_reports/` (or `rename_reports/`
under `logs_dir` in `creds.py`) - dry runs and cancelled runs too. It holds every
message with a timestamp, the command, the header and the result, the full
folder list, the shared client's messages, and the full detail of any
unexpected error (the screen shows one line and says the detail is in the
log). Nothing is created for `-h`, an argument mistake or a `creds.py`
problem: the run stops before the log starts.

If writing or closing the log fails after it has opened - a full or
disconnected disk - the run starts no further change: before the prompt it
stops with nothing written; while writing it stops before the next change,
keeping what was already done (a folder can be partly done - NEEDS ATTENTION
says what to fix). It then says `NOT saved log:` instead of `Saved log:`,
names the write error, adds "The log is incomplete. Retain the displayed
outcomes before closing Terminal." and exits 1 (Ctrl-C keeps 130). Detail
kept only in the log, such as an unexpected error's full traceback, may be
lost.

```
2026-09-30 10:15:02,118 [INFO] Command: python3 aspace-rename-directories.py -d /Volumes/Drive/one_inch
2026-09-30 10:15:02,118 [INFO]   Target:  PRODUCTION (https://api-aspace.jpcarchive.org, repo 2, resource 7)
...
2026-09-30 10:15:04,456 [INFO] Processing directory: JPC_AV_00001
2026-09-30 10:15:04,790 [INFO] RefID: b645fa3ffd01ad7364c9658f83fdceda, Archival Object ID: 12345
2026-09-30 10:15:05,101 [INFO] Extracted runtime: 01:15:42 for file: JPC_AV_00001.mkv
2026-09-30 10:15:06,567 [INFO] ArchivesSpace record updated: Duration -> 01:15:42
2026-09-30 10:15:07,123 [INFO] Directory renamed to: JPC_AV_00001_refid_b645fa3ffd01ad7364c9658f83fdceda
```

**Ctrl-C:**

- **While planning** (before the prompt): nothing has been written. The run
  says "Interrupted while planning" and exits 130.
- **At the prompt:** a cancel, like any answer but `yes` - nothing written
  or renamed, no RESULT, exit 1.
- **While writing:** the run stops and RESULT reports how far it got - the
  folders done, the one interrupted, and those not reached. A folder whose
  write was under way is marked *Outcome unknown*: compare the record in
  ArchivesSpace and the folder on disk with the PLAN and RESULT before
  rerunning. Exit 130.
- **While logging out** (after every folder was processed): RESULT still
  shows every outcome - they stand - and says the run was interrupted while
  logging out. Exit 130.

The log holds everything up to the interruption.

## Notes

- The script matches directories to ArchivesSpace records using the Component Unique Identifier field (`component_id`); every search candidate is fetched and verified as an exact match within the AV resource.
- If multiple verified matches exist for one identifier, the directory FAILS with a clean-up-duplicates message — the script never picks one arbitrarily.
- A failed search (network/server error) is reported as such, distinct from "no record found", and fails the directory so it is retried on a later run.
- Directory names must be exactly `JPC_AV_<digits>`; anything else (including already-renamed `_refid_` directories) is not processed. Only folders directly inside `-d` are checked - nothing deeper.
- If `.mkv` extraction or API updates fail for a directory, the script logs the error and moves on to the next directory.
- Authentication is always required, even when using `--no-update`, because the ArchivesSpace lookup for `ref_id` is needed for renaming.
- `--no-update` renames directories **without** requiring a media file. A directory renamed this way (e.g. before its transfer finished) gets the `_refid_` suffix and is therefore **excluded from all future runs** — its record will never receive a Duration unless you process it manually. Only use `--no-update` on directories whose records are already up to date.

## Troubleshooting

| Error | Solution |
|-------|----------|
| `mediainfo` not found | Install `mediainfo` and ensure it is on your system PATH |
| `unrecognized arguments - not shown, ...` | A folder path typed without `-d`: put `-d` in front of it (or use `--single` for folders named one by one), as the lines below the error say. What was typed is not repeated, in case it was a password |
| Authentication failed | Check `creds.py` credentials and ArchivesSpace URL |
| No record with this Component Unique Identifier | Verify the identifier exists in ArchivesSpace (AV resource) |
| N records share this Component Unique Identifier | Clean up the duplicate records in ArchivesSpace first |
| Search failed ... retry later | Transient network/server problem — the record was NOT assumed missing; rerun |
| N media files found - expected exactly one | Remove or relocate extra media files from the directory |