# Changelog

Release notes for the JPC AV tools in this repository: the `jpc-` commands and
the Python tools they run. Each entry describes what changed in that release.

Entries describe the tools as they were at the time - they are history, not
current instructions. For current use, start with the
[quick start](QUICK_START.md). Entries before the directory reorganization name
the old folders: `aspace_csv_import/` is now `data_import_export/`, and
`aspace_rename_directories/` is now `refid_appending/`.

Dates are in America/New_York time. From v3.5 on, each date is the release day
noted at the time; a release is a push to `main` on GitHub. Older entries
distinguish commit dates, documentation dates and development spans rather than
asserting an original release date: "commit dated" is the day the change and
its entry were committed, "entry written" the day only the entry was, and v3.4
shows its development span. A commit's place in today's `main` history does not
show when it reached `main` or GitHub.

## Releases

- **v5.0.1** (2026-10-23): `jpc-rename` stops before resending an update
  once its log has failed, and the rate-limit warning shows before the wait
  - `jpc-rename` checks its log before every attempt to update a record,
    including the resend after an expired session is renewed; once the log
    cannot be written it makes no further catalog updates - "Stopped before
    updating the record ... - nothing changed" - and renames nothing further
  - The "Airtable rate limit" warning now shows before the 30-second wait,
    also when output goes to a pipe or a file. When a write-back write is
    refused and the output has failed, the write-back stops before that
    wait, with no further writes. When a read is refused, the warning is
    flushed as far as the output allows and the read may still be retried;
    the write-back's check before its next write then stops any further
    writes
  - After pulling: existing editable installs (`python -m pip install -e .`)
    need nothing reinstalled; reinstalling only refreshes the version
    `python -m pip show jpc-av-tools` reports

- **v5.0.0** (2026-10-22): **BREAKING for direct script use** - the tool
  folders are renamed and the documentation is reorganized
  - **Breaking (direct use only):** `aspace_csv_import/` is now
    `data_import_export/`, and `aspace_rename_directories/` is now
    `refid_appending/`. Direct `python3` commands, bookmarks and notes
    that name the old folders need the new paths; script and module names
    are unchanged
  - **New default pull folder:** `jpc-pull` now saves to
    `data_import_export/__airtable_exports__/`. Earlier pulls stay in
    `aspace_csv_import/__airtable_exports__/`, and filling one writes its
    ready and review files beside it
  - **Unchanged:** the `jpc-` command names, their options and their
    behaviour
  - New documentation: `QUICK_START.md` (setup, with an operators' section
    for production and write access),
    `data_import_export/IMPORTING_AND_UPDATING_DATA.md` and
    `refid_appending/APPENDING_REFIDS_TO_FOLDERS.md`. The READMEs are now
    short introductions, and release notes moved to this file
  - Help: every `jpc` screen ends with FURTHER READING; review-row help
    follows manual 3.B (a missing Edited, Raw or Promo grouping is held
    and escalated, not created); the write-back summaries and the
    by-hand recording steps name `ASpace Item RefID`; the importer's own
    `-h` runs from the repository folder
  - After pulling: existing editable installs (`python -m pip install -e .`)
    need nothing reinstalled - the console entry points are unchanged;
    reinstalling only refreshes the version `python -m pip show
    jpc-av-tools` reports

- **v4.0.1** (2026-10-21): the write-back's reading phase shows promptly, and
  progress counters fit the terminal while they update
  - The write-back announces its reading - the field list, then three
    tables - before the first request, and shows each table's count as it
    finishes, also when its output goes to a pipe or a file
  - In a terminal, the shared progress counters (the write-back's reading,
    jpc-check (and jpc-lookup), jpc-fill and jpc-mads among them) shorten
    their label while updating in place, keeping their numbers whole;
    where even the numbers cannot fit, each update is printed as an
    ordinary line. Finished counts and the write-back's write progress
    are unchanged
  - After pulling: existing editable installs (`python -m pip install -e .`)
    need nothing reinstalled; reinstalling only refreshes the version
    `python -m pip show jpc-av-tools` reports

