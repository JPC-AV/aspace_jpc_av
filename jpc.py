"""
The jpc- commands: one short command per workflow step.

    jpc-pull --view NAME          save an Airtable view as a CSV
    jpc-check --file FILE         which numbers ArchivesSpace has; does Airtable agree
    jpc-fill --file FILE          fill blank parents; save ready and human-review CSVs
    jpc-import --file FILE        create records (PLAN, then type yes)
    jpc-update --file FILE        update records (PLAN, then type yes)
    jpc-writeback --report JSON   record a create run's results in Airtable
    jpc / jpc --help              this list

Each command runs exactly one existing tool with that step's fixed flags
filled in, and nothing else: the tools keep all their own checks, opening
lines, PLANs and yes prompts. The launcher only builds the command line -
from a short allowlist per command, so a contradictory or unknown flag is
refused however it is spelled - prints it, and hands the terminal to the
tool (same Python; Ctrl-C and the exit code are the tool's own).

Installed as commands by `python -m pip install -e .` in the repo root,
inside the JPC_AV environment (see pyproject.toml). Standard library plus
console.py only, so the help screens work even when a package is missing.
"""

import importlib.util
import os
import shlex
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))  # console.py sits beside this file

from console import Colors  # noqa: E402

# Help text that several screens show word for word. A screen names a
# block as {name} inside its own text; command_help formats the block with
# the screen's colors and puts it there. Text that differs because the
# operations differ stays in each screen.
SHARED_HELP = {
    # check, import, update, writeback: under the first HOW IT WORKS heading
    "jpc_av_definition": """      JPC_AV_xxxxx below means the catalog number: CATALOG_NUMBER in
      Airtable, the Component Unique Identifier in ArchivesSpace.""",
    # pull (NEXT STEPS) and fill (HOW IT WORKS)
    "fill_how_parents": """    {bold}How it finds parents{reset}
      EJS Episode and ASpace File Type identify the parent record: for example,
      the Edited file under Episode 4006. Exactly one match fills the item's
      blank ASpace Parent RefID cell. If EJS Episode is blank, an episode named
      in ASpace Title can be used; when both name an episode, they must agree.

      A parent RefID already in the pulled CSV is never replaced. If the lookup
      finds a different RefID, the original is kept and the row goes into the
      review file. The "Parent Note" column includes the lookup's different
      RefID so you can compare them. An episode/title disagreement also sends
      the row for review.""",
    # pull (NEXT STEPS) and fill (OUTPUT): the two files jpc-fill saves
    "fill_files": """      • {ready}jpc-fill_{{VIEW}}_YYYYMMDD_HHMM_parent_ref-id_ready_for_ASpace_import.csv{reset}
        Rows with a parent supplied or found and no unresolved fill issue.
        The added "Path" column shows the hierarchy when the lookup succeeds.
        "Parent Note" says "episode taken from the title" when a blank
        parent was filled using the title's episode. Other ready rows have a
        blank note.

        Ready means parent-ready: the import dry run still checks dates,
        formats and the other requirements, and can still refuse a row.

      • {review}jpc-fill_{{VIEW}}_YYYYMMDD_HHMM_needs_human_review.csv{reset}
        Rows needing human review. "Parent Note" describes the problem,
        such as a missing match or a different parent RefID.

        The added "Fix in" column tells you where to investigate. Check
        Airtable first; "Airtable, then ArchivesSpace" means inspect the
        ArchivesSpace hierarchy if the episode and file type in Airtable
        are correct.

        Held items always go here. Without a supplied parent, TBD or several
        episodes, Raw footage, and missing or ambiguous matches need review.
        Correct the indicated source, then pull and fill again for those rows.

        "Parent Note" exists only in these CSVs, not in Airtable. To preserve
        any of its text, manually paste it into "ASpace Issue" in Airtable's
        <<< ASpace_import >>> table. It is not copied back automatically.

        The review file is saved even when empty. If either output file already
        exists, jpc-fill refuses to replace it.

        jpc-fill leaves the pulled CSV, Airtable and ArchivesSpace unchanged.""",
    # import and update: FILE PATHS
    "import_save_folder": """    {bold}Save folder{reset}
      A real run saves its reports in the import reports folder: by default
      ~/aspace_import_reports/, or import_reports/ inside the logs_dir folder
      set in creds.py. The run prints each saved file's full path near the
      end ("Saved import report: ..."). A dry run saves nothing.""",
    # import and update: OUTPUT
    "run_output_opening": """    A dry run saves nothing; its PLAN is on screen only.

    A real run saves, in the import reports folder (see FILE PATHS):""",
    "receipt_csv_bullet": """      • {cyan}import_report_YYYYMMDD_HHMMSS_PID.csv{reset}
        The same receipt, as a spreadsheet.""",
    "log_bullet": """      • {cyan}csv_import_YYYYMMDD_HHMMSS_PID.log{reset}
        The run's log.""",
    "cancel_and_ctrl_c": """      A run cancelled at the yes prompt wrote nothing, so it saves only the
      log. After a Ctrl-C, any receipt saved covers only the rows reached;
      a Ctrl-C before processing began saves none.""",
    # import, update and writeback: OUTPUT
    "run_stamp": """      {bold}YYYYMMDD_HHMMSS{reset} is the run's date and time; {bold}PID{reset} is its process ID, so
      two runs started in the same second never share a name.""",
}


def help_blocks(*blocks):
    """Subsections of one help section, a blank line apart."""
    return "\n\n".join(blocks)


def full_path_of_pull(example):
    """FILE PATHS "Full path" for a screen whose input is the CSV jpc-pull
    saved; example is a pulled CSV's name."""
    return ("""    {bold}Full path{reset}
      Give --file the CSV that jpc-pull saved. Its full path is on the
      "Saved pulled CSV:" line near the end of a successful jpc-pull run.
      Copy that path and paste it after --file; a full path works from any
      folder. Dragging a file from Finder also gives its full path.

      Example on this computer:
      {cyan}{exports}/""" + example + "{reset}")


def short_path(example, folder):
    """FILE PATHS "Short path": example is a bare file name, folder the
    folder it sits in."""
    return ("""    {bold}Short path{reset}
      A file name or relative path is read from your current folder.
      A bare file name works when you are in the folder containing the file.

      Example: {cyan}""" + example + """{reset}
      This works when your current folder is """ + folder + ".")


def paths_with_spaces(example):
    """FILE PATHS "Paths with spaces", quoting this screen's example."""
    return "    {bold}Paths with spaces{reset}\n      Put the path in quotes: {command}" + example + "{reset}"


def runs_footer(verb):
    """The closing lines of every RUNS section."""
    return ("\n\n    Run these python3 commands from the aspace_jpc_av repository folder."
            f"\n    The shorter jpc-{verb} command works from any folder.")


def refusal_note(flag):
    """The closing lines of every EXIT section; flag is the command's input."""
    return (f"\n\n    A launcher refusal stops before the tool runs: a missing {flag},"
            "\n    an unsupported flag, or a value starting with '-'.")


