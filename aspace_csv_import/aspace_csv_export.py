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
whole hierarchy), one record's children (--parent), or an explicit list of
catalog numbers (--list FILE, plain text one-per-line or any CSV with a
CATALOG_NUMBER column).

Hierarchy: rows come out in depth-first tree order - the order the staff
interface shows - and every row carries Level, Depth (0 for a top-level
series; an ephemera item under a tape is one deeper than the tape) and
Path (its ancestors' display strings, joined with " > "). Path survives
sorting and filtering where row order does not, and it says in words what
the ASpace Parent RefID column says as a ref_id. A --list export keeps
list order but carries the same three columns. Delete them if unwanted;
--update-only ignores them either way.

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

import sheet_rules as col  # single source of truth for CSV header names

# Add parent directory to path for the shared client and creds.py import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aspace_client
from aspace_client import ASpaceClient

# Reuse the importer's console helpers and note-reading logic so the export
# shows values the same way an update run would compare them.
from aspace_csv_import import (Colors, print_status, print_header,
                               get_note_content, staff_link_for, RUN_COMMAND,
                               parse_date, render_options)

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
try:
    from creds import logs_dir
except ImportError:
    logs_dir = ""
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
    linked_cache = {}
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
            placed, reason = place_record(
                record, lambda uri: fetch_linked(client, uri, linked_cache))
            if placed is None:
                problems.append(f"{number}: its {reason}")
                continue
            # list order is kept - no tree sort, so no approximate-order note
            refid, depth, path, _, _ = placed
            row, _ = build_row(record, refid, depth, path)
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


def fetch_resource(client):
    """Every archival object in the resource, fetched and shape-checked.
    Returns (records, None) or (None, reason) - a partial or malformed fetch
    must never pose as the whole resource. Records the search index listed
    but that turn out to live elsewhere are still in the list; callers
    filter on resource ref (and count them as anomalies)."""
    ids = list_resource_records(client)
    if ids is None:
        return None, "could not enumerate the resource's records"
    print_status("info", f"{len(ids)} record(s) in the resource - "
                         f"fetching in batches of {BATCH}...")
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
                          col.FILE_TYPE, col.PARENT_NOTE, "Path"):
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
    blank ("..., Episode 4006, ..."); when both are present they must agree,
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
        existing = (row.get(col.PARENT_REFID) or "").strip()
        file_type = (row.get(col.FILE_TYPE) or "").strip()
        episode_cell = (row.get(col.EJS_EPISODE) or "").strip()
        key = episode_key(episode_cell)
        title_key, title_text = episode_from_title(row.get(col.TITLE))
        from_title = key is None and title_key not in (None, UNCLEAR)
        if from_title:
            key, episode_cell = title_key, title_text.split(None, 1)[1]
        found, path, note = "", "", ""
        conflict = False  # needs review even when the sheet already has a parent
        if key is not None and title_key not in (None, UNCLEAR) and key != title_key:
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


def write_filled_csv(headers, rows, path, provenance=None):
    """The input sheet, column order kept, with Path and Parent Note added
    (after the parent column) when the sheet did not already carry them.
    Atomic, provenance first line - same as every export."""
    fieldnames = list(headers)
    at = fieldnames.index(col.PARENT_REFID) + 1
    for extra in (col.PARENT_NOTE, "Path"):
        if extra not in fieldnames:
            fieldnames.insert(at, extra)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        if provenance:
            f.write(f"# {provenance}\n")
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, path)


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


