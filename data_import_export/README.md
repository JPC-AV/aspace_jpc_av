# Data tools: Airtable and ArchivesSpace

This folder holds the tools that move and check item data between Airtable and ArchivesSpace: pulling a view from Airtable, checking which records exist, filling parent RefIDs, creating and updating ArchivesSpace records, exporting records, recording a production create's results back in Airtable, and checking which items are live in MADS.

**How to do the work: [Importing and Updating Data](IMPORTING_AND_UPDATING_DATA.md).** Setup is in the [quick start](../QUICK_START.md).

## Everyday commands

| Command | Systems |
|---|---|
| `jpc-pull` | Reads Airtable |
| `jpc-check` (or `jpc-lookup`), `jpc-fill` | Read ArchivesSpace |
| `jpc-import`, `jpc-update` | Write ArchivesSpace, after `yes` |
| `jpc-writeback` | Writes Airtable, after `yes` (production create reports only) |
| `jpc-mads` | Reads the public MADS site |

The ArchivesSpace commands need `--env production` or `--env sandbox` on every run; there is no default. Airtable has one real base. `jpc-STEP --help` explains each command completely.

## Scripts in this folder

- `airtable_pull.py` - runs `jpc-pull`; saves pulls in `__airtable_exports__/` here.
- `aspace_csv_export.py` - runs `jpc-check` and `jpc-fill`; run directly, it also exports records.
- `aspace_csv_import.py` - runs `jpc-import` and `jpc-update`.
- `airtable_writeback.py` - runs `jpc-writeback`.
- `check_mads.py` - runs `jpc-mads`.
- `check_extent_types.py` - lists the extent types ArchivesSpace accepts (troubleshooting).
- `sheet_rules.py` - the shared column names and checks; not run on its own.

Exact field rules are in [docs/CSV_TO_ASPACE_MAPPING.md](docs/CSV_TO_ASPACE_MAPPING.md), with a worked example in [docs/EXAMPLE_MAPPING.md](docs/EXAMPLE_MAPPING.md). [docs/POTENTIAL_MAPPINGS.md](docs/POTENTIAL_MAPPINGS.md) collects ideas for future mappings, not current behaviour. Release notes are in the repository's [CHANGELOG.md](../CHANGELOG.md).