# Each command: the tool it runs, its one named input, the flags the tool
# always gets, the extra flags a person may add (flag -> metavar, or None
# for a switch), and whether it talks to ArchivesSpace (and so takes
# --env). "base" builds the fixed part of the tool's arguments from the
# input; extras follow in the order given.
COMMANDS = {
    "pull": {
        "title": "save an Airtable view as a CSV",
        "summary": "Save an Airtable view of <<< ASpace_import >>> as a CSV (read-only)",
        "script": "aspace_csv_import/airtable_pull.py",
        "input": ("--view", "NAME", "The Airtable view, exactly as spelled in Airtable"),
        "base": lambda value: [value],
        "extras": {"--no-color": None},
        "aspace": False,
        "example": "jpc-pull --view one-inch_check",
        "help": {
            "environment": """    Reads the configured Airtable base, not ArchivesSpace.
    --env is not supported.""",
            "paths": help_blocks(
                """    {bold}Save folder{reset}
      Inside your copy of the tools repository:
      {cyan}aspace_jpc_av/aspace_csv_import/__airtable_exports__/{reset}

      This location stays the same regardless of the directory from which
      you run jpc-pull. Its full path depends on where you installed the tools.
      jpc-pull creates the folder automatically if it is missing.""",
                """    {bold}Full path{reset}
      Look for "Saved pulled CSV:" in the terminal output near the end of
      a successful jpc-pull run. That path identifies the CSV just saved.
      Use it with jpc-fill --file to read the CSV from any folder.
      Dragging a file from Finder also gives its full path.

      Example on this computer:
      {cyan}{exports}/one-inch_check_20260930_0545.csv{reset}""",
                short_path("one-inch_check_20260930_0545.csv", "__airtable_exports__"),
                paths_with_spaces("'My Batch.csv'")),
            "output": """    One CSV is saved:
      {cyan}{{VIEW}}_YYYYMMDD_HHMM.csv{reset}

      {bold}{{VIEW}}{reset} will be replaced with the Airtable view's name.
      {bold}YYYYMMDD_HHMM{reset} is the pull's date and time.
      Example: {cyan}one-inch_check_20260930_0545.csv{reset}

      The CSV contains the view's rows and visible columns in their Airtable
      order. ASpace Hold and ASpace Issue are included even when hidden in
      the view. The first row in the CSV records the command, view and pull
      time. Earlier CSV output files are never overwritten. The pull saves
      a local CSV. Airtable and ArchivesSpace are unchanged.""",
            "next_steps": """    In the normal JPCA ArchivesSpace <-> Airtable workflow, the usual next
    step when preparing new records is {bold}jpc-fill{reset}.

    jpc-fill reads the pulled CSV and looks up existing parent records in
    ArchivesSpace. It saves new CSV files with parent RefIDs filled in.
    The ready CSV is then used by {bold}jpc-import{reset} to create item records under
    those parents in ArchivesSpace.

    jpc-fill creates no ArchivesSpace records and writes nothing to Airtable.

    {bold}Run jpc-fill{reset}
      {command}jpc-fill --file PULL{reset}

      Replace {bold}PULL{reset} with the CSV's full path from the "Saved pulled CSV:"
      line printed near the end of a successful jpc-pull run.

      For a sandbox batch, add --env sandbox; jpc-fill defaults to production.

{fill_how_parents}

    {bold}Files jpc-fill saves{reset}
      Two files are saved beside the pull:

{fill_files}

    {bold}Further instructions: {command}jpc-fill --help{reset}
""",
            "runs": """    jpc-pull runs the Python tool airtable_pull.py for you.
    You do not need to run it separately.

    {bold}Equivalent direct command{reset}
      {command}python3 aspace_csv_import/airtable_pull.py NAME{reset}
      Replace NAME with the Airtable view's name; quote names with spaces.

    {bold}Underlying tool's help{reset}
      {command}python3 aspace_csv_import/airtable_pull.py --help{reset}
      This describes the Python tool's direct-use options. jpc-pull accepts
      only the flags listed in OPTIONS above.""",
            "exit": """    {ok}{bold}0{reset}    Saved      The CSV was saved.
    {bad}{bold}1{reset}    Stopped    No token, a view or token problem, an empty view,
                    or a pull with this name already exists for this minute.
    {warn}{bold}2{reset}    Refused    An argument was rejected; the error explains why.
    {warn}{bold}130{reset}  Stopped    Interrupted with Ctrl-C. The CSV may or may not have
                    been saved, and a saved one's path may not have been
                    printed - look in the save folder. A .tmp file there is
                    not a finished pull.""",
        },
    },
    "check": {
        "title": "check JPC_AV_xxxxx in ArchivesSpace",
        "summary": "Which JPC_AV_xxxxx ArchivesSpace has - and, for a pull, does Airtable agree (read-only)",
        "script": "aspace_csv_import/aspace_csv_export.py",
        "input": ("--file", "FILE", "A pulled CSV, or a plain list of JPC_AV_xxxxx (one per line)"),
        "base": lambda value: ["--check", value],
        "extras": {"--output": "PATH", "--no-color": None},
        "aspace": True,
        "example": "jpc-check --file one-inch_check_20260930_0545.csv",
        "help": {
            "paths": help_blocks(
                """    {bold}Full path{reset}
      Give --file a CSV that jpc-pull saved, or a plain text list of
      JPC_AV_xxxxx (one per line). A pull's full path is on the
      "Saved pulled CSV:" line near the end of a successful jpc-pull run.
      Copy that path and paste it after --file; a full path works from any
      folder. Dragging a file from Finder also gives its full path.

      Example on this computer:
      {cyan}{exports}/one-inch_check_20260930_0545.csv{reset}""",
                short_path("one-inch_check_20260930_0545.csv", "__airtable_exports__"),
                """    {bold}Save folder{reset}
      jpc-check saves nothing unless you add --output PATH. The CSV then goes
      exactly where PATH says - a short PATH is read from your current folder.
      Missing folders in PATH are created. A file already at PATH is replaced;
      the input file never is.""",
                paths_with_spaces("'My Batch.csv'")),
            "how": """    {bold}What it checks{reset}
{jpc_av_definition}

      Each JPC_AV_xxxxx is looked up live in ArchivesSpace, read-only: does a
      record carry it? Records at every level are searched, so a JPC_AV_xxxxx
      on a file or series record is caught too.

    {bold}Comparing with Airtable{reset}
      When the file is a pull, jpc-check also compares its Airtable columns
      with what ArchivesSpace holds. The Airtable values come from the pull -
      a snapshot taken when it was pulled; Airtable is not read again.

      The pull saves only the columns the view shows, plus ASpace Hold and
      ASpace Issue, which it always includes. So a column can be compared
      only if the view shows it.

      jpc-check compares up to two Airtable columns with ArchivesSpace.
      Neither is required - each one the file has adds its own comparison:

        • {bold}ASpace Parent RefID{reset}
            Compares parents: finds "parent differs", and a blank Airtable
            parent where ArchivesSpace has one.

        • {bold}((( ASpace Item Record Created ))){reset}
            Finds items in ArchivesSpace that are not marked Yes. When the
            view also includes the Yes rows, it finds "Marked Yes, not found
            in ArchivesSpace" too - a view that filters out Yes rows can
            never show it.

      A column the file lacks is never treated as blank. If only one is
      missing, the opening lines name it under "Not checked:". If both are
      missing, the opening Mode line says the file has no Airtable tracking
      columns, and jpc-check only reports whether each JPC_AV_xxxxx exists.

    {bold}One line per JPC_AV_xxxxx{reset}
      Each JPC_AV_xxxxx lands on exactly one line - the first that applies, in
      the order below. Names appear in the colors the check uses on screen.

      {bold}Lines that need review{reset} - any of these makes jpc-check exit 2:

        • {warn}{bold}Could not check{reset}
            The lookup failed, the JPC_AV_xxxxx is malformed (not JPC_AV_
            followed by digits), the record is malformed, its parent could
            not be read while ASpace Parent RefID is being compared, or Item
            Record Created is unreadable (e.g. "Yes, No").

        • {bad}{bold}Ambiguous{reset}
            Several records carry the same JPC_AV_xxxxx.

        • {bad}{bold}Conflicting rows in the file{reset}
            The JPC_AV_xxxxx is on rows in the file that disagree (parent,
            Yes, hold or issue).

        • {bad}{bold}Not an item record{reset}
            The JPC_AV_xxxxx is on a record that is not an item (a file,
            series...).

        • {bad}{bold}Marked Yes, not found in ArchivesSpace{reset}
            Airtable says the record was created, but no record carries the
            JPC_AV_xxxxx.

        • {bad}{bold}In ArchivesSpace, parent differs{reset}
            Airtable's parent is not the record's parent in ArchivesSpace.

        • {warn}{bold}In ArchivesSpace, Airtable incomplete{reset}
            The Airtable parent is blank while ArchivesSpace has one, or the
            item is not marked Yes.

      {bold}Lines with no comparison problem:{reset}

      Hold and issue markers may still need attention. These lines do not
      by themselves establish that an item is ready to import.

        • {ok}{bold}In ArchivesSpace, compared fields agree{reset}
            The compared columns match.

        • {ok}{bold}In ArchivesSpace{reset}
            The record exists; nothing was compared (a plain list, or a file
            with neither of the two compared columns).

        • {bold}Not found by catalog number{reset}
            No record carries the JPC_AV_xxxxx - not a verdict that the item
            is new.

      A line needing review lists every fact that applies. Held rows are
      marked [on hold: ...]; open issues on rows not held, [issue: ...].

      jpc-check copies nothing and fixes nothing: it shows where Airtable
      and ArchivesSpace disagree today.""",
            "output": """    On screen:
      The opening lines say what was compared, with what - including the
      pull's view and time, read from the pull's first line ("unknown" for
      any other file). RESULT counts each line; then each line's
      JPC_AV_xxxxx, the ones needing review first.

    With --output PATH, also a CSV:
      {cyan}PATH{reset}

      Columns: CATALOG_NUMBER, Outcome, ArchivesSpace parent, Airtable
      parent, ((( ASpace Item Record Created ))), ASpace Hold, ASpace Issue,
      Detail. A column the input lacked says "(not in file)" - not the same
      as an empty cell.

      jpc-check leaves the input file, Airtable and ArchivesSpace unchanged.""",
            "next_steps": """    What comes next depends on the result. If you used --env sandbox for
    jpc-check, the answers are about the sandbox; add --env sandbox to any
    command below that should use it too.

    {bold}JPC_AV_xxxxx not found - a create batch{reset}
      Continue with {bold}jpc-fill{reset}:
      {command}jpc-fill --file PULL{reset}

      Replace {bold}PULL{reset} with the CSV's full path from the "Saved pulled CSV:"
      line printed near the end of a successful jpc-pull run.

    {bold}JPC_AV_xxxxx already in ArchivesSpace - when preparing records to create{reset}
      A create batch is for items not yet in ArchivesSpace. An item already
      there would be a duplicate: jpc-import stops the whole batch before
      writing anything if any row already exists (with --keep-going, it
      skips those rows instead).

      Normally jpc-writeback sets the parent and Yes after an import creates
      a record. This create run will not create an already-existing item, so
      its write-back will not update that item's Airtable fields. If an
      earlier production import created the item and its write-back was
      never run, run jpc-writeback with that import's report instead. For
      items without a usable production create report, update Airtable by
      hand:

        1. Confirm the production record is the intended item - compare the
           title and path the check shows.
        2. Enter its parent in ASpace Parent RefID. Run jpc-check with
           --output PATH: the CSV's "ArchivesSpace parent" column has it.
        3. Set ASpace Item Record Created to Yes in the ((( ASpace_tracking )))
           table (it shows in <<< ASpace_import >>> as
           ((( ASpace Item Record Created )))).
        4. Pull again.

      Do not mark Yes based on a sandbox result. If you cannot confirm the
      record yet, leave the item out of the create view until you can.

    {bold}Lines needing review{reset}
      Correct Airtable where it is wrong. Where the cause is unclear, tick
      ASpace Hold and record the evidence in ASpace Issue in the
      <<< ASpace_import >>> table, so no create run touches the item.
      Then pull again and re-check.

    {bold}Could not check / Ambiguous{reset}
      Retry a failed lookup later. Several records carrying the same
      JPC_AV_xxxxx must be cleaned up in ArchivesSpace first.

    {bold}Further instructions: {command}jpc-fill --help{reset}
""",
            "runs": """    jpc-check runs the Python tool aspace_csv_export.py for you, in its
    --check mode. You do not need to run it separately.

    {bold}Equivalent direct command{reset}
      {command}python3 aspace_csv_import/aspace_csv_export.py --check FILE --env production{reset}
      Replace FILE with the CSV's path; quote paths with spaces.

    {bold}Underlying tool's help{reset}
      {command}python3 aspace_csv_import/aspace_csv_export.py --help{reset}
      This describes all of the Python tool's direct-use options (export,
      --check and --fill-parents). jpc-check accepts only the flags listed
      in OPTIONS above.""",
            "exit": """    {ok}{bold}0{reset}    Clear      Every JPC_AV_xxxxx got a definite answer and nothing
                    needs review. Ones simply not found count as definite.
    {bad}{bold}1{reset}    Stopped    The list could not be read or login failed - nothing
                    was checked. Or the --output CSV could not be saved;
                    the check itself ran and its result is on screen.
    {warn}{bold}2{reset}    Review     Something needs review or could not be checked.
                    Also: an argument was rejected.
    {warn}{bold}130{reset}  Stopped    Interrupted with Ctrl-C. Airtable and ArchivesSpace
                    are unchanged. With --output, a file at PATH may be an
                    older report - its presence does not mean this run saved
                    it. A .tmp file is not a finished report.""",
        },
    },
    "fill": {
        "title": "fill parent RefIDs in a CSV",
        "summary": "Fill blank parent RefIDs; save ready and human-review CSVs (read-only)",
        "script": "aspace_csv_import/aspace_csv_export.py",
        "input": ("--file", "FILE", "The CSV saved by jpc-pull"),
        "base": lambda value: ["--fill-parents", value],
        "extras": {"--no-color": None},
        "aspace": True,
        "example": "jpc-fill --file one-inch_check_20260930_0545.csv",
        "help": {
            "paths": help_blocks(
                full_path_of_pull("one-inch_check_20260930_0545.csv"),
                short_path("one-inch_check_20260930_0545.csv", "__airtable_exports__"),
                """    {bold}Save folder{reset}
      jpc-fill saves its two files beside the input CSV - in the same folder
      as the pulled CSV, regardless of the directory from which you run it.""",
                paths_with_spaces("'My Batch.csv'")),
            "how": """    {bold}What "fill" means{reset}
      jpc-fill fills in blank ASpace Parent RefID cells - that column only.
      Despite the similar name, it is not the opposite of jpc-pull: jpc-pull
      copies an Airtable view into a CSV; jpc-fill reads that CSV, looks up
      existing parent records in ArchivesSpace, and saves two new CSV files.

      jpc-fill creates no ArchivesSpace records and writes nothing to Airtable.

{fill_how_parents}

    {bold}When the whole fill stops{reset}
      Several matching file records for one row send just that row to the
      review file. Duplicate normalized episode keys stop the whole fill
      instead, before either CSV is saved.

      Each episode record's title is reduced to a key: numbers compare as
      numbers and other text ignores case. So "Episode 09" and "Episode 9"
      have the same key, as do "Episode Pilot" and "Episode pilot", and two
      "Episode 4006" records. If any two episode records anywhere in the
      resource share a key, jpc-fill says "duplicate episode key ... correct
      the hierarchy in ArchivesSpace and rerun" and saves nothing. Correct
      the episode records in ArchivesSpace, then run jpc-fill again.""",
            "output": """    Two files are saved beside the pull:

{fill_files}

    {bold}{{VIEW}}_YYYYMMDD_HHMM{reset} is the pulled CSV's name without .csv.
    Example: {cyan}one-inch_check_20260930_0545.csv{reset} gives
    {cyan}jpc-fill_one-inch_check_20260930_0545_parent_ref-id_ready_for_ASpace_import.csv{reset}""",
            "next_steps": """    In the normal JPCA ArchivesSpace <-> Airtable workflow, the next step
    when preparing new records is {bold}jpc-import{reset}, run on the ready file.

    If you used --env sandbox for jpc-fill, add it to both import commands
    below. Each command defaults to production independently.

    {bold}If the ready file contains rows, dry-run it first{reset}
      {command}jpc-import --file READY --dry-run{reset}

      Replace {bold}READY{reset} with the ready CSV's full path from the
      "Saved ready CSV:" line printed near the end of a successful
      jpc-fill run.

      The dry run checks every row against ArchivesSpace and shows the PLAN:
      each title, where it will sit, its dates, format, container and notes.
      If any row fails the checks, it lists those rows instead of a PLAN.
      It writes nothing.

    {bold}Then the real import{reset}
      {command}jpc-import --file READY{reset}

      The plan is shown again; records are created only after you type yes.

    {bold}The review file{reset}
      For each row, read "Parent Note" and "Fix in", correct the source -
      Airtable, or the ArchivesSpace hierarchy - then pull and fill again
      for those rows. They are not imported until they come back ready.

    {bold}Further instructions: {command}jpc-import --help{reset}
""",
            "runs": """    jpc-fill runs the Python tool aspace_csv_export.py for you, in its
    --fill-parents mode. You do not need to run it separately.

    {bold}Equivalent direct command{reset}
      {command}python3 aspace_csv_import/aspace_csv_export.py --fill-parents FILE --env production{reset}
      Replace FILE with the pulled CSV's path; quote paths with spaces.

    {bold}Underlying tool's help{reset}
      {command}python3 aspace_csv_import/aspace_csv_export.py --help{reset}
      This describes all of the Python tool's direct-use options (export,
      --check and --fill-parents). jpc-fill accepts only the flags listed in
      OPTIONS above.""",
            "exit": """    {ok}{bold}0{reset}    Ready      Every row is in the ready file; the review file is empty.
    {bad}{bold}1{reset}    Stopped    Nothing usable was saved: the pulled CSV could not be
                    read, login failed, the ArchivesSpace hierarchy could not
                    be read (including duplicate normalized episode keys -
                    see HOW IT WORKS), or a file could not be written.
                    If the ready file fails after the review file was saved,
                    the message names the review file to delete.
    {warn}{bold}2{reset}    Review     Some rows need human review - expected; both files
                    are saved. Also: an argument was rejected, or an output
                    file already exists (nothing is saved).
    {warn}{bold}130{reset}  Stopped    Interrupted with Ctrl-C. Each file is saved whole or
                    not at all, but not as a pair. The review file is saved
                    first: if it is there without the ready file, delete it
                    before running again, or the rerun refuses. If both are
                    there, both were saved, even if their paths were not
                    printed. A .tmp file is not a finished CSV.""",
        },
    },
    "import": {
        "title": "create ArchivesSpace records",
        "summary": "Create records: checks every row, shows the PLAN, writes after you type yes",
        "script": "aspace_csv_import/aspace_csv_import.py",
        "input": ("--file", "FILE", "The ready CSV saved by jpc-fill"),
        "base": lambda value: ["--create-records", "--file", value],
        "extras": {"--dry-run": None, "--keep-going": None, "--no-color": None},
        "aspace": True,
        "example": "jpc-import --file jpc-fill_DVD-batch_20260930_0900_parent_ref-id_ready_for_ASpace_import.csv --dry-run",
        "help": {
            "paths": help_blocks(
                """    {bold}Full path{reset}
      Give --file the ready CSV that jpc-fill saved. Its full path is on the
      "Saved ready CSV:" line near the end of a successful jpc-fill run.
      Copy that path and paste it after --file; a full path works from any
      folder. Dragging a file from Finder also gives its full path.

      Example on this computer:
      {cyan}{exports}/jpc-fill_DVD-batch_20260930_0900_parent_ref-id_ready_for_ASpace_import.csv{reset}""",
                short_path("jpc-fill_DVD-batch_20260930_0900_parent_ref-id_ready_for_ASpace_import.csv", "__airtable_exports__"),
                "{import_save_folder}",
                paths_with_spaces("'My Batch.csv'")),
            "how": """    {bold}What it creates{reset}
{jpc_av_definition}

      One item record per row, under the parent named in the row's ASpace
      Parent RefID, with the row's title, dates, format and notes. Each item
      is linked to an AV Case top container whose indicator is its
      JPC_AV_xxxxx: an existing one is reused, otherwise one is created.

    {bold}Checks before anything is written{reset}
      First the CSV itself is checked, before connecting to ArchivesSpace.
      Any problem found here stops the whole run (exit 1), with or without
      --keep-going:

        • The CSV has every import column, no duplicate headers, no stray
          extra cells, and at least one row.
        • Each JPC_AV_xxxxx is present, well formed (JPC_AV_ followed by
          digits) and appears only once in the file.
        • Each row has an ASpace Parent RefID.
        • Dates are real dates within 1940-2020; a two-digit year such as
          11/2/93 means 1993 (40-99 are 19xx, 00-20 are 20xx).

      Held rows skip these content checks; the hold is dealt with below.

      Then each row is checked against live ArchivesSpace:

        • The JPC_AV_xxxxx is not already in ArchivesSpace.
        • The parent exists in this resource.
        • Original Format is a term in ArchivesSpace's extent list.
        • The item's AV Case container is not ambiguous.
        • The item is not on hold (ASpace Hold).

      The PLAN then shows what would happen to every row: each record to be
      created - title, where it will sit, dates, format, container and notes
      in full - and, with --keep-going, each row skipped or refused, with
      the reason.

    {bold}Dry run and real run{reset}
      --dry-run checks every row and shows the PLAN, then each row's
      simulated outcome ("Would be created") and a "RESULT - dry run"
      summary. Nothing is written and no files are saved.

      A real run shows the PLAN, then asks:

          Type yes to write, anything else to cancel:

      Only yes writes. Anything else cancels, and nothing is written.

    {bold}When rows already exist or have a problem{reset}
      Without --keep-going: one row that fails the live checks - already in
      ArchivesSpace, or any other problem, a hold included - stops the whole
      run before anything is written. Instead of the PLAN, the run prints
      "... failed preflight - ABORTING, nothing was written", lists each
      problem row with its reason, then the rows that passed but were not
      created.

      With --keep-going: rows already in ArchivesSpace are skipped, rows
      failing the other live checks (held rows included) are refused, and
      the rest are created after yes. A problem found in the CSV check still
      stops the whole run.

    {bold}During writing{reset}
      In either mode, a row that fails while being written is reported and
      the run moves on to the next row. A fatal error or Ctrl-C can stop
      the run partway. Item records already created are not rolled back -
      they stay in ArchivesSpace.

      One write-time difference between the modes: just before each row is
      written, its JPC_AV_xxxxx is looked up again. If a record with that
      JPC_AV_xxxxx has appeared in ArchivesSpace since the checks, a run
      without --keep-going stops there and writes no later rows. With
      --keep-going, exactly one existing record means the row is skipped;
      more than one means it is refused. Either way the run carries on.""",
            "output": """{run_output_opening}

      • {cyan}import_report_YYYYMMDD_HHMMSS_PID.json{reset}
        What happened to each row - the receipt jpc-writeback reads.
{receipt_csv_bullet}
      • {cyan}import_records_YYYYMMDD_HHMMSS_PID.json{reset}
        Each record created, as ArchivesSpace stored it, read back after the
        write. Saved only when the run created records. If a read-back
        fails, that record is missing from the file (the run says "Records
        file incomplete"), and the write-back sends that row to review.
{log_bullet}

{cancel_and_ctrl_c}

{run_stamp}
      Example: {cyan}import_report_20260929_084410_5702.json{reset}

    RESULT counts each outcome: Created, Skipped, On hold, Failed or refused,
    Outcome unknown, and rows not written or not reached. Each saved file's
    path is printed ("Saved import report: ..."); a file that could not be
    saved is printed in red as "NOT saved ...".

    jpc-import never changes Airtable or the input CSV.""",
            "next_steps": """    After a real create run in production, the next step is
    {bold}jpc-writeback{reset}, which records the results in Airtable: each created
    item's parent in ASpace Parent RefID, and Yes in ASpace Item Record
    Created.

    If you used --env sandbox, stop here: the write-back accepts production
    imports only. After a dry run, run the real import first.

    {bold}Record the results{reset}
      {command}jpc-writeback --report REPORT --run{reset}

      Replace {bold}REPORT{reset} with the import report's full path from the
      "Saved import report:" line printed near the end of the run. (The run
      also prints the full write-back command under NEXT STEP.)

      Every change is listed, row by row; Airtable is written only after
      you type yes.

    {bold}Preview only (optional){reset}
      {command}jpc-writeback --report REPORT{reset}

      Shows the same list of changes and writes nothing.

    {bold}A created record deleted since{reset}
      Add --exclude-catalog JPC_AV_xxxxx for each one - to the --run
      command, and to a preview if you run one - or Airtable would record
      it as created.

    {bold}A PARTIAL run{reset}
      The write-back records only the confirmed creations. Check any
      "Outcome unknown" JPC_AV_xxxxx in ArchivesSpace before rerunning -
      the record may exist.

    {bold}Rows skipped - already in ArchivesSpace{reset}
      Do not import them again. Confirm the production record is the
      intended item, then bring Airtable up to date - see "JPC_AV_xxxxx
      already in ArchivesSpace" in jpc-check --help.

    {bold}Rows refused{reset}
      Correct each problem at its source (Airtable, or the ArchivesSpace
      hierarchy), then pull, fill and import those rows again.

    {bold}Further instructions: {command}jpc-writeback --help{reset}
""",
            "runs": """    jpc-import runs the Python tool aspace_csv_import.py for you, in its
    --create-records mode. You do not need to run it separately.

    {bold}Equivalent direct command{reset}
      {command}python3 aspace_csv_import/aspace_csv_import.py --create-records --file FILE --env production{reset}
      Replace FILE with the ready CSV's path; quote paths with spaces.

    {bold}Underlying tool's help{reset}
      {command}python3 aspace_csv_import/aspace_csv_import.py --help{reset}
      This describes all of the Python tool's direct-use options (creating
      and updating). jpc-import accepts only the flags listed in OPTIONS
      above.""",
            "exit": """    {ok}{bold}0{reset}    Done       Every row was carried out.
    {bad}{bold}1{reset}    Stopped    Before the yes - a bad CSV, a login problem, or
                    cancelled at the prompt - nothing was written to
                    ArchivesSpace. A fatal error after writing began saves a
                    partial report: check it in ArchivesSpace before rerunning.
    {warn}{bold}2{reset}    Review     Some rows failed, were refused or held, or a problem
                    row stopped the whole run before writing (the run lists
                    the rows and why). Also: an argument was rejected.
    {bad}{bold}3{reset}    Unsaved    Records may have been written, but the reports could
                    not be saved - check ArchivesSpace before rerunning.
    {warn}{bold}130{reset}  Stopped    Interrupted with Ctrl-C. Any receipt saved covers
                    only the rows reached; a Ctrl-C before processing began,
                    or during a dry run, saves none.""",
        },
    },
    "update": {
        "title": "update ArchivesSpace records",
        "summary": "Update existing records: checks every row, shows each change in the PLAN, writes after you type yes",
        "script": "aspace_csv_import/aspace_csv_import.py",
        "input": ("--file", "FILE", "The CSV saved by jpc-pull; its columns decide which fields change"),
        "base": lambda value: ["--update-only", "--file", value],
        "extras": {"--dry-run": None, "--no-color": None},
        "aspace": True,
        "example": "jpc-update --file titles_20260930_0900.csv --dry-run",
        "help": {
            "paths": help_blocks(
                full_path_of_pull("titles_20260930_0900.csv"),
                short_path("titles_20260930_0900.csv", "__airtable_exports__"),
                "{import_save_folder}",
                paths_with_spaces("'My Batch.csv'")),
            "how": """    {bold}What it changes{reset}
{jpc_av_definition}

      jpc-update changes item records already in ArchivesSpace; it never
      creates one. Each row's JPC_AV_xxxxx must match exactly one record.

      The CSV's columns decide what can change - so the Airtable view you
      pulled decides it. A column the CSV does not have is left untouched,
      and the run's first lines name both lists ("will update:" and "Left
      untouched (not in CSV):"). Updatable columns:

        • ASpace Title - the title.
        • Creation or Recording Date, Edit Date, Broadcast Date - each
          changes only the ArchivesSpace date with the same label
          (creation, Edited, broadcast): its begin date and the expression
          made from it. Its other properties and the record's other dates
          are kept; a label the record lacks is added.
        • Original Format - the format (extent type). The rest of an
          existing extent is kept; a record without an extent gets one.
        • ASpace Scope and Contents Note, ASpace PhysTech Note - in the
          first note of that type that contains text, all the text in its
          first non-empty text block (a Text sub note in ArchivesSpace) is
          replaced, however many paragraphs it holds. Other text blocks,
          other notes and the Duration list are kept; a record without that
          note gets one.

      Never changed: the JPC_AV_xxxxx, the parent (ASpace Parent RefID is
      ignored) and the AV Case container.

      A blank cell never clears anything: the ArchivesSpace value stays as
      it is. To remove text, clear the Airtable cell and delete that text
      in the ArchivesSpace staff interface - only that text, since a
      PhysTech note can also hold the Duration list.

    {bold}Checks before anything is written{reset}
      First the CSV itself is checked, before connecting to ArchivesSpace.
      Any problem found here stops the whole run (exit 1):

        • The CSV has CATALOG_NUMBER and at least one updatable column, no
          duplicate headers, no stray extra cells, and at least one row.
        • Each JPC_AV_xxxxx is present, well formed (JPC_AV_ followed by
          digits) and appears only once in the file.
        • Dates are real dates. A date outside 1940-2020 gets a warning:
          it is accepted only if it matches the date already stored.

      Held rows skip the date check; the hold is dealt with below.

      Then each row is checked against live ArchivesSpace. Any problem
      stops the whole run before anything is written - updates have no
      --keep-going:

        • The item is not on hold (ASpace Hold).
        • The JPC_AV_xxxxx matches exactly one record, and it is an item.
        • A changed format is a term in ArchivesSpace's extent list, and
          the record has no more than one extent.
        • A changed date is not one of several dates with that label on the
          record, and not a date range.
        • No change sets a date outside 1940-2020.

      jpc-pull always includes ASpace Hold, so a hold set before the pull
      is honored. A hold set after the pull is not - pull again.

      The PLAN then shows every record that will change, with each field's
      current and new value in full (notes too); unchanged records are
      counted.

    {bold}Dry run and real run{reset}
      --dry-run checks every row and shows the PLAN, then each row's
      simulated outcome ("Would update") and a "RESULT - dry run" summary.
      Nothing is written and no files are saved.

      A real run shows the PLAN, then asks:

          Type yes to write, anything else to cancel:

      Only yes writes. Anything else cancels, and nothing is written. When
      no record would change, nothing is asked and nothing is written to
      ArchivesSpace.

    {bold}During writing{reset}
      Each record is read again just before it is written. If it no longer
      matches the PLAN - someone edited it in the meantime - that row is
      refused ("Record changed after the preview") and left as it is.

      A row that fails while being written is reported and the run moves
      on to the next row. A fatal error or Ctrl-C can stop the run partway.
      Records already updated are not rolled back.""",
            "output": """{run_output_opening}

      • {cyan}import_report_YYYYMMDD_HHMMSS_PID.json{reset}
        What happened to each row - updated, unchanged or failed - and the
        changes made.
{receipt_csv_bullet}
      • {cyan}import_records_YYYYMMDD_HHMMSS_PID.json{reset}
        Each record updated or verified unchanged, as ArchivesSpace stores
        it after the run. Not saved when a problem row stopped the run
        before writing. If a read-back fails, that record is missing from
        the file (the run says "Records file incomplete").
{log_bullet}

{cancel_and_ctrl_c}

{run_stamp}
      Example: {cyan}import_report_20260929_084410_5702.json{reset}

    RESULT counts each outcome: Updated, Unchanged, On hold, Failed or
    refused, Outcome unknown, and rows not written or not reached. Each
    saved file's path is printed ("Saved import report: ..."); a file that
    could not be saved is printed in red as "NOT saved ...".

    jpc-update never changes Airtable or the input CSV.""",
            "next_steps": """    There is no write-back after an update: the new values came from
    Airtable, so Airtable already has them.

    If you used --env sandbox, the run targeted the sandbox, not
    production. Every command that continues in the sandbox needs
    --env sandbox too. To update production, start there with a dry run
    without --env sandbox and review that PLAN before the real run - a
    sandbox PLAN is not a production PLAN.

    {bold}After a dry run{reset}
      If the PLAN shows what you expect, run the real update on the same
      file, in the same environment as the dry run:

      {command}jpc-update --file PULL{reset}

      Add --env sandbox if the dry run used it. If Airtable changed after
      the pull, pull again and dry-run the new file first.

    {bold}A problem row stopped the run{reset}
      Nothing was written. Fix each listed row, pull again and rerun:

        • on hold - leave the item out of the view until it is ready, or
          clear ASpace Hold once it is.
        • No record found - jpc-update never creates. Check the JPC_AV_xxxxx;
          a new item needs jpc-fill and jpc-import instead.
        • Several records, or not an item - fix the record in ArchivesSpace.
        • Invalid extent type - correct Original Format in Airtable.
        • Several extents, several same-label dates, or a date range - the
          CSV cannot say which to change. Edit that record by hand in
          ArchivesSpace and leave the row out of the view.

    {bold}Rows refused while writing{reset}
      "Record changed after the preview": someone edited the record after
      the PLAN. Run jpc-update again (dry run first) to see its current
      changes. For any other failure, check the record in ArchivesSpace,
      then rerun the same file - rows already updated come out unchanged.""",
            "runs": """    jpc-update runs the Python tool aspace_csv_import.py for you, in its
    --update-only mode. You do not need to run it separately.

    {bold}Equivalent direct command{reset}
      {command}python3 aspace_csv_import/aspace_csv_import.py --update-only --file FILE --env production{reset}
      Replace FILE with the pulled CSV's path; quote paths with spaces.

    {bold}Underlying tool's help{reset}
      {command}python3 aspace_csv_import/aspace_csv_import.py --help{reset}
      This describes all of the Python tool's direct-use options (creating
      and updating). jpc-update accepts only the flags listed in OPTIONS
      above.""",
            "exit": """    {ok}{bold}0{reset}    Done       Every row was updated or already up to date.
    {bad}{bold}1{reset}    Stopped    Before the yes - a bad CSV, a login problem, or
                    cancelled at the prompt - nothing was written to
                    ArchivesSpace. A fatal error after writing began saves a
                    partial report: check it in ArchivesSpace before rerunning.
    {warn}{bold}2{reset}    Review     Some rows failed or were refused, or a problem row
                    (a hold included) stopped the whole run before writing
                    (the run lists the rows and why). Also: an argument was
                    rejected.
    {bad}{bold}3{reset}    Unsaved    Records may have been written, but the reports could
                    not be saved - check ArchivesSpace before rerunning.
    {warn}{bold}130{reset}  Stopped    Interrupted with Ctrl-C. Any receipt saved covers
                    only the rows reached; a Ctrl-C before processing began,
                    or during a dry run, saves none.""",
        },
    },
    "writeback": {
        "title": "record import results in Airtable",
        "summary": "Record a production create run's results in Airtable: preview by default; --run shows every change and writes after you type yes",
        "script": "aspace_csv_import/airtable_writeback.py",
        "input": ("--report", "REPORT.json", "The import_report_<stamp>.json saved by a real production create run"),
        "base": lambda value: [value],
        "extras": {"--run": None, "--exclude-catalog": "JPC_AV_xxxxx", "--no-color": None},
        "repeatable": {"--exclude-catalog"},
        "aspace": False,
        "example": "jpc-writeback --report import_report_20260929_084410_5702.json --run",
        "help": {
            "environment": """    Reads and writes the configured Airtable base, not ArchivesSpace.
    --env is not supported: only production import reports are accepted.

    Tokens, from creds.py (or the shell variable named in brackets):
      airtable_pat_read_only   every read (AIRTABLE_PAT_READ_ONLY)
      airtable_pat_write       the writes - needed only with --run
                               (AIRTABLE_PAT_WRITE)

    creds.py also needs a production entry: its repo_id is used to check
    the record URIs in the report.""",
            "paths": help_blocks(
                """    {bold}Full path{reset}
      Give --report the import report that jpc-import saved - the .json
      file, not the .csv. Its full path is on the "Saved import report:"
      line near the end of the import run. Copy that path and paste it
      after --report; a full path works from any folder. Dragging a file
      from Finder also gives its full path.

      Example in the default folder:
      {cyan}~/aspace_import_reports/import_report_20260929_084410_5702.json{reset}""",
                short_path("import_report_20260929_084410_5702.json", "the import reports folder"),
                """    {bold}Save folder{reset}
      With --run, the outcomes file is saved in the same folder as the
      import report. The run prints its full path near the end ("Saved
      write-back outcomes: ..."). A preview saves nothing.""",
                paths_with_spaces("'My Report.json'")),
            "how": """    {bold}What it writes{reset}
{jpc_av_definition}

      For each row the import created, two Airtable fields:

        • ASpace Parent RefID in <<< ASpace_import >>> - the parent the
          import used. Written only into a blank cell; a parent already
          there is never replaced.
        • ASpace Item Record Created in ((( ASpace_tracking ))) - set to
          Yes.

      Rows the import skipped, refused or failed are left alone.
      ArchivesSpace is never contacted: jpc-writeback reads the import
      report, its records file and Airtable.

    {bold}Checks before anything is written{reset}
      First the report: it must be the .json report of a real (not dry-run)
      production create run. A dry-run or sandbox report, or the .csv
      receipt, stops the run (exit 1) with nothing written.

      Then Airtable is read again - three tables, about a minute each - so
      the plan uses Airtable as it is now. A created row is written only if
      all of these hold; otherwise it is listed for review and left alone:

        • The report has a valid JPC_AV_xxxxx and parent RefID for it,
          only once, with a production record URI and a read-back snapshot
          of the record (from the import's records file).
        • Exactly one JPCA-AV_SOURCE row (the table CATALOG_NUMBER links
          to) is named with the JPC_AV_xxxxx, and exactly one
          <<< ASpace_import >>> row and one ((( ASpace_tracking ))) row link
          to that same source record - neither linking other items too.
        • The item is not on hold in Airtable now (ASpace Hold) - a hold
          ticked after the import counts too.
        • Airtable's ASpace Parent RefID is blank, or already the parent
          the import used.

    {bold}Leaving rows out{reset}
      --exclude-catalog JPC_AV_xxxxx drops one created row before Airtable
      is read - for example a record deleted in ArchivesSpace since the
      import, which Airtable must not record as created. Repeat the flag
      for each one. Each value must be a row the report created; otherwise
      the run stops and nothing is written.

    {bold}Preview and --run{reset}
      Without --run, jpc-writeback shows the PLAN - counts, the rows for
      review and every change, row by row:

          JPC_AV_xxxxx  parent (blank) -> REFID  |  created No -> Yes  |  title

      then the command to run with --run. Nothing is written and nothing
      is saved.

      With --run it shows the same, then a summary, and asks:

          Type yes to write, anything else to cancel:

      Only yes writes. When nothing is left to write, nothing is asked.

    {bold}During writing{reset}
      Parents are written first, ten rows at a time, each confirmed from
      Airtable's reply; then Yes, only for rows whose parent is in place.
      The run stops at the first refused write, lost reply or Ctrl-C. Rows
      in a batch whose reply was lost are "unknown": the write may or may
      not have landed.

      Running the same command again is safe: it re-reads Airtable, writes
      only what is still missing, and counts finished rows as already done.""",
            "output": """    A preview saves nothing; its PLAN is on screen only.

    A --run past the yes prompt (or with nothing left to write) saves,
    beside the import report:

      • {cyan}airtable_writeback_YYYYMMDD_HHMMSS_PID.csv{reset}
        One line per row the import created: CATALOG_NUMBER, ASpace Parent
        RefID, outcome and note. The first line records the command and
        the time.

      A run cancelled at the yes prompt wrote nothing and saves nothing.
      A Ctrl-C while the file is being saved can leave none, even after
      Airtable was written - run the same command again to re-check.

{run_stamp}

    Outcomes: done; already done; partial (parent written, Yes not yet);
    parent not confirmed; unknown (a write may or may not have landed);
    not started; review; excluded.

    RESULT counts them, except excluded rows - the PLAN counts those. The
    saved file's path is printed ("Saved write-back outcomes: ..."); if it
    could not be saved, the run says so in red - Airtable was still
    written as shown.

    jpc-writeback never changes ArchivesSpace, the import report or the
    records file.""",
            "next_steps": """    {bold}After a preview{reset}
      If the changes are what you expect, run it with --run, keeping any
      --exclude-catalog flags:

      {command}jpc-writeback --report REPORT --run{reset}

    {bold}Unfinished rows{reset}
      Partial, parent not confirmed, unknown or not started: run the same
      --run command again. It re-reads Airtable and finishes what is left.

    {bold}Rows for review{reset}
      Nothing was written for them. By the note shown:

        • on hold in Airtable - left alone on purpose. Once the hold is
          cleared, run the same command again.
        • Airtable already has parent ... - compare both parents in
          ArchivesSpace and correct whichever is wrong. If Airtable was
          wrong, run the same command again; if the record moved, set Yes
          by hand.
        • JPCA-AV_SOURCE row(s) named it, row(s) link to it, or a row links
          several items - fix those records in Airtable, then run the same
          command again.
        • no read-back snapshot, or not a production archival object -
          confirm the record in ArchivesSpace, then update Airtable by
          hand: see "JPC_AV_xxxxx already in ArchivesSpace" in
          {command}jpc-check --help{reset}.

    {bold}Check the result (optional){reset}
      Pull a view of <<< ASpace_import >>> that shows ASpace Parent RefID
      and ((( ASpace Item Record Created ))) for these items, then compare
      it with ArchivesSpace:

      {command}jpc-check --file PULL{reset}

      Replace PULL with the new CSV's full path from the "Saved pulled
      CSV:" line printed near the end of the pull.

    {bold}Further instructions: {command}jpc-check --help{reset}
""",
            "runs": """    jpc-writeback runs the Python tool airtable_writeback.py for you.
    You do not need to run it separately.

    {bold}Equivalent direct command{reset}
      {command}python3 aspace_csv_import/airtable_writeback.py REPORT.json --run{reset}
      Replace REPORT.json with the import report's path; quote paths with
      spaces. Leave out --run for a preview.

    {bold}Underlying tool's help{reset}
      {command}python3 aspace_csv_import/airtable_writeback.py --help{reset}
      This describes the Python tool's direct-use options. jpc-writeback
      accepts only the flags listed in OPTIONS above.""",
            "exit": """    {ok}{bold}0{reset}    Done       All eligible, non-excluded rows were written or
                    already done; nothing remains unfinished or for review.
                    A preview: nothing for review.
    {bad}{bold}1{reset}    Stopped    A report, token or Airtable setup problem, or
                    cancelled while reading or at the prompt - nothing was
                    written. After writing began: a refused or unknown
                    write, Ctrl-C during the writes, or the outcomes file
                    could not be saved - run the same command again to
                    re-check and finish.
    {warn}{bold}2{reset}    Review     Rows for review, or unfinished rows (run the same
                    command again). A preview: rows for review. Also: an
                    argument was rejected.
    {warn}{bold}130{reset}  Stopped    Ctrl-C at another moment: while the PLAN or RESULT
                    was shown, or while the outcomes file was being saved.
                    After the yes, Airtable may be written and the outcomes
                    file missing - run the same command again to re-check.""",
        },
    },
}
ORDER = ["pull", "check", "fill", "import", "update", "writeback"]

