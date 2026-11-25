#!/usr/bin/env python3
"""ArchivesSpace CSV Export - the reverse of the importer.

Pulls every archival object in the configured AV resource and writes a CSV
shaped EXACTLY like the import sheet (same column headers, from
sheet_rules.py), plus audit columns from ArchivesSpace. That makes the round
trip real: export -> edit in a spreadsheet -> re-import with --update-only.

Round-trip rules this export honors:
  - Blank in ArchivesSpace = blank cell. Never a placeholder like "(empty)":
    blank means "leave alone" to the importer, and a placeholder would be
    WRITTEN INTO records on re-import.
  - Dates are exported as the ISO begin value exactly as stored (yyyy-mm-dd,
    or the partial yyyy-mm / yyyy many cataloged records carry) - formats
    the importer accepts back unchanged.
  - Notes are read with the same logic the importer's change detection uses
    (get_note_content), so what you see is what an update would compare to.
  - Records with structures the importer refuses to edit (multiple extents,
    multiple same-label dates, range dates) are flagged in the Warnings
    column so you know those rows aren't safely editable by CSV. Multiple
    same-type notes are NOT flagged - update-only edits the first
    text-bearing note and keeps the rest, so they round-trip.

Scope: ONLY the configured AV resource (resource_id in creds.py). The rest
of the repository is never enumerated.

Filling parents (--fill-parents FILE): the other direction. Given a sheet
with an ASpace File Type column, fill its empty ASpace Parent RefID cells
with the ref_id of that file record (Edited, Promo...) under the row's
episode - from EJS Episode, or from the title when that is blank (which is
why EJS Episode should be kept filled: the title then only cross-checks it,
and must agree) - plus Path and Parent Note. Duplicate normalized episode keys abort
the run without writing a CSV. Otherwise, exactly one file match fills a
cell; anything else stays blank with the reason. Raw rows are left for a person
(a multi-tape set has its own file record). Writes a new file; read-only
against ArchivesSpace like everything else here.

Selection: everything at a level (--level, default item; 'all' for the
whole hierarchy), one record's children (--parent), an explicit list of
catalog numbers (--list FILE, plain text one-per-line or any CSV with a
CATALOG_NUMBER column), or records named one by one (--record, repeatable:
a full JPC_AV_xxxxx or a ref ID, at any level).

Records in full (--record, T-166): the named records are saved as a record
package of three files side by side - the complete records exactly as the
API returned them (JSON, run details kept outside each unchanged record),
the usual export CSV, and a notes CSV with every note part and every
Defined List item on its own row (label and value apart, original order,
each row pointing into the JSON). Linked records stay references. Besides
the named records, only their ancestors and the records each search
returns are read, and none of those is saved. The JSON is not an import
payload and not a backup. No package file ever replaces another.

Hierarchy: rows come out in depth-first tree order - the order the staff
interface shows - and every row carries Level, Depth (0 for a top-level
series; an ephemera item under a tape is one deeper than the tape) and
Path (its ancestors' display strings, joined with " > "). Path survives
sorting and filtering where row order does not, and it says in words what
the ASpace Parent RefID column says as a ref_id. A --list or --record
export keeps the order given but carries the same three columns. Delete
them if unwanted; --update-only ignores them either way.

Read-only: this script makes no ArchivesSpace writes (its only output is
the CSV file, or with --record the record package).
"""

import argparse
import copy
import csv
import io
import json
import logging
import re
import os
import sys
from datetime import datetime
from pathlib import Path

import sheet_rules as col  # single source of truth for CSV header names
from sheet_rules import read_catalog_list  # noqa: E402,F401 - shared with check_mads

# Add parent directory to path for the shared client and creds.py import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aspace_client
from aspace_client import ASpaceClient

# Reuse the importer's console helpers and note-reading logic so the export
# shows values the same way an update run would compare them.
from console import (Colors, print_status, print_header, print_section,  # shared display
                     render_options, progress, close_progress, print_run_header,
                     print_result, print_saved, help_screen, styled_parser)
from aspace_csv_import import (get_note_content, staff_link_for, RUN_COMMAND, parse_date,
                               REF_ID_TEXT_RE)


# Batch size for id_set fetches - one API call per BATCH records instead of
# one call per record, which is the difference between minutes and an hour
# over the VPN. Kept well under ArchivesSpace's page-size ceiling (250).
BATCH = 50

# Archival-object levels ArchivesSpace defines, plus "all". A misspelled
# --level must be an error, not a successful empty export.
LEVELS = ["all", "class", "collection", "file", "fonds", "item", "otherlevel",
          "recordgrp", "series", "subfonds", "subgrp", "subseries"]

# Column order of the export file: identity and status first, then where
# the record sits in the tree (Level, Depth, Path - see hierarchy_for), then
# the import-shaped metadata, then links and audit trail. "MADS live"
# appears only when --mads-live was given. Order is cosmetic for round-trips
# - every reader in the toolset matches columns by header name, and
# --update-only ignores every column it does not manage.
EXPORT_COLUMNS = [
    col.CATALOG, "ASpace Ref ID", "Warnings", "MADS live",
    "Level", "Depth", "Path",
    col.PARENT_REFID, col.TITLE, col.CREATION_DATE, col.EDIT_DATE,
    col.BROADCAST_DATE, col.ORIGINAL_FORMAT, col.DESCRIPTION, col.PHYSTECH,
    "ASpace URI", "ASpace Staff Link", "MADS URL",
    "Created By", "Create Time", "Last Modified By", "Last Modified Time",
]
OPTIONAL_EXPORT_COLUMNS = {"MADS live"}
# Stay-in-sync guard (sheet_rules owns both lists): every required import
# column is exported, every extra column is a declared audit column, and no
# column appears twice - so a future edit to either side fails at import time.
assert len(EXPORT_COLUMNS) == len(set(EXPORT_COLUMNS)), "EXPORT_COLUMNS has a duplicate"
assert set(col.REQUIRED_COLUMNS) <= set(EXPORT_COLUMNS), \
    "EXPORT_COLUMNS is missing a required import column"
assert set(EXPORT_COLUMNS) - set(col.REQUIRED_COLUMNS) == set(col.EXPORT_AUDIT_COLUMNS), \
    "EXPORT_COLUMNS and sheet_rules.EXPORT_AUDIT_COLUMNS have drifted"

# Public MADS URL for a catalog number (DAMS ingest auto-publishes to MADS,
# so this is where the item WILL be public - the URL is derived, not checked;
# --mads-live actually checks). check_mads owns the URL scheme and the check.
from check_mads import MADS_URL_PREFIX, check_many, summarize, clobber_problem  # noqa: E402

# Import optional logs_dir (same convention as the importer)
import creds_loader  # noqa: E402
logs_dir = creds_loader.setting("logs_dir", "")
# A custom logs_dir gets a per-script subfolder (matching the importer/rename
# convention) so the tools sharing one creds setting don't interleave files.
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/aspace_import_reports")
OUTPUT_DIR = os.path.join(logs_dir, "export_reports") if logs_dir else DEFAULT_OUTPUT_DIR


def build_row(record, parent_refid, depth=0, path=""):
    """Map one archival object record to an import-shaped CSV row.

    `depth` and `path` come from hierarchy_for (0 and "" for a root record).
    Returns (row_dict, warnings) where warnings lists the structures the
    importer would refuse to edit on this record, plus metadata gaps worth
    fixing: no component ID (the record is unreachable by anything keyed on
    catalog number), no title, no dates. A non-item level is not a warning:
    the Level column says what the record is.
    """
    warnings = []
    row = {
        col.CATALOG: record.get("component_id") or "",
        col.PARENT_REFID: parent_refid or "",
        col.TITLE: record.get("title") or "",
    }
    # Gap flags by cataloging rule: only item-level records carry component
    # IDs; every archival object needs a title and a date EXCEPT file-level
    # nodes, which are generic organizing buckets (Edited/Raw/Promo), not
    # intellectual archival levels - they need neither dates nor IDs.
    level = record.get("level")
    if level == "item" and not row[col.CATALOG]:
        warnings.append("no component ID in ASpace")
    elif row[col.CATALOG] and not col.valid_catalog_number(row[col.CATALOG]):
        warnings.append("component ID is not JPC_AV_ + digits - the importer and "
                        "MADS check will refuse it")
    if not row[col.TITLE]:
        warnings.append("no Title in ASpace")

    dates = record.get("dates") or []
    if level != "file" and not dates:
        warnings.append("no Date in ASpace")
    for column, label in col.DATE_COLUMNS:
        matching = [d for d in dates if d.get("label") == label]
        row[column] = (matching[0].get("begin") or "") if matching else ""
        if row[column] and parse_date(row[column], strict_range=False) is None:
            # the importer's own parser (range check aside) is the exact rule
            # the sheet meets on the way back: a begin it cannot read - wrong
            # shape, month 13, Feb 29 in a common year - means the sheet will
            # be refused until the record is fixed in ArchivesSpace
            warnings.append(f"'{label}' date {row[column]!r} is not a valid ISO date - the "
                            f"importer will refuse this sheet; fix the record in ArchivesSpace")
        elif row[column] and not col.begin_in_range(row[column]):
            lo, hi = col.AV_DATE_YEAR_RANGE
            warnings.append(f"'{label}' date {row[column]} is outside {lo}-{hi} - check it "
                            f"(--update-only keeps it only if unchanged)")
        if len(matching) > 1:
            warnings.append(f"{len(matching)} '{label}' dates - --update-only will refuse to change them")
        elif matching and (matching[0].get("end")
                           or matching[0].get("date_type") != "single"):
            # a range (or a non-single/untyped date): a one-value CSV cell
            # cannot express it, so --update-only will refuse to change it
            # the stored date_type is named only from the standard list,
            # never quoted (it comes from the server's reply)
            kind = col.date_type_text(matching[0].get("date_type"))
            shape = ("has an end date" if matching[0].get("end")
                     else "has an unrecognized date_type" if kind == "unrecognized"
                     else f"has date_type {kind}")
            warnings.append(f"'{label}' date {shape} - --update-only will refuse to change it")

    extents = record.get("extents") or []
    row[col.ORIGINAL_FORMAT] = (extents[0].get("extent_type") or "") if extents else ""
    if len(extents) > 1:
        warnings.append(f"{len(extents)} extents - --update-only will refuse to change Original Format")

    notes = record.get("notes") or []
    # (Multiple same-type notes are NOT flagged: --update-only edits the
    # first text-bearing note and preserves the rest, so they round-trip.)
    row[col.DESCRIPTION] = get_note_content(notes, "scopecontent") or ""
    row[col.PHYSTECH] = get_note_content(notes, "phystech") or ""

    row["ASpace Ref ID"] = record.get("ref_id") or ""
    row["ASpace URI"] = record.get("uri") or ""
    row["ASpace Staff Link"] = staff_link_for(record.get("uri"))
    row["MADS URL"] = (MADS_URL_PREFIX + row[col.CATALOG]) if row[col.CATALOG] else ""
    row["Created By"] = record.get("created_by") or ""
    row["Create Time"] = record.get("create_time") or ""
    row["Last Modified By"] = record.get("last_modified_by") or ""
    row["Last Modified Time"] = record.get("user_mtime") or ""
    row["Warnings"] = "; ".join(warnings)
    row["Level"] = level or ""
    row["Depth"] = depth
    row["Path"] = path
    return row, warnings


def display_of(record):
    """What the ArchivesSpace tree shows for a record: its display string
    (title plus dates), falling back to title, component ID, then uri."""
    return (record.get("display_string") or record.get("title")
            or record.get("component_id") or record.get("uri") or "")


def fetch_linked(client, uri, cache):
    """A linked record (a parent or further ancestor), fetched once per
    distinct uri. Returns (record, None), or (None, reason) when it cannot
    be used: failed, malformed, identifying as some other record, or outside
    the configured resource - an ancestor from another resource must never
    lend its title to a Path or its ref_id to a parent column. The reason
    says whether a retry could help (a failed read) or the record itself
    needs fixing (a parent in another resource); the two must not be
    reported alike. Callers treat None as a failure, never as "no parent":
    a blank in the sheet would be indistinguishable from a root record."""
    if uri not in cache:
        linked = client.get(uri)
        if (not isinstance(linked, dict) or linked.get("uri") != uri
                or record_shape_problem(linked)):
            logging.error(f"Could not read linked record {uri}")
            cache[uri] = (None, "could not be read - retry later")
        elif linked["resource"]["ref"] != aspace_client.RESOURCE_URI:
            logging.error(f"Linked record {uri} belongs to another resource")
            cache[uri] = (None, "belongs to another resource - fix the record in ArchivesSpace")
        else:
            cache[uri] = (linked, None)
    return cache[uri]


def ancestor_chain(record, resolve):
    """The record's ancestors, root first, each resolved through `resolve`
    (uri -> (record, None) or (None, reason)). Returns (chain, None), or
    (None, reason) if any ancestor could not be resolved or the parent
    links form a cycle - an unknown ancestry must fail the export, never
    print as a shallower depth or a shorter path."""
    chain = []
    seen = {record.get("uri")}
    parent = record.get("parent")
    while parent:
        uri = parent["ref"]
        if uri in seen:
            logging.error(f"Parent links of {record.get('uri')} form a cycle at {uri}")
            return None, f"parent links form a cycle at {uri} - fix the record in ArchivesSpace"
        seen.add(uri)
        ancestor, reason = resolve(uri)
        if ancestor is None:
            return None, f"linked parent {uri} {reason}"
        chain.append(ancestor)
        parent = ancestor.get("parent")
    chain.reverse()
    return chain, None


def hierarchy_for(record, chain):
    """(depth, path, sort_key, approximate) placing the record in the tree.

    Depth counts ancestors (0 for a top-level series; an ephemera item under
    a tape is one deeper than the tape). Path is the ancestors' display
    strings joined with " > " - the row's own title is already a column, and
    the path survives sorting and filtering where row order does not. The
    sort key reproduces the staff tree's order: ArchivesSpace keeps an
    integer `position` among siblings (gaps are normal after moves, so only
    the order of the numbers means anything); a parent's key is a prefix of
    its children's, so sorting rows by it yields depth-first tree order.
    `approximate` is True when the record or any ancestor has no position,
    so part of that order came from uri numbers instead.
    """
    def own_key(r):
        pos = r.get("position")
        oid = int(str(r.get("uri", "")).rsplit("/", 1)[-1] or 0)
        return ((0, pos) if isinstance(pos, int) and not isinstance(pos, bool)
                else (1, 0), oid)
    path = " > ".join(display_of(a) for a in chain)
    members = [*chain, record]
    sort_key = tuple(own_key(r) for r in members)
    # ArchivesSpace assigns a position on every create, so a blank is rare -
    # but the schema allows it, and a blank ANYWHERE in the chain makes the
    # order of this row (and its siblings, and their subtrees) fall back to
    # uri order. The caller discloses that on sorted exports.
    approximate = any(not isinstance(r.get("position"), int) or isinstance(r.get("position"), bool)
                      for r in members)
    return len(chain), path, sort_key, approximate


