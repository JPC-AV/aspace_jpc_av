#!/usr/bin/env python3
"""ArchivesSpace CSV Export - the reverse of the importer.

Pulls every archival object in the configured AV resource and writes a CSV
shaped EXACTLY like the import sheet (same column headers, from
csv_columns.py), plus audit columns from ArchivesSpace. That makes the round
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

Selection: everything at a level (--level, default item), one series'
children (--parent), or an explicit list of catalog numbers (--list FILE,
plain text one-per-line or any CSV with a CATALOG_NUMBER column).

Read-only: this script makes no ArchivesSpace writes (its only output is
the CSV file).
"""

import argparse
import csv
import logging
import re
import os
import sys
from datetime import datetime
from pathlib import Path

import csv_columns as col  # single source of truth for CSV header names

# Add parent directory to path for the shared client and creds.py import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aspace_client
from aspace_client import ASpaceClient

# Reuse the importer's console helpers and note-reading logic so the export
# shows values the same way an update run would compare them.
from aspace_csv_import import (Colors, print_status, print_header,
                               get_note_content, staff_link_for, RUN_COMMAND,
                               parse_date)

# Batch size for id_set fetches - one API call per BATCH records instead of
# one call per record, which is the difference between minutes and an hour
# over the VPN. Kept well under ArchivesSpace's page-size ceiling (250).
BATCH = 50

# Warning text for non-item rows (in the Warnings cell of every export path;
# the console counts these once rather than listing every structural node).
NON_ITEM_NOTE = "not item - --update-only will refuse to change it"

# Archival-object levels ArchivesSpace defines, plus "all". A misspelled
# --level must be an error, not a successful empty export.
LEVELS = ["all", "class", "collection", "file", "fonds", "item", "otherlevel",
          "recordgrp", "series", "subfonds", "subgrp", "subseries"]

# Column order of the export file: identity and status first, then the
# import-shaped metadata, then links and audit trail. "MADS live" appears
# only when --mads-live was given. Order is cosmetic for round-trips - every
# reader in the toolset matches columns by header name.
EXPORT_COLUMNS = [
    col.CATALOG, "ASpace Ref ID", "Warnings", "MADS live",
    col.PARENT_REFID, col.TITLE, col.CREATION_DATE, col.EDIT_DATE,
    col.BROADCAST_DATE, col.ORIGINAL_FORMAT, col.DESCRIPTION, col.PHYSTECH,
    "ASpace URI", "ASpace Staff Link", "MADS URL",
    "Created By", "Create Time", "Last Modified By", "Last Modified Time",
]
OPTIONAL_EXPORT_COLUMNS = {"MADS live"}
# Stay-in-sync guard (csv_columns owns both lists): every required import
# column is exported, every extra column is a declared audit column, and no
# column appears twice - so a future edit to either side fails at import time.
assert len(EXPORT_COLUMNS) == len(set(EXPORT_COLUMNS)), "EXPORT_COLUMNS has a duplicate"
assert set(col.REQUIRED_COLUMNS) <= set(EXPORT_COLUMNS), \
    "EXPORT_COLUMNS is missing a required import column"
assert set(EXPORT_COLUMNS) - set(col.REQUIRED_COLUMNS) == set(col.EXPORT_AUDIT_COLUMNS), \
    "EXPORT_COLUMNS and csv_columns.EXPORT_AUDIT_COLUMNS have drifted"

# Public MADS URL for a catalog number (DAMS ingest auto-publishes to MADS,
# so this is where the item WILL be public - the URL is derived, not checked;
# --mads-live actually checks). check_mads owns the URL scheme and the check.
from check_mads import MADS_URL_PREFIX, check_many, summarize, clobber_problem  # noqa: E402

# Import optional logs_dir (same convention as the importer)
try:
    from creds import logs_dir
except ImportError:
    logs_dir = ""
# A custom logs_dir gets a per-script subfolder (matching the importer/rename
# convention) so the tools sharing one creds setting don't interleave files.
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/aspace_import_reports")
OUTPUT_DIR = os.path.join(logs_dir, "export_reports") if logs_dir else DEFAULT_OUTPUT_DIR