- **v4.0.0** (2026-10-21): **BREAKING** - the `jpc-` ArchivesSpace commands
  need an explicit environment
  - **Breaking:** `jpc-check` (and `jpc-lookup`), `jpc-fill`, `jpc-import`,
    `jpc-update` and `jpc-rename` need `--env production` or
    `--env sandbox` on every run. There is no default: a command without
    it stops before anything runs (exit 2) and says to choose one, even
    when `creds.py` has only one environment. `--env production` is now
    accepted. Add `--env` to saved commands and notes
  - Help, examples and the `jpc` overview show the flag. `jpc-pull`'s next
    steps show `--env ENV` with a line saying to replace it with
    production or sandbox, since a pull has no ArchivesSpace target
  - Unchanged: `jpc-pull`, `jpc-writeback` and `jpc-mads` take no `--env`;
    the write-back still accepts production reports only; the direct
    Python tools still use their only configured environment and require
    `--env` when several are configured
  - After pulling, with the documented editable install
    (`python -m pip install -e .`): nothing to reinstall - the commands
    are the same; reinstalling only refreshes the version
    `python -m pip show jpc-av-tools` reports

- **v3.8.0** (2026-10-21): `jpc-lookup`, another name for `jpc-check`
  - `jpc-lookup` runs `jpc-check` itself: the same options, environment
    rules (production unless `--env sandbox`), output and exit codes; its
    help and messages name `jpc-check`
  - After pulling: run `python -m pip install -e .` once in each
    environment that has the commands - the reinstall refreshes the
    installed commands and adds `jpc-lookup`. `jpc-lookup --help` then
    shows `jpc-check`'s help. Ordinary pulls that add no command still
    need no reinstall. With the optional zsh hint, a Terminal opened
    before the pull keeps the hint it loaded; a new Terminal reloads it

- **v3.7.0** (2026-10-21): the write-back records each item's own ref ID and
  shows its progress
  - The write-back also fills `ASpace Item RefID` in
    `<<< ASpace_import >>>` with the item's own ref ID, taken from the
    record the import read back (not the parent's ref ID or the URI). It
    is written only into a blank cell, with the parent, and confirmed
    before Yes; a row whose cell already holds another value, or whose
    item ref ID is missing or unusable, is left for review. A later run
    fills a blank one on rows already written back. The field must exist
    in Airtable as single line text, or the run stops with nothing written
  - While writing, the write-back shows each step and how many of its
    batches are done - re-checking, then rows written and confirmed so far
  - After pulling: nothing to reinstall; reinstalling only refreshes the
    version `python -m pip show jpc-av-tools` reports

- **v3.6.10** (2026-10-20): write-back rechecks, truthful importer logs, values
  not repeated
  - The write-back reads each batch's rows again just before writing it
    (and after any rate-limit wait) and leaves changed rows alone; a failed
    screen output stops further writes and still tries to save the receipt
  - The CSV importer checks its log before the yes prompt and every catalog
    write: if the log cannot be written it sends no further writes, keeps
    each row's outcome and says "NOT saved log" (exit 1; lost receipts and
    Ctrl-C keep 3 and 130)
  - A repo_id or resource_id that is not digits is refused by name when the
    environment is chosen, before anything is shown (jpc-check, jpc-fill and
    jpc-rename then exit 2); jpc- commands no longer repeat a stray word or
    an unknown option name
  - Airtable schema refusals describe an unexpected view or field type, and
    count unknown column IDs, instead of quoting them; a ref ID that is not
    plain text is left out of the importer's status line and receipts; each
    ArchivesSpace request uses the one URL it checked
  - After pulling: nothing to reinstall; reinstalling only refreshes the
    version `python -m pip show jpc-av-tools` reports

- **v3.6.9** (2026-10-20): honest rename logs, safer report saving
  - The rename tool notices when writing its log fails after the log
    opened: it starts no further change, says the log was NOT saved and
    exits 1 (Ctrl-C keeps 130); changes already made are kept and reported
  - Reports and CSVs are saved through a temporary file the run itself
    created: an existing file or link at a staging name is never written
    through or removed
  - An unusable vocabulary id or an unrecognized stored date type is
    refused or described without repeating the server's value, and the
    multi-extent refusal no longer quotes the record's extent types
  - RESULT and NEXT STEP count each problem row once - on hold, outcome
    unknown or failed - so issue text can no longer make a held row read
    as an unknown outcome
  - After pulling: nothing to reinstall; reinstalling only refreshes the
    version `python -m pip show jpc-av-tools` reports