# Where a refused flag belongs instead - said in the refusal.
ELSEWHERE = {
    "--update-only": "to update records: jpc-update",
    "--create-records": "to create records: jpc-import",
    "--check": "to check numbers: jpc-check",
    "--fill-parents": "to fill parents: jpc-fill",
    "-n": "use --dry-run",
    "-f": "the input is given with its named flag, once",
    "-o": "use --output",
    "-u": "credentials come from creds.py - jpc never takes a username or password",
    "-p": "credentials come from creds.py - jpc never takes a username or password",
    "--username": "credentials come from creds.py - jpc never takes a username or password",
    "--password": "credentials come from creds.py - jpc never takes a username or password",
}


class Refused(Exception):
    """A command line the launcher will not run; the message says why."""


def parse(verb, args):
    """(input value, env, extras) from a command's arguments, or Refused.

    Only exact, long spellings on the command's allowlist are accepted:
    anything else - an abbreviation, an attached value (--file=x), a
    repeated flag, a short form - is refused, so nothing can quietly
    replace the operation or the input the command owns."""
    spec = COMMANDS[verb]
    input_flag, metavar, _ = spec["input"]
    extras_allowed = spec["extras"]
    repeatable = spec.get("repeatable", set())
    value, env, extras, seen = None, None, [], set()

    def take(flag, i, metavar):
        if i + 1 >= len(args):
            raise Refused(f"{flag} needs a value: {flag} {metavar}")
        if args[i + 1].startswith("-"):
            # a flag where a value belongs (--file -n): refused here, not
            # handed to the tool as a file name
            raise Refused(f"{flag} needs a value: {flag} {metavar} - a value may not start "
                          f"with '-' (for a file named that way, write ./ in front)")
        return args[i + 1]

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == input_flag:
            if value is not None:
                raise Refused(f"{input_flag} was given twice - give one {metavar}")
            value = take(arg, i, metavar)
            i += 2
        elif arg == "--env" and spec["aspace"]:
            if env is not None:
                raise Refused("--env was given twice")
            env = take(arg, i, "sandbox")
            if env != "sandbox":
                # the refused value is not repeated: errors never echo input
                raise Refused("--env takes only 'sandbox' (production is the default)")
            i += 2
        elif arg in extras_allowed:
            if arg in seen and arg not in repeatable:
                raise Refused(f"{arg} was given twice")
            seen.add(arg)
            if extras_allowed[arg]:
                extras += [arg, take(arg, i, extras_allowed[arg])]
                i += 2
            else:
                extras.append(arg)
                i += 1
        else:
            raise Refused(_refusal(verb, arg))
    if value is None:
        raise Refused(f"jpc-{verb} needs {input_flag} {metavar}")
    return value, env, extras