def run_fill_parents(sheet_path, out_path):
    """--fill-parents end to end. Returns the exit code: 0 when every row
    has a parent, 2 when some were left for a person (the file is accurate
    but not complete), 1 on failure (nothing written)."""
    headers, rows, problem = read_fill_sheet(sheet_path)  # before any network work
    if rows is None:
        print_status("error", problem)
        return 1
    client = ASpaceClient()
    print_status("info", f"Connecting to {aspace_client.ASPACE_URL}...")
    if not client.login():
        print_status("error", "Authentication failed")
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
    provenance = (f"{RUN_COMMAND} | target: {aspace_client.ACTIVE_ENV} | "
                  f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    write_filled_csv(headers, rows, out_path, provenance)
    print_status("success", f"Wrote {len(rows)} row(s) to: {out_path}")
    print_status("info", f"{filled} parent(s) filled, {kept} already in the sheet, "
                         f"{len(unresolved)} left for a person")
    if unresolved:
        print_status("warning", "Rows without a filled parent (see the Parent Note column):")
        for row_num, catalog, note in unresolved:
            print_status("warning", f"row {row_num} {catalog or '(no catalog number)'}: {note}",
                         indent=1)
        return 2
    return 0


SELECT_OPTIONS = [
    ("--level LEVEL", "", "Only records at this level: item (default), file, subseries, series... or all"),
    ("--parent REFID", "", "Only the direct children of this record (combines with --level)"),
    ("--list FILE", "", "Exactly these catalog numbers (text, one per line, or a CSV with CATALOG_NUMBER); list order kept"),
]
FILL_OPTIONS = [
    ("--fill-parents FILE", "", "Fill blank ASpace Parent RefID cells from EJS Episode + ASpace File Type; writes a new file"),
    ("", "", "(keep EJS Episode filled - a blank cell falls back to the title, which must then follow the pattern)"),
]
EXPORT_CLI_OPTIONS = [
    ("--mads-live", "", "Add a MADS live column: Yes / No / check failed / invalid catalog number"),
    ("-o, --output PATH", "", "Output CSV path (default: timestamped file in the reports folder)"),
    ("--env NAME", "", "Target environment from creds.py (required when several are configured)"),
]


def get_colored_help():
    """The -h screen, laid out like the importer's."""
    C = Colors
    return "\n" + f"""{C.BOLD}{C.CYAN}===============================================================================
              ArchivesSpace CSV Export Script
==============================================================================={C.RESET}

{C.BOLD}DESCRIPTION{C.RESET}
    Reads AV records from ArchivesSpace - never writes to it:
    {C.GREEN}1.{C.RESET} Exports records to an import-shaped CSV, in tree order, with Level, Depth and Path
    {C.GREEN}2.{C.RESET} Fills a sheet's blank ASpace Parent RefID column (--fill-parents)
    {C.GREEN}3.{C.RESET} Checks whether exported records are live in MADS (--mads-live)

{C.BOLD}USAGE{C.RESET}
    {C.GREEN}${C.RESET} python3 aspace_csv_export.py [--level LEVEL] [--parent REFID] [options]
    {C.GREEN}${C.RESET} python3 aspace_csv_export.py --list FILE [options]
    {C.GREEN}${C.RESET} python3 aspace_csv_export.py --fill-parents FILE [-o PATH] [--env NAME]

{C.BOLD}SELECT{C.RESET} {C.DIM}(what to export; default: every item-level record){C.RESET}
{render_options(SELECT_OPTIONS)}

{C.BOLD}FILL PARENTS{C.RESET} {C.DIM}(instead of an export){C.RESET}
{render_options(FILL_OPTIONS)}

{C.BOLD}OPTIONS{C.RESET}
{render_options(EXPORT_CLI_OPTIONS)}

{C.BOLD}EXAMPLES{C.RESET}
    {C.GREEN}${C.RESET} python3 aspace_csv_export.py --level all --env production
    {C.GREEN}${C.RESET} python3 aspace_csv_export.py --level item --mads-live --env production
    {C.GREEN}${C.RESET} python3 aspace_csv_export.py --list batch.csv --env production
    {C.GREEN}${C.RESET} python3 aspace_csv_export.py --fill-parents batch.csv -o batch_filled.csv --env production

{C.BOLD}EXIT{C.RESET}
    {C.GREEN}0{C.RESET}  done
    {C.YELLOW}2{C.RESET}  file written but incomplete: parents left blank, listed numbers not found, or MADS checks failed
       (also a bad argument or a creds.py problem - then nothing is written)
    {C.RED}1{C.RESET}  failed - nothing written

{C.BOLD}OUTPUT{C.RESET}
    Reports saved to: {C.CYAN}{OUTPUT_DIR}/{C.RESET}
    {C.DIM}Can be changed by setting logs_dir in creds.py{C.RESET}
"""


def build_parser():
    """The exporter's command-line parser: same look as the importer's -
    a styled -h screen, and on error the short usage plus option list."""
    class CustomArgumentParser(argparse.ArgumentParser):
        def format_usage(self):
            C = Colors
            usage = (f"\nusage: {self.prog} [--level LEVEL] [--parent REFID] [options]\n"
                     f"       {self.prog} --list FILE [options]\n"
                     f"       {self.prog} --fill-parents FILE [-o PATH] [--env NAME]\n")
            hint = f"       {C.DIM}Use -h or --help for detailed information{C.RESET}\n"
            options = "\n" + "\n".join(render_options(group, indent="  ") for group in
                                        (SELECT_OPTIONS, FILL_OPTIONS, EXPORT_CLI_OPTIONS)) + "\n"
            return usage + hint + options

        def format_help(self):
            return "\n" + super().format_help()

        def error(self, message):
            self.print_usage(sys.stderr)
            self.exit(2, f"\n{Colors.RED}error: {message}{Colors.RESET}\n")

    parser = CustomArgumentParser(description=get_colored_help(),
                                  formatter_class=argparse.RawDescriptionHelpFormatter,
                                  add_help=False, usage=argparse.SUPPRESS)
    parser.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)
    parser.add_argument("--level", default="item", choices=LEVELS, metavar="LEVEL",
                        help=argparse.SUPPRESS)
    parser.add_argument("--parent", metavar="REFID", help=argparse.SUPPRESS)
    parser.add_argument("--list", metavar="FILE", dest="list_file", help=argparse.SUPPRESS)
    parser.add_argument("--fill-parents", metavar="FILE", dest="fill_file", help=argparse.SUPPRESS)
    parser.add_argument("--mads-live", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-o", "--output", metavar="PATH", help=argparse.SUPPRESS)
    parser.add_argument("--env", metavar="NAME", help=argparse.SUPPRESS)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.list_file and args.parent:
        parser.error("--list names the exact records to export - it cannot "
                     "be combined with --parent")
    if args.fill_file and (args.list_file or args.parent or args.mads_live
                           or args.level != "item"):
        parser.error("--fill-parents fills a sheet's parent column - it cannot be "
                     "combined with --list, --parent, --level or --mads-live")

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
    default_name = (f"parents_filled_{aspace_client.ACTIVE_ENV}_{stamp}.csv" if args.fill_file
                    else f"aspace_export_{aspace_client.ACTIVE_ENV}_{stamp}.csv")
    out_path = col.resolve_output_path(args.output, OUTPUT_DIR, default_name)

    for input_file in (args.list_file, args.fill_file):
        if input_file:
            problem = clobber_problem(input_file, out_path)
            if problem:
                parser.error(problem)  # before any network work

    print_header("ArchivesSpace CSV Export")
    target = (f"{aspace_client.ACTIVE_ENV.upper()} ({aspace_client.ASPACE_URL}, "
              f"repo {aspace_client.REPO_ID}, resource {aspace_client.RESOURCE_ID})")
    # Production gets the loud color, same convention as the importer.
    target_color = Colors.RED if aspace_client.ACTIVE_ENV == 'production' else Colors.GREEN
    print(f"  Target: {target_color}{Colors.BOLD}{target}{Colors.RESET}")
    print(f"  Command: {RUN_COMMAND}")
    if args.fill_file:
        print(f"  Fill parents: {args.fill_file}")
        sys.exit(run_fill_parents(args.fill_file, out_path))
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
    non_items = sum(1 for r in rows if r.get("Level") != "item")
    def _other_warnings(r):
        return [w for w in r.get("Warnings", "").split("; ") if w]
    flagged = sum(1 for r in rows if _other_warnings(r))
    print_status("success", f"Exported {len(rows)} record(s) to: {out_path}")
    if non_items:
        print_status("info", f"{non_items} of those are not item-level records (see the "
                             f"Level column) - --update-only edits items only, so those "
                             f"rows are for reference, not re-import")
    if flagged:
        print_status("warning", f"{flagged} record(s) have Warnings - metadata gaps "
                                f"(no component ID/title/date) or structures "
                                f"--update-only will refuse to edit:")
        for r in rows:
            others = _other_warnings(r)
            if others:
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