def build_row(record, parent_refid):
    """Map one archival object record to an import-shaped CSV row.

    Returns (row_dict, warnings) where warnings lists the structures the
    importer would refuse to edit on this record, plus metadata gaps worth
    fixing: no component ID (the record is unreachable by anything keyed on
    catalog number), no title, no dates.
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
    if level != "item":
        warnings.append(f"level is {level or 'missing'}, {NON_ITEM_NOTE}")
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
            warnings.append(f"{len(matching)} '{label}' dates")
        elif matching and (matching[0].get("end")
                           or matching[0].get("date_type") != "single"):
            # a range (or a non-single/untyped date): a one-value CSV cell
            # cannot express it, so --update-only will refuse to change it
            shape = ("with an end date" if matching[0].get("end")
                     else f"date_type {matching[0].get('date_type') or 'missing'}")
            warnings.append(f"'{label}' date is {shape} - --update-only will refuse to change it")

    extents = record.get("extents") or []
    row[col.ORIGINAL_FORMAT] = (extents[0].get("extent_type") or "") if extents else ""
    if len(extents) > 1:
        warnings.append(f"{len(extents)} extents")

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
    row["_level"] = level  # for console notes only; never written (not an export column)
    return row, warnings


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
            logging.error(f"id_set batch mismatch: asked for {sorted(wanted)}, got {got}")
            return None
        records.extend(result)
        print_status("info", f"Fetched {min(start + BATCH, len(ids))}/{len(ids)} records...")
    return records


def parent_refid_for(client, parent_uri, cache):
    """ref_id of a parent record, fetched once per distinct parent.

    Returns "" for a record with no parent, and None when a linked parent
    could not be read (failed or malformed response) - callers treat None
    as a failure, never as "no parent": a blank in the sheet would be
    indistinguishable from a root record."""
    if not parent_uri:
        return ""
    if parent_uri not in cache:
        parent = client.get(parent_uri)
        if not isinstance(parent, dict) or parent.get("uri") != parent_uri:
            logging.error(f"Could not read linked parent {parent_uri}")
            cache[parent_uri] = None
        else:
            ref_id = parent.get("ref_id")
            if not isinstance(ref_id, str) or not ref_id:
                # a real linked parent always has one - anything else is a
                # malformed read, never "no parent"
                logging.error(f"Linked parent {parent_uri} has no usable ref_id")
                cache[parent_uri] = None
            else:
                cache[parent_uri] = ref_id
    return cache[parent_uri]


def read_catalog_list(path):
    """Catalog numbers from a list file, order kept, duplicates dropped.

    Two shapes are accepted: plain text (one JPC_AV_xxxxx per line, blanks
    ignored) or a CSV with a CATALOG_NUMBER column - so an old import sheet
    or report can be fed straight back in. Returns (numbers, problem).
    """
    try:
        with col.open_csv(path) as f:
            pos = f.tell()
            headers = csv.DictReader(f, strict=True).fieldnames or []
            f.seek(pos)
            if col.CATALOG in headers:
                # CSV-shaped: the exact header must be present once - two
                # CATALOG_NUMBER columns would silently select the last.
                duplicates = col.duplicate_headers(headers)
                if duplicates:
                    return None, (f"{path}: duplicate column header(s): "
                                  f"{'; '.join(duplicates)} - remove the stale duplicate(s)")
                numbers = []
                for row_num, r in enumerate(csv.DictReader(f, strict=True), 1):
                    overflow = col.overflow_problem(r, row_num)
                    if overflow:
                        return None, f"{path}: {overflow}"
                    numbers.append((r.get(col.CATALOG) or '').strip())
            else:
                numbers = [line.strip().strip(',') for line in f
                           if not line.startswith('#')]
    except UnicodeDecodeError as e:
        return None, (f"could not read {path}: not UTF-8 text (byte {e.start}: {e.reason}) "
                      f"- save the file as UTF-8 CSV")
    except csv.Error as e:
        return None, f"could not parse {path} as CSV: {e}"
    except OSError as e:
        return None, f"could not read {path}: {e}"
    seen = set()
    ordered = []
    for n in numbers:
        if n and n not in seen:
            seen.add(n)
            ordered.append(n)
    if not ordered:
        return None, f"no catalog numbers found in {path}"
    return ordered, None


def export_by_list(client, catalog_numbers):
    """Export exactly the listed catalog numbers, in list order.

    Each number goes through the importer's verified lookup, so a number
    that is missing, ambiguous, or unsearchable is reported by name instead
    of silently absent from the output. Returns (rows, problems).
    """
    rows = []
    problems = []
    parent_cache = {}
    for i, number in enumerate(catalog_numbers, 1):
        if not col.valid_catalog_number(number):
            problems.append(f"{number}: malformed catalog number (must be JPC_AV_ + digits) "
                            f"- not looked up")
            continue
        lookup = client.find_archival_object(number)
        if lookup.status == "found":
            record = lookup.record
            problem = record_shape_problem(record)
            if problem:
                problems.append(f"{number}: malformed record ({problem}) - retry later")
                continue
            parent_uri = record["parent"]["ref"] if record.get("parent") else ""
            parent_refid = parent_refid_for(client, parent_uri, parent_cache)
            if parent_refid is None:
                problems.append(f"{number}: its parent {parent_uri} could not be read - retry later")
                continue
            row, _ = build_row(record, parent_refid)  # non-item rows are flagged by build_row
            rows.append(row)
        elif lookup.status == "none":
            problems.append(f"{number}: not found in the resource")
        elif lookup.status == "multiple":
            problems.append(f"{number}: {lookup.count} records share this number")
        else:
            problems.append(f"{number}: lookup failed - retry later")
        if i % 25 == 0:
            print_status("info", f"Looked up {i}/{len(catalog_numbers)}...")
    return rows, problems


def export_records(client, level, parent_filter_refid=None):
    """Pull, filter, and map every matching record.

    Returns (rows, anomalies) or (None, reason) on failure. anomalies counts
    fetched records that don't belong to the configured resource - the guard
    against stale search-index hits (the index, not the tree, is the
    enumeration source; an index claim is verified against the record).
    """
    ids = list_resource_records(client)
    if ids is None:
        return None, "could not enumerate the resource's records"
    print_status("info", f"{len(ids)} record(s) in the resource - "
                         f"fetching in batches of {BATCH}...")

    records = fetch_records(client, ids)
    if records is None:
        return None, "a batch fetch failed - no partial export was written"

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
    parent_cache = {}
    # Shape first: a record missing the fields the filters read is malformed
    # and fails the export - it must not be silently dropped (no level),
    # misread as a stale hit (no resource), or crash (parent). In the same
    # pass, count component IDs across EVERY well-formed in-resource record
    # at every level - the importer's duplicate check spans the whole
    # resource, so a selected row must be flagged even when the other holder
    # is a series or lives under another parent.
    id_counts = {}
    for record in records:
        problem = record_shape_problem(record)
        if problem:
            return None, (f"malformed record {record.get('uri')!r} ({problem}) "
                          f"- no partial export was written")
        if record["resource"]["ref"] == aspace_client.RESOURCE_URI and record.get("component_id"):
            id_counts[record["component_id"]] = id_counts.get(record["component_id"], 0) + 1
    for record in records:
        if record["resource"]["ref"] != aspace_client.RESOURCE_URI:
            anomalies += 1  # stale index hit: a well-formed record no longer in the resource
            continue
        if level != "all" and record["level"] != level:
            continue
        parent_uri = record["parent"]["ref"] if record.get("parent") else ""
        if parent_filter_uri and parent_uri != parent_filter_uri:
            continue
        parent_refid = parent_refid_for(client, parent_uri, parent_cache)
        if parent_refid is None:
            return None, (f"linked parent {parent_uri} of "
                          f"{record.get('component_id') or record.get('uri')} could not be "
                          f"read - no partial export was written")
        row, _ = build_row(record, parent_refid)
        rows.append(row)
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
                  "last_modified_by", "user_mtime"):
        value = record.get(field)
        if value is not None and not isinstance(value, str):
            return field
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


def write_export_csv(rows, path, extra_headers=(), provenance=None):
    """Write the export atomically - the final path only ever holds a
    complete file (a .tmp is never mistakable for a finished export).

    `provenance` (the command that made the file, plus target/time) is
    written as a raw '# ...' first line so the sheet explains its own
    origin; every tool's CSV reader skips '#' lines (col.open_csv)."""
    fieldnames = [c for c in EXPORT_COLUMNS
                  if c not in OPTIONAL_EXPORT_COLUMNS or c in extra_headers]
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        if provenance:
            f.write(f"# {provenance}\n")
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, path)