def shown(arg):
    """An argument as it may appear in a message. An attached value is
    never echoed (--password=SECRET, -pSECRET): a refused argument can be a
    credential, and errors get pasted into support conversations."""
    if arg.startswith("--"):
        name, sep, _ = arg.partition("=")
        return name + ("=..." if sep else "")
    if arg.startswith("-") and len(arg) > 2:
        return arg[:2] + "..."
    return arg


def _refusal(verb, arg):
    spec = COMMANDS[verb]
    allowed = allowed_flags(verb)
    name = arg.split("=", 1)[0] if arg.startswith("--") else arg[:2]
    if arg == "--env":
        return f"--env is not used by jpc-{verb} (it reads and writes Airtable only)"
    if not arg.startswith("-"):
        flag, metavar, _ = spec["input"]
        return (f"unexpected {arg!r} - give the input as {flag} {metavar}, "
                f"and flags only from: {', '.join(allowed)}")
    hint = ELSEWHERE.get(name)
    if "=" in arg:
        hint = f"write it as {name} VALUE (two words)" if name in allowed else hint
    return (f"{shown(arg)} is not allowed with jpc-{verb}"
            + (f" ({hint})" if hint else "")
            + f" - allowed: {', '.join(allowed)}")


def allowed_flags(verb):
    spec = COMMANDS[verb]
    flags = [spec["input"][0]] + list(spec["extras"])
    return flags + (["--env"] if spec["aspace"] else [])


