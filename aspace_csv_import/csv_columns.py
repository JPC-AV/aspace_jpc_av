"""The sheet contract: everything that makes a CSV valid for this collection.

Started as the single source of truth for column names (the source
spreadsheet occasionally renames its headers - edit the constants HERE and
nothing else; every tool imports them instead of carrying string literals,
including the required-column lists and -h help text). It now also holds
the shared rules every reader applies, so no two tools can disagree about a
sheet:

  - the catalog-number contract (JPC_AV_ + ASCII digits)
  - the AV date range (1940-2020) and two-digit-year resolution
  - header rules (duplicates), overflow-cell and strict-quoting expectations
  - file safety: reading a sheet once (CsvSnapshot), skipping provenance
    lines (open_csv), never overwriting an input (clobber_problem), and
    creating exactly the directory an output lands in (resolve_output_path)

Deliberately pure: standard library only, no network, no knowledge of
ArchivesSpace - the offline validator and the public-only MADS checker
depend on this module and nothing heavier. Talking to ArchivesSpace safely
is aspace_client.py's job.
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
# Columns aspace_csv_export.py adds beyond the import-shaped ones. Listed
# here so the validators recognize an exported CSV fed back in (no
# "unexpected column" noise) - the exporter asserts it stays in sync.
EXPORT_AUDIT_COLUMNS = [
    "ASpace Ref ID", "Warnings", "MADS live",
    "ASpace URI", "ASpace Staff Link", "MADS URL",
    "Created By", "Create Time", "Last Modified By", "Last Modified Time",
]

OPTIONAL_COLUMNS = [
    "EJS Season", "EJS Episode", "Content TRT", "ORIGINAL_MEDIA_TYPE",
] + EXPORT_AUDIT_COLUMNS


# The catalog-number contract, shared by every tool: JPC_AV_ followed by
# ASCII digits (the same rule check_mads.py and the rename tool apply).
# A near-miss like JPC_AV_12O01 (letter O) must never become a record.
import re as _re
CATALOG_NUMBER_RE = _re.compile(r"JPC_AV_[0-9]+")


# The JPC AV material spans 1940-2020: no item, edit, or broadcast date can
# fall outside that range. Every parsed date (full, partial, or two-digit
# year) is checked against it, so an impossible year is rejected as a typo
# instead of being written into the catalog.
AV_DATE_YEAR_RANGE = (1940, 2020)


def resolve_two_digit_year(year):
    """Map the year strptime('%y') produced (its own 1969-2068 window) onto
    the collection's range: 40-99 -> 1940-1999, 00-20 -> 2000-2020. Anything
    else (21-39) is impossible in either century and is returned out of
    range so the caller rejects it."""
    yy = year % 100
    return 1900 + yy if yy >= 40 else 2000 + yy


def begin_in_range(begin):
    """True if a stored/parsed begin value (YYYY, YYYY-MM or YYYY-MM-DD)
    starts with a year inside AV_DATE_YEAR_RANGE; False for anything else."""
    # ASCII digits only: str.isdigit() also accepts superscripts and other
    # Unicode digits that int() then rejects.
    return (isinstance(begin, str) and _re.fullmatch(r"[0-9]{4}", begin[:4]) is not None
            and year_in_range(int(begin[:4])))


def year_in_range(year):
    """True if a four-digit year falls inside AV_DATE_YEAR_RANGE."""
    return AV_DATE_YEAR_RANGE[0] <= year <= AV_DATE_YEAR_RANGE[1]


def valid_catalog_number(value):
    """True for a well-formed catalog number (JPC_AV_ + ASCII digits)."""
    return isinstance(value, str) and CATALOG_NUMBER_RE.fullmatch(value) is not None


def overflow_problem(row, row_num):
    """A message if the row has cells beyond the header (DictReader files
    them under the None key), else None. ANY extra cell - blank or not -
    means the row's fields have shifted (an unquoted or trailing comma);
    every reader must refuse such a row the same way the importer does."""
    overflow = row.get(None)
    if not overflow:
        return None
    shown = next((v for v in overflow if (v or '').strip()), '')
    return (f"Row {row_num}: {len(overflow)} extra cell(s) beyond the header "
            f"(first: {shown!r}) - an unquoted or trailing comma? fix the row")


def duplicate_headers(headers):
    """Header names that collide after normalization (case, whitespace).

    DictReader silently keeps only the LAST exact duplicate's value, and a
    variant like "CATALOG_NUMBER " looks identical to a human while being a
    separate stale column - either can hide a bad value behind a good one.
    Empty header cells (stray trailing commas) are ignored. Returns a sorted
    list of descriptions, empty when the headers are clean.
    """
    groups = {}
    for header in headers or []:
        key = (header or '').strip().casefold()
        if key:
            groups.setdefault(key, []).append(header)
    return sorted(', '.join(repr(n) for n in names)
                  for names in groups.values() if len(names) > 1)


def resolve_output_path(custom, default_dir, default_name):
    """The path a report will be written to, with its parent directory
    created. A custom -o path stands on its own: its parent is created and
    the tool's default reports directory is never touched or required."""
    import os
    path = custom or os.path.join(default_dir, default_name)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return path


def same_file(a, b):
    """True when two paths name the same file (resolved path or hard link)."""
    import os
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.realpath(a) == os.path.realpath(b)


def clobber_problem(input_path, out_path):
    """Why writing `out_path` (via its .tmp staging file) would destroy
    `input_path`, or None. Check BEFORE any network work: both the final
    path and the temporary path are compared, since the input could be
    either (e.g. an input literally named report.csv.tmp)."""
    import os
    for candidate in (out_path, out_path + ".tmp"):
        if os.path.exists(candidate) and same_file(candidate, input_path):
            return (f"refusing to write {candidate} - it is the input file "
                    f"{input_path} (choose another -o)")
    return None


class CsvSnapshot:
    """The complete text of a CSV, read from disk ONCE.

    The importer validates a sheet, then authenticates, then processes it;
    handing the same snapshot to both steps guarantees the rows written are
    exactly the rows validated - a file rewritten in between is never seen.
    Accepted anywhere a path is (open_csv)."""

    def __init__(self, path):
        self.path = path
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            self.text = f.read()

    def __str__(self):
        return str(self.path)  # a pathlib.Path is a valid input too


def open_csv(source):
    """Open a CSV for reading, skipping leading '#' provenance lines.

    `source` is a path or a CsvSnapshot. Export files carry the command
    that produced them as a '# ...' first line (so a sheet explains its own
    origin); every tool that reads CSVs opens them through here, making
    that line invisible to header parsing.
    """
    import io
    if isinstance(source, CsvSnapshot):
        f = io.StringIO(source.text, newline='')
    else:
        f = open(source, 'r', encoding='utf-8-sig', newline='')
    while True:
        pos = f.tell()
        line = f.readline()
        if not line.startswith('#'):
            f.seek(pos)
            return f
