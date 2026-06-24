"""Pure date-formatting helpers for DACS single-date expressions.

DACS "exact single dates" are displayed as `YYYY Month D` — e.g. 1982-08-01
becomes "1982 August 1" (no leading zero on the day), matching the JPC finding
aid precedent. ArchivesSpace keeps the ISO value in the structured begin/end
fields; only the human-readable `expression` string is reformatted.

This module has NO network or third-party dependencies so it can be unit-tested
in isolation, away from the production API.
"""

import re
from datetime import datetime

# Hard-coded so output never depends on the host's locale (strftime("%B") would).
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# A complete ISO single date, exactly YYYY-MM-DD. Year-only and year-month
# values deliberately do NOT match — per scope, those are left for manual review.
ISO_FULL = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def iso_to_dacs(value):
    """Convert a full ISO date 'YYYY-MM-DD' to a DACS expression 'YYYY Month D'.

    Returns None for anything that is not a real, complete ISO date (empty,
    year-only, year-month, or an invalid calendar date like 2020-02-30). None
    means "do not touch this one" so callers skip and report it rather than
    guessing.
    """
    if not value:
        return None
    m = ISO_FULL.match(value.strip())
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        datetime(year, month, day)  # reject impossible dates (e.g. 02-30)
    except ValueError:
        return None
    return f"{year} {MONTHS[month - 1]} {day}"


def is_iso_expression(value):
    """True if the string looks like a bare ISO date (YYYY-MM-DD) — i.e. an
    expression that script 2 should reformat. Real calendar validity is checked
    by iso_to_dacs() before any conversion."""
    return bool(value) and bool(ISO_FULL.match(value.strip()))


def is_blank(value):
    """True if a date expression is missing or only whitespace."""
    return value is None or str(value).strip() == ""


# Expression styles selectable at the command line.
STYLES = ("iso", "dacs")


def expression_for(begin, style):
    """Build the expression value to write for a given begin date and style.

    Both styles fill ONLY from a complete, valid YYYY-MM-DD begin:
    - 'iso'  : the full ISO begin verbatim (1982-08-01)
    - 'dacs' : the DACS single-date form (1982 August 1)

    Returns None for a blank, non-full (year-only / year-month), or invalid
    begin — the caller flags those for manual handling rather than writing a
    partial value like "1982-11".
    """
    dacs = iso_to_dacs(begin)  # non-None only for a complete, valid YYYY-MM-DD
    if dacs is None:
        return None
    if style == "iso":
        return str(begin).strip()
    if style == "dacs":
        return dacs
    raise ValueError(f"unknown style: {style!r}")


def date_identity(date):
    """Identifying fields of a date subrecord, used to re-match the same entry
    after a re-fetch (the embedded list index is not stable across edits)."""
    return (date.get("date_type"), date.get("label"),
            date.get("begin"), date.get("end"))


def expression_unchanged(current, expected):
    """True if a date's current expression still equals the planned 'old' value
    captured during the scan: blank matches blank; otherwise exact (trimmed).
    Used at apply time so a change is only written if the field is still in the
    exact state the report showed."""
    if is_blank(expected):
        return is_blank(current)
    return str(current or "").strip() == str(expected).strip()