def build(verb, value, env, extras):
    """The exact argument list the tool gets: the running Python, the
    script (found beside this file), its fixed flags, --env once for the
    ArchivesSpace tools, then the extras in the order given."""
    spec = COMMANDS[verb]
    argv = [sys.executable, str(ROOT / spec["script"])] + spec["base"](value)
    if spec["aspace"]:
        argv += ["--env", env or "production"]
    return argv + extras


def usage(verb):
    spec = COMMANDS[verb]
    flag, metavar, _ = spec["input"]
    parts = [f"jpc-{verb} {flag} {metavar}"]
    for extra, meta in spec["extras"].items():
        parts.append(f"[{extra}{' ' + meta if meta else ''}]"
                     + ("..." if extra in spec.get("repeatable", ()) else ""))
    if spec["aspace"]:
        parts.append("[--env sandbox]")
    return " ".join(parts)


EXTRA_HELP = {
    "--no-color": "Disable colored output",
    "--output": "Also save the answer as a CSV at PATH",
    "--dry-run": "Preview only: check every row and show the PLAN - nothing is written",
    "--keep-going": ("Skip rows already in ArchivesSpace, refuse rows that fail the live\n"
                     "checks (holds included), and create the rest. A problem found in the\n"
                     "CSV check still stops the whole run."),
    "--run": "Write to Airtable: shows every change, writes after you type yes",
    "--exclude-catalog": "Leave out this JPC_AV_xxxxx (e.g. a record deleted since the import); repeat for each",
}