- **v3.6.8** (2026-10-19): direct tools' argument errors no longer repeat what
  was typed
  - Every direct tool now refuses a mistyped or stray argument without
    repeating it, as the importer and extent checker already did; a wrong
    `--level` lists the levels to choose from, and a folder path typed
    without `-d` gets the `-d PATH` hint
  - An unknown `--env` name, and `--exclude-catalog` values that are not
    created rows in the report, are refused without showing them
  - The export creates its output folder only after the `--list` or
    `--check` input has been read, so a refused input leaves none behind
  - The importer's "Not written" and "Warnings are not errors" notes are
    wrapped to fit the screen
  - After pulling: nothing to reinstall; reinstalling only refreshes the
    version `python -m pip show jpc-av-tools` reports

- **v3.6.7** (2026-10-19): two clearer messages
  - The rename tool, run directly with one environment configured, now
    says why that environment cannot be used - the same explanation the
    other tools give, never the value - instead of "no environments
    configured"
  - `--check`'s closing note is wrapped to fit the screen and names
    JPC_AV_xxxxx
  - The Version History gains its missing v3.4 entry
  - After pulling: nothing to reinstall; reinstalling only refreshes the
    version `python -m pip show jpc-av-tools` reports

- **v3.6.6** (2026-10-19): `--check` reads its input once
  - The list or pulled sheet is read from disk once, and its numbers, rows
    and pull details all come from that one read - a file saved again
    during the check can no longer mix two versions
  - After pulling: nothing to reinstall; reinstalling only refreshes the
    version `python -m pip show jpc-av-tools` reports

- **v3.6.5** (2026-10-19): the write-back tries to keep its receipt after a
  Ctrl-C
  - Once writing has begun, an interrupted run still tries to save this
    run's outcomes file (an interrupted save is tried once more) and to
    say whether it was saved; nothing more is sent to Airtable. Pressing
    Ctrl-C again, or a disk or filesystem problem, can still prevent the
    save or that message
  - A Ctrl-C pressed again during the writes marks only the batch then in
    flight unknown. The receipt never replaces an existing file; a report
    folder that cannot publish it safely now stops the run before anything
    is written to Airtable
  - After pulling: nothing to reinstall; reinstalling only refreshes the
    version `python -m pip show jpc-av-tools` reports

- **v3.6.4** (2026-10-19): links in ArchivesSpace replies are checked first
  - A record's parent and container links are followed only when they
    are plain record paths in the configured repository; anything else
    shows "(path unavailable)" or leaves that container out of the
    records file
  - Every ArchivesSpace request must be a path on the configured server,
    so the session is never sent to another host; it is not a check
    that the path stays under the server's base path
  - The rename tool no longer quotes a ref_id it refuses as invalid
  - After pulling: nothing to reinstall; reinstalling only refreshes the
    version `python -m pip show jpc-av-tools` reports

- **v3.6.3** (2026-10-19): two more refusals no longer quote server values
  - An update refused because the record no longer matches or is not an
    item, and an export stopped by a mismatched batch, name the check and
    the record expected - not the values the server returned. Titles,
    notes and other record details are shown as before
  - A Cloudflare block page's Ray ID is shown only when it is 8-32 hex
    characters; anything else is left out
  - After pulling: nothing to reinstall; reinstalling only refreshes the
    version `python -m pip show jpc-av-tools` reports

- **v3.6.2** (2026-10-18): server error replies are no longer copied into
  messages
  - ArchivesSpace and Airtable errors give the HTTP status and a fixed
    explanation (for ArchivesSpace, the names of flagged fields such as
    title or dates), never the server's own text, which can echo back
    what was sent, a token included
  - Airtable redirects are not followed and their address is not shown:
    a redirected pull stops with nothing read; a redirected write-back is
    reported as unknown, like a timeout - rerun to re-check
  - The rename tool no longer quotes a mismatched record's values when
    it refuses one; it still names what it expected
  - After pulling: nothing to reinstall; reinstalling only refreshes the
    version `python -m pip show jpc-av-tools` reports

