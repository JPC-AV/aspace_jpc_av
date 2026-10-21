# JPC ArchivesSpace AV Tools

Python scripts for managing audiovisual archival objects in ArchivesSpace for the Johnson Publishing Company collection.

## Overview

This repository contains the tools for the Johnson Publishing Company Archive (JPCA) audiovisual collection processing. They create, update, export and check records in ArchivesSpace and support the ingest workflow of assets to the Smithsonian DAMS.

1. **aspace_csv_import** — Creates and updates item-level archival objects from CSV metadata
2. **aspace_csv_export** — Exports AV records to an import-shaped CSV (round trip / audit), optionally checking MADS
3. **check_mads** (`jpc-mads`) — Reports which items are live in MADS, the public DAMS delivery
4. **aspace_rename_directories** — Processes digitized video folders: records each runtime in ArchivesSpace and adds the record's ref ID to the folder name

## Directory Structure

```
aspace_jpc_av/
├── README.md                     # This file
├── aspace_client.py              # Shared ArchivesSpace API client (used by both scripts)
├── console.py                    # Shared terminal display: -h screens, run headers, RESULT blocks
├── jpc.py                        # The jpc- commands: one short command per workflow step
├── pyproject.toml                # Installs the jpc- commands (python -m pip install -e .)
├── creds_template.py             # Credential template (see Setup below)
├── creds.py                      # Your local credentials (gitignored, you create this)
├── requirements.txt              # Python dependencies
│
├── aspace_csv_import/
│   ├── aspace_csv_import.py      # Main import script
│   ├── aspace_csv_export.py      # Export AV records to a CSV; --check, --fill-parents
│   ├── airtable_pull.py          # Save an Airtable view as a CSV (read-only)
│   ├── airtable_writeback.py     # Record a create run's results in Airtable
│   ├── check_mads.py             # Check which items are live in MADS (public DAMS delivery)
│   ├── check_extent_types.py     # Utility to validate extent types against ASpace
│   ├── sheet_rules.py            # The sheet contract: column names + validation rules (imported, never run)
│   ├── README.md                 # Detailed usage documentation
│   └── docs/
│       ├── CSV_TO_ASPACE_MAPPING.md   # Field mapping reference
│       ├── EXAMPLE_MAPPING.md         # Example CSV to JSON mappings
│       └── POTENTIAL_MAPPINGS.md      # Unmapped fields for future use
│
└── aspace_rename_directories/
    ├── aspace-rename-directories.py  # Main processing script
    └── README.md                     # Detailed usage documentation
```

### File Descriptions

More detailed descriptions of each file and usage in directory-specific README.md files.

| File | User Interaction | Description |
|------|------------------|-------------|
| `aspace_client.py` | Backend | Shared API client: credentials loading, one keep-alive session, login/logout, retries, verified lookups, and scope-locked writes. Both main scripts build on it. |
| `console.py` | Backend | Shared terminal display for every tool: the -h layout, argument-error screen, run header, RESULT block, saved-file lines and colors (`--no-color`). |
| `jpc.py` | Run via the `jpc-` commands | The short commands for each workflow step (`jpc-pull`, `jpc-check`, `jpc-fill`, `jpc-import`, `jpc-update`, `jpc-writeback`, `jpc-rename`, `jpc-mads`). Each runs one tool with that step's fixed flags; `jpc` lists them. |
| `pyproject.toml` | One-time setup | Installs the `jpc-` commands into the active environment. |
| `creds_template.py` | Reference only | Template showing required credential format. Do not edit directly. |
| `creds.py` | User creates/edits | Your local credentials file. You create this from the template. |
| `requirements.txt` | One-time setup | Python package dependencies. Run `pip install -r requirements.txt` once. |
| `aspace_csv_import.py` | Run via command line | Main script for importing CSV metadata to ArchivesSpace. |
| `aspace_csv_export.py` | Run via command line | Exports AV records to an import-shaped CSV in tree order with hierarchy and audit columns; `--mads-live` checks MADS; `--check` says which catalog numbers are in ArchivesSpace and whether an Airtable pull agrees; `--fill-parents` fills parent ref IDs. Read-only. |
| `airtable_pull.py` | Run via command line | Saves one Airtable view of `<<< ASpace_import >>>` as a CSV. Read-only. |
| `airtable_writeback.py` | Run via command line | After a production create run, records each created item's parent, its own ref ID (`ASpace Item RefID`) and `ASpace Item Record Created` = Yes in Airtable, after you confirm. |
| `check_mads.py` | Run via command line | Checks which catalog numbers are live in MADS (public URLs only), from a list or a batch folder. Everyday runs: `jpc-mads`. |
| `check_extent_types.py` | Run via command line | Troubleshooting: lists valid extent types in your ASpace instance. The import's dry run already checks formats. |
| `sheet_rules.py` | Backend | The sheet contract: column names and the validation rules every tool applies. |
| `docs/*.md` | Reference | Field-mapping contract, a worked example, and the unmapped-column analysis. |
| `aspace-rename-directories.py` | Run via command line | Processes digitized video folders: records runtimes in ArchivesSpace and adds ref IDs to folder names. Everyday runs: `jpc-rename`. |