def launcher_help_screen(title, sections):
    C = Colors
    rule = "─" * 79
    lines = [f"{C.DIM}{rule}{C.RESET}",
             f"{C.BOLD}{C.CYAN}{title.center(79).rstrip()}{C.RESET}",
             f"{C.DIM}{rule}{C.RESET}"]
    for section in sections:
        name, note, body = section if len(section) == 3 else (section[0], None, section[1])
        heading = f"{C.BOLD}{C.CYAN}{name}{C.RESET}"
        if note:
            heading += f" {C.DIM}({note}){C.RESET}"
        lines.extend(["", "", heading, body.rstrip("\n")])
    return "\n" + "\n".join(lines) + "\n"


def launcher_options(options):
    C = Colors
    lines = []
    for flag, note, description in options:
        label = f" {C.YELLOW if note == '(required)' else C.DIM}{note}{C.RESET}" if note else ""
        lines.append(f"    {C.BOLD}{C.CYAN}{flag}{C.RESET}{label}")
        # a line break written into the description is kept as written
        lines.extend(textwrap.fill(part, width=78, initial_indent="      ",
                                   subsequent_indent="      ", break_long_words=False,
                                   break_on_hyphens=False)
                     for part in description.split("\n"))
    return "\n".join(lines)


def command_help(verb):
    """jpc-VERB --help: what this command accepts - never the tool's own
    help, which lists flags the launcher refuses."""
    C = Colors
    spec = COMMANDS[verb]
    custom = spec.get("help", {})
    flag, metavar, input_help = spec["input"]
    options = [(f"{flag} {metavar}", "(required)", input_help)]
    options += [(f"{extra}{' ' + meta if meta else ''}", "(optional)", EXTRA_HELP[extra])
                for extra, meta in spec["extras"].items()]
    if spec["aspace"]:
        options.append(("--env sandbox", "(optional)", "Uses the sandbox env instead of the default production env"))
    sections = [
        ("DESCRIPTION", textwrap.fill(f"{spec['summary']}.", width=78,
                                     initial_indent="    ", subsequent_indent="    ",
                                     break_long_words=False, break_on_hyphens=False)),
        ("USAGE", C.BOLD + C.GREEN + textwrap.fill(usage(verb), width=72, initial_indent="    ",
                               subsequent_indent="      ", break_long_words=False,
                               break_on_hyphens=False)
                  + C.RESET),
        ("OPTIONS", launcher_options(options)),
    ]
    if "environment" in custom:
        sections.append(("ENVIRONMENT", custom["environment"]))
    elif spec["aspace"]:
        sections.append(("ENVIRONMENT", f"    {C.RED}{C.BOLD}Production by default{C.RESET} - "
                                        f"unlike the tool itself, which asks for --env.\n"
                                        f"    Add --env sandbox for the sandbox."))
    exports = str(ROOT / "aspace_csv_import" / "__airtable_exports__")  # as the pull prints it
    style = dict(exports=exports, bold=C.BOLD, cyan=C.CYAN, command=C.GREEN,
                 ready=C.GREEN, review=C.YELLOW, dim=C.DIM, reset=C.RESET,
                 ok=C.GREEN, bad=C.RED, warn=C.YELLOW)
    style.update({name: text.format(**style) for name, text in SHARED_HELP.items()})
    sections.append(("EXAMPLES", f"    {C.GREEN}{spec['example']}{C.RESET}"))
    sections.append(("FILE PATHS", custom["paths"].format(**style)))
    if "how" in custom:
        sections.append(("HOW IT WORKS", custom["how"].format(**style)))
    if "output" in custom:
        sections.append(("OUTPUT", custom["output"].format(**style)))
    if "next_steps" in custom:
        sections.append(("NEXT STEPS", custom["next_steps"].format(**style)))
    sections.append(("RUNS", custom["runs"].format(**style) + runs_footer(verb)))
    sections.append(("EXIT", custom["exit"].format(**style) + refusal_note(flag)))
    return launcher_help_screen(f"jpc-{verb}: {spec['title']}", sections)


