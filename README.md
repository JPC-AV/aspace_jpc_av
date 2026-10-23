# JPC ArchivesSpace AV Tools

Tools for the Johnson Publishing Company Archive (JPCA) audiovisual collection. They move item data between Airtable and ArchivesSpace, link digitized folders to their ArchivesSpace records, and check which items the Smithsonian DAMS has published in MADS. Each workflow step has a short `jpc-` command.

**Start here: [JPC AV Tools Quick Start](QUICK_START.md)** - install the commands, set up private access, check the setup and rehearse in the sandbox.

## Commands

| Command | What it does | What it touches |
|---|---|---|
| `jpc-pull` | Saves one Airtable view as a CSV | Reads Airtable; saves a CSV in `data_import_export/__airtable_exports__/` |
| `jpc-check` (or `jpc-lookup`) | Says which JPC_AV_xxxxx are in ArchivesSpace, and whether a pull agrees | Reads ArchivesSpace |
| `jpc-fill` | Fills parent RefIDs: a ready CSV to import, a review CSV for a person | Reads ArchivesSpace; saves CSVs beside its input |
| `jpc-import` | Creates item records | **Writes ArchivesSpace**, after you type `yes` |
| `jpc-update` | Updates item records | **Writes ArchivesSpace**, after you type `yes` |
| `jpc-writeback` | Records a production create's results in Airtable | **Writes Airtable**, after you type `yes` |
| `jpc-rename` | Records each runtime and adds the record's ref ID to each folder name | **Writes ArchivesSpace and renames folders**, after you type `yes` |
| `jpc-mads` | Says which items are live in MADS | Reads the public MADS site |

- Every command that talks to ArchivesSpace needs `--env production` or `--env sandbox` on every run. There is no default.
- Airtable has one real base: there is no sandbox Airtable.
- `jpc-rename` renames the real folders even with `--env sandbox`; practise only on copies.
- `jpc` lists the commands and the workflows in order. `jpc-STEP --help` (for example `jpc-fill --help`) explains a step completely: what it checks, what it saves and what to do next.

## Guides

- **[Importing and Updating Data](data_import_export/IMPORTING_AND_UPDATING_DATA.md)** - pulling from Airtable, checking, filling parents, creating and updating ArchivesSpace records, exporting, recording results back in Airtable, and MADS checks.
- **[Appending RefIDs to Folders](refid_appending/APPENDING_REFIDS_TO_FOLDERS.md)** - after digitization: runtimes, physical details and folder names.
- **[JPC AV Processing Manual](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md)** - how the material is arranged and described, and why. The [documentation index](https://github.com/JPC-AV/documentation_jpc_av/blob/main/README.md) lists everything.

## What's in this repository

- `data_import_export/` - the data tools (pull, check, fill, import, update, export, write-back, MADS) and their [field mapping reference](data_import_export/docs/CSV_TO_ASPACE_MAPPING.md).
- `refid_appending/` - the folder tool behind `jpc-rename`.
- At the top: `jpc.py` (the `jpc-` commands), the shared ArchivesSpace client and display code, and `creds_template.py`, the template for your private `creds.py`.

Before the 2026 reorganization these folders were named `aspace_csv_import/` and `aspace_rename_directories/`; the script and command names did not change.

## Setup

Setup - installation, environments and private access - is in the [quick start](QUICK_START.md).

## Changes and license

Release notes are in [CHANGELOG.md](CHANGELOG.md). See [LICENSE](LICENSE) for the license.