### Logs and Reports

Every tool writes its reports to its own folder:

- **aspace_csv_import** — `~/aspace_import_reports/`: log, CSV and JSON receipts, and `import_records_*.json` (the records as stored after the run)
- **aspace_csv_export** — `~/aspace_import_reports/` (export CSVs)
- **check_mads** — `~/aspace_mads_reports/`
- **aspace_rename_directories** — `~/aspace_rename_reports/`

Setting `logs_dir` in `creds.py` moves them all under one parent, each tool in its own subfolder (`import_reports/`, `export_reports/`, `mads_reports/`, `rename_reports/`). Log files include the exact command run, timestamps, actions taken, and any errors encountered.

## Setup

For each person, in this order. Step 3 is once **per Python environment**:
the `jpc-` commands exist only in the environment they were installed into -
whichever one you choose. Its name does not matter.

### 1. Get the tools

```bash
mkdir -p ~/github/jpc
```

```bash
cd ~/github/jpc && git clone https://github.com/JPC-AV/aspace_jpc_av.git
```

The `&&` runs the clone only if the `cd` worked.

The checkout can live anywhere; the examples below use
`~/github/jpc/aspace_jpc_av` - use your own path. Later, `git pull` in that
folder brings the tools up to date.

### 2. Choose a Python environment

Any Python 3.9 or newer environment works - one you already use (for
example the Conda environment from AV-Spex), a new one, or a plain one
inside the checkout:

```bash
conda activate YOUR-ENVIRONMENT
```

or, without Conda, from the checkout folder:

```bash
python3 -m venv jpca_aspace
source jpca_aspace/bin/activate
```

The Terminal prompt then starts with the environment's name in
parentheses, such as `(JPC_AV)` or `(jpca_aspace)`.

**The name does not matter.** The commands work in any environment,
whatever it is called: `JPC_AV`, `jpca_aspace` and `YOUR-ENVIRONMENT` in
these instructions are only examples. Use any environment you like - what
matters is that you install the commands into it (step 3) and activate it
before using them. (The optional hint in step 5 does not go by name either:
it looks inside the environments Conda lists, and the checkout's
`jpca_aspace`, for the commands themselves.)

### 3. Install the `jpc-` commands into that environment

With the environment active, go to the checkout folder and install:

```bash
cd ~/github/jpc/aspace_jpc_av
```

```bash
python -m pip install -e .
```

This installs `jpc`, `jpc-pull`, `jpc-check` (also as `jpc-lookup`), `jpc-fill`, `jpc-import`,
`jpc-update`, `jpc-writeback`, `jpc-rename` and `jpc-mads`, and the one package the tools need
(`requests`), into the **active environment only**, whatever its name. The
commands exist whenever that environment is active; another environment
needs its own install. The `-e` (editable) matters: the commands run the tools in this
folder, so `git pull` keeps them current - reinstall only when a command is
added or renamed. (`pip install -r requirements.txt` installs just
`requests`, for running the tools directly without the commands.)