def overview_help():
    """jpc / jpc --help: every step, in workflow order."""
    C = Colors
    # what each step touches outside this computer; only the writers are loud
    touches = {"pull": "reads Airtable", "check": "reads ArchivesSpace",
               "fill": "reads ArchivesSpace", "import": "writes ArchivesSpace",
               "update": "writes ArchivesSpace", "writeback": "writes Airtable"}
    width = max(len(f"jpc-{v}") for v in ORDER)
    title_width = max(len(COMMANDS[v]["title"]) for v in ORDER)
    lines = [f"    {C.GREEN}{'jpc-' + v:<{width}}{C.RESET}  {COMMANDS[v]['title']:<{title_width}}   "
             + (f"{C.YELLOW}{C.BOLD}{touches[v]}{C.RESET}" if touches[v].startswith("writes")
                else f"{C.DIM}{touches[v]}{C.RESET}")
             for v in ORDER]

    def steps(rows):
        return "\n".join(f"      {n}. {C.GREEN}{cmd:<36}{C.RESET}  {note}"
                         for n, (cmd, note) in enumerate(rows, 1))
    create = steps([("jpc-pull --view NAME", "save the batch's Airtable view"),
                    ("jpc-check --file PULL", "optional: which already exist"),
                    ("jpc-fill --file PULL", "parents; ready and review CSVs"),
                    ("jpc-import --file READY --dry-run", "check every row, show the PLAN"),
                    ("jpc-import --file READY", "PLAN again, type yes to write"),
                    ("jpc-writeback --report REPORT --run", "record the results in Airtable")])
    update = steps([("jpc-pull --view NAME", "view with the fields to change"),
                    ("jpc-update --file PULL --dry-run", "show each change in the PLAN"),
                    ("jpc-update --file PULL", "PLAN again, type yes to write")])
    return launcher_help_screen("jpc - one short command per workflow step", [
        ("DESCRIPTION", f"""    The jpc- commands carry the JPCA ArchivesSpace <-> Airtable workflow,
    one step per command. Each runs one existing Python tool with that
    step's fixed flags filled in; the tools keep all their own checks,
    PLANs and yes prompts.

    Every command has its own detailed help: {C.GREEN}jpc-STEP --help{C.RESET}"""),
        ("USAGE", f"    {C.GREEN}jpc-STEP --INPUT VALUE [options]{C.RESET}\n"
                  f"    {C.GREEN}jpc-STEP --help{C.RESET}\n\n"
                  f"    Note the hyphen: {C.GREEN}jpc-import{C.RESET}, not jpc import."),
        ("COMMANDS", "in workflow order", "\n".join(lines) + f"""

    Only the steps that write change anything outside this computer, and
    each shows its changes and asks for yes before writing."""),
        ("ENVIRONMENT", f"""    jpc-check, jpc-fill, jpc-import and jpc-update talk to ArchivesSpace.
    They use {C.RED}{C.BOLD}PRODUCTION{C.RESET} unless you add --env sandbox - on EACH command:
    every one defaults to production on its own. The other two, jpc-pull
    and jpc-writeback, work on Airtable only and take no --env."""),
        ("WORKFLOWS", f"""    These workflows use production. For sandbox work, add --env sandbox
    to every ArchivesSpace command and stop before jpc-writeback.

    {C.BOLD}Create new item records{C.RESET}
{create}

    {C.BOLD}Update existing item records{C.RESET}
{update}

    NAME    the Airtable view's exact name
    PULL    the path from "Saved pulled CSV:"
    READY   the path from "Saved ready CSV:"
    REPORT  the JSON path from "Saved import report:"

    Each command's --help explains its step in detail."""),
        ("SETUP", f"""    Once per machine, with the JPC_AV environment active, in the repo folder:
        {C.GREEN}python -m pip install -e .{C.RESET}
    "command not found": the JPC_AV environment is not active, or this
    one-time install has not been done yet."""),
        ("EXIT", f"""    Each command exits with its tool's own code - see its --help.
    {C.YELLOW}2{C.RESET} when a jpc- command refuses the command line, before the tool runs."""),
    ])