def main():
    parser = argparse.ArgumentParser(
        description="Export the AV resource's archival objects to an "
                    "import-shaped CSV (round-trip with --update-only).")
    parser.add_argument("--level", default="item", choices=LEVELS, metavar="LEVEL",
                        help="Only records at this level (default: item; "
                             f"'all' for every level; one of: {', '.join(LEVELS)})")
    parser.add_argument("--parent", metavar="REFID",
                        help="Only direct children of this parent ref_id")
    parser.add_argument("--list", metavar="FILE", dest="list_file",
                        help="Export exactly these catalog numbers: plain "
                             "text one per line, or any CSV with a "
                             "CATALOG_NUMBER column (--level/--parent do "
                             "not apply)")
    parser.add_argument("--mads-live", action="store_true",
                        help="Check each record's public MADS URL and add a "
                             "'MADS live' column (Yes / No / check failed / "
                             "invalid catalog number)")
    parser.add_argument("-o", "--output", metavar="PATH",
                        help="Output CSV path (default: timestamped file "
                             f"in {OUTPUT_DIR})")
    parser.add_argument("--env", metavar="NAME",
                        help="Target environment from creds.py (required "
                             "when several are configured)")
    args = parser.parse_args()

    if args.list_file and args.parent:
        parser.error("--list names the exact records to export - it cannot "
                     "be combined with --parent")

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
    out_path = col.resolve_output_path(
        args.output, OUTPUT_DIR, f"aspace_export_{aspace_client.ACTIVE_ENV}_{stamp}.csv")

    if args.list_file:
        problem = clobber_problem(args.list_file, out_path)
        if problem:
            parser.error(problem)  # before any network work

    print_header("ArchivesSpace CSV Export")
    target = (f"{aspace_client.ACTIVE_ENV.upper()} ({aspace_client.ASPACE_URL}, "
              f"repo {aspace_client.REPO_ID}, resource {aspace_client.RESOURCE_ID})")
    # Production gets the loud color, same convention as the importer.
    target_color = Colors.RED if aspace_client.ACTIVE_ENV == 'production' else Colors.GREEN
    print(f"  Target: {target_color}{Colors.BOLD}{target}{Colors.RESET}")
    print(f"  Command: {RUN_COMMAND}")
    if args.list_file:
        print(f"  List: {args.list_file}")
    else:
        print(f"  Level: {args.level}" + (f"  Parent: {args.parent}" if args.parent else ""))

    client = ASpaceClient()
    print_status("info", f"Connecting to {aspace_client.ASPACE_URL}...")
    if not client.login():
        print_status("error", "Authentication failed")
        sys.exit(1)
    print_status("success", "Authenticated")

    problems = []
    anomalies = 0
    try:
        if args.list_file:
            numbers, problem = read_catalog_list(args.list_file)
            if numbers is None:
                print_status("error", problem)
                sys.exit(1)
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
            mads_incomplete = check_failed
            print_status("warning", f"{check_failed} MADS check(s) failed or had an invalid "
                                    f"catalog number - 'check failed' is not proof of absence; "
                                    f"re-run --mads-live for those")

    provenance = (f"{RUN_COMMAND} | target: {aspace_client.ACTIVE_ENV} | "
                  f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    write_export_csv(rows, out_path, extra_headers, provenance)
    non_items = sum(1 for r in rows if r.get("_level") not in (None, "item"))
    def _other_warnings(r):
        return [w for w in r.get("Warnings", "").split("; ") if w and NON_ITEM_NOTE not in w]
    flagged = sum(1 for r in rows if _other_warnings(r))
    print_status("success", f"Exported {len(rows)} record(s) to: {out_path}")
    if non_items:
        print_status("info", f"{non_items} of those are not item-level records - "
                             f"--update-only edits items only, so those rows are for "
                             f"reference, not re-import")
    if flagged:
        print_status("warning", f"{flagged} record(s) have Warnings - metadata gaps "
                                f"(no component ID/title/date) or structures "
                                f"--update-only will refuse to edit:")
        for r in rows:
            others = _other_warnings(r)
            if others:  # the non-item note is in the file; the console counts it once above
                label = r.get(col.CATALOG) or f"(no catalog number) {r.get(col.TITLE) or '(no title)'}"
                print_status("warning", f"{label}: {'; '.join(others)}", indent=1)
                if r.get("ASpace Staff Link"):
                    print(f"       {Colors.DIM}{r['ASpace Staff Link']}{Colors.RESET}")
    if anomalies:
        print_status("warning", f"{anomalies} record(s) skipped: the search index "
                                f"listed them but the fetched record is not in the "
                                f"configured resource (stale index entry)")
    if problems:
        print_status("error", f"{len(problems)} listed number(s) could NOT be exported:")
        for problem in problems:
            print_status("error", problem, indent=1)
        sys.exit(2)  # the file is complete for what was found; the gaps are named
    if mads_incomplete:
        sys.exit(2)  # same signal as check_mads.py: the file is accurate but not complete


if __name__ == "__main__":
    main()