def list_resource_records(client):
    """Enumerate EVERY archival object in the AV resource via the search index.

    The tree's /ordered_records endpoint was abandoned here: it silently
    omits unpublished nodes AND their entire subtrees, so records verifiably
    in the resource were missing from its listing - an incomplete export
    masquerading as complete. The search index sees records regardless of
    publish status. (It lags writes by up to about a minute, so a record
    created moments ago may be missing - same caveat as the importer's
    duplicate checks.)

    Level filtering happens after the fetch - the index enumerates uris only.
    Returns a list of numeric ids, or None on failure (callers abort; a
    partial enumeration must never masquerade as the whole resource).
    """
    prefix = f"/repositories/{aspace_client.REPO_ID}/archival_objects/"
    uris = client.search_record_uris(
        {"q": f'resource:"{aspace_client.RESOURCE_URI}"',
         "type[]": "archival_object"},
        uri_prefix=prefix)
    if uris is None:
        return None
    return [int(uri.rsplit("/", 1)[-1]) for uri in uris]


def fetch_records(client, ids):
    """Fetch full records in id_set batches. Returns the records, or None if
    any batch fails - a partial export must never pose as a complete one."""
    try:
        return _fetch_batches(client, ids)
    finally:
        close_progress()


def _fetch_batches(client, ids):
    records = []
    prefix = f"/repositories/{aspace_client.REPO_ID}/archival_objects/"
    for start in range(0, len(ids), BATCH):
        chunk = ids[start:start + BATCH]
        id_set = ",".join(str(i) for i in chunk)
        result = client.get(f"/repositories/{aspace_client.REPO_ID}"
                            f"/archival_objects?id_set={id_set}")
        # Depending on version the batch endpoint returns a bare list or a
        # dict with 'results'.
        if isinstance(result, dict):
            result = result.get("results")
        if not isinstance(result, list):
            return None
        # The batch must return EXACTLY the requested records, once each,
        # each identifying as its own uri - anything else (a record missing,
        # substituted, duplicated, or malformed) fails the export rather
        # than shipping a file that only looks complete.
        wanted = {f"{prefix}{i}" for i in chunk}
        got = [r.get("uri") if isinstance(r, dict) else None for r in result]
        if (not all(isinstance(u, str) for u in got)
                or len(got) != len(wanted) or set(got) != wanted
                or len(set(got)) != len(got)):
            # Name the failed check, never the returned uris: a reply can
            # carry anything in them. The requested uris are our own.
            if not all(isinstance(u, str) for u in got):
                reason = "a returned record has no usable uri"
            elif len(got) != len(wanted):
                reason = f"{len(got)} records returned for {len(wanted)} requested"
            elif len(set(got)) != len(got):
                reason = "a record was returned more than once"
            else:
                reason = "a returned record was not one of those requested"
            logging.error(f"id_set batch mismatch: asked for {sorted(wanted)}; {reason} "
                          f"(returned uris not shown)")
            return None
        records.extend(result)
        progress("Fetched records", min(start + BATCH, len(ids)), len(ids))
    return records


def parent_refid(chain):
    """ref_id of the immediate parent (last of the ancestor chain), "" for a
    root record, None when the parent has no usable ref_id - a real linked
    parent always has one, so anything else is a malformed read, never
    "no parent"."""
    if not chain:
        return ""
    ref_id = chain[-1].get("ref_id")
    if not isinstance(ref_id, str) or not ref_id:
        logging.error(f"Linked parent {chain[-1].get('uri')} has no usable ref_id")
        return None
    return ref_id


def place_record(record, resolve):
    """Everything a row needs about where a record sits: (parent_refid,
    depth, path, sort_key, approximate), or (None, reason) if its ancestry
    could not be established. `approximate` is True when a position is
    missing somewhere in the chain (the sort falls back to uri order)."""
    chain, reason = ancestor_chain(record, resolve)
    if chain is None:
        return None, reason
    refid = parent_refid(chain)
    if refid is None:
        return None, f"linked parent {chain[-1].get('uri')} has no usable ref_id - retry later"
    depth, path, sort_key, approximate = hierarchy_for(record, chain)
    return (refid, depth, path, sort_key, approximate), None


APPROXIMATE_ORDER_NOTE = "no position in ASpace (this record or an ancestor) - tree order here is approximate"


def _add_warning(row, text):
    row["Warnings"] = "; ".join(w for w in (row.get("Warnings", ""), text) if w)


def _row_for(client, record, linked_cache):
    """The export row for one looked-up record: (row, None), or (None,
    reason) when the record's shape is unusable or its place in the tree
    cannot be established. The reason reads after "<value>: ". Shared by
    --list and --record."""
    problem = record_shape_problem(record)
    if problem:
        return None, f"malformed record ({problem}) - retry later"
    placed, reason = place_record(
        record, lambda uri: fetch_linked(client, uri, linked_cache))
    if placed is None:
        return None, f"its {reason}"
    # the order given is kept - no tree sort, so no approximate-order note
    refid, depth, path, _, _ = placed
    row, _ = build_row(record, refid, depth, path)
    return row, None


def export_by_list(client, catalog_numbers):
    """Export exactly the listed catalog numbers, in list order.

    Each number goes through the importer's verified lookup, so a number
    that is missing, ambiguous, or unsearchable is reported by name instead
    of silently absent from the output. Returns (rows, problems).
    """
    rows = []
    problems = []
    linked_cache = {}
    try:
        for i, number in enumerate(catalog_numbers, 1):
            if not col.valid_catalog_number(number):
                problems.append(f"{number}: malformed catalog number (must be JPC_AV_ + digits) "
                                f"- not looked up")
                continue
            lookup = client.find_archival_object(number)
            if lookup.status == "found":
                row, reason = _row_for(client, lookup.record, linked_cache)
                if row is None:
                    problems.append(f"{number}: {reason}")
                    continue
                rows.append(row)
            elif lookup.status == "none":
                problems.append(f"{number}: not found in the resource")
            elif lookup.status == "multiple":
                problems.append(f"{number}: {lookup.count} records share this number")
            else:
                problems.append(f"{number}: lookup failed - retry later")
            progress("Looked up", i, len(catalog_numbers))
    finally:
        close_progress()
    return rows, problems


def fetch_resource(client):
    """Every archival object in the resource, fetched and shape-checked.
    Returns (records, None) or (None, reason) - a partial or malformed fetch
    must never pose as the whole resource. Records the search index listed
    but that turn out to live elsewhere are still in the list; callers
    filter on resource ref (and count them as anomalies)."""
    ids = list_resource_records(client)
    if ids is None:
        return None, "could not enumerate the resource's records"
    print_status("info", f"Reading the whole AV resource ({len(ids)} records)...")
    records = fetch_records(client, ids)
    if records is None:
        return None, "a batch fetch failed - no partial export was written"
    # Shape first: a record missing the fields the filters read is malformed
    # and fails the run - it must not be silently dropped (no level), misread
    # as a stale hit (no resource), or crash (parent).
    for record in records:
        problem = record_shape_problem(record)
        if problem:
            return None, (f"malformed record {record.get('uri')!r} ({problem}) "
                          f"- no partial export was written")
    return records, None


# ---------------------------------------------------------------------------
# --fill-parents: fill ASpace Parent RefID from EJS Episode + ASpace File Type
# ---------------------------------------------------------------------------
_EPISODE_TITLE_RE = re.compile(r"Episode\s+(.+)", re.IGNORECASE)
# The title pattern is "<Series>, Episode <n>[, <Qualifier>]": the episode
# is one whole comma-separated part of the title.
_EPISODE_WORD_RE = re.compile(r"\bepisode\b", re.IGNORECASE)
_EPISODE_PART_RE = re.compile(r"episode\s+([0-9]+|[a-z]+)", re.IGNORECASE)
# Any later comma part holding an episode-shaped number - a standalone two-
# or four-digit number (Celebrity Showcase / EJS) - means the title may name
# more than one episode ("4007", "and 4007", "or 4007", "plus 4007",
# "4007/4008", "thru 4008"), whatever word sits in front of it. Qualifiers
# with single digits ("Tape 1 of 3") read normally; one with such a number
# ("30-second promo") is refused - failing toward review, never a guess.
_EPISODE_SHAPED_NUMBER_RE = re.compile(r"(?<![0-9])(?:[0-9]{2}|[0-9]{4})(?![0-9])")
UNCLEAR = object()  # the title mentions an episode, but not one it is safe to read


def episode_from_title(title):
    """(key, text) for the episode a title names.

    key is the episode key (4006; "pilot"), None when the title names no
    episode, or UNCLEAR when it mentions one that cannot be read safely:
    two mentions ("... recut from Episode 4007"), or an episode part that is
    not a single number or word ("Episode 4006/4007", "Episode 4006-4007",
    "Episode 4006.5"). Those need a person, never a best guess. text is the
    episode part as written, for notes. EJS episodes are four digits and
    Celebrity Showcase two, so a number alone decides the program (the
    index refuses to run if two episodes share a key)."""
    title = title or ""
    mentions = len(_EPISODE_WORD_RE.findall(title))
    if mentions == 0:
        return None, ""
    parts = [p.strip() for p in title.split(",")]
    episode_parts = [p for p in parts if _EPISODE_WORD_RE.match(p)]
    if mentions == 1 and len(episode_parts) == 1:
        match = _EPISODE_PART_RE.fullmatch(episode_parts[0])
        # a later part naming another episode-shaped number means the
        # title may name more than one episode
        continued = any(_EPISODE_SHAPED_NUMBER_RE.search(p)
                        for p in parts[parts.index(episode_parts[0]) + 1:])
        if match and not continued:
            return episode_key(match.group(1)), episode_parts[0]
    shown = episode_parts[0] if episode_parts else title
    return UNCLEAR, shown


def episode_cell_rule(cell):
    """(value, note) for an EJS Episode cell, before any lookup.

    Airtable's EJS Episode is a single select whose options include TBD and
    several-episode lists ("14, 15"). Neither names one episode, so the row
    is left for a person with a note - a deliberate rule, not the result of
    a failed lookup, and never overridden by the title. One pair of wrapping
    quotes is dropped first: Airtable's Download CSV writes a comma-holding
    option as '"14, 15"'. note is None for an ordinary value."""
    value = (cell or "").strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1].strip()
    if value.casefold() == "tbd":
        return value, f"{col.EJS_EPISODE} is TBD - fill it once the episode is known"
    if "," in value:
        return value, (f"{col.EJS_EPISODE} {value!r} names more than one episode - "
                       f"choose the parent by hand")
    return value, None


RAW_NOTE = ("Raw: fill by hand - a multi-tape set goes under its own file "
            "record beneath Raw")


def episode_key(value):
    """Comparable key for an episode, from a sheet cell ("4006", "Episode
    4006", "9", "4006.0" out of a spreadsheet) or an ArchivesSpace subseries
    title ("Episode 09", "Episode pilot"). Numbers compare as numbers, so a
    sheet's 9 finds "Episode 09"; anything else compares case-insensitively.
    Returns None for a blank."""
    value = (value or "").strip()
    match = _EPISODE_TITLE_RE.fullmatch(value)
    if match:
        value = match.group(1).strip()
    if not value:
        return None
    if re.fullmatch(r"[0-9]+(\.0+)?", value):
        return int(value.split(".")[0])
    return value.casefold()


def index_file_records(client, records):
    """Map (episode key, file title) -> [(file record, path an item under it
    would carry)], plus the set of episode keys that exist at all (so "no
    such episode" and "episode has no Promo record" are told apart).
    Duplicate normalized episode keys in the resource fail the whole run.
    Returns (index, episodes, None) or (None, None, reason)."""
    in_resource = [r for r in records if r["resource"]["ref"] == aspace_client.RESOURCE_URI]
    by_uri = {r["uri"]: r for r in in_resource}
    index, episodes, episode_records = {}, set(), {}

    def register_episode(record):
        if record["level"] != "subseries":
            return None
        title = (record.get("title") or "").strip()
        if not _EPISODE_TITLE_RE.fullmatch(title):
            return None
        key = episode_key(title)
        previous = episode_records.get(key)
        if previous is not None and previous["uri"] != record["uri"]:
            return (f"duplicate episode key {key!r}: {previous.get('title')!r} "
                    f"({previous['uri']}) and {record.get('title')!r} "
                    f"({record['uri']}) - episode keys must be unique; "
                    "correct the hierarchy in ArchivesSpace and rerun. No CSV was written")
        episode_records[key] = record
        episodes.add(key)
        return None

    for record in in_resource:
        reason = register_episode(record)
        if reason:
            return None, None, reason

    linked_cache = {}
    def resolve(uri):
        if uri in by_uri:
            return by_uri[uri], None
        record, reason = fetch_linked(client, uri, linked_cache)
        if record is not None:
            reason = register_episode(record)
            if reason:
                return None, reason
        return record, reason

    for record in in_resource:
        if record["level"] != "file" or not record.get("parent"):
            continue
        parent, reason = resolve(record["parent"]["ref"])
        if parent is None:
            return None, None, f"linked parent {record['parent']['ref']} {reason}"
        title = (parent.get("title") or "").strip()
        if parent.get("level") != "subseries" or not _EPISODE_TITLE_RE.fullmatch(title):
            continue  # a file under a season or series (Segment Reels...) - not episode-keyed
        placed, reason = place_record(record, resolve)
        if placed is None:
            return None, None, f"{reason} (record {record.get('uri')})"
        _, _, path, _, _ = placed
        item_path = " > ".join(p for p in (path, display_of(record)) if p)
        key = (episode_key(title), (record.get("title") or "").strip().casefold())
        index.setdefault(key, []).append((record, item_path))
    return index, episodes, None