def requests_available():
    """True when the tools' one third-party package can be imported."""
    if "requests" in sys.modules:
        return True
    try:
        return importlib.util.find_spec("requests") is not None
    except (ImportError, ValueError):
        return False


def missing_package():
    """The friendly message when the environment is active but lacks a
    package the tools need (an inactive environment has no jpc commands)."""
    return ("the required package 'requests' is not installed in this Python.\n"
            "       Activate the JPC_AV environment (conda activate JPC_AV), and if it is\n"
            "       active, run: python -m pip install -e . in the repo folder")


def refuse(verb, message):
    C = Colors
    prefix = f"jpc-{verb}" if verb else "jpc"
    print(f"{C.RED}{prefix}: error: {message}{C.RESET}", file=sys.stderr)
    if verb:
        print(f"{C.DIM}usage: {usage(verb)}   (jpc-{verb} --help for details){C.RESET}",
              file=sys.stderr)
    return 2


def run(verb, args, execute=os.execv):
    """One jpc- command end to end. Returns an exit code for refusals and
    help; on success it never returns - the tool replaces this process."""
    if "--no-color" in args:
        Colors.disable()
    if "--help" in args or "-h" in args:
        print(command_help(verb))
        return 0
    try:
        value, env, extras = parse(verb, args)
    except Refused as e:
        return refuse(verb, str(e))
    if not requests_available():
        refuse(None, missing_package())
        return 1
    argv = build(verb, value, env, extras)
    C = Colors
    if COMMANDS[verb]["aspace"]:
        label = (f"{C.RED}{C.BOLD}PRODUCTION{C.RESET} (jpc default - add --env sandbox for the sandbox)"
                 if env is None else f"{C.GREEN}{C.BOLD}SANDBOX{C.RESET} (--env sandbox)")
        print(f"Environment: {label}")
    print(f"{C.DIM}Running: {shlex.join(argv)}{C.RESET}", flush=True)
    sys.stderr.flush()
    execute(argv[0], argv)
    return 0  # only reached when a test replaces execute


def overview(args=None):
    """The bare `jpc` command: the overview, and a pointer when someone
    types `jpc import ...` with a space."""
    args = sys.argv[1:] if args is None else args
    if "--no-color" in args:
        Colors.disable()
    rest = [a for a in args if a != "--no-color"]
    if not rest or rest[0] in ("--help", "-h"):
        print(overview_help())
        return 0
    word = rest[0]
    if word in COMMANDS:
        return refuse(None, f"the command is jpc-{word} (with a hyphen): jpc-{word} --help")
    return refuse(None, f"unknown {shown(word)!r} - the commands are "
                        f"{', '.join('jpc-' + v for v in ORDER)} (jpc --help lists them)")


# Entry points named in pyproject.toml ([project.scripts]).
def main():
    sys.exit(overview())


def _entry(verb):
    def entry():
        sys.exit(run(verb, sys.argv[1:]))
    entry.__name__ = verb
    return entry


pull = _entry("pull")
check = _entry("check")
fill = _entry("fill")
import_ = _entry("import")
update = _entry("update")
writeback = _entry("writeback")


if __name__ == "__main__":
    main()