- **v3.6.1** (2026-10-18): authentication tokens are checked before use
  - The Airtable read and write tokens, and the session token
    ArchivesSpace returns at login, must be text of visible characters
    only - no spaces, line breaks or other control characters. A token
    that is not is refused, naming its setting, never the token, and
    nothing is sent with it; a preview still needs no write token
  - Connection errors are reported by kind, never with the HTTP library's
    own text, which can quote a token; a write whose outcome is unknown
    is still reported as unknown
  - After pulling: nothing to reinstall; reinstalling only refreshes the
    version `python -m pip show jpc-av-tools` reports

- **v3.6** (2026-10-18): import reports record their ArchivesSpace target
  - Import reports and records files record the run's ArchivesSpace target
    (server URL, repository, resource), captured once before anything is
    written, with the run's start time
  - The write-back accepts only a real production create report whose
    target matches creds.py's production entry and whose records file -
    read only from the path the report records - is from the same run;
    anything else stops before Airtable is read. Reports saved before 3.6
    record no target and are not accepted. A snapshot that does not match
    its record, or is outside the target resource, sends only that row to
    review. The check compares recorded settings; it does not contact
    ArchivesSpace, so it cannot show that the records still exist or that
    the production entry really is production
  - When a production create run's records file cannot be saved, the
    importer says the write-back cannot use the report and how to record
    the created items by hand
  - Already released since 3.5: the importer's and extent checker's
    argument errors no longer repeat typed values, and the rename wording
    for Failed is corrected; a `baseURL` or `staff_url` holding a user
    name, password, `?` or `#` is refused before anything is shown,
    logged or sent, and never printed
  - After pulling: nothing to reinstall - an editable install
    (`python -m pip install -e .`) runs the updated code. Reinstalling only
    refreshes the version `python -m pip show jpc-av-tools` reports