def read_fill_sheet(path):
    """The sheet to fill: (headers, rows, None) or (None, None, problem).
    Same strictness as every other reader - one header each, no overflow
    cells, UTF-8 - and the four columns the lookup needs must be present."""
    # EJS Episode is optional: a blank (or absent) column falls back to the
    # episode named in the title.
    needed = [col.CATALOG, col.PARENT_REFID, col.FILE_TYPE]
    try:
        with col.open_csv(path) as f:
            reader = csv.DictReader(f, strict=True)
            headers = reader.fieldnames or []
            duplicates = col.duplicate_headers(headers)
            if duplicates:
                return None, None, (f"{path}: duplicate column header(s): "
                                    f"{'; '.join(duplicates)} - remove the stale duplicate(s)")
            # The two columns this mode adds are matched by exact spelling
            # (a sheet that already carries "Path" is filled in place). A
            # near-miss ("path", "Parent Note ") would pass the duplicate
            # check yet collide with the added column in the OUTPUT - a sheet
            # the importer's validator then rejects. Refuse it up front.
            # The same goes for every column the lookup READS: a near-miss
            # like "EJS Episode " would otherwise be treated as an absent
            # column - its values silently ignored, the title winning.
            for known in (col.CATALOG, col.TITLE, col.PARENT_REFID, col.EJS_EPISODE,
                          col.FILE_TYPE, col.PARENT_NOTE, "Path", col.HOLD, col.ISSUE):
                variants = [h for h in headers
                            if h != known and (h or "").strip().casefold() == known.casefold()]
                if variants:
                    return None, None, (f"{path}: column {variants[0]!r} is not spelled "
                                        f"exactly {known!r} - rename it (or remove it); "
                                        f"otherwise its contents would be ignored or "
                                        f"collide in the filled file")
            missing = [c for c in needed if c not in headers]
            if missing:
                return None, None, f"{path}: missing column(s): {', '.join(missing)}"
            # This mode REWRITES the sheet, so every column must survive the
            # round trip by name. Two or more unnamed columns all key as ""
            # and DictReader keeps only the last one's cells - the others'
            # contents would vanish from the output while the run reports
            # success. (A single unnamed column round-trips by position.)
            unnamed = [i for i, h in enumerate(headers, 1) if not (h or "").strip()]
            if len(unnamed) > 1:
                return None, None, (f"{path}: {len(unnamed)} columns have no header "
                                    f"(columns {', '.join(map(str, unnamed))}) - their "
                                    f"contents could not be carried into the filled file; "
                                    f"name or remove them")
            rows = []
            for row_num, row in enumerate(reader, 1):
                overflow = col.overflow_problem(row, row_num)
                if overflow:
                    return None, None, f"{path}: {overflow}"
                rows.append(row)
    except UnicodeDecodeError as e:
        return None, None, (f"could not read {path}: not UTF-8 text (byte {e.start}: "
                            f"{e.reason}) - save the file as UTF-8 CSV")
    except csv.Error as e:
        return None, None, f"could not parse {path} as CSV: {e}"
    except OSError as e:
        return None, None, f"could not read {path}: {e}"
    if not rows:
        return None, None, f"no data rows in {path}"
    return list(headers), rows, None


def fill_parents(rows, index, episodes):
    """Fill each row's parent ref_id, Path and Parent Note in place.

    The episode comes from EJS Episode, or from the title when that cell is
    blank ("..., Episode 4006, ..."). An EJS Episode of TBD or a list
    ("14, 15") is left for a person outright - no title fallback, no lookup
    (episode_cell_rule). When both are present they must agree,
    or the row is left blank - a typo in either must not pick a parent.
    Exactly one matching file record fills the cell; anything else leaves it
    blank with the reason in Parent Note - never a guess. A value already in
    the sheet is never replaced (a disagreement is noted). Raw rows are left
    for a person: whether a tape belongs to a multi-tape set, which has its
    own file record, cannot be told from the sheet.
    Returns counts: filled, kept, and unresolved [(row_num, catalog, note)].
    """
    filled = kept = 0
    unresolved = []
    for row_num, row in enumerate(rows, 1):
        held = col.hold_problem(row)
        if held:
            # A held item is never made ready, whatever its parent: it waits
            # in the review file until the hold is lifted in Airtable.
            row["Path"], row[col.PARENT_NOTE] = "", held
            unresolved.append((row_num, row.get(col.CATALOG, ""), held))
            continue
        existing = (row.get(col.PARENT_REFID) or "").strip()
        file_type = (row.get(col.FILE_TYPE) or "").strip()
        episode_cell, cell_note = episode_cell_rule(row.get(col.EJS_EPISODE))
        if cell_note:
            key, title_key, title_text, from_title = None, None, "", False
        else:
            key = episode_key(episode_cell)
            title_key, title_text = episode_from_title(row.get(col.TITLE))
            from_title = key is None and title_key not in (None, UNCLEAR)
            if from_title:
                key, episode_cell = title_key, title_text.split(None, 1)[1]
        found, path, note = "", "", ""
        conflict = False  # needs review even when the sheet already has a parent
        if cell_note:
            note = cell_note
        elif key is not None and title_key not in (None, UNCLEAR) and key != title_key:
            # compared whatever the kind (4006 vs "pilot" disagrees too), and
            # before the Raw rule: a Raw row can contradict itself as well
            note = (f"{col.EJS_EPISODE} {episode_cell} and the title's {title_text!r} "
                    f"disagree - correct one of them")
            conflict = True
        elif file_type.casefold() == "raw":
            note = RAW_NOTE
        elif key is None and title_key is UNCLEAR:
            note = (f"the title's episode ({title_text!r}) is not a single episode - "
                    f"fill {col.EJS_EPISODE}")
        elif key is None or not file_type:
            missing = []
            if key is None:
                missing.append(f"{col.EJS_EPISODE} (and no episode in the title)")
            if not file_type:
                missing.append(col.FILE_TYPE)
            note = "no " + " or ".join(missing)
        else:
            hits = index.get((key, file_type.casefold()), [])
            if len(hits) == 1:
                found, path = hits[0][0].get("ref_id") or "", hits[0][1]
                if not found:
                    note = "the matching file record has no ref_id - retry later"
                elif from_title:
                    note = "episode taken from the title"
            elif len(hits) > 1:
                note = (f"{len(hits)} {file_type} records match Episode {episode_cell} "
                        f"- fill by hand")
            elif key in episodes:
                note = f"Episode {episode_cell} has no {file_type} record in ArchivesSpace"
            else:
                note = f"Episode {episode_cell} not found in ArchivesSpace"
        if existing:
            kept += 1
            if found and found != existing:
                note = f"sheet value kept; the lookup found a different parent ({found})"
                path = ""
                unresolved.append((row_num, row.get(col.CATALOG, ""), note))
            elif conflict:
                # the supplied parent stands, but the sheet contradicts itself
                note = f"sheet value kept; {note}"
                unresolved.append((row_num, row.get(col.CATALOG, ""), note))
            else:
                note = ""  # nothing to add to a row a person already filled
        elif found:
            row[col.PARENT_REFID] = found
            filled += 1
        else:
            unresolved.append((row_num, row.get(col.CATALOG, ""), note))
        row["Path"] = path
        row[col.PARENT_NOTE] = note
    return filled, kept, unresolved


FIX_IN = "Fix in"  # review file only: where a row's problem gets fixed


def write_filled_csv(headers, rows, path, provenance=None, extra_columns=()):
    """The input sheet, column order kept, with Path and Parent Note added
    (after the parent column) when the sheet did not already carry them,
    plus any extra_columns after Parent Note. Atomic, provenance first
    line - same as every export."""
    fieldnames = list(headers)
    at = fieldnames.index(col.PARENT_REFID) + 1
    for extra in (col.PARENT_NOTE, "Path"):
        if extra not in fieldnames:
            fieldnames.insert(at, extra)
    at = fieldnames.index(col.PARENT_NOTE) + 1
    for extra in reversed(extra_columns):
        if extra not in fieldnames:
            fieldnames.insert(at, extra)
    def write(f):
        if provenance:
            f.write(f"# {provenance}\n")
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    col.save_via_temp(path, write, newline="")


def export_records(client, level, parent_filter_refid=None):
    """Pull, filter, and map every matching record.

    Returns (rows, anomalies) or (None, reason) on failure. anomalies counts
    fetched records that don't belong to the configured resource - the guard
    against stale search-index hits (the index, not the tree, is the
    enumeration source; an index claim is verified against the record).
    """
    records, reason = fetch_resource(client)
    if records is None:
        return None, reason

    # --parent: resolve the target once, then keep only its direct children.
    parent_filter_uri = None
    if parent_filter_refid:
        lookup = client.find_parent(parent_filter_refid)
        if lookup.status != "found":
            return None, (f"--parent {parent_filter_refid}: "
                          f"{lookup.problem or 'no such record in the resource'}")
        parent_filter_uri = lookup.uri

    rows = []
    anomalies = 0
    # Shape first: a record missing the fields the filters read is malformed
    # and fails the export - it must not be silently dropped (no level),
    # misread as a stale hit (no resource), or crash (parent). In the same
    # pass, count component IDs across EVERY well-formed in-resource record
    # at every level - the importer's duplicate check spans the whole
    # resource, so a selected row must be flagged even when the other holder
    # is a series or lives under another parent.
    id_counts = {}
    for record in records:
        if record["resource"]["ref"] == aspace_client.RESOURCE_URI and record.get("component_id"):
            id_counts[record["component_id"]] = id_counts.get(record["component_id"], 0) + 1
    # Ancestors come from this same fetch (the whole resource is in hand);
    # one the index missed (it lags writes) is fetched on demand.
    by_uri = {r["uri"]: r for r in records
              if r["resource"]["ref"] == aspace_client.RESOURCE_URI}
    linked_cache = {}
    def resolve(uri):
        if uri in by_uri:
            return by_uri[uri], None
        return fetch_linked(client, uri, linked_cache)
    keyed = []
    for record in records:
        if record["resource"]["ref"] != aspace_client.RESOURCE_URI:
            anomalies += 1  # stale index hit: a well-formed record no longer in the resource
            continue
        if level != "all" and record["level"] != level:
            continue
        parent_uri = record["parent"]["ref"] if record.get("parent") else ""
        if parent_filter_uri and parent_uri != parent_filter_uri:
            continue
        placed, reason = place_record(record, resolve)
        if placed is None:
            return None, (f"{reason} (record "
                          f"{record.get('component_id') or record.get('uri')}) "
                          f"- no partial export was written")
        refid, depth, path, sort_key, approximate = placed
        row, _ = build_row(record, refid, depth, path)
        if approximate:
            _add_warning(row, APPROXIMATE_ORDER_NOTE)
        keyed.append((sort_key, row))
    # Depth-first tree order, exactly as the staff interface lists them.
    keyed.sort(key=lambda kr: kr[0])
    rows = [row for _, row in keyed]
    flag_duplicate_catalog_numbers(rows, id_counts)
    return rows, anomalies


def _repo_pinned(collection):
    """Canonical uri pattern for a collection inside OUR repository - the
    scope check is only complete if the repository is pinned too."""
    return re.compile(rf"/repositories/{re.escape(str(aspace_client.REPO_ID))}/{collection}/[0-9]+")


def record_shape_problem(record):
    """Why a fetched archival object cannot be safely filtered/exported, or
    None if its shape is sound: a non-empty level, a canonical resource
    uri, and - when present - a parent that is an object with a canonical
    archival-object uri. Empty strings are as malformed as wrong types:
    level "" would silently vanish from an item export, parent ref "" would
    read as a root record, resource ref "" as a stale index hit."""
    if not isinstance(record, dict):
        return "not a record"
    resource = record.get("resource")
    if (not isinstance(resource, dict) or not isinstance(resource.get("ref"), str)
            or not _repo_pinned("resources").fullmatch(resource["ref"])):
        return "resource"
    level = record.get("level")
    if not isinstance(level, str) or level not in LEVELS or level == "all":
        # ArchivesSpace enforces its level vocabulary, so an unknown value is
        # malformed - and must not be silently dropped by the level filter.
        return "level"
    # A component ID may be absent or blank (a cataloging gap, flagged in
    # Warnings) but any PRESENT value must be a string - it becomes a dict
    # key, a MADS url, and a CSV cell.
    component_id = record.get("component_id")
    if component_id is not None and not isinstance(component_id, str):
        return "component_id"
    # Everything build_row serializes into a cell must be a string (or
    # absent) - a list-valued title would be written as literal text and
    # could be round-tripped back as a title; and every collection
    # build_row iterates must be a list of objects, or it crashes.
    for field in ("title", "ref_id", "created_by", "create_time",
                  "last_modified_by", "user_mtime", "display_string"):
        value = record.get(field)
        if value is not None and not isinstance(value, str):
            return field
    # position orders siblings in the tree (hierarchy_for); absent is
    # tolerated, anything but an integer is malformed
    position = record.get("position")
    if position is not None and (not isinstance(position, int) or isinstance(position, bool)):
        return "position"
    for field in ("dates", "extents", "notes"):
        items = record.get(field)
        if items is None:
            continue
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            return field
    # ...and the VALUES inside those objects that build_row / get_note_content
    # read must be strings (or absent): a list-valued begin or content would
    # be serialized into a cell as literal text.
    def _str_or_none(obj, keys):
        return all(obj.get(k) is None or isinstance(obj.get(k), str) for k in keys)
    for d in record.get("dates") or []:
        if not _str_or_none(d, ("label", "begin", "end", "date_type", "expression")):
            return "dates"
    for e in record.get("extents") or []:
        if not _str_or_none(e, ("extent_type", "portion", "number", "physical_details")):
            return "extents"
    for note in record.get("notes") or []:
        if not _str_or_none(note, ("type", "label", "jsonmodel_type")):
            return "notes"
        content = note.get("content")  # single-part notes carry content directly
        if content is not None and not (isinstance(content, str) or (
                isinstance(content, list) and all(isinstance(c, str) for c in content))):
            return "notes"
        if "subnotes" in note:
            # present means it must be a list of objects - get_note_content
            # iterates it whenever the key exists, so an explicit null crashes
            subnotes = note["subnotes"]
            if not isinstance(subnotes, list) or not all(isinstance(sn, dict) for sn in subnotes):
                return "notes"
        else:
            subnotes = []
        for sn in subnotes:
            if not _str_or_none(sn, ("content", "jsonmodel_type")):
                return "notes"
    parent = record.get("parent")
    if parent is not None and (not isinstance(parent, dict)
                               or not isinstance(parent.get("ref"), str)
                               or not _repo_pinned("archival_objects").fullmatch(parent["ref"])):
        return "parent"
    return None