**After a pull that adds a command** - `jpc-lookup` (3.8.0) is the
newest - run the install again, once in each environment that has the
commands. The
reinstall is what creates the new command: until then the shell answers
"command not found" (with the hint on, it says to reinstall).

### 4. Configure credentials

**Important:** The repository does not contain a `creds.py` file for security reasons. You must create one locally.

After cloning or pulling this repository to your local machine:

1. Open the `creds_template.py` file to see the required format
2. Create a **new file** called `creds.py` in the same directory (the repo root)
3. Copy the contents of `creds_template.py` into your new `creds.py` file
4. Fill in your actual credentials in `creds.py`

**Do NOT edit `creds_template.py` directly.** If you accidentally commit your credentials to GitHub, they will be exposed publicly. The `creds.py` file is listed in `.gitignore` so it will not be tracked or uploaded.

Your `creds.py` declares one entry per ArchivesSpace instance you can access:

```python
environments = {
    "sandbox": {
        "baseURL": "https://your-sandbox-api-url.org",
        "user": "your_username",
        "password": "your_password",
        "repo_id": "your_repository_id",      # differs between instances!
        "resource_id": "your_resource_id",    # differs between instances!
        "staff_url": "https://your-sandbox-staff-url.org",  # optional: clickable report links
    },
    # add a "production" entry only if you have production access
}
```

New setups use this `environments` block. A legacy flat `creds.py`
(top-level `baseURL`/`user`/etc.) still works and is treated as a single
`production` environment, but the block makes each target explicit.

