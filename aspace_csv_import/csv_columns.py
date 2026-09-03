"""Single source of truth for the CSV export's column names.

The source spreadsheet occasionally renames its headers. When that happens,
edit the constants HERE and nothing else — aspace_csv_import.py and
csv_utils.py import these instead of carrying their own string literals
(including required_columns lists and the -h help text, which are built from
this module).

Constants are the stable internal handle; the string is whatever the export
currently calls that column.
"""

# ── Column headers (edit these when the export renames a column) ────────────
CATALOG = "CATALOG_NUMBER"                    # Component unique ID / container indicator
PARENT_REFID = "ASpace Parent RefID"          # Parent archival object link
TITLE = "ASpace Title"                        # Item title (falls back to CATALOG)
CREATION_DATE = "Creation or Recording Date"  # dates[] label: creation
EDIT_DATE = "Edit Date"                       # dates[] label: Edited
BROADCAST_DATE = "Broadcast Date"             # dates[] label: broadcast
ORIGINAL_FORMAT = "Original Format"           # extent_type (must match ASpace dropdown)
DESCRIPTION = "ASpace Scope and Contents Note"  # scopecontent note
PHYSTECH = "ASpace PhysTech Note"             # phystech note

# All columns that map to ArchivesSpace fields — must be present in the header.
REQUIRED_COLUMNS = [
    CATALOG,
    PARENT_REFID,
    TITLE,
    CREATION_DATE,
    EDIT_DATE,
    BROADCAST_DATE,
    ORIGINAL_FORMAT,
    DESCRIPTION,
    PHYSTECH,
]

# Date columns and the ArchivesSpace date label each one maps to.
DATE_COLUMNS = [
    (CREATION_DATE, "creation"),
    (EDIT_DATE, "Edited"),
    (BROADCAST_DATE, "broadcast"),
]

# Columns whose values update mode can change on an existing record. CATALOG
# is the matching key (never changed); PARENT_REFID is only used when creating.
MUTABLE_COLUMNS = [
    TITLE,
    CREATION_DATE,
    EDIT_DATE,
    BROADCAST_DATE,
    ORIGINAL_FORMAT,
    DESCRIPTION,
    PHYSTECH,
]

# Columns we recognize in the export but don't require or import.
OPTIONAL_COLUMNS = [
    "EJS Season", "EJS Episode", "Content TRT", "ORIGINAL_MEDIA_TYPE",
]


def open_csv(path):
    """Open a CSV for reading, skipping leading '#' provenance lines.

    Export files carry the command that produced them as a '# ...' first
    line (so a sheet explains its own origin); every tool that reads CSVs
    opens them through here, making that line invisible to header parsing.
    """
    f = open(path, 'r', encoding='utf-8-sig', newline='')
    while True:
        pos = f.tell()
        line = f.readline()
        if not line.startswith('#'):
            f.seek(pos)
            return f
