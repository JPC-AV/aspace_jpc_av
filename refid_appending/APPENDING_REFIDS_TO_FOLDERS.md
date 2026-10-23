# Appending RefIDs to Folders

After digitization, each `JPC_AV_xxxxx` folder in a batch is linked to its item record in ArchivesSpace. The operation:

- records the media file's runtime as the Duration in the record's Physical Characteristics and Technical Requirements note, and fills a blank physical details where it applies;
- appends the record's RefID (the 32-character ref ID ArchivesSpace assigns) to the folder's name: `JPC_AV_00001/` becomes `JPC_AV_00001_refid_<RefID>/`.

The command is `jpc-rename`, which runs the script `refid_appending/aspace-rename-directories.py`. It writes to ArchivesSpace and renames real folders on disk; it never changes Airtable. `JPC_AV_xxxxx` is the catalog number: `CATALOG_NUMBER` in Airtable, the Component Unique Identifier in ArchivesSpace.

The processing manual owns the rules the tool applies: folder naming in [section 1.F](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#1f-directory-names-after-archivesspace-linking), the two fields in [section 0.B](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#0b-fields-populated-via-directory-processing-script). For the full option list and outputs, see `jpc-rename --help`.

**Contents:** [Before you start](#before-you-start) - [The after-digitization sequence](#the-after-digitization-sequence) - [Running a batch](#running-a-batch) - [How the tool decides](#how-the-tool-decides) - [Problems and recovery](#problems-and-recovery) - [The log](#the-log) - [Running the tool directly](#running-the-tool-directly)

## Before you start

**Setup.** Follow the [JPC AV Tools Quick Start](../QUICK_START.md) and activate the tools' Python environment. Folder work needs one more program, `mediainfo`, which reads the runtimes. If it is installed, this prints its location:

```bash
command -v mediainfo
```

It is usually installed already - vrecord and other tools the team uses bring it with them. If not, the [quick start](../QUICK_START.md#1-before-you-begin) shows how to install it.

**Environment.** Every run needs `--env production` or `--env sandbox`. There is no default, and a command never switches to another environment.

**The folders are real in either environment.** `--env sandbox` changes only which ArchivesSpace is used: a real sandbox run still renames the folders, with the sandbox records' RefIDs, which may not match production. Try the sandbox only on disposable copies of the folders. The sandbox is refreshed from production from time to time, so sandbox records are temporary practice.

**The batch folder.** `BATCH` below is the folder that directly holds the digitized `JPC_AV_xxxxx` folders, such as `/Volumes/AV_DRIVE/batch`. Dragging it from Finder into Terminal gives its full path; quote a path with spaces.

## The after-digitization sequence

Replace `ENV` with `production` or `sandbox` - the same on every step. Sandbox work stops before DAMS ingest, and sandbox rename runs use disposable copies: the folders are renamed in either environment.

1. Dry run - check every folder:

   ```bash
   jpc-rename --directory BATCH --env ENV --dry-run
   ```

2. Real run - read the PLAN, then type `yes`:

   ```bash
   jpc-rename --directory BATCH --env ENV
   ```

3. DAMS ingest, outside these tools (production only).

4. About a day after ingest, check which items are live in MADS (no `--env`: it reads the public MADS site; options and results are in [Importing and Updating Data](../data_import_export/IMPORTING_AND_UPDATING_DATA.md#check-which-items-are-live-in-mads)):

   ```bash
   jpc-mads --directory BATCH
   ```

For optical-disc batches, add `--mp4` to both `jpc-rename` commands:

```bash
jpc-rename --directory BATCH --env ENV --dry-run --mp4
jpc-rename --directory BATCH --env ENV --mp4
```

## Running a batch

### 1. Dry run

The dry run checks every folder as a real run would, reading only, and shows each folder's outcome ("Would update ArchivesSpace record", "Would rename directory") and a "FOLDERS - dry run" summary. Nothing is written or renamed; the log is saved. Check that:

- the opening `Target` line names the environment you meant, and `Media` the format;
- `Targets selected` matches the number of item folders (if none, check that `BATCH` directly holds them and they are not already renamed);
- each failed folder is fixed ([Refused folders](#refused-folders)) and dry-run again, or left for later - the others go ahead without it.

### 2. Real run: the PLAN and yes

The real run checks every folder again, reading only, then shows the PLAN:

```text
PLAN - what this run will change (nothing written yet)

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

  Type yes to go ahead, anything else to cancel:
```

Each folder shows its current and new Duration, any fill (`Physical details (blank) -> 'SD video, color, sound'`) and its new name - or `already up to date` (record not rewritten, folder still renamed), or `refused` and why. Check the environment before typing `yes`: the opening `Target` line always names it, and `About to write` names it whenever a record will be updated.

Only `yes` writes. Anything else, Ctrl-C at the prompt included, cancels: nothing is written or renamed. When nothing would change, nothing is asked.

After `yes`, only the PLAN's folders are processed, each read again just before it is written and refused if its planned changes no longer match ("changed after the PLAN"). The record is updated first, then the folder renamed. If the update fails, nothing is renamed; a successful update is not rolled back if the rename fails.

### 3. Read the result

```text
FOLDERS
  Targets selected      53
  Done                  52
  Failed                 1

CHANGES MADE
  ArchivesSpace records updated                50
  Folders renamed                              52
  Records already correct (not rewritten)       2

NEEDS ATTENTION
  JPC_AV_04144  failed
      JPC_AV_04144: 2 media files found (JPC_AV_04144.mkv, JPC_AV_04144_v2.mkv) - expected exactly one. Skipping.
```

**FOLDERS** counts each folder once: done, already up to date, partly done (some changes kept, others not), failed (refused folders included), outcome unknown, or not reached (the run stopped first). **CHANGES MADE** counts only confirmed changes that were kept. **NEEDS ATTENTION** names each unfinished folder: what was done, the problem and any manual fix.

## How the tool decides

### Which folders it reads

Only folders directly inside `BATCH` are checked - nothing deeper - and only those named exactly `JPC_AV_` followed by digits. An already renamed folder (`JPC_AV_xxxxx_refid_...`) does not match, so every later run skips it, in either environment. A symlinked folder is refused.

Each run handles one media format and reads only the media file. The default is a vrecord `.mkv` delivery:

```text
JPC_AV_00001/
├── JPC_AV_00001.mkv
├── JPC_AV_00001_2024-02-07_checksums.md5
├── JPC_AV_00001_qc_metadata/
└── JPC_AV_00001_vrecord_metadata/
```

With `--mp4`, an optical-disc package from [makeiso-video.py](https://github.com/JPC-AV/optical_disc_jpc_av):

```text
JPC_AV_14180/
├── JPC_AV_14180.iso
├── JPC_AV_14180_manifest.json
└── access_JPC_AV_14180/
    ├── JPC_AV_14180.mp4                    the runtime is read from here
    └── JPC_AV_14180_access_manifest.json
```

Only the `JPC_AV_xxxxx` folder itself is renamed; everything inside keeps its name, and no checksum manifest changes. Audio deliveries are not yet handled ([manual Appendix B](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#appendix-b-open-questions-and-items-under-discussion)).

### Checks before anything is written

A folder that fails a check is refused and left as it is; the others go ahead.

1. **One record:** the `JPC_AV_xxxxx` matches exactly one item record in the AV resource, with a valid RefID. A failed search is reported as such, never as "not found".
2. **One media file, named after the folder:** exactly one `.mkv` in the folder (with `--mp4`, one `.mp4` in `access_JPC_AV_xxxxx/`), named exactly after the folder, letter case included. A `JPC_AV_00002.mkv` inside `JPC_AV_00001/` is refused, never measured. macOS `._` files are ignored.
3. **A runtime:** `mediainfo` reads an `hh:mm:ss` runtime from it.
4. **A free name:** no folder with the new name exists.
5. **One title:** with `--mp4`, not a multi-title disc (`JPC_AV_14180_title02.mp4` and so on), which has no single runtime.

### What changes in ArchivesSpace

- **Duration:** every existing Duration entry, in any Physical Characteristics and Technical Requirements note, is set to the runtime; other entries are kept. A record without one gets the Duration list, and the note if it has none. Reruns never duplicate it ([exact structure](../data_import_export/docs/CSV_TO_ASPACE_MAPPING.md#added-after-digitization-aspace-rename-directoriespy)).
- **Physical details:** a blank value is set to `SD video, color, sound` on a record with exactly one extent. An existing value is never changed, so corrections made in ArchivesSpace survive reruns. A record with no extent or several gets no fill. That is not policy: its extents are corrected and its physical details set by hand ([manual 3.E](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#3e-when-to-use-file-vs-item-level)). The PLAN does not flag such a record; only the log mentions it. Tapes that differ (BW, silent, HD) are set by hand, before or after the run ([manual 7.C](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#7c-physical-details-for-extent)).
- A record that already has this runtime and needs no fill is not rewritten.

## Problems and recovery

### Refused folders

Fix what the reason names ([Checks before anything is written](#checks-before-anything-is-written)), then run the same commands again; renamed folders are skipped.

| Reason (in part) | What to do |
|---|---|
| no record with this Component Unique Identifier | Check the `JPC_AV_xxxxx` and `--env`; a new item needs its record first ([Importing and Updating Data](../data_import_export/IMPORTING_AND_UPDATING_DATA.md)) |
| N records share this Component Unique Identifier | Clean up the duplicates in ArchivesSpace |
| search failed | Connection or server problem; run again |
| no .mkv (or .mp4) file found, N media files found, does not match directory name | Fix the folder's contents; for an optical-disc batch, add `--mp4` |
| no access_JPC_AV_xxxxx/ directory found | Incomplete optical-disc transfer, or `--mp4` used on an `.mkv` batch (check the `Media` line) |
| Could not extract a valid runtime | Check the file, and that `mediainfo` is installed |
| Target directory already exists | Find out which folder is right before changing either |
| changed after the PLAN | Run again |
| multi-title disc | See below |

A login problem or a missing `BATCH` folder stops the run with an error and no RESULT; see the [Quick Start](../QUICK_START.md) for login problems.

### Multi-title discs

`jpc-rename` refuses a multi-title disc every time, so rerunning never finishes one:

1. Complete the record by hand in ArchivesSpace. Which runtime to record - one per titleset or a single aggregate - is not yet decided; consult before proceeding ([manual Appendix B](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#appendix-b-open-questions-and-items-under-discussion)). Enter its Duration as manual [4.D.iv](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#4div-physical-characteristics-and-technical-requirements-note) describes, and its physical details if blank.
2. Rename just that folder with the direct tool. `--no-update` reads no media file and changes no record, which is why the record work comes first:

   ```bash
   cd ~/github/jpc/aspace_jpc_av
   python3 refid_appending/aspace-rename-directories.py --single PATH --no-update --mp4 --env production
   ```

   `PATH` is that `JPC_AV_xxxxx` folder. The tool checks the record, shows a PLAN with the new name and asks for `yes`.

### Unfinished folders and interruptions

- **Partly done:** the record was updated but the folder not renamed. Fix the reason shown and run again: the record comes out already up to date and the folder is renamed.
- **Outcome unknown:** a write was interrupted or its result is unknown; nothing is rolled back. Compare the record in ArchivesSpace and the folder on disk with the PLAN and RESULT before running again (for an uncertain rename, NEEDS ATTENTION gives both possible folder locations).
- **A manual fix named:** do it first, for example deleting an empty placeholder folder the run could not remove.
- **Ctrl-C** while planning writes nothing; at the prompt it cancels. While writing, it stops the run, and RESULT shows what each folder reached.

Before running again, deal with every folder that is partly done, has an unknown outcome or has a manual fix named. A refused folder can be fixed or left as it is: the next run refuses it again and the others go ahead. Then dry-run with the same `--env`.

## The log

Every run saves `rename_YYYYMMDD_HHMMSS_PID.log` in `~/aspace_rename_reports/`, or in `rename_reports/` inside the `logs_dir` folder set in `creds.py` - dry runs and cancelled runs too, but not a run stopped by an argument or `creds.py` problem. The run prints its path ("Saved log:"). It holds every message, timestamped, and is the run's only record.

If writing the log fails after it opens - a full or disconnected disk - the run starts no further change. It prints "NOT saved log:" and "The log is incomplete. Retain the displayed outcomes before closing Terminal." (exit 1, or 130 if the run was also interrupted with Ctrl-C).

## Running the tool directly

`jpc-rename` accepts only `--directory`, `--env`, `--dry-run`, `--mp4` and `--no-color`. The script has further options for exceptions; its help lists them all. Run it from the tools repository folder with the environment active:

```bash
cd ~/github/jpc/aspace_jpc_av
python3 refid_appending/aspace-rename-directories.py --help
```

Its batch folder option is `-d PATH`. Run directly, it uses the only environment in `creds.py`; with several configured, it requires `--env NAME`.

- `--single PATH [PATH ...]` - these `JPC_AV_xxxxx` folders themselves, in place of `-d`.
- `--no-update` - rename only; no media file is read, nothing is written to the record. The renamed folder is skipped by every later run, so its record never gets a Duration from the tool. Use it only when the record is already complete.
- `--no-rename` - update ArchivesSpace only; the folder keeps its name, so a later run selects it again.
- `--rename-media` - also rename the media file to `JPC_AV_xxxxx_refid_<RefID>.mkv`. Only for `.mkv` batches (refused with `--mp4`, whose manifests record the inner names), and refused for a folder whose checksum manifest names the media file or cannot be read, since the rename would orphan that entry.
