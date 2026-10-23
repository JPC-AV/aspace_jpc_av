# Importing and Updating Data

This guide covers the JPC AV data work across Airtable and ArchivesSpace: pulling Airtable views, checking items, preparing CSVs, creating and updating item records, recording production results in Airtable, exporting records and checking MADS. Each step except the record export has a short `jpc-` command. Its help, `jpc-STEP --help`, lists every option, output and exit code; this guide gives the complete procedures, with more on files, eligibility and recovery.

Processing policy - arrangement, hierarchy, titles - is in the [processing manual](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md). Digitized folders are in [Appending RefIDs to Folders](../refid_appending/APPENDING_REFIDS_TO_FOLDERS.md).

## Contents

1. [Before a run](#before-a-run)
2. [Create new item records](#create-new-item-records)
3. [Update existing item records](#update-existing-item-records)
4. [Check and export](#check-and-export)
5. [Prepare the CSV](#prepare-the-csv)
6. [Read results and saved files](#read-results-and-saved-files)
7. [Write-back eligibility and recovery](#write-back-eligibility-and-recovery)
8. [Troubleshooting](#troubleshooting)
9. [Advanced direct use](#advanced-direct-use)

## Before a run

Set up the tools once with the [quick start](../QUICK_START.md). Each session, connect the VPN and activate the environment that has the commands. Production access and the Airtable write token are for operators: see [production and write access](../QUICK_START.md#10-production-and-write-access-operators-only).

### Choose the environment

`jpc-check` (or `jpc-lookup`), `jpc-fill`, `jpc-import`, `jpc-update` and `jpc-rename` talk to ArchivesSpace and need `--env production` or `--env sandbox` on every run. There is no default: without it, a command stops before anything runs (exit 2); with an environment not configured, it stops (exit 1) and never switches. `jpc-pull`, `jpc-writeback` and `jpc-mads` take no `--env`. Use the same `--env` throughout a batch.

- **Airtable has one real base.** `jpc-pull` reads it and `jpc-writeback` writes to it, whichever ArchivesSpace you use.
- **The sandbox is practice.** It is refreshed from production from time to time, so records created there do not last, and a sandbox PLAN is not a production PLAN. Sandbox work stops before `jpc-writeback` and DAMS ingest.
- **`jpc-rename` renames real folders**, even with `--env sandbox`; practise only on disposable copies.
- **MADS is public**; `jpc-mads` only reads it.

### Give the input path

A bare file name or relative path is read from your current folder; a full path works anywhere. Each command prints the full path of every file it saves: copy it, or drag the file from Finder into the Terminal. Quote a path with spaces: `'My Batch.csv'`.

Below, replace `NAME` with the Airtable view's exact name; `PULL`, `READY` and `REPORT` with the paths printed after "Saved pulled CSV:", "Saved ready CSV:" and "Saved import report:"; and `BATCH` with the folder holding the digitized JPC_AV_xxxxx folders.

### What each command reads and writes

| Command | Reads | Writes or saves |
|---|---|---|
| `jpc-pull` | Airtable | pulled CSV |
| `jpc-check`, `jpc-lookup` | ArchivesSpace, the pull | CSV with `--output` |
| `jpc-fill` | ArchivesSpace | ready and review CSVs |
| `jpc-import`, `jpc-update` | ArchivesSpace | **ArchivesSpace**, after `yes`; reports, log |
| `jpc-writeback` | import report and records file, Airtable | **Airtable** (`--run`, after `yes`); outcomes CSV |
| `jpc-mads` | public MADS | MADS report |
| `jpc-rename` | ArchivesSpace, media files | **ArchivesSpace and folder names**, after `yes`; log |
| direct export | ArchivesSpace (MADS with `--mads-live`) | export CSV |

Only the writing steps change anything outside your computer, and each shows its changes and asks for `yes` first.

## Create new item records

1. Make the Airtable view
2. Pull it (`jpc-pull`)
3. Optional: check which items already exist (`jpc-check`)
4. Fill parents: save ready and review CSVs (`jpc-fill`)
5. Dry-run the import and read the PLAN (`jpc-import`)
6. Run the import: the PLAN again, then type `yes` (`jpc-import`)
7. Record the results in Airtable, production only (`jpc-writeback`)

The commands show the production workflow. A sandbox rehearsal uses `--env sandbox` on every ArchivesSpace step and stops after step 6.

### 1. Make the Airtable view

In `<<< ASpace_import >>>`, make a collaborative grid view for the batch, named without spaces ([manual 0.E](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#0e-where-the-data-lives-and-how-it-moves)). Filter out rows whose `ASpace Item Record Created` is Yes and rows with `ASpace Hold` ticked. Show the nine import columns plus `ASpace File Type` and `EJS Episode` ([Prepare the CSV](#prepare-the-csv)), and keep `EJS Episode` filled.

### 2. Pull the view

```bash
jpc-pull --view NAME
```

Checkpoint: RESULT counts rows, columns, held rows and open issues, and "Saved pulled CSV:" gives the path. The file, `{VIEW}_YYYYMMDD_HHMM.csv`, goes to `data_import_export/__airtable_exports__/` in your checkout, from whichever folder you run. The pull warns if an import column is missing. Leave the file as pulled; if Airtable changes, pull again and use only the new file.

### 3. Check which items already exist (optional)

```bash
jpc-check --file PULL --env production
```

One item already in ArchivesSpace stops the whole import. Leave such items out of the view, or [record them in Airtable by hand](#record-a-created-item-by-hand), then pull again.

### 4. Fill parents

```bash
jpc-fill --file PULL --env production
```

`jpc-fill` fills blank `ASpace Parent RefID` cells and nothing else. `EJS Episode` and `ASpace File Type` identify the parent - for example the Edited file under Episode 4006 - and exactly one match fills the cell. If `EJS Episode` is blank, the episode in `ASpace Title` is used; if both name one, they must agree. A parent RefID already in the pull is never replaced. Airtable, ArchivesSpace and the pull are unchanged.

Checkpoint: RESULT counts parent-ready and review rows, grouped by reason; "Saved ready CSV:" and "Saved review CSV:" give two files beside the pull:

- `jpc-fill_{VIEW}_YYYYMMDD_HHMM_parent_ref-id_ready_for_ASpace_import.csv` - the **ready file**, used by every later step. Ready means parent-ready: the import dry run can still refuse a row.
- `jpc-fill_{VIEW}_YYYYMMDD_HHMM_needs_human_review.csv` - the **review file**, saved even when empty, giving each row's problem (`Parent Note`) and where to look first (`Fix in`).

Exit 0: every row is ready. Exit 2: some rows need review - expected.

#### Work through the review file

- **`Airtable (hold)`** - the item is held. Once the issue is resolved, clear `ASpace Hold`.
- **`Airtable`** - the sheet needs a person: an episode that is TBD or several, a missing episode or file type, an episode that disagrees with the title, a supplied parent that differs from the lookup's (the note gives the lookup's RefID to compare), or Raw footage. Correct Airtable, or enter the parent's RefID in `ASpace Parent RefID` there. For Raw, the parent is Raw itself for an independent tape, or the set's own file record beneath Raw for a tape in a multi-tape set ([manual 3.E](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#3e-when-to-use-file-vs-item-level)).
- **`Airtable, then ArchivesSpace`** - the lookup found no matching record, or several: see below.

Then pull and fill again; review rows are not imported until they come back ready. `Parent Note` is not copied to Airtable: paste any text worth keeping into `ASpace Issue`.

#### Review rows whose parent cannot be found

"Airtable, then ArchivesSpace" means: check Airtable first, and turn to the ArchivesSpace hierarchy only if Airtable is right.

1. **Check Airtable's `EJS Episode` and `ASpace File Type`** (or the title's episode, if `EJS Episode` is blank). If either is wrong, correct it, then pull and fill again.
2. **If Airtable is right, the ArchivesSpace side needs attention. Do not create the missing record yourself.**
   - **A missing Edited, Raw or Promo grouping:** these production-stage groupings are pre-created, and processing staff do not create them. Hold the item - tick `ASpace Hold` in Airtable, with the reason in `ASpace Issue` - pull again after ticking the hold, and contact the designated archivist named in [manual 3.B](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#episode-vs-season-sub-series) (holds: [0.E](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#rules-that-keep-the-two-in-step)).
   - **A missing episode:** sub-series are not created without prior consultation ([manual 3.A](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#3a-overview)). Hold the item the same way and ask.
   - **Several matching records:** if it is clear which is right, enter its RefID in `ASpace Parent RefID` in Airtable; otherwise hold the item, with the evidence in `ASpace Issue`, and ask.
   - **"The matching file record has no ref_id":** run `jpc-fill` again later.
3. Once settled, clear any hold, then pull and fill again.

The one record here that processing staff may create is a **multi-tape unit's own file record beneath Raw**, whose title is defined by the Media Archivist ([manual 3.E](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#3e-when-to-use-file-vs-item-level), [4.C](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#4c-file-level-description)).

#### When the fill stops or refuses

- **"duplicate episode key ... correct the hierarchy in ArchivesSpace and rerun"** (exit 1): two episode records reduce to one key, such as "Episode 09" and "Episode 9". Nothing is saved until they are corrected in ArchivesSpace.
- **An output file already exists** (exit 2): nothing is replaced. Pull again for a new name, or move the earlier pair aside.
- **Interrupted:** the review file is saved first; one without its ready file must be deleted before running again.

### 5. Dry-run the import

```bash
jpc-import --file READY --env production --dry-run
```

The dry run checks the CSV, then every row against live ArchivesSpace (not already there, parent exists, valid format, unambiguous container, not on hold). It writes and saves nothing. If every row passes, it shows the PLAN:

```text
PLAN - what this run will do (nothing written yet)
  create   JPC_AV_01521  Ebony/Jet Showcase, Episode 5021
           under:     Ebony/Jet Showcase, TV series > Season 5 > Episode 5021 > Edited
           dates:     creation 1990-03-09    format: DVD    container: new AV Case
           phystech:  video has visual timecode throughout

  1 to create (1 new AV Case container(s)), 0 to skip, 0 refused
```

Read each title, the parent it goes `under:`, the stored dates, the format, whether the container is new, and the notes. If any row fails, the run prints "... failed preflight - ABORTING, nothing was written" and lists each problem row instead. Correct each at its source, then pull, fill and dry-run again.

### 6. Run the import

```bash
jpc-import --file READY --env production
```

The run checks again, shows the PLAN, then asks:

```text
  About to write to ArchivesSpace (PRODUCTION)
    Create 40 record(s), with 38 new AV Case container(s)
    Skip 0, refused 0

  Type yes to write, anything else to cancel:
```

Check the environment in parentheses. Only `yes` writes. A row that fails while being written is reported and the run moves on; created records are not rolled back. Just before each write the JPC_AV_xxxxx is looked up again: if a record with it has appeared since the checks, a run without `--keep-going` stops there and writes no later rows (they show as not reached). RESULT counts each outcome, then each saved file is listed, for example:

```text
  Saved import report:  ~/aspace_import_reports/import_report_20260929_084410_5702.json
```

The screen shows the full path in place of `~`. This `.json` file is the `REPORT` for the write-back; a production run that created records also prints the exact `jpc-writeback` command under "NEXT STEP". **After `--env sandbox`, stop here.**

#### A partial result

```text
  PARTIAL run: 38 created, 1 outcome unknown, 1 not reached (interrupted). The write-back records only the 38 created.
  Check these in ArchivesSpace before rerunning - they may exist: JPC_AV_01523
```

- **Created** rows are in ArchivesSpace; the write-back records only those.
- **Outcome unknown**: a write was sent but its result is not known (a lost reply, or Ctrl-C mid-write). Check each "Outcome unknown" JPC_AV_xxxxx in ArchivesSpace before rerunning - the record may exist.
- **Not reached, failed or refused** rows were not created. Correct each, then pull, fill and import them, in a view without the items now created.

**Wait a minute or two before rerunning** after a run that created records: the duplicate check uses ArchivesSpace's search index, which updates on a short delay, so an immediate rerun could create a duplicate.

#### Rows that already exist

Without `--keep-going`, one row already in ArchivesSpace, or any other problem row (a hold included), stops the whole run before anything is written; the routine fix is a view that leaves those items out. `--keep-going` is for deliberate recovery, such as finishing a partly created batch:

```bash
jpc-import --file READY --env production --keep-going --dry-run
```

It skips existing rows, refuses rows failing other live checks (holds included) and creates the rest; the PLAN lists each. A CSV problem still stops the run. Do not import skipped rows again: confirm each record, then [record it by hand](#record-a-created-item-by-hand).

### 7. Record the results in Airtable

Production only, promptly after the import. Preview, then write:

```bash
jpc-writeback --report REPORT
```

```bash
jpc-writeback --report REPORT --run
```

It checks the report, reads Airtable again (three tables, about a minute each) and shows its PLAN: one line for each row it will change - parent, item ref ID and Yes - with rows for review listed separately:

```text
JPC_AV_xxxxx  parent (blank) -> REFID  |  item ref ID (blank) -> ITEMREF  |  created No -> Yes  |  title
```

With `--run` it writes only after `yes`; "Saved write-back outcomes:" then gives the outcomes file. For each created record since deleted in ArchivesSpace, add `--exclude-catalog JPC_AV_xxxxx` to both commands. Eligibility, review rows and recovery are in [section 7](#write-back-eligibility-and-recovery). To confirm the result, pull a view showing `ASpace Parent RefID` and `((( ASpace Item Record Created )))` and run `jpc-check --file PULL --env production`.

## Update existing item records

`jpc-update` changes item records already in ArchivesSpace. It never creates one, and there is no write-back: the values came from Airtable.

1. **Pull a narrow view** of records already in ArchivesSpace, showing `CATALOG_NUMBER` and only the fields to change ([Update sheets](#update-sheets)). A column the CSV lacks is left untouched.

   ```bash
   jpc-pull --view NAME
   ```

2. **Dry-run.** The first lines name the columns to update ("will update:") and to leave alone ("Left untouched (not in CSV):"). The PLAN shows each changing record's current and new values, notes in full. Any problem row stops the whole run before writing - updates have no `--keep-going`.

   ```bash
   jpc-update --file PULL --env production --dry-run
   ```

   ```text
     update   JPC_AV_00468  Old Title
              title:       Old Title
                           -> New Title
   ```

3. **Run it** on the same file with the same `--env`; nothing is written without `yes`, and nothing is asked when nothing would change. A record edited after the PLAN is refused ("Record changed after the preview") and left as it is. If Airtable changed after the pull, pull again and dry-run first.

   ```bash
   jpc-update --file PULL --env production
   ```

4. **Verify.** RESULT counts Updated, Unchanged, and any failed, refused or unknown rows; the records file holds each record as stored after the run.
   - **"Record changed after the preview"** - someone edited that record after the PLAN. Run `jpc-update` again with `--dry-run` first, to see its current changes, before any real run.
   - **A failed row, or one with an unknown outcome** - check the record in ArchivesSpace, then rerun the same file; rows already updated come out unchanged.

A sandbox PLAN is not a production PLAN: dry-run with `--env production` before updating production.

### Changes that need another approach

- **A new item** - the create workflow; `jpc-update` reports "No record found".
- **Clearing a value** - a blank cell never clears anything. Clear the Airtable cell and delete that text in the ArchivesSpace staff interface - only that text, since a PhysTech note can also hold the Duration list.
- **Another parent** - `jpc-update` never moves a record. Move it in ArchivesSpace, then correct Airtable ([manual 0.E](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#rules-that-keep-the-two-in-step)).
- **The JPC_AV_xxxxx or AV Case container** - never changed.
- **Several extents, several dates with one label, or a date range** - edit the record by hand in ArchivesSpace and leave the row out of the view.
- **Runtime (Duration)** - recorded by `jpc-rename` after digitization, which also fills a blank physical details.
- **Fields the tools do not manage**, such as agents - entered in ArchivesSpace ([manual 0.C](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#0c-fields-entered-manually-in-archivesspace)).

Correct Airtable-managed fields in Airtable: the next update writes Airtable's value over ArchivesSpace.

## Check and export

Three questions, three tools: whether each JPC_AV_xxxxx is in ArchivesSpace and the pull agrees (`jpc-check`); exactly what ArchivesSpace holds (the direct export); and which items are live in MADS (`jpc-mads`). `jpc-lookup` is another name for `jpc-check`: the same command, options and answers.

### Check JPC_AV_xxxxx in ArchivesSpace

```bash
jpc-check --file PULL --env production
```

`--file` takes a pull or a plain list of JPC_AV_xxxxx, one per line; each is looked up live, read-only, at every level. `--output PATH` also saves a CSV. Given a pull, it compares `ASpace Parent RefID` and `((( ASpace Item Record Created )))` with ArchivesSpace - each only if the view showed it; include Yes rows to find items marked Yes but missing. Airtable is not read again.

`jpc-check --help` defines every result line. Note especially:

- **"Not found by JPC_AV_xxxxx"** is not a verdict that the item is new.
- **"Could not check"** is not "not found": the lookup failed - retry later. **"Ambiguous"** (several records share a JPC_AV_xxxxx) must be cleaned up in ArchivesSpace first.
- A line with no comparison problem does not by itself mean the item is ready to import.

Exit 2 means something needs review or could not be checked. Correct Airtable where it is wrong. Where the cause is unclear, tick `ASpace Hold` and record the evidence in `ASpace Issue`, then pull again and re-check.

### Export records as stored

To see records exactly as ArchivesSpace holds them - to confirm an import or review stored data - run the export tool directly ([Export records](#export-records)); given a pull, it exports exactly those items. An export is for review: corrections to Airtable-managed fields are still made in Airtable.

### Check which items are live in MADS

This section is the authoritative account of the MADS check; the folder guide links here. MADS is the public DAMS delivery. `jpc-mads` reads each item's public MADS page and saves a report. It never contacts ArchivesSpace or Airtable, changes no folders, takes no `--env`, and reads `creds.py` only for `logs_dir`.

```bash
jpc-mads --directory BATCH
```

```bash
jpc-mads --file PULL
```

- **`--directory BATCH`** checks the item folders directly inside the batch folder, named `JPC_AV_xxxxx` or `JPC_AV_xxxxx_refid_<RefID>`. A JPC_AV_xxxxx in several folders is checked once and those folders are listed for review, as are symlinks and `JPC_AV_` names that are not item folders (these are not checked). A folder being there does not prove the item reached DAMS.
- **`--file FILE`** takes a plain list, one JPC_AV_xxxxx per line, or any CSV with a `CATALOG_NUMBER` column, such as a pull.

Answers:

- **Yes** - live in MADS.
- **No** - not in MADS. MADS publishes an item within about a day of DAMS ingest: after a recent ingest, wait a day and check again. Still No: look into that item's DAMS ingest, outside these tools.
- **check failed** - the check itself errored; not evidence the item is missing. Run the same command again.
- **invalid catalog number** - not JPC_AV_ followed by digits; never looked up. Correct the list.

RESULT counts each answer and, with `--directory`, names the folders for review (In more than one folder, Skipped symlinks, Not recognized): fix the batch folder and check again. The report, `mads_check_YYYYMMDD_HHMMSS_PID.csv` (`CATALOG_NUMBER`, `MADS URL`, `MADS live`, `Checked`), goes to `~/aspace_mads_reports/`, `mads_reports/` inside `logs_dir`, or `--output PATH`; "Saved MADS report:" gives the path.

Exit 0: all Yes or No, nothing for review. Exit 2: checks failed, an invalid JPC_AV_xxxxx, or folders for review. Exit 1: nothing checked (unreadable input, no item folders, or a report that would overwrite the input), or the report not saved - RESULT still shows the answers. After Ctrl-C the report may already be saved; a `.tmp` file is not one.

## Prepare the CSV

The CSV is normally a pull, used as it is; other columns are ignored. Exact column rules are in the [field mapping contract](docs/CSV_TO_ASPACE_MAPPING.md); [EXAMPLE_MAPPING.md](docs/EXAMPLE_MAPPING.md) follows one row into a record.

### Create sheets

`jpc-import` needs all nine import column headers, even where a cell may be blank:

- `CATALOG_NUMBER` - required: JPC_AV_ followed by digits, once per file.
- `ASpace Parent RefID` - required; `jpc-fill` fills blank cells.
- `ASpace Title` - blank uses the JPC_AV_xxxxx as the title.
- `Creation or Recording Date`, `Edit Date`, `Broadcast Date` - real dates within 1940-2020, month-first or ISO, never day-first. In a two-digit year, 40-99 are 19xx and 00-20 are 20xx.
- `Original Format` - a term in ArchivesSpace's extent list; blank creates no extent.
- `ASpace Scope and Contents Note`, `ASpace PhysTech Note`.

`jpc-fill` needs `CATALOG_NUMBER`, `ASpace Parent RefID` and `ASpace File Type` (Edited, Promo or Raw), and reads `EJS Episode` (4006, or 09 for Celebrity Showcase). Keep `EJS Episode` filled: when it is blank, the title must follow the title pattern exactly ([manual 5.B](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#5b-ebonyjet-showcase-title-pattern)). The fill refuses two or more unnamed columns, and near-misses of its column names (`EJS Episode ` with a trailing space, `path` for `Path`): fix the name in Airtable and pull again.

### Update sheets

`jpc-update` accepts `CATALOG_NUMBER` (each once, matching exactly one item record) plus at least one of:

- `ASpace Title`.
- The three date columns - each changes only the ArchivesSpace date with its label. A date outside 1940-2020 gets a warning and is accepted only if it matches the stored date.
- `Original Format` - only the extent type changes.
- The two note columns - the first non-empty text block of that note is replaced in full; other text and the Duration list are kept.

`ASpace Parent RefID` is ignored. A blank cell never clears a stored value.

### Holds and issues

`jpc-pull` always includes these two `<<< ASpace_import >>>` fields, even when the view hides them:

- **`ASpace Hold`** (checkbox) alone decides whether an item is processed; in the CSV it must be `checked` or blank. A held row goes to the fill's review file, stops a whole `jpc-import` or `jpc-update` batch before writing (with `--keep-going`, the import refuses just that row), is left alone by the write-back, and is marked by `jpc-check`.
- **`ASpace Issue`** (text) says what needs attention: on a held row, the reason. On a row not held, the pull and fill show it, and the row is processed as usual. Clear it once resolved.

A CSV carries holds as of its pull: tick the box before pulling, and pull again after ticking one. A sheet without the `ASpace Hold` column is not guarded. The write-back reads holds live, so a hold ticked after the import counts - but not one ticked between its last read and the write ([manual 0.E](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#rules-that-keep-the-two-in-step)).

## Read results and saved files

Each saved file's full path follows "Saved ...:"; a file that could not be saved shows in red as "NOT saved ...".

| File | Purpose | Normal location | When |
|---|---|---|---|
| `{VIEW}_YYYYMMDD_HHMM.csv` | pulled view | `data_import_export/__airtable_exports__/` | each `jpc-pull` |
| `jpc-fill_{VIEW}_..._ready_for_ASpace_import.csv` and `..._needs_human_review.csv` | ready and review rows | beside the pulled CSV | `jpc-fill` |
| check CSV | check answers | `PATH` | `jpc-check` with `--output PATH` |
| `import_report_<stamp>.json` and `.csv` | each row's outcome; `jpc-writeback` reads the `.json` | `~/aspace_import_reports/`, or `import_reports/` in `logs_dir` | real `jpc-import`, `jpc-update` runs |
| `import_records_<stamp>.json` | records as stored after the run | as above | a create that created records; an update not stopped by a problem row |
| `csv_import_<stamp>.log` | run log | as above | real runs, even cancelled ones |
| `airtable_writeback_<stamp>.csv` | write-back outcomes, one line per created row: `CATALOG_NUMBER`, `ASpace Parent RefID`, `ASpace Item RefID`, outcome, note | beside the import report | `jpc-writeback --run`, past `yes` or with nothing left to write |
| `mads_check_<stamp>.csv` | MADS answers | `~/aspace_mads_reports/`, or `mads_reports/` in `logs_dir` | `jpc-mads` |
| `aspace_export_<env>_<stamp>.csv` | records as stored | `~/aspace_import_reports/`, or `export_reports/` in `logs_dir` | direct export |

`<stamp>` is the run's date, time and process ID. `logs_dir` is an optional `creds.py` setting. A `.tmp` file is never a finished file.

**The fill writes beside its input, wherever that is.** Pulls made before the data folder was renamed stay in `aspace_csv_import/__airtable_exports__/`; they still work by full path, and filling one writes beside it, in the old folder. Do not delete the old folder while a batch it holds is in progress.

### Cancellation and interruption

- **Dry run (`jpc-import`, `jpc-update`) or preview (`jpc-writeback`):** nothing written or saved.
- **Anything but `yes`:** nothing written; `jpc-import` and `jpc-update` save only the log.
- **Ctrl-C or a fatal error while writing:** what was written stays (no rollback), and a row may have an unknown outcome. `jpc-import` and `jpc-update` try to save receipts covering the rows reached, and `jpc-writeback` tries to save its outcomes file. Check the Saved and NOT saved lines for what was actually saved: a second Ctrl-C while the files are being written can leave none, and a leftover `.tmp` file is never a receipt.
- **Log cannot be written** (`jpc-import`, `jpc-update`): no further writes; "NOT saved log". The run exits 1, unless its reports could not be saved either (exit 3) or it was interrupted (exit 130).
- **Reports cannot be saved:** after `jpc-import` or `jpc-update` (exit 3), records may have been written - check ArchivesSpace before rerunning. After `jpc-writeback`, Airtable was still written as shown.
- **An interrupted pull** may or may not have saved its CSV: look in the save folder.

Recovery then follows each command's own rule: [jpc-import](#a-partial-result), [jpc-update](#update-existing-item-records) (step 4), [jpc-writeback](#finish-an-unfinished-write-back).

## Write-back eligibility and recovery

`jpc-writeback` reads the import report, its records file and Airtable. It never contacts ArchivesSpace and never changes the report or records file.

### Before the first write-back

It needs a `production` entry in `creds.py`, the Airtable read token (`airtable_pat_read_only`) and, for `--run`, the write token (`airtable_pat_write`) - both for the one real base. See [production and write access](../QUICK_START.md#10-production-and-write-access-operators-only).

It checks these fields first, and stops with nothing written if one is missing or has another type:

- **`ASpace Parent RefID`** in `<<< ASpace_import >>>`, single line text: gets the import's parent, only in a blank cell.
- **`ASpace Item RefID`** in `<<< ASpace_import >>>`, single line text - create it before the first write-back, which does not create it: gets the item's own ref ID from the import's read-back (never the parent's), only in a blank cell.
- **`ASpace Item Record Created`** in `((( ASpace_tracking )))`, a single select with a `Yes` option: set to Yes; an existing Yes is kept.
- **`CATALOG_NUMBER`** in `<<< ASpace_import >>>` and **`JPCA-AV_SOURCE`** in `((( ASpace_tracking )))`: links to the same table.
- **`ASpace Hold`**, if present: a checkbox, spelled exactly.

### Which reports are accepted

Before reading Airtable, the write-back stops (exit 1), writing nothing, unless:

- the report is the `.json` (not the `.csv`) of a real `jpc-import` run with `--env production` - sandbox, dry-run and `jpc-update` reports are refused;
- its recorded ArchivesSpace target (server URL, repository, resource) matches `creds.py`'s production entry - this shows that recorded settings agree, not that the records still exist or that the entry really is production;
- when records were created, the records file is at the path the report recorded and is from the same run. It is read only from that path, so leave both files where the import saved them.

### Which rows are written

Only rows the import created, and each only if all of these hold; otherwise it is listed for review and left alone:

- The report has a valid JPC_AV_xxxxx and parent RefID for it, only once, with a production record URI and a matching read-back snapshot in the report's resource, whose own ref ID is usable (and matches the report's, when given).
- Exactly one `JPCA-AV_SOURCE` row is named with the JPC_AV_xxxxx, and exactly one `<<< ASpace_import >>>` row and one `((( ASpace_tracking )))` row link to it, neither linking other items.
- The item is not on hold in Airtable now.
- `ASpace Parent RefID` is blank or already the import's parent; `ASpace Item RefID` is blank or already the item's own ref ID.

`--exclude-catalog JPC_AV_xxxxx` drops a created row - for a record deleted since the import. Repeat it for each, on the preview and the `--run`; a value that is not a created row stops the run.

### How it writes, and outcomes

Parents and item ref IDs are written first, ten rows at a time, each confirmed from Airtable's reply; Yes follows only where both are in place. Each batch is read again just before writing: a row changed since the PLAN is left alone as "changed". An edit made between that read and the write can still be overwritten; Airtable cannot make a write conditional. The run stops at the first refused write, lost reply or Ctrl-C.

Outcomes: **done**, **already done**, **excluded**, **review**; and **partial** (parent or item ref ID written, Yes not yet), **not confirmed**, **unknown** (a write may or may not have landed), **not started** and **changed** - all finished by running again.

### Finish an unfinished write-back

Run the same `--run` command again, with any `--exclude-catalog` flags:

```bash
jpc-writeback --report REPORT --run
```

It re-reads Airtable, shows the current plan, writes only what is still missing - including a blank `ASpace Item RefID` when the parent and Yes are set - and counts finished rows as already done. Do the same if the outcomes file was not saved, or the run ended without saying.

### Rows for review

Nothing was written for them. By the note shown:

- **On hold in Airtable** - left alone on purpose; once the hold is cleared, run again.
- **Airtable already has a different parent** - compare with the record in ArchivesSpace. If Airtable was wrong, correct it and run the same command again; if the record moved, set Yes by hand (a rerun would list the row for review again).
- **Airtable already has a different `ASpace Item RefID`** - compare with the record in ArchivesSpace and correct whichever is wrong, then run again.
- **Source rows or links do not match** - fix those records in Airtable, then run again.
- **Snapshot, item ref ID or record URI problems** - confirm the record in ArchivesSpace, then record it by hand (below).

### Record a created item by hand

For an item in production ArchivesSpace without a usable production create report. If an earlier production import created it and its write-back never ran, run `jpc-writeback` with that report instead. Otherwise:

1. Confirm the production record is the intended item - its JPC_AV_xxxxx, and the title and path `jpc-check` shows.
2. Enter its parent in `ASpace Parent RefID`. Run `jpc-check --file PULL --env production --output PATH`: the CSV's "ArchivesSpace parent" column has it.
3. Enter the item's own ref ID in `ASpace Item RefID` - never the parent's ref ID or the record URI. `jpc-check` does not show it: from the repository folder, export the item and copy its "ASpace Ref ID" column ([Export records](#export-records)):

   ```bash
   python3 data_import_export/aspace_csv_export.py --list PULL --env production
   ```

4. Set `ASpace Item Record Created` to Yes in `((( ASpace_tracking )))`.
5. Pull again.

Never mark Yes from a sandbox result. If you cannot confirm the record yet, leave the item out of the create view.

## Troubleshooting

Setup problems - "command not found", a missing package, `creds.py`, VPN or login refusals, "choose the ArchivesSpace environment", "production is not set up on this computer" - are in the quick start's [common setup problems](../QUICK_START.md#9-common-setup-problems).

- **`jpc-pull`: "no view named ..."** - names must match exactly; the message lists the views. Only grid views can be pulled.
- **`jpc-pull`: "... already exists (a pull of this view this minute)"** - wait a minute and run again.
- **`jpc-import`: "Parent not found: ..."** - check the RefID in Airtable, and that `jpc-fill` and `jpc-import` used the same `--env`. If the parent record is missing, [hold the item and ask](#review-rows-whose-parent-cannot-be-found).
- **"Invalid extent type: ..."** - correct `Original Format` in Airtable ([manual 7.A](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#7a-extent-type-original-format)); `check_extent_types.py` lists the terms.
- **`jpc-update`: "No record found for JPC_AV_xxxxx"** - check the JPC_AV_xxxxx and `--env`. Several records, or not an item: fix the record in ArchivesSpace.
- **`jpc-writeback` refuses the report** - see [which reports are accepted](#which-reports-are-accepted). For a target that "does not match creds.py's production entry", check `creds.py`; never edit the report.
- **`jpc-writeback`: "could not read the records file this report names"** - keep it where the import saved it. If `logs_dir` is a relative path, the recorded path may stop resolving from another folder: run the write-back from the folder where the import ran, while it and its files remain. An absolute `logs_dir` avoids this.
- **`jpc-writeback`: "has no field named ..." or "has another field type"** - correct the field ([Before the first write-back](#before-the-first-write-back)).

## Advanced direct use

Each `jpc-` command runs one Python tool; its help (under RUNS) shows the direct equivalent. Two capabilities exist only directly: the record export and the extent-type check. Run direct commands from the repository folder:

```bash
cd ~/github/jpc/aspace_jpc_av
```

Run directly, a tool that talks to ArchivesSpace uses the only environment in `creds.py`; with several configured, every run must name one with `--env NAME`, and there is no default. The examples always name it.

### Export records

`aspace_csv_export.py` exports AV records, read-only, to an import-shaped CSV with audit columns (ref ID, Warnings, Level, Depth, Path, URI, staff link, MADS URL, created/modified), in tree order; a `--list` export keeps list order. The Warnings column flags:

- **Metadata gaps the policy cares about:** an item with no title or date, and a missing Component Unique Identifier, which also blocks re-import.
- **Rows the importer will refuse on re-import:** a JPC_AV_xxxxx that is not `JPC_AV_` plus digits or is shared by two records, and a stored date that is not a valid ISO date.
- **Fields whose editing through the sheet is restricted:** a date outside 1940-2020 may be corrected to one inside the range but not changed to another outside it; a range or non-single date, a label shared by several dates, and the type on a record with several extents cannot be changed at all.
- **Approximate tree order:** a record or ancestor with no position in ArchivesSpace; this one does not affect re-import.

Non-item rows are not warned - the Level column identifies them - but `jpc-update` refuses them all the same; a blank Warnings cell on a series or file row does not make it re-importable.

```bash
python3 data_import_export/aspace_csv_export.py --list PULL --env production
```

```bash
python3 data_import_export/aspace_csv_export.py --level item --mads-live --env production
```

- `--list FILE` - exactly these JPC_AV_xxxxx (a list, or a CSV with `CATALOG_NUMBER` such as a pull); not with `--parent`.
- `--level LEVEL` - `item` (default), `file`, `subseries`, `series` and others, or `all`.
- `--parent REFID` - only this record's direct children; combines with `--level`.
- `--mads-live` - adds a `MADS live` column.
- `-o PATH` - save at `PATH`.

Exit 2 means the file was written but is incomplete: listed items not found, or MADS checks failed.

### List extent types

```bash
python3 data_import_export/check_extent_types.py FILE --env production
```

Lists the extent types ArchivesSpace accepts and checks a CSV's `Original Format` values; leave out `FILE` for the list alone. It is authoritative for create sheets; for update sheets, a retired stored term shows as INVALID but is kept unchanged by `jpc-update`.

### Direct help and passwords

Each tool's own help, such as `python3 data_import_export/aspace_csv_import.py --help`, describes its direct options.

**Do not put a password on the command line.** `aspace_csv_import.py` and `check_extent_types.py` accept `-u` and `-p` (username and password), but a typed password is saved in your shell history and visible to other programs in the process list. Keep credentials in `creds.py` ([quick start](../QUICK_START.md)). The `jpc-` commands never accept them.

The direct folder tool is covered in [Appending RefIDs to Folders](../refid_appending/APPENDING_REFIDS_TO_FOLDERS.md). Release history is in the [changelog](../CHANGELOG.md).