def flag_duplicate_catalog_numbers(rows, counts):
    """Warn on rows whose component ID is shared anywhere in the resource
    (`counts`: component ID -> occurrences across every level, computed
    before filtering) - the importer refuses those, so a round-trip sheet
    should say so up front even when the other holder wasn't exported."""
    for r in rows:
        cat = r.get(col.CATALOG)
        if cat and counts.get(cat, 0) > 1:
            extra = f"component ID shared by {counts[cat]} records - the importer will refuse it"
            r["Warnings"] = "; ".join(w for w in (r.get("Warnings", ""), extra) if w)


def export_fieldnames(extra_headers=()):
    """The export CSV's columns: EXPORT_COLUMNS, with an optional column
    only when asked for (MADS live)."""
    return [c for c in EXPORT_COLUMNS if c not in OPTIONAL_EXPORT_COLUMNS or c in extra_headers]


def write_export_csv(rows, path, extra_headers=(), provenance=None):
    """Write the export atomically - the final path only ever holds a
    complete file (a .tmp is never mistakable for a finished export).

    `provenance` (the command that made the file, plus target/time) is
    written as a raw '# ...' first line so the sheet explains its own
    origin; every tool's CSV reader skips '#' lines (col.open_csv)."""
    fieldnames = export_fieldnames(extra_headers)

    def write(f):
        if provenance:
            f.write(f"# {provenance}\n")
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    col.save_via_temp(path, write, newline="")


def fill_output_paths(sheet_path):
    """The ready and human-review CSV paths beside the input sheet."""
    directory = os.path.dirname(sheet_path) or "."
    stem = os.path.splitext(os.path.basename(sheet_path))[0]
    return (os.path.join(directory, f"jpc-fill_{stem}_parent_ref-id_ready_for_ASpace_import.csv"),
            os.path.join(directory, f"jpc-fill_{stem}_needs_human_review.csv"))


def fix_in(note):
    """Where to look first for a review row. "Airtable" when the sheet
    itself needs a person (TBD, several episodes, Raw, a conflict): enter
    the parent or correct the episode, then pull again. When the lookup
    found nothing, or too much, in ArchivesSpace, the cause may still be an
    Airtable typo (episode, file type) - so check Airtable first, and fix
    the ArchivesSpace hierarchy only if Airtable's value is right."""
    if note.startswith("on hold") or col.HOLD in note:
        return "Airtable (hold)"
    if ("in ArchivesSpace" in note or "records match" in note
            or "has no ref_id" in note):
        return "Airtable, then ArchivesSpace"
    return "Airtable"


def split_filled(rows, filled, unresolved):
    """(ready, review, counts) from fill_parents' results. The split follows
    the explicit unresolved list - never the note text or a blank cell.
    counts: ready rows whose parent came from the lookup vs. was already in
    the sheet (a person's value, taken as given)."""
    review_nums = {row_num for row_num, _, _ in unresolved}
    ready = [r for i, r in enumerate(rows, 1) if i not in review_nums]
    review = [r for i, r in enumerate(rows, 1) if i in review_nums]
    for r in review:
        r[FIX_IN] = fix_in(r.get(col.PARENT_NOTE) or "")
    return ready, review, {"by lookup": filled, "supplied": len(ready) - filled}


# Review reasons, in the order they are shown; each note falls in the first
# group whose test matches it.
REVIEW_GROUPS = [
    ("On hold", lambda n: n.startswith("on hold") or col.HOLD in n),
    ("EJS Episode is TBD", lambda n: "is TBD" in n),
    ("More than one episode", lambda n: "more than one episode" in n
                                        or "not a single episode" in n),
    ("Raw - choose the parent by hand", lambda n: n.startswith("Raw")),
    ("Airtable's parent differs from the lookup", lambda n: "different parent" in n),
    ("Episode and title disagree", lambda n: "disagree" in n),
    ("Missing in ArchivesSpace", lambda n: "not found in ArchivesSpace" in n
                                           or "has no " in n),
    ("Several matching records", lambda n: "records match" in n),
    ("No episode given", lambda n: n.startswith("no ")),
    ("Other", lambda n: True),
]


def open_issues(rows):
    """[(catalog number, ASpace Issue text)] for rows that are not held but
    carry an issue - listed for the operator, never refused."""
    return [((row.get(col.CATALOG) or "").strip(), col.open_issue(row))
            for row in rows if col.open_issue(row)]


def print_fill_result(ready, review, counts, unresolved, ready_path, review_path,
                      issues=()):
    """The fill's answer, set apart and easy to scan: the two counts first,
    then the review rows grouped by reason (a group whose rows share one
    note lists just their catalog numbers), then the open issues on rows
    that are not held - shown, not refused."""
    C = Colors
    print_section("RESULT")
    print(f"  {C.GREEN}{C.BOLD}Parent-ready    {len(ready):>6}{C.RESET}")
    print(f"  {'':<16}{counts['by lookup']:>6}   parent found by lookup")
    print(f"  {'':<16}{counts['supplied']:>6}   parent kept as entered in Airtable")
    print()
    color = C.YELLOW if review else C.GREEN
    print(f"  {color}{C.BOLD}Needs review    {len(review):>6}{C.RESET}")
    if review:
        _print_review_groups(unresolved)
    if issues:
        print(f"\n  {C.YELLOW}{C.BOLD}Open issues     {len(issues):>6}{C.RESET}   "
              f"{C.DIM}{col.ISSUE} text on rows not held - still processed{C.RESET}")
        for catalog, text in issues:
            print(f"      {catalog or '(no catalog number)'}   {text}")
    print_saved([("ready CSV", ready_path), ("review CSV", review_path)])
    print()
    if review:
        print(f"  {C.DIM}Fix review rows where the {FIX_IN} column says, then pull again.{C.RESET}")
    print(f"  {C.DIM}Parent-ready rows can still be refused at import (format, dates) - "
          f"the import's dry run checks them.{C.RESET}\n")


def _print_review_groups(unresolved):
    """Every review row, grouped by reason in REVIEW_GROUPS order."""
    C = Colors
    groups = {label: [] for label, _ in REVIEW_GROUPS}
    for _row_num, catalog, note in unresolved:
        label = next(label for label, test in REVIEW_GROUPS if test(note))
        groups[label].append((catalog or "(no catalog number)", note))
    for label, rows in groups.items():
        if not rows:
            continue
        print(f"\n    {C.BOLD}{label} ({len(rows)}){C.RESET}")
        notes = {note for _, note in rows}
        if len(notes) == 1 and len(rows) > 1:
            print(f"      {C.DIM}{next(iter(notes))}{C.RESET}")
            numbers = [catalog for catalog, _ in rows]
            for i in range(0, len(numbers), 4):
                print("      " + "   ".join(numbers[i:i + 4]))
        else:
            for catalog, note in rows:
                print(f"      {catalog}   {note}")


