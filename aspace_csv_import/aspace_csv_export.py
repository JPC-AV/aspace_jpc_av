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
  - Dates are exported as the ISO begin value (yyyy-mm-dd) - the format the
    importer accepts back.
  - Notes are read with the same logic the importer's change detection uses
    (get_note_content), so what you see is what an update would compare to.
  - Records with structures the importer refuses to edit (multiple extents,
    multiple same-label dates, multiple same-type notes) are flagged in the
    Warnings column so you know those rows aren't safely editable by CSV.

Scope: ONLY the configured AV resource (resource_id in creds.py). The rest
of the repository is never enumerated.

Selection: everything at a level (--level, default item), one series'
children (--parent), or an explicit list of catalog numbers (--list FILE,
plain text one-per-line or any CSV with a CATALOG_NUMBER column).

Read-only: this script makes no writes of any kind.
"""

import argparse
import csv
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
                               get_note_content, staff_link_for, RUN_COMMAND)

# Batch size for id_set fetches - one API call per BATCH records instead of
# one call per record, which is the difference between minutes and an hour
# over the VPN. Kept well under ArchivesSpace's page-size ceiling (250).
BATCH = 50

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

# Public MADS URL for a catalog number (DAMS ingest auto-publishes to MADS,
# so this is where the item WILL be public - the URL is derived, not checked;
# --mads-live actually checks). check_mads owns the URL scheme and the check.
from check_mads import MADS_URL_PREFIX, check_many, summarize  # noqa: E402

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
    if level == "item" and not row[col.CATALOG]:
        warnings.append("no component ID in ASpace")
    if not row[col.TITLE]:
        warnings.append("no Title in ASpace")

    dates = record.get("dates") or []
    if level != "file" and not dates:
        warnings.append("no Date in ASpace")
    for column, label in col.DATE_COLUMNS:
        matching = [d for d in dates if d.get("label") == label]
        row[column] = (matching[0].get("begin") or "") if matching else ""
        if len(matching) > 1:
            warnings.append(f"{len(matching)} '{label}' dates")

    extents = record.get("extents") or []
    row[col.ORIGINAL_FORMAT] = (extents[0].get("extent_type") or "") if extents else ""
    if len(extents) > 1:
        warnings.append(f"{len(extents)} extents")

    notes = record.get("notes") or []
    row[col.DESCRIPTION] = get_note_content(notes, "scopecontent") or ""
    row[col.PHYSTECH] = get_note_content(notes, "phystech") or ""
    for note_type, name in (("scopecontent", "scopecontent"), ("phystech", "phystech")):
        count = sum(1 for n in notes if n.get("type") == note_type)
        if count > 1:
            warnings.append(f"{count} {name} notes")

    row["ASpace Ref ID"] = record.get("ref_id") or ""
    row["ASpace URI"] = record.get("uri") or ""
    row["ASpace Staff Link"] = staff_link_for(record.get("uri"))
    row["MADS URL"] = (MADS_URL_PREFIX + row[col.CATALOG]) if row[col.CATALOG] else ""
    row["Created By"] = record.get("created_by") or ""
    row["Create Time"] = record.get("create_time") or ""
    row["Last Modified By"] = record.get("last_modified_by") or ""
    row["Last Modified Time"] = record.get("user_mtime") or ""
    row["Warnings"] = "; ".join(warnings)
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
        records.extend(r for r in result if isinstance(r, dict))
        print_status("info", f"Fetched {min(start + BATCH, len(ids))}/{len(ids)} records...")
    return records


def parent_refid_for(client, parent_uri, cache):
    """ref_id of a parent record, fetched once per distinct parent."""
    if not parent_uri:
        return ""
    if parent_uri not in cache:
        parent = client.get(parent_uri)
        cache[parent_uri] = (parent.get("ref_id") or "") if isinstance(parent, dict) else ""
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
            first = f.readline()
            f.seek(pos)
            if col.CATALOG in first:
                numbers = [(r.get(col.CATALOG) or '').strip()
                           for r in csv.DictReader(f)]
            else:
                numbers = [line.strip().strip(',') for line in f
                           if not line.startswith('#')]
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
        lookup = client.find_archival_object(number)
        if lookup.status == "found":
            record = lookup.record
            parent_uri = (record.get("parent") or {}).get("ref") or ""
            row, _ = build_row(record, parent_refid_for(client, parent_uri, parent_cache))
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
    for record in records:
        resource_ref = (record.get("resource") or {}).get("ref")
        if resource_ref != aspace_client.RESOURCE_URI:
            anomalies += 1  # stale index hit: record no longer in the resource
            continue
        if level != "all" and record.get("level") != level:
            continue
        parent_uri = (record.get("parent") or {}).get("ref") or ""
        if parent_filter_uri and parent_uri != parent_filter_uri:
            continue
        row, _ = build_row(record, parent_refid_for(client, parent_uri, parent_cache))
        rows.append(row)
    return rows, anomalies


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
    parser.add_argument("--level", default="item",
                        help="Only records at this level (default: item; "
                             "'all' for every level)")
    parser.add_argument("--parent", metavar="REFID",
                        help="Only direct children of this parent ref_id")
    parser.add_argument("--list", metavar="FILE", dest="list_file",
                        help="Export exactly these catalog numbers: plain "
                             "text one per line, or any CSV with a "
                             "CATALOG_NUMBER column (--level/--parent do "
                             "not apply)")
    parser.add_argument("--mads-live", action="store_true",
                        help="Check each record's public MADS URL and add a "
                             "'MADS live' column (Yes/No/check failed)")
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
        parser.error("no environments configured in creds.py (see creds_template.py)")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stamp = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    out_path = args.output or os.path.join(
        OUTPUT_DIR, f"aspace_export_{aspace_client.ACTIVE_ENV}_{stamp}.csv")

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

    extra_headers = []
    if args.mads_live and rows:
        cats = [r.get(col.CATALOG, "") for r in rows]
        print_status("info", f"Checking MADS liveness for "
                             f"{len(set(c for c in cats if c))} catalog number(s)...")
        mads = check_many(cats)
        for r in rows:
            r["MADS live"] = mads.get(r.get(col.CATALOG, ""), "")
        extra_headers = ["MADS live"]
        live, not_live, check_failed = summarize(mads)
        print_status("info", f"MADS: {live} live, {not_live} not in MADS"
                             + (f", {check_failed} check failed (network/odd "
                                f"response - not proof of absence)" if check_failed else ""))

    provenance = (f"{RUN_COMMAND} | target: {aspace_client.ACTIVE_ENV} | "
                  f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    write_export_csv(rows, out_path, extra_headers, provenance)
    flagged = sum(1 for r in rows if r.get("Warnings"))
    print_status("success", f"Exported {len(rows)} record(s) to: {out_path}")
    if flagged:
        print_status("warning", f"{flagged} record(s) have Warnings - metadata gaps "
                                f"(no component ID/title/date) or structures "
                                f"--update-only will refuse to edit:")
        for r in rows:
            if r.get("Warnings"):
                label = r.get(col.CATALOG) or f"(no catalog number) {r.get(col.TITLE) or '(no title)'}"
                print_status("warning", f"{label}: {r['Warnings']}", indent=1)
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


if __name__ == "__main__":
    main()