How the scripts pick the target **when run directly** (the `jpc-` commands
default to production instead - see [Commands](#commands)):

- **One entry configured** — used automatically, nothing to type. If you only
  have sandbox access, production is unreachable from your machine.
- **Several entries configured** — every run must say which target with
  `--env sandbox` or `--env production`. There is no default, so a forgotten
  flag is a hard error, never a silent write to the wrong instance. Every run
  prints and logs a `Target:` line naming the instance it touched.

Ask your ArchivesSpace administrator if you don't know these values.

### 5. Optional: the zsh hint

One line in `~/.zshrc` makes a `jpc` command that is not found say why -
which environment has the commands, or how to install them. It finds that
environment by looking for the commands inside the environments it checks,
not by name:

```bash
[ -f ~/github/jpc/aspace_jpc_av/jpc-shell-hint.zsh ] && source ~/github/jpc/aspace_jpc_av/jpc-shell-hint.zsh
```

Use your own checkout's path; the bare `jpc` command prints the exact line.
The `[ -f ... ] &&` part skips the line when the file is not there - for
example while the checkout is on an older branch - so a new Terminal never
opens with an error.
The hint acts only when `jpc` or a `jpc-...` command is not found. Only
then does it look - at the environments Conda lists and at the checkout's
`jpca_aspace` - and it never activates, installs or runs anything. If
`~/.zshrc` already defines a `command_not_found_handler`, that one stays
and the hint stays off.

**After a `git pull`** the hint file is current, but a Terminal that was
already open keeps the hint it loaded. Open a new Terminal to use the
revised hint; the `~/.zshrc` line stays as it is. (A new command still needs
the reinstall in step 3 - the new Terminal only reloads the hint.)

### 6. Check the setup

Open a new Terminal, go to a folder outside the checkout (`cd ~`), activate
your environment, then:

```bash
jpc
```

```bash
jpc-check --help
```

`jpc` lists the commands and `jpc-check --help` shows its help screen.

### What's wrong?

- **`command not found: jpc-...`** - the environment that has the
  commands is not active (the prompt shows which one is), or they are not
  installed in the active environment yet (step 3). With the hint on, the
  message says which, and gives the command to run.
- **`the required package 'requests' is not installed`** - repeat step 3
  with the environment these commands belong to active.
- **`production is not set up on this computer`** - for sandbox work, add
  `--env sandbox`; for production work, configure production access: a
  `production` entry in `creds.py` (step 4).
- **`the sandbox is not set up on this computer`** - add a `sandbox` entry
  to `creds.py` (step 4).

## Commands

One short command per workflow step, runnable from any folder (see Setup).
Each runs one tool with that step's fixed flags filled in; the tools keep all
their own checks, PLANs and `yes` prompts. `jpc` lists them;
`jpc-STEP --help` shows what a step accepts.

| Command | Runs |
|---------|------|
| `jpc-pull --view NAME` | `airtable_pull.py NAME` |
| `jpc-check --file FILE [--output PATH]` | `aspace_csv_export.py --check FILE --env production` |
| `jpc-lookup --file FILE [--output PATH]` | the same as `jpc-check` (another name for it) |
| `jpc-fill --file FILE` | `aspace_csv_export.py --fill-parents FILE --env production` |
| `jpc-import --file FILE [--dry-run] [--keep-going]` | `aspace_csv_import.py --create-records --file FILE --env production` |
| `jpc-update --file FILE [--dry-run]` | `aspace_csv_import.py --update-only --file FILE --env production` |
| `jpc-writeback --report REPORT.json [--run] [--exclude-catalog JPC_AV_xxxxx]...` | `airtable_writeback.py REPORT.json` |
| `jpc-rename --directory PATH [--dry-run] [--mp4]` | `aspace-rename-directories.py -d PATH --env production` |
| `jpc-mads (--file FILE \| --directory BATCH) [--output PATH]` | `check_mads.py FILE` or `check_mads.py --directory BATCH` |

- **Production by default** for the commands that talk to ArchivesSpace,
  shown before anything runs; add `--env sandbox` for the sandbox. (Direct
  tools require `--env` when several environments are configured.) Each
  command decides on its own, so a sandbox trial needs `--env sandbox` on
  **every** step - and a sandbox import never goes on to `jpc-writeback`
  (the write-back accepts production reports only). The Airtable commands
  and `jpc-mads` (public MADS only) take no `--env`.
- **`jpc-rename` renames the real folders in either environment.**
  `--env sandbox` changes only which ArchivesSpace it reads and writes; the
  folders on disk are renamed all the same, with the sandbox records' ref
  IDs. Try the sandbox only on disposable copies of the folders.
- **A target missing from `creds.py` stops the command.** On a computer set
  up for the sandbox only, a command without `--env sandbox` stops before
  anything runs (exit 1), names what `creds.py` has and shows the command
  with `--env sandbox`; it never switches environments by itself.
- **Paths are read from the folder you are in.** Pasting the full path a
  tool printed ("Saved pulled CSV: ...") works from anywhere.
- **Only the flags listed**, in their long form: anything else - a short
  form (`-f`, `-n`), an abbreviation, `--file=x`, a repeated flag, a
  username or password, a flag for another step - is refused before anything
  runs, and the message says what to use instead.
- Each command prints the exact tool command it runs, then hands over: the
  tool's prompts, Ctrl-C and exit code are its own. A tool started this way
  prints its next step as a `jpc-` command; run directly, it prints the long
  command, which always works too.
- Export has no `jpc-` command yet; run it directly.

## Scripts

### aspace_csv_import

Creates or updates archival objects in ArchivesSpace from CSV metadata. Handles titles, dates, extents, notes, and container instances. Every run states its mode (`--create-records` or `--update-only`), checks every row first, and prints a plan of what it will create, skip, refuse or change; a real run writes only after you type `yes`, and a real create ends with the exact command to record the results in Airtable. A dry run (`-n`) shows the plan and writes nothing.

```bash
cd aspace_csv_import
python3 aspace_csv_import.py --create-records -f data.csv --dry-run
```

See [aspace_csv_import/README.md](aspace_csv_import/README.md) for full documentation.

### aspace_csv_export

The reverse of the importer: exports AV records to an import-shaped CSV with audit columns (ref ID, Warnings, Level, Depth, Path, URI, staff link, MADS URL, created/modified) for round-trip editing with `--update-only` or as an audit report. Rows come out in tree order (`--list` keeps list order), so `--level all` reads like the ArchivesSpace tree. `--check FILE` prints which catalog numbers are in ArchivesSpace and, given an Airtable pull, whether its parent and Item Record Created agree with ArchivesSpace. `--fill-parents FILE` fills a sheet's empty parent ref IDs from its `EJS Episode` and `ASpace File Type` columns, writing `jpc-fill_FILE_parent_ref-id_ready_for_ASpace_import.csv` and `jpc-fill_FILE_needs_human_review.csv` beside it (`FILE` is the input name without `.csv`). Read-only.

```bash
cd aspace_csv_import
python3 aspace_csv_export.py --level item --mads-live
```

### airtable_pull and airtable_writeback

`airtable_pull.py VIEW` saves one grid view of the Airtable `<<< ASpace_import >>>` table as a CSV (read-only). After a real production create run, `airtable_writeback.py REPORT.json --run` records the results in Airtable: each created row's parent, its own ref ID (`ASpace Item RefID`) and `ASpace Item Record Created` = Yes. It lists every change row by row and writes only after you type `yes`. Tokens go in `creds.py` as `airtable_pat_read_only` (all reads) and `airtable_pat_write` (writes only).

```bash
cd aspace_csv_import
python3 airtable_pull.py VIEW_NAME
python3 airtable_writeback.py <reports>/import_report_<stamp>.json --run
```

### check_mads

Reports which catalog numbers are live in MADS (the public DAMS delivery). Public URLs only; ArchivesSpace is never contacted, so it takes no `--env`. It reads either a list of JPC_AV_xxxxx or a batch folder (the item folders directly inside it, renamed or not) - one or the other - and saves a report of Yes / No / check failed / invalid catalog number. A folder being there does not prove the item was delivered to or ingested by DAMS.

```bash
jpc-mads --directory /Volumes/AV_DRIVE/batch
```

`jpc-mads` (see [Commands](#commands)) is the everyday run; `jpc-mads --help` has the details.

All of these are documented in [aspace_csv_import/README.md](aspace_csv_import/README.md).

### aspace_rename_directories

Processes digitized video folders: reads each media file's runtime with `mediainfo` (`.mkv`, or optical-disc `.mp4` with `--mp4`), writes it to the record's Duration (a Defined List subnote of the Physical Characteristics and Technical Requirements note), fills a blank physical details on a single-extent record, and renames each folder with the record's ref ID. A real run first shows a PLAN of every change and writes only after you type `yes`; each folder is checked again just before it is written. A dry run shows each folder's outcome, leaves ArchivesSpace and folder names unchanged, and saves a log.

```bash
jpc-rename --directory /path/to/videos --dry-run
```

`jpc-rename` (see [Commands](#commands)) is the everyday run. The tool run directly also offers `--single`, `--rename-media`, `--no-update` and `--no-rename`. See [aspace_rename_directories/README.md](aspace_rename_directories/README.md) for full documentation.

## Workflow

Typical usage order:

1. **CSV Import** — Create archival objects from catalog metadata (validate, check parents and formats, dry run, real run)
2. **Directory Processing** (`jpc-rename`) — After digitization: a dry run, then the real run (PLAN, then `yes`) records each runtime and gives each folder its ref ID
3. **DAMS ingest** — Run by the operator, outside these tools; MADS publishes the item within about a day
4. **MADS check** (`jpc-mads`) — After ingest: `jpc-mads --directory BATCH` on the same batch folder (or `--file` a list) shows which items are live in MADS
5. **Export** — Any time: pull records to a CSV for auditing or round-trip edits

## Environments

Every ArchivesSpace tool supports sandbox and production (`check_mads.py` and `jpc-mads` talk only to the public MADS site and take no environment). `creds.py` holds an `environments` dict with one entry per instance. When running the tools directly: with one configured it is selected automatically, with several every run must pass `--env NAME` (there is no default). The `jpc-` commands differ: they use production unless `--env sandbox` is given, and show the environment before anything runs (see [Commands](#commands)). The environment is chosen once per run, before anything connects.