def run_fill_parents(sheet_path, ready_path, review_path):
    """--fill-parents end to end: writes the parent-ready rows and the rows
    for review as two files. Returns the exit code: 0 when every row is
    parent-ready, 2 when some are for review (expected - both files are
    written), 1 on failure - nothing written, except when the ready file
    fails after the review file was written (the message then says so)."""
    headers, rows, problem = read_fill_sheet(sheet_path)  # before any network work
    if rows is None:
        print_status("error", problem)
        return 1
    client = ASpaceClient()
    print_status("info", f"Connecting to {aspace_client.ASPACE_URL}...")
    if not client.login():
        print_status("error", f"Could not log in: {client.login_problem}")
        return 1
    print_status("success", "Authenticated")
    try:
        records, reason = fetch_resource(client)
        if records is not None:
            index, episodes, reason = index_file_records(client, records)
    finally:
        client.logout()
    if records is None or index is None:
        print_status("error", f"Hierarchy problem: {reason}")
        return 1
    filled, kept, unresolved = fill_parents(rows, index, episodes)
    ready, review, counts = split_filled(rows, filled, unresolved)
    provenance = (f"{RUN_COMMAND} | target: {aspace_client.ACTIVE_ENV} | "
                  f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    # review first, ready last: a ready file never appears without its pair
    try:
        write_filled_csv(headers, review, review_path, provenance, extra_columns=(FIX_IN,))
    except OSError as e:
        print_status("error", f"Could not write {review_path}: {e} - nothing written")
        return 1
    try:
        write_filled_csv(headers, ready, ready_path, provenance)
    except OSError as e:
        print_status("error", f"Could not write {ready_path}: {e} - the pair is incomplete; "
                              f"delete {review_path} and run the fill again")
        return 1
    print_fill_result(ready, review, counts, unresolved, ready_path, review_path,
                      open_issues(rows))
    return 2 if review else 0


# ------------------------------------------------------------------
# --check: which catalog numbers ArchivesSpace has - and, given an Airtable
# pull, whether Airtable's tracking columns agree with it. Read-only.
# ------------------------------------------------------------------

# The Airtable columns --check compares, when the file has them.
COMPARED_COLUMNS = (col.PARENT_REFID, col.CREATED_LOOKUP)

# An agreeing number is counted instead of listed on screen only when the
# file has all of these, each spelled exactly (see counted_only).
COUNT_ONLY_COLUMNS = COMPARED_COLUMNS + (col.HOLD, col.ISSUE)

# Every number lands on exactly ONE line, the first that applies in this
# order; everything else that applies is kept in its Detail.
CHECK_LINES = [
    ("cannot", "Could not check", "unknown"),
    ("ambiguous", "Ambiguous", "bad"),
    ("conflict", "Conflicting rows in the file", "bad"),
    ("not_item", "Not an item record", "bad"),
    ("yes_missing", "Marked Yes, not found in ArchivesSpace", "bad"),
    ("parent_differs", "In ArchivesSpace, parent differs", "bad"),
    ("incomplete", "In ArchivesSpace, Airtable incomplete", "attention"),
    ("agrees", "In ArchivesSpace, compared fields agree", "ok"),
    ("found", "In ArchivesSpace", "ok"),
    ("not_found", "Not found by JPC_AV_xxxxx", "info"),
]
CHECK_LABELS = {key: label for key, label, _ in CHECK_LINES}
REVIEW_KEYS = {"cannot", "ambiguous", "conflict", "not_item", "yes_missing",
               "parent_differs", "incomplete"}

# An Airtable pull's first line: "# python3 .../airtable_pull.py VIEW |
# airtable view: VIEW | 2026-09-30 01:51". Only that line dates the
# snapshot; a fill, export or import report dates something else.
PULL_PROVENANCE_RE = re.compile(
    r"^#.*\bairtable_pull\.py\b.*\| airtable view: (?P<view>.*) \| "
    r"(?P<when>\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*$")

NOT_IN_FILE = "(not in file)"


def created_state(value):
    """ASpace Item Record Created as a pull writes it: 'yes', 'no', 'blank',
    or 'unreadable' (anything else - e.g. 'Yes, No' from a lookup that sees
    two tracking rows). Unreadable is never taken for 'not Yes'."""
    text = (value or "").strip()
    if not text:
        return "blank"
    return {"yes": "yes", "no": "no"}.get(text.casefold(), "unreadable")


def read_check_input(path):
    """The list to check, and what Airtable says about each number.

    Returns (sheet, problem). sheet: numbers (order kept, each once), facts
    ({number: [one dict per row]}), columns ({name: present}), warnings,
    pulled ((view, when) from a pull's provenance line, or None) and plain
    (True for a plain text list). The list itself is read by
    read_catalog_list, so a check accepts exactly what --list does.

    The file is read from disk once: the numbers, the rows and the
    provenance line all come from that one captured text, so a file saved
    again meanwhile can never mix two versions into one check."""
    try:
        source = col.CsvSnapshot(path)
    except (UnicodeDecodeError, OSError) as e:
        return None, col.read_problem(path, e)
    numbers, problem = read_catalog_list(source)
    if numbers is None:
        return None, problem
    sheet = {"numbers": numbers, "facts": {}, "warnings": [], "pulled": None,
             "plain": True, "columns": {c: False for c in COMPARED_COLUMNS + (col.HOLD, col.ISSUE)}}
    with col.open_csv(source) as f:
        pos = f.tell()
        headers = csv.DictReader(f, strict=True).fieldnames or []
        if col.CATALOG not in headers:
            return sheet, None
        sheet["plain"] = False
        f.seek(pos)
        rows = list(csv.DictReader(f, strict=True))
    # the first line as before: universal newlines (LF, CRLF or a bare CR)
    first = io.StringIO(source.text, newline=None).readline()
    match = PULL_PROVENANCE_RE.match(first.rstrip("\n"))
    if match:
        sheet["pulled"] = (match["view"], match["when"])
    for name in sheet["columns"]:
        variant = col.near_miss_name(headers, name)
        if name in headers:
            sheet["columns"][name] = True
        elif variant is not None:
            # this check only reports: a misspelled column costs just that
            # column (the import-side tools refuse such a sheet outright)
            sheet["warnings"].append(f"column {variant!r} is not spelled exactly {name!r} - "
                                     f"{'not compared' if name in COMPARED_COLUMNS else 'not shown'}")
    has = sheet["columns"]
    for row in rows:
        number = (row.get(col.CATALOG) or "").strip()
        if not number:
            continue
        sheet["facts"].setdefault(number, []).append({
            "parent": (row.get(col.PARENT_REFID) or "").strip() if has[col.PARENT_REFID] else None,
            "created": (row.get(col.CREATED_LOOKUP) or "").strip() if has[col.CREATED_LOOKUP] else None,
            "hold": col.hold_problem(row) if has[col.HOLD] else None,
            "issue": (row.get(col.ISSUE) or "").strip() if has[col.ISSUE] else None,
        })
    return sheet, None


def check_records(client, numbers):
    """Look every number up (read-only), at any level: a record carrying the
    number at another level is a conflict, not an absence. Returns
    {number: {status, title, path, level, parent, parent_problem}}; status
    is found / none / multiple / failed / malformed (the number) /
    malformed_record. parent is the parent's ref_id, "" for a top-level
    record, None when it could not be read. A failed lookup is never
    evidence of absence."""
    results = {}
    linked_cache = {}
    try:
        for i, number in enumerate(numbers, 1):
            entry = {"status": None, "title": "", "path": "", "level": "",
                     "parent": None, "parent_problem": None}
            if not col.valid_catalog_number(number):
                entry["status"] = "malformed"
            else:
                lookup = client.find_archival_object(number)
                if lookup.status == "found":
                    record = lookup.record
                    shape = record_shape_problem(record)
                    if shape:
                        entry.update(status="malformed_record",
                                     title=f"the record is malformed ({shape}) - check it in ArchivesSpace")
                        results[number] = entry
                        progress("Checked", i, len(numbers))
                        continue
                    entry.update(status="found", level=record.get("level") or "",
                                 title=(record.get("title") or "").strip() or "(no title)")
                    try:
                        placed, reason = place_record(
                            record, lambda uri: fetch_linked(client, uri, linked_cache))
                    except (AttributeError, KeyError, TypeError, ValueError) as e:
                        # a malformed ancestor: this number cannot be placed;
                        # the others are still checked
                        placed, reason = None, f"malformed ancestor ({type(e).__name__}: {e})"
                    if placed:
                        entry["parent"], entry["path"] = placed[0], placed[2]
                    else:
                        entry["parent_problem"] = reason
                elif lookup.status == "none":
                    entry["status"] = "none"
                elif lookup.status == "multiple":
                    entry.update(status="multiple", title=f"{lookup.count} records share this number")
                else:
                    entry["status"] = "failed"
            results[number] = entry
            progress("Checked", i, len(numbers))
    finally:
        close_progress()
    return results


def classify(number, found, rows, columns):
    """One number's line (a CHECK_LINES key) and every fact behind it."""
    facts, status = [], found["status"]
    if status == "found":
        facts.append(found["title"] + (f"  ({found['path']})" if found["path"] else ""))
    elif status == "none":
        facts.append("no record with this catalog number")
    elif status == "multiple":
        facts.append(f"{found['title']} - clean up first")
    elif status == "failed":
        facts.append("lookup failed - retry; do not treat as absent")
    elif status == "malformed_record":
        facts.append(found["title"])
    else:
        facts.append("not of the form JPC_AV_ + digits - not looked up")

    distinct = [dict(t) for t in {tuple(sorted(r.items())) for r in rows}]
    conflict = len(distinct) > 1
    if conflict:
        for field in ("parent", "created", "hold", "issue"):
            values = sorted({repr(r[field]) for r in rows})
            if len(values) > 1:
                facts.append(f"rows disagree on {field}: {' / '.join(values)}")
    airtable = rows[0] if rows and not conflict else {}
    parent_col, created_col = columns[col.PARENT_REFID], columns[col.CREATED_LOOKUP]
    created = created_state(airtable.get("created")) if created_col and airtable else None
    at_parent = airtable.get("parent") if parent_col and airtable else None

    bad_status = sorted({r["created"] for r in rows
                         if created_col and created_state(r["created"]) == "unreadable"})
    unreadable = bool(bad_status)
    if unreadable:
        facts.append(f"Item Record Created unreadable: {' / '.join(map(repr, bad_status))}")
    parent_unread = status == "found" and parent_col and found["parent_problem"]
    if parent_unread:
        facts.append(f"ArchivesSpace parent could not be read: {found['parent_problem']}")
    not_item = status == "found" and found["level"] != "item"
    if not_item:
        facts.append(f"the record is at level {found['level'] or '(none)'!r}, not an item")
    # the ArchivesSpace parent is known when it was read: a ref_id, or ""
    # for a top-level record (no parent) - only None means unknown
    known = status == "found" and parent_col and airtable and found["parent"] is not None
    as_parent = found["parent"] or "none (top level)"
    differs = bool(known and at_parent and at_parent != found["parent"])
    if differs:
        facts.append(f"parent differs: Airtable {at_parent}, ArchivesSpace {as_parent}")
    blank_parent = bool(known and not at_parent and found["parent"])
    if blank_parent:
        facts.append(f"Airtable parent blank (ArchivesSpace: {as_parent})")
    not_yes = status == "found" and created in ("no", "blank")
    if not_yes:
        facts.append(f"not marked Yes (Item Record Created: {airtable['created'] or 'blank'})")
    yes_missing = status == "none" and created == "yes"
    if yes_missing:
        facts.append("Airtable says the record was created")

    if status in ("failed", "malformed", "malformed_record") or unreadable or parent_unread:
        key = "cannot"
    elif status == "multiple":
        key = "ambiguous"
    elif conflict:
        key = "conflict"
    elif not_item:
        key = "not_item"
    elif yes_missing:
        key = "yes_missing"
    elif differs:
        key = "parent_differs"
    elif blank_parent or not_yes:
        key = "incomplete"
    elif status == "found":
        key = "agrees" if (parent_col or created_col) and airtable else "found"
    else:
        key = "not_found"
    return key, facts


def check_markers(rows):
    """The hold and open-issue notes to show beside a number."""
    holds = sorted({r["hold"] for r in rows if r.get("hold")})
    issues = sorted({r["issue"] for r in rows if r.get("issue") and not r.get("hold")})
    return holds + [f"issue: {i}" for i in issues]


def counted_only(outcome, columns):
    """Whether the screen counts this number instead of listing it: its line
    is "compared fields agree", the file has every COUNT_ONLY_COLUMNS column
    (`columns`: which ones read_check_input found, spelled exactly), and none
    of its rows is held - an unreadable hold included - or carries issue
    text. Screen only: the outcome, its line and the CSV never change."""
    return (outcome["key"] == "agrees"
            and all((columns or {}).get(name) for name in COUNT_ONLY_COLUMNS)
            and not any(row["hold"] or row["issue"] for row in outcome["rows"]))


def print_check_result(outcomes, columns=None):
    """RESULT (every number on one line), then each line's numbers - review
    lines first; an agreeing number with nothing to note is counted, not
    listed (counted_only). Returns the exit code: 2 if anything needs review
    or could not be checked, else 0 (numbers not found are a definite
    answer)."""
    counts = {key: sum(1 for o in outcomes if o["key"] == key) for key, _, _ in CHECK_LINES}
    print_result([("JPC_AV_xxxxx checked", len(outcomes), "neutral", True)]
                 + [(label, counts[key], tone) for key, label, tone in CHECK_LINES])
    for key, label, tone in CHECK_LINES:
        group = [o for o in outcomes if o["key"] == key]
        if not group:
            continue
        color = {"ok": Colors.GREEN, "bad": Colors.RED, "info": Colors.CYAN,
                 "neutral": ""}.get(tone, Colors.YELLOW)
        print(f"\n  {color}{Colors.BOLD}{label} ({len(group)}){Colors.RESET}")
        listed = [o for o in group if not counted_only(o, columns)]
        for o in listed:
            # the first fact on the number's line; for a line that needs
            # review, every further fact on a line of its own beneath it
            first = "" if key == "not_found" else o["facts"][0]
            marks = [f"{Colors.YELLOW}[{m}]{Colors.RESET}" for m in o["marks"]]
            print("      " + "  ".join(part for part in [o["number"], first] + marks if part))
            if key in REVIEW_KEYS:
                for fact in o["facts"][1:]:
                    print(f"{'':20}{fact}")
        unlisted = len(group) - len(listed)
        if unlisted:
            print(f"      {'and ' if listed else ''}{unlisted}{' more' if listed else ''} "
                  f"with no hold or issue (not listed; --output lists all)")
    print(f"\n  {Colors.DIM}\"In ArchivesSpace\" means a record with that JPC_AV_xxxxx exists; "
          f"only{Colors.RESET}")
    print(f"  {Colors.DIM}the listed Airtable columns were compared, no other metadata.{Colors.RESET}")
    return 2 if any(o["key"] in REVIEW_KEYS for o in outcomes) else 0


def write_check_csv(outcomes, sheet, path, provenance=None):
    """The check's answer as a CSV (only when -o asks for one), as complete
    as the screen. A column absent from the input says so - it is not the
    same as an empty cell."""
    has = sheet["columns"]

    def cell(o, field, name):
        if not has[name]:
            return NOT_IN_FILE
        values = sorted({r[field] or "" for r in o["rows"]})
        return " / ".join(values)

    def write(f):
        if provenance:
            f.write(f"# {provenance}\n")
        writer = csv.writer(f)
        writer.writerow([col.CATALOG, "Outcome", "ArchivesSpace parent", "Airtable parent",
                         col.CREATED_LOOKUP, col.HOLD, col.ISSUE, "Detail"])
        for o in outcomes:
            writer.writerow([o["number"], CHECK_LABELS[o["key"]], o["found"]["parent"] or "",
                             cell(o, "parent", col.PARENT_REFID),
                             cell(o, "created", col.CREATED_LOOKUP),
                             cell(o, "hold", col.HOLD), cell(o, "issue", col.ISSUE),
                             "; ".join(o["facts"])])
    col.save_via_temp(path, write, newline="")


def run_check(list_path, csv_path=None, source=None):
    """--check end to end. Returns the exit code: 0 or 2 (see
    print_check_result); 1 when the list cannot be read or login fails
    (nothing checked), or when the -o report cannot be saved (checked, but
    not saved)."""
    sheet, problem = read_check_input(list_path)  # before any network work
    has = sheet["columns"] if sheet else {}
    compared = [c for c in COMPARED_COLUMNS if has.get(c)]
    if sheet is None:
        mode = None
    elif sheet["plain"]:
        mode = "live ArchivesSpace only (a plain list - Airtable not compared)"
    elif not compared:
        mode = "live ArchivesSpace only (no Airtable tracking columns in the file)"
    elif sheet["pulled"]:
        mode = (f"live ArchivesSpace compared with this Airtable snapshot "
                f"(view '{sheet['pulled'][0]}', pulled {sheet['pulled'][1]})")
    else:
        mode = "live ArchivesSpace compared with this file's Airtable columns (pulled: unknown)"
    missing = [c for c in COMPARED_COLUMNS if not has.get(c)]
    print_run_header("Check catalog numbers in ArchivesSpace (read-only)", target=source,
                     input=os.path.abspath(list_path), mode=mode,
                     extra=[("Compared", ", ".join(compared)),
                            ("Not checked", compared and missing
                             and f"{', '.join(missing)} (not in the file)")])
    if sheet is None:
        print_status("error", problem)
        return 1
    for warning in sheet["warnings"]:
        print_status("warning", warning)
    if csv_path:
        col.ensure_parent(csv_path)  # the input is usable: the -o folder, before login
    client = ASpaceClient()
    print_status("info", f"Connecting to {aspace_client.ASPACE_URL}...")
    if not client.login():
        print_status("error", f"Could not log in: {client.login_problem}")
        return 1
    print_status("success", "Authenticated")
    print_status("info", f"Checking {len(sheet['numbers'])} catalog number(s)...")
    try:
        found = check_records(client, sheet["numbers"])
    finally:
        client.logout()
    outcomes = []
    for number in sheet["numbers"]:
        rows = sheet["facts"].get(number, [])
        key, facts = classify(number, found[number], rows, has)
        outcomes.append({"number": number, "key": key, "facts": facts, "rows": rows,
                         "found": found[number], "marks": check_markers(rows)})
    code = print_check_result(outcomes, has)
    if csv_path:
        provenance = (f"{RUN_COMMAND} | target: {aspace_client.ACTIVE_ENV} | "
                      f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        try:
            write_check_csv(outcomes, sheet, csv_path, provenance)
        except OSError as e:
            print_saved([], failed=[("check CSV", csv_path)])
            print_status("error", f"The check itself completed (above), but its report could "
                                  f"not be saved: {e}")
            print()
            return 1
        print_saved([("check CSV", csv_path)])
    print()
    return code


def mark_mads_live(rows):
    """--mads-live: fill each row's MADS live cell and print the counts.
    Returns how many checks failed or could not be made (a row with no
    catalog number) - 'check failed' is not proof of absence."""
    cats = [r.get(col.CATALOG, "") for r in rows]
    print_status("info", f"Checking MADS liveness for "
                         f"{len(set(c for c in cats if c))} catalog number(s)...")
    mads = check_many(cats)
    for r in rows:
        # a row with no catalog number cannot be checked - say so in
        # the cell, and count it as incomplete, rather than leaving a
        # blank that reads like "not checked yet"
        r["MADS live"] = mads.get(r.get(col.CATALOG, ""), "invalid catalog number")
    mads = {**mads, **{f"(row {i})": "invalid catalog number"
                       for i, r in enumerate(rows, 1) if not r.get(col.CATALOG)}}
    live, not_live, check_failed = summarize(mads)
    print_status("info", f"MADS: {live} live, {not_live} not in MADS")
    if check_failed:
        print_status("warning", f"{check_failed} MADS check(s) failed or had an invalid "
                                f"catalog number - 'check failed' is not proof of absence; "
                                f"re-run --mads-live for those")
    return check_failed


def _row_warnings(row):
    return [w for w in row.get("Warnings", "").split("; ") if w]


def print_row_warnings(rows):
    """The rows that carry Warnings, each with its staff link."""
    flagged = sum(1 for r in rows if _row_warnings(r))
    if not flagged:
        return
    print()
    print_status("warning", f"{flagged} record(s) have Warnings:")
    for r in rows:
        others = _row_warnings(r)
        if others:
            label = r.get(col.CATALOG) or f"(no catalog number) {r.get(col.TITLE) or '(no title)'}"
            print_status("warning", f"{label}: {'; '.join(others)}", indent=1)
            if r.get("ASpace Staff Link"):
                print(f"       {Colors.DIM}{r['ASpace Staff Link']}{Colors.RESET}")


# ------------------------------------------------------------------
# --record: named records in full (T-166). Read-only, like everything here:
# the named records are looked up one by one (never the whole resource) and
# saved as a record package - the complete records as JSON, the usual
# export CSV, and a notes CSV - none of which ever replaces an existing file.
# ------------------------------------------------------------------

# How one --record value is read, in this order. A full catalog number
# first. Then the shapes refused rather than guessed at: bare digits
# (catalog-number shorthand, accepted nowhere in the tools) and anything
# that starts like a catalog number without being one (jpc_av_01561,
# JPC-AV-01561, JPC_AV_ alone, a pasted JPC_AV_xxxxx_refid_... folder name).
# Then a ref ID in the importer's usable shape (REF_ID_TEXT_RE), case kept.
# The shape alone decides: a catalog lookup that finds nothing is never
# retried as a ref ID, so what a value means never depends on what exists.
BARE_DIGITS_RE = re.compile(r"[0-9]+")
JPC_AV_LIKE_RE = re.compile(r"jpc[_-]?av", re.IGNORECASE)   # matched at the start

REFID_NOT_FOUND = ("no record with this ref ID in the resource - it may belong to another "
                   "resource or repository, or be too new for the search index")

# The notes CSV: one row per piece of note content (see note_rows).
NOTES_COLUMNS = ["ASpace Ref ID", "ASpace URI", col.CATALOG, "Note #", "Note Type",
                 "Note Model", "Note Label", "Note Published", "Part #", "Part Model",
                 "Part Title", "Item #", "Entry #", "Row Kind", "Label", "Value",
                 "Not Shown", "JSON Pointer"]

# The fields each note and subnote model from ArchivesSpace's published
# schemas shows in its own columns; any other field present is named in Not
# Shown (jsonmodel_type aside), and an unknown model gets an 'unmapped' row.
_NOTE_SHOWN = {"note_multipart": {"type", "label", "publish", "subnotes"},
               "note_singlepart": {"type", "label", "publish", "content"},
               "note_bibliography": {"type", "label", "publish", "content", "items"},
               "note_index": {"type", "label", "publish", "content", "items"}}
_PART_SHOWN = {"note_text": {"content"},
               "note_definedlist": {"title", "items"},
               "note_orderedlist": {"title", "items"},
               "note_chronology": {"title", "items"}}

PACKAGE_ROLES = (("json", "record JSON"), ("main_csv", "main CSV"), ("notes_csv", "notes CSV"))


def record_value_kind(value):
    """'catalog', 'refid', or None (reserved or malformed) for one value."""
    if col.valid_catalog_number(value):
        return "catalog"
    if BARE_DIGITS_RE.fullmatch(value) or JPC_AV_LIKE_RE.match(value):
        return None
    if REF_ID_TEXT_RE.fullmatch(value):
        return "refid"
    return None


def classify_record_values(values):
    """The --record values as ([(position, value, kind)], None), surrounding
    spaces stripped and exact repeats dropped (the first kept) - or (None,
    message) when any value is reserved or malformed. The message counts the
    bad values and gives their --record positions, never a value: it is
    raised after parsing, where the parser's own hiding no longer applies,
    and what was typed could be anything, even a password."""
    bad, named, seen = [], [], set()
    for position, raw in enumerate(values, 1):
        value = raw.strip()
        kind = record_value_kind(value)
        if kind is None:
            bad.append(position)
        elif value not in seen:
            seen.add(value)
            named.append((position, value, kind))
    if not bad:
        return named, None
    positions = ", ".join(str(p) for p in bad[:10])
    if len(bad) > 10:
        positions += f" and {len(bad) - 10} more"
    plural = len(bad) > 1
    return None, (f"--record: {len(bad)} of the {len(values)} value{'s' if len(values) > 1 else ''} "
                  f"given (position{'s' if plural else ''} {positions}) {'are' if plural else 'is'} "
                  f"not a full JPC_AV_xxxxx or a usable ref ID - not shown; bare digits and other "
                  f"JPC_AV-like forms are reserved; one value per --record; nothing was looked up")


def usable_package_json_path(path):
    """True when -o can name a record package's JSON file: it ends in .json
    and has a name before it."""
    return path.lower().endswith(".json") and len(os.path.basename(path)) > len(".json")


def record_package_paths(json_path):
    """The record package's three files, side by side: the JSON, then - its
    name without .json - the main CSV and the notes CSV."""
    stem = json_path[:-len(".json")]
    return {"json": json_path, "main_csv": f"{stem}.csv", "notes_csv": f"{stem}_notes.csv"}


def catalog_number_check(client, record, uri, cache):
    """Whether a record found by ref ID shares its JPC_AV_xxxxx (component
    ID) with any other record - the whole-resource export's duplicate check,
    for one record. (A record found by its catalog number was checked by
    that lookup.) `cache` maps component ID -> Lookup for the run, shared
    with the catalog-number lookups, so the two routes never disagree.
    Returns (check, warnings): the JSON entry and the texts for the row.
    Whatever the search cannot vouch for is 'incomplete' - never 'not
    shared' by a default count of zero. One check is a search walk (one or
    more pages) plus a GET for every candidate."""
    cid = record.get("component_id")
    if not isinstance(cid, str) or not cid:
        return {"status": "not applicable", "reason": "no component ID"}, []
    if cid not in cache:
        cache[cid] = client.find_archival_object(cid)
    lookup = cache[cid]
    holders = [u for u, _ in lookup.matches] if lookup.status in ("found", "multiple") else []
    if lookup.status == "found" and holders == [uri]:
        return {"status": "not shared"}, []
    if lookup.status == "multiple" and uri in holders:
        n = len(holders)
        # the whole-resource export's exact text (flag_duplicate_catalog_numbers)
        return ({"status": "shared", "holders": n},
                [f"component ID shared by {n} records - the importer will refuse it"])
    if lookup.status in ("found", "multiple"):
        # other records hold it, but the index did not return this one
        n = len(holders) + 1
        reason = "the search found other records with this component ID but not this one"
        return ({"status": "incomplete", "shared": True, "holders_at_least": n, "reason": reason},
                [f"component ID shared by at least {n} records - the importer will refuse it",
                 f"duplicate check incomplete - {reason}; retry later"])
    reason = ("the search found no record with this component ID, not even this one "
              "(the index may lag)" if lookup.status == "none" else "the search failed")
    return ({"status": "incomplete", "reason": reason},
            [f"duplicate check incomplete - {reason}; retry later"])


def export_by_record(client, named):
    """Look up each --record value with the verified helpers - a catalog
    number with find_archival_object, a ref ID with find_parent (any level,
    pinned to the configured resource) - and keep every record found.

    Returns (requested, entries, notes). `requested`: one dict per value, in
    the order given, with its outcome. `entries`: one per distinct record
    (by its verified uri), in the order first found, each holding an
    untouched deep copy of the record as returned, its placement, its
    duplicate check and its export row (None when the row could not be
    built - the record is still kept for the JSON). `notes`: info lines for
    values that named a record already found."""
    requested, entries, notes = [], [], []
    by_uri, linked_cache, cid_cache = {}, {}, {}
    try:
        for i, (position, value, kind) in enumerate(named, 1):
            ask = {"position": position, "value": value,
                   "kind": "catalog number" if kind == "catalog" else "ref ID"}
            requested.append(ask)
            if kind == "catalog":
                if value not in cid_cache:
                    cid_cache[value] = client.find_archival_object(value)
                lookup = cid_cache[value]
            else:
                lookup = client.find_parent(value)
            progress("Looked up", i, len(named))
            if lookup.status != "found":
                what = "JPC_AV_xxxxx" if kind == "catalog" else "ref ID"
                ask["result"] = "not exported"
                ask["outcome"] = (
                    ("not found in the resource" if kind == "catalog" else REFID_NOT_FOUND)
                    if lookup.status == "none" else
                    f"{lookup.count} records share this {what}" if lookup.status == "multiple"
                    else "lookup failed - retry later")
                continue
            ask["uri"] = lookup.uri
            first = by_uri.get(lookup.uri)
            if first is not None:
                # the same record, named again: one entry; the note says what
                # happened to it - "exported once" only if it really was
                first_value = first["requested_as"][0]
                first["requested_as"].append(value)
                first["requested_positions"].append(position)
                ask["result"], ask["same_as"] = "same record", first_value
                ask["outcome"] = (f"same record as {first_value} - exported once"
                                  if first["row"] is not None else
                                  f"same record as {first_value} - {first['outcome']} (see above)")
                notes.append(f"{value}: {ask['outcome']}")
                continue
            entry = {"requested_as": [value], "requested_positions": [position],
                     "uri": lookup.uri,
                     "record": copy.deepcopy(lookup.record)}   # as returned; never modified
            row, reason = _row_for(client, lookup.record, linked_cache)
            if row is None:
                entry["placement"] = {"status": "failed", "reason": reason}
                entry["outcome"] = f"incomplete - no main CSV row: {reason}"
            else:
                entry["placement"] = {"status": "placed", "depth": row["Depth"],
                                      "path": row["Path"], "parent_ref_id": row[col.PARENT_REFID]}
                entry["outcome"] = "exported"
            if kind == "catalog":
                check, warnings = {"status": "not shared"}, []   # that lookup found exactly one
            else:
                check, warnings = catalog_number_check(client, lookup.record, lookup.uri, cid_cache)
            entry["catalog_number_check"] = check
            if check["status"] == "incomplete":
                entry["outcome"] += " - duplicate check incomplete"
            for text in (warnings if row is not None else ()):
                _add_warning(row, text)
            entry["row"] = row
            ask["result"] = "exported" if row is not None else "incomplete"
            ask["outcome"] = entry["outcome"]
            by_uri[lookup.uri] = entry
            entries.append(entry)
    finally:
        close_progress()
    return requested, entries, notes


def _cell(value):
    """A stored value as CSV text, exactly: text as it is (markup and line
    breaks kept, nothing trimmed), nothing for an absent value, true/false
    for a flag, anything else as JSON - never dropped."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False)


def _unshown(level, obj, shown):
    """'level: field, field' for the fields of `obj` its row does not show."""
    if not isinstance(obj, dict):
        return []
    keys = [k for k in obj if k not in shown and k != "jsonmodel_type"]
    return [f"{level}: {', '.join(keys)}"] if keys else []


def _part_rows(add, part, p, pointer):
    """The rows for one subnote of a multipart note (see note_rows)."""
    if not isinstance(part, dict):
        add("unmapped", pointer, **{"Part #": p + 1, "Value": _cell(part)})
        return
    model = part.get("jsonmodel_type")
    cells = {"Part #": p + 1, "Part Model": _cell(model) if model is not None else "(none)",
             "Part Title": _cell(part.get("title"))}
    if model not in _PART_SHOWN:
        add("unmapped", pointer, _unshown("part", part, set()), **cells)
        return
    extra = _unshown("part", part, _PART_SHOWN[model])
    if model == "note_text":
        add("text", pointer, extra, Value=_cell(part.get("content")), **cells)
        return
    items = part.get("items")
    if items is not None and not isinstance(items, list):
        add("unmapped", f"{pointer}/items", extra, **cells)
        return
    if not items:
        add("empty list", pointer, extra, **cells)
        return
    for i, item in enumerate(items):
        at, number = f"{pointer}/items/{i}", {"Item #": i + 1}
        if model == "note_definedlist" and isinstance(item, dict):
            # label and value kept apart; the item's own extra fields named
            add("list item", at, extra + _unshown("item", item, {"label", "value"}), **cells,
                **number, Label=_cell(item.get("label")), Value=_cell(item.get("value")))
        elif model == "note_orderedlist" and isinstance(item, str):
            add("list item", at, extra, **cells, **number, Value=item)
        elif model == "note_chronology" and isinstance(item, dict):
            item_extra = extra + _unshown("item", item, {"event_date", "events"})
            label, events = _cell(item.get("event_date")), item.get("events")
            if events is not None and not isinstance(events, list):
                add("unmapped", f"{at}/events", item_extra, **cells, **number, Label=label)
            elif not events:
                add("empty item", at, item_extra, **cells, **number, Label=label)
            else:
                for e, event in enumerate(events):
                    add("event" if isinstance(event, str) else "unmapped", f"{at}/events/{e}",
                        item_extra, **cells, **number, **{"Entry #": e + 1},
                        Label=label, Value=_cell(event))
        else:
            add("unmapped", at, extra, **cells, **number, Value=_cell(item))


def note_rows(record):
    """The notes CSV rows for one record (its identity columns aside): one
    row per piece of note content, in the record's own order - each text
    subnote, each Defined List item (Label and Value apart), each ordered
    list item, each chronology event, each content string and index or
    bibliography item - plus a row for an empty note, list or chronology
    item, and an 'unmapped' row for any structure ArchivesSpace's published
    schemas don't define, so nothing is skipped unseen. Every row's JSON
    Pointer (RFC 6901, zero-based) locates its element in the record."""
    rows = []
    notes = record.get("notes")
    if notes is None:
        return rows
    if not isinstance(notes, list):
        return [{"Row Kind": "unmapped", "Value": _cell(notes), "JSON Pointer": "/notes"}]
    for n, note in enumerate(notes):
        pointer = f"/notes/{n}"
        if not isinstance(note, dict):
            rows.append({"Note #": n + 1, "Row Kind": "unmapped", "Value": _cell(note),
                         "JSON Pointer": pointer})
            continue
        model = note.get("jsonmodel_type")
        base = {"Note #": n + 1, "Note Type": _cell(note.get("type")), "Note Model": _cell(model),
                "Note Label": _cell(note.get("label")), "Note Published": _cell(note.get("publish"))}
        # an unknown model still shows its type, label and publish columns
        note_extra = _unshown("note", note, _NOTE_SHOWN.get(model, {"type", "label", "publish"}))

        def add(kind, at, extra=(), **cells):
            rows.append({**base, **cells, "Row Kind": kind,
                         "Not Shown": "; ".join(note_extra + list(extra)), "JSON Pointer": at})
        before = len(rows)
        if model not in _NOTE_SHOWN:
            add("unmapped", pointer)
        elif model == "note_multipart":
            subnotes = note.get("subnotes")
            if subnotes is not None and not isinstance(subnotes, list):
                add("unmapped", f"{pointer}/subnotes")
            for p, part in enumerate(subnotes if isinstance(subnotes, list) else []):
                _part_rows(add, part, p, f"{pointer}/subnotes/{p}")
        else:
            for field in ("content", "items"):
                values = note.get(field) if field in _NOTE_SHOWN[model] else None
                if values is None:
                    continue
                if not isinstance(values, list):
                    add("unmapped", f"{pointer}/{field}", **{"Part Model": field})
                    continue
                for i, value in enumerate(values):
                    at, cells = f"{pointer}/{field}/{i}", {"Part Model": field, "Item #": i + 1}
                    if field == "items" and model == "note_index" and isinstance(value, dict):
                        add("list item", at, _unshown("item", value, {"type", "value"}), **cells,
                            Label=_cell(value.get("type")), Value=_cell(value.get("value")))
                    elif isinstance(value, str) and not (field == "items" and model == "note_index"):
                        add("text" if field == "content" else "list item", at, **cells, Value=value)
                    else:
                        add("unmapped", at, **cells, Value=_cell(value))
        if len(rows) == before:
            add("empty note", pointer)
    return rows


def defined_list_counts(record):
    """(Defined Lists, their items) in a record's multipart notes, or None
    when its notes, subnotes or list items are not in the schemas' shape -
    the record is still kept whole in the JSON; only the count is
    unavailable."""
    notes = record.get("notes")
    if notes is None:
        return 0, 0
    if not isinstance(notes, list):
        return None
    lists = items = 0
    for note in notes:
        if not (isinstance(note, dict) and note.get("jsonmodel_type") == "note_multipart"):
            continue
        subnotes = note.get("subnotes")
        if subnotes is None:
            continue
        if not isinstance(subnotes, list):
            return None
        for part in subnotes:
            if isinstance(part, dict) and part.get("jsonmodel_type") == "note_definedlist":
                lists += 1
                entries = part.get("items")
                if entries is None:
                    continue
                if not isinstance(entries, list):
                    return None
                items += len(entries)
    return lists, items


def notes_csv_rows(entries):
    """Every entry's note rows, each with its record's identity columns;
    records each entry's row count for the JSON."""
    rows = []
    for entry in entries:
        record = entry["record"]
        ident = {"ASpace Ref ID": _cell(record.get("ref_id")), "ASpace URI": _cell(record.get("uri")),
                 col.CATALOG: _cell(record.get("component_id"))}
        own = [{**ident, **r} for r in note_rows(record)]
        entry["notes_csv_rows"] = len(own)
        rows.extend(own)
    return rows


def csv_text(fieldnames, rows, provenance):
    """A CSV as text, laid out exactly as write_export_csv writes one: the
    '# provenance' first line, the header, the rows."""
    buf = io.StringIO(newline="")
    buf.write(f"# {provenance}\n")
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def publish_new(path, text):
    """Save one package file without ever replacing anything there:
    (status, reason, leftover) - ('saved', None, leftover) or ('not saved',
    reason, leftover). `leftover` is a temporary file that could not be
    removed (None when cleanup worked); it never changes the status."""
    try:
        leftover = col.save_new_via_temp(path, lambda f: f.write(text), newline="")
    except FileExistsError as e:
        return ("not saved", "the name already exists - nothing there was changed",
                getattr(e, "leftover", None))
    except OSError as e:
        return "not saved", str(e), getattr(e, "leftover", None)
    return "saved", None, leftover


def settle_outcomes(requested, entries, files):
    """Word every record's outcome by what was really saved, once both CSVs
    have been published (the JSON, written after, carries these words). A
    record is 'exported' only when its row is in a main CSV that was saved,
    and a repeat is 'exported once' only then; otherwise the words say what
    is missing, never that something was saved. Returns the repeat notes."""
    main_saved = files["main_csv"][0] == "saved"
    notes_saved = files["notes_csv"][0] == "saved"
    entry_of = {}
    for e in entries:
        dup = (" - duplicate check incomplete"
               if e["catalog_number_check"]["status"] == "incomplete" else "")
        if e["row"] is None:
            e["outcome"] = f"incomplete - no main CSV row: {e['placement']['reason']}{dup}"
            e["main_csv_row"] = f"none - {e['placement']['reason']}"
        elif main_saved:
            e["outcome"] = f"exported{dup}"
            e["main_csv_row"] = "included"
        else:
            e["outcome"] = ("incomplete - its main CSV row was built, but the main CSV "
                            f"was not saved{dup}")
            e["main_csv_row"] = "built, but the main CSV was not saved"
        e["notes_csv"] = e.get("notes_csv_rows", 0) if notes_saved else files["notes_csv"][0]
        for value in e["requested_as"]:
            entry_of[value] = e
    notes = []
    for ask in requested:
        e = entry_of.get(ask["value"])
        if e is None:
            continue                       # not found or failed: its outcome stands
        if ask["result"] == "same record":
            ask["outcome"] = (f"same record as {ask['same_as']} - exported once"
                              if e["outcome"].startswith("exported") else
                              f"same record as {ask['same_as']} - {e['outcome']} (see above)")
            notes.append(f"{ask['value']}: {ask['outcome']}")
        else:
            ask["result"] = "exported" if e["outcome"].startswith("exported") else "incomplete"
            ask["outcome"] = e["outcome"]
    return notes


def record_package_document(requested, entries, files, paths, provenance_command):
    """The JSON: run details, requests and outcomes, file statuses - and each
    record exactly as returned, under its own 'record' key, kept apart from
    everything this tool adds."""
    def public_entry(e):
        out = {"requested_as": e["requested_as"], "requested_positions": e["requested_positions"],
               "uri": e["uri"], "outcome": e["outcome"], "placement": e["placement"],
               "catalog_number_check": e["catalog_number_check"],
               "outputs": {"main_csv_row": e["main_csv_row"], "notes_csv_rows": e["notes_csv"]}}
        if "mads_live" in e:
            out["mads_live"] = e["mads_live"]
        out["record"] = e["record"]
        return out
    summary = {"requested": len(requested),
               "records": len(entries),
               "exported": sum(1 for e in entries if e["outcome"].startswith("exported")),
               "saved_incomplete": sum(1 for e in entries if not e["outcome"].startswith("exported")),
               "not_exported": sum(1 for a in requested if a["result"] == "not exported"),
               "duplicate_check_incomplete": sum(1 for e in entries
                                                 if e["catalog_number_check"]["status"] == "incomplete")}
    return {
        "export_format": "jpc-aspace-records",
        "export_format_version": 1,
        "provenance": {"command": provenance_command, "target": aspace_client.ACTIVE_ENV,
                       "repository": f"/repositories/{aspace_client.REPO_ID}",
                       "resource": aspace_client.RESOURCE_URI,
                       "exported_at": datetime.now().astimezone().isoformat(timespec="seconds")},
        "requested": requested,
        "summary": summary,
        "files": {role: {"name": os.path.basename(paths[role]), "status": files[role][0],
                         **({"reason": files[role][1]} if files[role][1] else {}),
                         **({"leftover_temporary_file": os.path.basename(files[role][2])}
                            if files[role][2] else {})}
                  for role in ("main_csv", "notes_csv")},
        "records": [public_entry(e) for e in entries],
    }


def print_record_summary(entries, limit=20):
    """A short look at each exported record, up to `limit`."""
    print_section("RECORDS")
    for n, e in enumerate(entries[:limit], 1):
        r = e["record"]
        print(f"  {n}. {r.get('component_id') or '(no JPC_AV_xxxxx)'}  "
              f"{r.get('level') or '(no level)'}  {r.get('title') or '(no title)'}")
        placement = e["placement"]
        if placement["status"] == "placed":
            print(f"     ref ID: {r.get('ref_id') or '(none)'}   "
                  f"parent ref ID: {placement['parent_ref_id'] or '(top level)'}")
            print(f"     Path: {placement['path'] or '(top level)'}")
        else:
            print(f"     ref ID: {r.get('ref_id') or '(none)'}")
            print(f"     Not placed: {placement['reason']}")
        counts = defined_list_counts(r)
        if counts is None:
            print("     Notes: not in the expected shape - kept as returned in the JSON")
        else:
            lists, items = counts
            notes = r.get("notes") or []
            print(f"     Notes: {len(notes)} (Defined Lists: {lists}, "
                  f"{items} item{'' if items == 1 else 's'})")
    if len(entries) > limit:
        print(f"  ... and {len(entries) - limit} more - see the files")


def run_record_export(named, paths, source, mads_live=False):
    """--record end to end. Returns the exit code: 0 when every named record
    was exported, every check was complete and all three files were saved;
    2 when the package was saved but something named is missing or
    incomplete (or a MADS check failed); 1 when logging in failed or any
    package file was not generated or not saved."""
    print_run_header("Export named records in full from ArchivesSpace (read-only)", target=source,
                     input=f"{len(named)} record(s) named with --record: "
                           f"{', '.join(v for _, v, _ in named)}",
                     mode="read ArchivesSpace, save a record package (JSON and two CSVs)")
    try:
        col.ensure_parent(paths["json"])   # values and -o accepted: the folder, before login
    except OSError as e:
        print_status("error", f"Could not create the output folder: {e} - nothing was written")
        return 1
    client = ASpaceClient()
    print_status("info", f"Connecting to {aspace_client.ASPACE_URL}...")
    if not client.login():
        print_status("error", f"Could not log in: {client.login_problem}")
        return 1
    print_status("success", "Authenticated")
    try:
        print_status("info", f"Looking up {len(named)} record(s) named with --record...")
        requested, entries, notes = export_by_record(client, named)
    finally:
        client.logout()

    rows = [e["row"] for e in entries if e["row"] is not None]
    extra_headers = ["MADS live"] if mads_live else []
    mads_incomplete = 0
    if mads_live and rows:
        mads_incomplete = mark_mads_live(rows)
        for e in entries:
            if e["row"] is not None:
                e["mads_live"] = e["row"]["MADS live"]

    # Each CSV is built and published on its own; the JSON is attempted
    # last, always, so it can say what really happened to each CSV. Its
    # existence means the JSON was saved - not that everything was.
    provenance = (f"{RUN_COMMAND} | target: {aspace_client.ACTIVE_ENV} | "
                  f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    files = {}
    for role, build in (("main_csv", lambda: csv_text(export_fieldnames(extra_headers), rows,
                                                      provenance)),
                        ("notes_csv", lambda: csv_text(NOTES_COLUMNS, notes_csv_rows(entries),
                                                       provenance))):
        try:
            text = build()
        except Exception as e:   # noqa: BLE001 - that CSV is lost, never the JSON
            files[role] = ("not generated", f"{type(e).__name__} while building it", None)
            continue
        files[role] = publish_new(paths[role], text)
    # Outcomes are worded only now, from what the CSVs really did; every
    # claim below about the JSON waits for the JSON's own result.
    notes = settle_outcomes(requested, entries, files)
    try:
        text = json.dumps(record_package_document(requested, entries, files, paths, RUN_COMMAND),
                          ensure_ascii=False, indent=2) + "\n"
    except Exception as e:       # noqa: BLE001
        files["json"] = ("not generated", f"{type(e).__name__} while building it", None)
    else:
        files["json"] = publish_new(paths["json"], text)
    complete = all(files[role][0] == "saved" for role, _ in PACKAGE_ROLES)
    json_saved = files["json"][0] == "saved"

    unplaced = [e for e in entries if e["row"] is None]
    not_exported = [a for a in requested if a["result"] == "not exported"]
    dup_incomplete = sum(1 for e in entries if e["catalog_number_check"]["status"] == "incomplete")
    if complete:
        print_result([("Exported", len(rows), "ok", True),
                      ("Saved, incomplete (in the JSON, no main CSV row)", len(unplaced),
                       "attention"),
                      ("Not item-level (for reference, not re-import)",
                       sum(1 for r in rows if r.get("Level") != "item"), "neutral"),
                      ("With warnings", sum(1 for r in rows if _row_warnings(r)), "attention"),
                      ("Duplicate check incomplete", dup_incomplete, "unknown"),
                      ("Not exported", len(not_exported), "bad"),
                      ("MADS checks failed or invalid", mads_incomplete, "unknown")])
        print_row_warnings(rows)
        if entries:
            print_record_summary(entries)
    for line in notes:
        print_status("info", line)
    if unplaced:
        print()
        print_status("warning", f"{len(unplaced)} record(s) " + (
            "saved in the JSON with no main CSV row:" if json_saved else
            "with no main CSV row - their full records were for the JSON, which was NOT saved:"))
        for e in unplaced:
            print_status("warning", f"{e['requested_as'][0]}: {e['placement']['reason']}", indent=1)
    if not_exported:
        print()
        print_status("error", f"{len(not_exported)} record(s) named with --record could NOT be "
                              f"exported:")
        for ask in not_exported:
            print_status("error", f"{ask['value']}: {ask['outcome']}", indent=1)
    print_saved([(label, paths[role]) for role, label in PACKAGE_ROLES if files[role][0] == "saved"],
                failed=[(label, paths[role]) for role, label in PACKAGE_ROLES
                        if files[role][0] != "saved"])
    for role, label in PACKAGE_ROLES:
        if files[role][0] != "saved":
            print_status("error", f"{label} {files[role][0]}: {files[role][1]}")
        if files[role][2]:
            # best-effort cleanup failed: the outcome above stands, the leftover is named
            print_status("warning", f"{label}: its temporary file could not be removed - "
                                    f"delete it by hand: {files[role][2]}")
    if not complete:
        kept = [label for role, label in PACKAGE_ROLES if files[role][0] == "saved"]
        where = (" (kept; the JSON's 'files' says what happened to each CSV)" if json_saved
                 else " (kept; the JSON was NOT saved)")
        print_status("error", "record package NOT complete - "
                              + (f"saved: {', '.join(kept)}{where}" if kept else "nothing was saved")
                              + "; run again with a new -o, or let it choose new names")
        print()
        return 1
    print()
    return 2 if (not_exported or unplaced or dup_incomplete or mads_incomplete) else 0


CHECK_OPTIONS = [
    ("--check FILE", "", "Which of these catalog numbers ArchivesSpace has (text list or any CSV with"),
    ("", "", "CATALOG_NUMBER). Given an Airtable pull, also compares its ASpace Parent RefID and"),
    ("", "", "Item Record Created with ArchivesSpace. Screen only unless -o is given."),
]
SELECT_OPTIONS = [
    ("--level LEVEL", "", "Only records at this level: item (default), file, subseries, series... or all"),
    ("--parent REFID", "", "Only the direct children of this record (combines with --level)"),
    ("--list FILE", "", "Exactly these catalog numbers (text, one per line, or a CSV with CATALOG_NUMBER); list order kept"),
    ("--record VALUE", "", "Exactly this record, at any level: a full"),
    ("", "", "JPC_AV_xxxxx or its ref ID (case kept)."),
    ("", "", "Repeat for more; the order given is kept."),
    ("", "", "Saves the record package (see OUTPUT)."),
    ("", "", "Not with --list, --parent or --level"),
]
FILL_OPTIONS = [
    ("--fill-parents FILE", "", "Fill blank ASpace Parent RefID cells from EJS Episode + ASpace File Type"),
    ("", "", "(keep EJS Episode filled - a blank cell falls back to the title, which must then follow the pattern)"),
    ("", "", "Writes jpc-fill_FILE_parent_ref-id_ready_for_ASpace_import.csv"),
    ("", "", "and jpc-fill_FILE_needs_human_review.csv beside FILE (FILE's name without .csv);"),
    ("", "", "never overwrites either - FILE itself is left untouched"),
]
EXPORT_CLI_OPTIONS = [
    ("--mads-live", "", "Add a MADS live column: Yes / No / check failed / invalid catalog number"),
    ("-o, --output PATH", "", "Export CSV path (default: timestamped file in the reports folder)"),
    ("", "", "With --record: -o FILE.json names the"),
    ("", "", "package's JSON; its CSVs are saved beside"),
    ("", "", "it as FILE.csv and FILE_notes.csv"),
    ("--env NAME", "", "Target environment from creds.py (required when several are configured)"),
    ("--no-color", "", "Disable colored output"),
]


HELP_TITLE = "Read ArchivesSpace: export, check, fill parents (read-only)"


def get_colored_help():
    """The -h screen, in the shared layout. One umbrella title: each run
    names its own mode in its heading."""
    C = Colors
    return help_screen(HELP_TITLE, [
        ("DESCRIPTION", f"""    Reads AV records from ArchivesSpace - never writes to it:
    {C.GREEN}1.{C.RESET} Exports records to an import-shaped CSV with Level, Depth and Path,
       in tree order (--list and --record: the order given)
    {C.GREEN}2.{C.RESET} Checks which catalog numbers are already in ArchivesSpace (--check)
    {C.GREEN}3.{C.RESET} Fills a sheet's blank ASpace Parent RefID column (--fill-parents)
    {C.GREEN}4.{C.RESET} Checks whether exported records are live in MADS (--mads-live)
    {C.GREEN}5.{C.RESET} Saves named records in full (--record): the JSON plus two CSVs"""),
        ("USAGE", f"""    {C.GREEN}${C.RESET} python3 data_import_export/aspace_csv_export.py [--level LEVEL] [--parent REFID] [options]
    {C.GREEN}${C.RESET} python3 data_import_export/aspace_csv_export.py --list FILE [options]
    {C.GREEN}${C.RESET} python3 data_import_export/aspace_csv_export.py --record VALUE [--record VALUE ...] [options]
    {C.GREEN}${C.RESET} python3 data_import_export/aspace_csv_export.py --check FILE [-o PATH] [--env NAME]
    {C.GREEN}${C.RESET} python3 data_import_export/aspace_csv_export.py --fill-parents FILE [--env NAME]"""),
        ("OPTIONS", render_options(EXPORT_CLI_OPTIONS)),
        ("CHECK", "instead of an export", render_options(CHECK_OPTIONS)),
        ("SELECT", "what to export; default: every item-level record", render_options(SELECT_OPTIONS)),
        ("FILL PARENTS", "instead of an export", render_options(FILL_OPTIONS)),
        ("EXAMPLES", f"""    {C.GREEN}${C.RESET} python3 data_import_export/aspace_csv_export.py --level all --env production
    {C.GREEN}${C.RESET} python3 data_import_export/aspace_csv_export.py --list batch.csv --env production
    {C.GREEN}${C.RESET} python3 data_import_export/aspace_csv_export.py --record JPC_AV_00000 --env production
    {C.GREEN}${C.RESET} python3 data_import_export/aspace_csv_export.py --check batch.csv --env production
    {C.GREEN}${C.RESET} python3 data_import_export/aspace_csv_export.py --fill-parents batch.csv --env production"""),
        ("OUTPUT", f"""    Exports: {C.CYAN}{OUTPUT_DIR}/{C.RESET} (or -o)
    --fill-parents: two CSVs beside FILE, using its name without .csv:
      jpc-fill_FILE_parent_ref-id_ready_for_ASpace_import.csv
      jpc-fill_FILE_needs_human_review.csv
    --check: on screen only (a CSV too with -o)
    --record: three files in the reports folder, never replacing an
    existing file:
      aspace_records_ENV_STAMP.json       the complete records, as returned
      aspace_records_ENV_STAMP.csv        the usual export columns
      aspace_records_ENV_STAMP_notes.csv  notes and Defined List items
    or, with -o FILE.json: FILE.json, FILE.csv and FILE_notes.csv
    {C.DIM}The reports folder can be changed by setting logs_dir in creds.py{C.RESET}"""),
        ("EXIT", f"""    {C.GREEN}0{C.RESET}  done
    {C.YELLOW}2{C.RESET}  written but incomplete: rows for review (--fill-parents, expected), listed numbers
       not found, or MADS checks failed; --record: a value not exported, a
       record saved incomplete or a duplicate check incomplete; --check:
       something needs review (Airtable disagrees or is incomplete, not an item,
       ambiguous) or could not be checked - numbers simply not found are exit 0;
       also a bad argument or a creds.py problem - then nothing is written
    {C.RED}1{C.RESET}  failed - nothing written (a fill whose ready file fails after its review file
       was written says so, and names the review file to delete); --check -o: the
       check ran but its report could not be saved; --record: a package file
       was not generated or not saved (the screen names those that were saved)"""),
    ])


def build_parser():
    """The exporter's command-line parser, in the shared style: its own -h
    screen, and on a mistake the usage lines plus the option list."""
    parser = styled_parser(["[--level LEVEL] [--parent REFID] [options]",
                            "--list FILE [options]",
                            "--record VALUE [--record VALUE ...] [options]",
                            "--check FILE [-o PATH] [--env NAME]",
                            "--fill-parents FILE [--env NAME]"],
                           get_colored_help,
                           [CHECK_OPTIONS, SELECT_OPTIONS, FILL_OPTIONS, EXPORT_CLI_OPTIONS],
                           hide_values=True)   # an argument error never repeats what was typed
    parser.add_argument("--level", default="item", choices=LEVELS, metavar="LEVEL",
                        help=argparse.SUPPRESS)
    parser.add_argument("--parent", metavar="REFID", help=argparse.SUPPRESS)
    parser.add_argument("--list", metavar="FILE", dest="list_file", help=argparse.SUPPRESS)
    parser.add_argument("--record", action="append", metavar="VALUE", dest="records",
                        help=argparse.SUPPRESS)
    parser.add_argument("--check", metavar="FILE", dest="check_file", help=argparse.SUPPRESS)
    parser.add_argument("--fill-parents", metavar="FILE", dest="fill_file", help=argparse.SUPPRESS)
    parser.add_argument("--mads-live", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-o", "--output", metavar="PATH", help=argparse.SUPPRESS)
    parser.add_argument("--env", metavar="NAME", help=argparse.SUPPRESS)
    parser.add_argument("--no-color", action="store_true", help=argparse.SUPPRESS)
    return parser


def main():
    aspace_client.console_logging()  # labelled detail, not a bare ERROR:root line
    parser = build_parser()
    args = parser.parse_args()
    if args.no_color:
        Colors.disable()

    if args.list_file and args.parent:
        parser.error("--list names the exact records to export - it cannot "
                     "be combined with --parent")
    if args.records and (args.list_file or args.parent or args.level != "item"):
        parser.error("--record names the exact records to export - it cannot be "
                     "combined with --list, --parent or --level")
    if args.fill_file and (args.list_file or args.records or args.parent or args.mads_live
                           or args.level != "item"):
        parser.error("--fill-parents fills a sheet's parent column - it cannot be "
                     "combined with --list, --record, --parent, --level or --mads-live")
    if args.check_file and (args.list_file or args.records or args.fill_file or args.parent
                            or args.mads_live or args.level != "item"):
        parser.error("--check only looks catalog numbers up - it cannot be combined "
                     "with --list, --record, --fill-parents, --parent, --level or --mads-live")
    if args.fill_file and args.output:
        parser.error("--fill-parents always writes its ready and human-review CSVs "
                     "beside FILE - -o does not apply")
    named = None
    if args.records:
        # Every value is classified before anything else happens: a reserved
        # or malformed one refuses the run before login, folders or files.
        named, problem = classify_record_values(args.records)
        if problem:
            parser.error(problem)
        if args.output and not usable_package_json_path(args.output):
            parser.error("with --record, -o FILE.json names the record package's JSON "
                         "file - it must end in .json (its CSVs are saved beside it as "
                         "FILE.csv and FILE_notes.csv); what was typed is not shown")

    # Environment selection: same contract as every other tool - auto with
    # one configured, explicit --env with several, no default.
    if args.env:
        try:
            aspace_client.select_environment(args.env)
        except ValueError as e:
            parser.error(str(e))
    elif aspace_client.ACTIVE_ENV is None:
        if len(aspace_client.ENVIRONMENTS) > 1:
            parser.error(f"multiple environments configured "
                         f"({', '.join(sorted(aspace_client.ENVIRONMENTS))}) - "
                         f"pass --env NAME to choose the target")
        parser.error(aspace_client.CONFIG_ERROR
                     or "no environments configured in creds.py (see creds_template.py)")

    stamp = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    package_paths = None
    if args.records:
        # The package's three names are checked now, before login, as fill
        # checks its pair; publication itself never replaces a file either,
        # so a name taken while the run is reading is still never overwritten.
        package_paths = record_package_paths(args.output or os.path.join(
            OUTPUT_DIR, f"aspace_records_{aspace_client.ACTIVE_ENV}_{stamp}.json"))
        existing = [p for p in package_paths.values() if os.path.lexists(p)]  # a dangling link too
        if existing:
            parser.error(f"{' and '.join(existing)} already exist(s) - move or rename them, "
                         f"or choose another -o (nothing was written)")
        out_path = None
    elif args.fill_file:
        # Both handoff files sit beside the pulled sheet and are never
        # overwritten: if either exists, nothing is written at all.
        fill_paths = fill_output_paths(args.fill_file)
        existing = [p for p in fill_paths if os.path.lexists(p)]  # a dangling symlink too
        if existing:
            parser.error(f"{' and '.join(existing)} already exist(s) - move or rename "
                         f"before filling again (nothing was written)")
        for path in fill_paths:
            problem = clobber_problem(args.fill_file, path)
            if problem:
                parser.error(problem)
        out_path = None
    elif args.check_file and not args.output:
        out_path = None  # screen only: no path, no reports folder touched
    else:
        default_name = f"aspace_export_{aspace_client.ACTIVE_ENV}_{stamp}.csv"
        # A --list or --check input is read first: its folder is created
        # only once that input is usable, so a refused one leaves none behind.
        out_path = col.resolve_output_path(args.output, OUTPUT_DIR, default_name,
                                           create=not (args.list_file or args.check_file))

    for input_file in (args.list_file, args.check_file):
        if input_file and (args.output or not args.check_file):
            problem = clobber_problem(input_file, out_path)
            if problem:
                parser.error(problem)  # before any network work

    source = (f"{aspace_client.ACTIVE_ENV.upper()} ({aspace_client.ASPACE_URL}, "
              f"repo {aspace_client.REPO_ID}, resource {aspace_client.RESOURCE_ID}) - read-only")
    if args.records:
        # its own branch: never the whole-resource export below
        sys.exit(run_record_export(named, package_paths, source, args.mads_live))
    if args.fill_file:
        print_run_header("Fill parents from ArchivesSpace (read-only)", target=source,
                         input=args.fill_file,
                         mode="read ArchivesSpace, save ready and review CSVs beside the input")
        sys.exit(run_fill_parents(args.fill_file, *fill_paths))
    if args.check_file:
        sys.exit(run_check(args.check_file, out_path if args.output else None, source))
    selection = (args.list_file if args.list_file else
                 f"level {args.level}" + (f", children of {args.parent}" if args.parent else ""))
    print_run_header("Export ArchivesSpace records to CSV (read-only)", target=source,
                     input=selection, mode="read ArchivesSpace, save a CSV")
    if args.list_file:
        numbers, problem = read_catalog_list(args.list_file)  # before any network work
        if numbers is None:
            print_status("error", problem)
            sys.exit(1)
        col.ensure_parent(out_path)  # the list is usable: its output folder, before login

    client = ASpaceClient()
    print_status("info", f"Connecting to {aspace_client.ASPACE_URL}...")
    if not client.login():
        print_status("error", f"Could not log in: {client.login_problem}")
        sys.exit(1)
    print_status("success", "Authenticated")

    problems = []
    anomalies = 0
    try:
        if args.list_file:
            print_status("info", f"Looking up {len(numbers)} listed catalog number(s)...")
            rows, problems = export_by_list(client, numbers)
        else:
            rows, anomalies = export_records(client, args.level, args.parent)
    finally:
        client.logout()

    if rows is None:
        print_status("error", f"Export failed: {anomalies}")
        sys.exit(1)

    extra_headers = ["MADS live"] if args.mads_live else []  # column present even when empty
    mads_incomplete = 0
    if args.mads_live and rows:
        mads_incomplete = mark_mads_live(rows)

    provenance = (f"{RUN_COMMAND} | target: {aspace_client.ACTIVE_ENV} | "
                  f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    write_export_csv(rows, out_path, extra_headers, provenance)
    non_items = sum(1 for r in rows if r.get("Level") != "item")
    flagged = sum(1 for r in rows if _row_warnings(r))
    print_result([("Exported", len(rows), "ok", True),
                  ("Not item-level (for reference, not re-import)", non_items, "neutral"),
                  ("With warnings", flagged, "attention"),
                  ("Skipped: stale search-index entries", anomalies, "attention"),
                  ("Could not be exported", len(problems), "bad"),
                  ("MADS checks failed or invalid", mads_incomplete, "unknown")])
    print_row_warnings(rows)
    if anomalies:
        print()
        print_status("warning", f"{anomalies} record(s) skipped: the search index "
                                f"listed them but the fetched record is not in the "
                                f"configured resource (stale index entry)")
    if problems:
        print()
        print_status("error", f"{len(problems)} listed number(s) could NOT be exported:")
        for problem in problems:
            print_status("error", problem, indent=1)
    print_saved([("export CSV", out_path)])
    print()
    if problems:
        sys.exit(2)  # the file is complete for what was found; the gaps are named
    if mads_incomplete:
        sys.exit(2)  # same signal as check_mads.py: the file is accurate but not complete


if __name__ == "__main__":
    main()