- **v3.5** (2026-10-18): `jpc-mads`, and next steps as `jpc-` commands
  - New `jpc-mads` command: which items are live in MADS, from a list
    (`--file`) or a batch folder's item folders (`--directory`);
    `check_mads.py` gains `--directory`, and `jpc-rename`'s help points to
    the check after DAMS ingest
  - A tool started by its `jpc-` command prints its NEXT STEP as a `jpc-`
    command (pull, import, write-back preview); run directly, it prints the
    long command as before
  - `--check`: labels name JPC_AV_xxxxx ("JPC_AV_xxxxx checked", "Not found
    by JPC_AV_xxxxx", also in the CSV's Outcome), not found is shown in
    cyan, and agreeing items with no hold or issue are counted, not listed,
    when the file has all four tracking columns (`-o` lists every one)
  - Strict create's Mode line and help are worded around preflight
  - Export `--list` reads and checks its list before logging in
  - The rename log is `rename_YYYYMMDD_HHMMSS_PID.log`, like the other
    reports
  - The importer's missing `-f` error adds "a CSV path needs -f in front of
    it: -f FILE"
  - After pulling: run `python -m pip install -e .` once in each environment
    that has the commands (this adds `jpc-mads`), then open a new Terminal;
    `python -m pip show jpc-av-tools` then reports Version 3.5

- **v3.4** (development span 2026-09-30 to 2026-10-17): the `jpc-` commands and
  `jpc-rename`
  - The first packaged version: a `jpc-` command for each workflow step
    (pull, check, fill, import, update, write-back) and `jpc`, which lists
    them; production by default, with detailed help screens;
    `--skip-duplicates` became `--keep-going`
  - `jpc-check`, `jpc-fill`, `jpc-import` and `jpc-update` stop before
    running when creds.py has no entry for the requested environment.
    Setup became an install guide, with an optional zsh hint for a `jpc-`
    command that is not found
  - New `jpc-rename`: the rename tool shows a PLAN of every change, and
    only `yes` writes or renames anything
  - Fixes: a creds.py that fails to load is reported by file, error type
    and line only, never the error text or the line itself; an uncertain
    folder rename no longer rolls media back; a failed MADS save keeps
    RESULT and exits 1; Ctrl-C at logout keeps the rename RESULT

- **v3.3** (commit dated 2026-09-30): `ASpace Issue`
  - The hold's reason field is renamed `ASpace Issue` and now records any
    open item, held or not; `ASpace Hold` alone still decides processing
  - The pull counts open issues on rows that are not held; the fill lists
    them without refusing the rows
  - `--check` compares an Airtable pull's parent and Item Record Created
    with ArchivesSpace, flags non-item records, and marks holds and issues;
    "new" became "Not found by catalog number"
  - `csv_utils.py` retired: the importer validates every sheet itself (dry
    runs included). For creating records, `--fill-parents` finds blank
    parents and the import preflight checks every parent before writing;
    there is no longer a standalone report checking all of a sheet's parent
    ref IDs, and a parent already filled in is checked at import, not by
    the fill

- **v3.2** (commit dated 2026-09-30): One display across the tools
  - Every tool's `-h` screen uses the same banner, a title saying what it
    does, and the same section order (DESCRIPTION, USAGE, ARGUMENTS, OPTIONS,
    EXAMPLES, OUTPUT, EXIT, NEXT STEP); a wrong argument shows the same
    usage-plus-options screen everywhere
  - Runs open with aligned Target / Input / Mode lines. A run that gets past
    its checks ends with a RESULT block that shows every category that
    happened, then `Saved <what>:  <full path>` lines (`NOT saved` when a
    file failed) and, where there is one, the NEXT STEP; a bad argument,
    CSV or login stops earlier with the error
  - The importer counts held rows, unknown outcomes, rows the run stopped
    before and rows never reached apart from failures
  - `--no-color` on every tool, including `aspace_csv_export.py`

- **v3.1** (commit dated 2026-09-29): Plan, confirm, and hand off
  - Every run checks all rows and prints a PLAN (create / skip / refused /
    update, with parent paths, normalized dates and full notes); real runs
    write only after a typed `yes`, containers included
  - `--skip-duplicates` checks every row too and shows skips and refusals
    before confirming
  - Updates apply exactly the previewed changes - a record edited after the
    preview is refused for that row
  - A real production create prints the exact Airtable write-back command,
    labelled PARTIAL when rows had unknown outcomes, failed or were not reached
  - Dry runs write no files; `aspace_csv_export.py --check` sorts catalog
    numbers into four outcomes on screen
  - A firewall block at login is no longer reported as a bad password
  - `ASpace Hold`: held rows go to review in the fill, stop strict create and
    update-only before any write, are refused by `--skip-duplicates`, are left
    alone by the write-back, and are marked by `--check`

- **v3.0** (release date unverified; entry written 2026-07-28 in `a98e917`):
  Safety hardening + update-only mode
  - New `--update-only` mode: narrow CSVs (CATALOG_NUMBER + columns to
    change), never creates records, resolves and preflights every row
    before anything is written — any predictable problem aborts the run
    with zero writes
  - Fail-closed everywhere: duplicate/parent/container lookups verify exact
    matches within the AV resource and abort on failure instead of guessing;
    failed report writes fail the run (exit 3)
  - Write safety: retries limited to reads (a timed-out POST is never blindly
    retried); top containers are reused by indicator and cleaned up if the
    record creation is definitively rejected
  - Update mode applies only detected changes — unchanged dates, extents,
    and notes keep their richer nested metadata (date expressions/certainty,
    extent physical_details, note labels and Duration defined lists);
    multi-extent and multi-same-label-date records are never collapsed
  - Blank CSV cells mean "leave the existing value alone"; day-first dates
    (13/02/2024) are rejected as malformed
  - Column names renamed (ASpace Title, ASpace Scope and Contents Note) and
    centralized in sheet_rules.py — future renames are a one-line edit
  - `csv_utils.py --validate --update-only` for narrow CSVs; docs corrected
    and expanded (ToC, workflows, real status symbols)

- **v2.0** (release date unverified; earlier listed as 2024; v2.0 commit
  `1be5308` dated 2025-12-02): Major update
  - Colorized terminal output
  - Smart change detection in update mode
  - "Unchanged" status for records with no differences
  - Cleaner output formatting
  - Credentials file support (creds.py)
  - Removed noisy logging from console
  - Added `--no-color` flag

- **First commit** (2023-11-27): `b76bcf0` starts this repository's recorded
  history; it is not a release. The importer's first recorded copy is
  `428a545` (2025-12-01); v1.0's original release date is unknown

- **v1.0** (release date unverified; earlier listed as 2024): Initial release
  - Earliest verified copy of the importer: commit `428a545`, dated
    2025-12-01, under `record_data_pushing/`
  - Basic CSV import functionality
  - Parent hierarchy support
  - Three duplicate modes
  - Comprehensive error handling
