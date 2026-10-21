#!/usr/bin/env python3
"""
Write a finished import run back to Airtable: for every record the run
really created in production, put its parent ref ID into
<<< ASpace_import >>> and set ASpace Item Record Created to Yes in
((( ASpace_tracking ))).

Preview by default; --run writes. Reads with airtable_pat_read_only,
writes with airtable_pat_write. Every run re-reads Airtable, so a rerun
after a stop finishes only what is left.
"""

import argparse
import csv
import io
import json
import os
import re
import secrets
import shlex
import stat
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests

import airtable_pull as pull  # Airtable config, GET helper, output styling
import aspace_client          # production repo id, from creds.py (no API call)
import sheet_rules as col

# ==============================
# CONFIGURATION
# ==============================

BASE_ID = pull.BASE_ID
IMPORT_TABLE_ID = pull.TABLE_ID          # <<< ASpace_import >>>
TRACKING_TABLE_ID = "tbl1E9gmY6VgMq4Ya"  # ((( ASpace_tracking )))

PARENT_FIELD = "ASpace Parent RefID"            # text, in ASpace_import
IMPORT_LINK_FIELD = "CATALOG_NUMBER"            # link to JPCA-AV_SOURCE
TRACKING_LINK_FIELD = "JPCA-AV_SOURCE"          # link to JPCA-AV_SOURCE
CREATED_FIELD = "ASpace Item Record Created"    # single select, in ASpace_tracking
CREATED_VALUE = "Yes"

# The Airtable tables as the base shows them - with their markers, so they
# are never mistaken for ArchivesSpace in the output
IMPORT_LABEL = "<<< ASpace_import >>>"
TRACKING_LABEL = "((( ASpace_tracking )))"

PATCH_BATCH = 10  # Airtable's per-request record limit

import creds_loader  # noqa: E402 - beside aspace_client at the repo root
AIRTABLE_PAT_WRITE = (creds_loader.setting("airtable_pat_write", "")
                      or os.environ.get("AIRTABLE_PAT_WRITE", ""))
WRITE_TOKEN = ("The Airtable write token", "airtable_pat_write", "AIRTABLE_PAT_WRITE")

REF_ID_RE = re.compile(r"[0-9a-f]{32}")
# An Airtable record ID ("rec" and letters/digits) - the only text a re-check
# puts into a formula: nothing that could quote or call anything
AIRTABLE_ID_RE = re.compile(r"rec[A-Za-z0-9]{1,30}")

from console import (Colors, print_status, print_run_header,  # shared display  # noqa: E402
                     print_result, print_saved, print_next_step, render_options,
                     help_screen, styled_parser, progress_count, close_progress,
                     started_by)
PullError = pull.PullError


class UncertainWrite(PullError):
    """A write whose outcome is unknown: it may or may not have been applied."""


class RateLimited(PullError):
    """A write refused with HTTP 429 - definitely not applied. The caller
    waits, re-checks the rows and only then tries again."""


class OutputStopped(PullError):
    """The screen output failed, so no further write is sent. Raised before
    a send: nothing is in flight."""

# ==============================
# HELP MENU
# ==============================

TITLE = "Record import results in Airtable"
ARGUMENTS = [("REPORT.json", "", "import_report_<stamp>.json from a REAL (not -n) production create run")]
OPTIONS = [
    ("--run", "", 'Show the plan, ask for "yes", then write (without it: preview only)'),
    ("--exclude-catalog JPC_AV_xxxxx", "", "Leave this created row out (repeatable) - e.g. a record"),
    ("", "", "deleted in ArchivesSpace since the import"),
    ("--no-color", "", "Disable colored output"),
]


def get_colored_help():
    """The -h screen, in the shared layout."""
    C = Colors
    return help_screen(TITLE, [
        ("DESCRIPTION", f"""    After a real production import, records its results in Airtable. For each
    row the run CREATED:
      - {PARENT_FIELD} in {IMPORT_LABEL} gets the parent the import used
      - {CREATED_FIELD} in {TRACKING_LABEL} is set to {CREATED_VALUE}
    The parent is written and confirmed first; {CREATED_VALUE} is set only after.

    Each batch's rows are read again just before they are written, and
    again after any rate-limit wait. A row whose links, hold, parent or
    {CREATED_VALUE} changed since the PLAN is left alone ("changed"); {CREATED_VALUE} is set only
    while the parent read back is the import's. An edit made between that
    read and the write can still be overwritten - Airtable cannot make a
    write conditional.

    Rows the run skipped, updated or refused are left alone. A row whose
    Airtable parent already differs, that matches no row or several, that is
    on hold in Airtable now, or whose read-back snapshot is missing, does not
    match or is outside the report's resource, is listed for review and not
    touched.

    Before Airtable is read, the report must be a real production create run
    whose recorded ArchivesSpace target (server URL, repository, resource)
    matches creds.py's production entry, with its records file from the same
    run - otherwise nothing is read or written. ArchivesSpace is not
    contacted: this shows that recorded settings agree, not that the records
    still exist or that the production entry really is production."""),
        ("USAGE", f"""    {C.GREEN}${C.RESET} python3 aspace_csv_import/airtable_writeback.py REPORT.json          {C.DIM}# preview{C.RESET}
    {C.GREEN}${C.RESET} python3 aspace_csv_import/airtable_writeback.py REPORT.json --run    {C.DIM}# shows the plan, asks, writes{C.RESET}"""),
        ("ARGUMENTS", render_options(ARGUMENTS)),
        ("OPTIONS", render_options(OPTIONS)),
        ("TOKENS", """    airtable_pat_read_only   read-only - schema and table reads (creds.py)
    airtable_pat_write       data.records:write on this base - the writes only"""),
        ("EXAMPLES", f"""    {C.GREEN}${C.RESET} python3 aspace_csv_import/airtable_writeback.py import_reports/import_report_<stamp>.json --run
    {C.GREEN}${C.RESET} python3 aspace_csv_import/airtable_writeback.py REPORT.json --exclude-catalog JPC_AV_13500 --run"""),
        ("OUTPUT", """    With --run: airtable_writeback_<stamp>.csv next to the report - each row's
    outcome (done / already done / partial / unknown / not started / changed
    / review). "unknown" means a write may or may not have landed (lost
    response, server error, Ctrl-C); run the same command again to settle it.
    If the screen output fails (a closed pipe), nothing more is written; the
    run still tries to save the file and, when stderr is available, says
    whether it was saved."""),
        ("EXIT", f"""    {C.GREEN}0{C.RESET}  done (or, previewing, nothing for review)
    {C.YELLOW}2{C.RESET}  rows for review or unfinished rows (rerun to finish), or a bad argument
    {C.RED}1{C.RESET}  stopped: a report or token problem, a refused or unknown write,
       cancelled at the prompt, the outcomes file could not be saved, or the
       screen output failed"""),
    ])


# ==============================
# IMPORT REPORT
# ==============================

# A run's start time exactly as the importer records it (datetime's
# isoformat(): date AND time, microseconds as 6 digits or none), so a
# missing, empty or date-only value never counts as a match - and no
# Python version's looser parser decides what is accepted.
START_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{6})?")
TARGET_LABELS = {"base_url": "server URL (base_url)", "repo_id": "repository (repo_id)",
                 "resource_id": "resource (resource_id)"}
NOTHING_DONE = "nothing was read from or written to Airtable"
CONSISTENCY = ("The check compares recorded settings with creds.py; ArchivesSpace is not "
               "contacted, so it cannot show that the records exist now or that the entry "
               "really is production.")


def valid_start_time(value):
    """True for YYYY-MM-DDTHH:MM:SS[.ffffff] naming a real moment."""
    if not isinstance(value, str) or not START_TIME_RE.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def run_problems(summary):
    """The fields of one summary - the report's or its records file's, each
    checked on its own before anything is compared - that do not describe a
    real production create run. Strict types: in Python True == 1 and
    False == 0, so equality alone would accept a masquerading value."""
    problems = []
    if summary.get("environment") != "production":
        problems.append("environment")
    if summary.get("dry_run") is not False:
        problems.append("dry_run")
    if summary.get("mode") != "create-records":
        problems.append("mode")
    if not valid_start_time(summary.get("start_time")):
        problems.append("start_time")
    problem = aspace_client.target_problem(summary.get("target"))
    if problem:
        problems.append(problem if problem.startswith("target") else f"target {problem}")
    return problems


def read_json(path, what, after=""):
    """A JSON file, or a PullError naming it and the operating system's
    reason - never the parser's own text, which can quote the file."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise PullError(f"could not read {what}: {e.strerror or 'unreadable'}{after}")
    except ValueError:
        raise PullError(f"could not read {what} as JSON{after}")


def load_records(summary):
    """The records file a report with created rows requires: only the path
    the report recorded, checked on its own and then against the report's
    run and target. Anything wrong stops the whole report."""
    rec_path = summary.get("records_file")
    if not isinstance(rec_path, str) or not rec_path:
        raise PullError(f"this report has created rows but names no records file "
                        f"(records_file); the write-back needs it to check each created "
                        f"record - {NOTHING_DONE}")
    data = read_json(rec_path, "the records file this report names (records_file)",
                     f" - the write-back reads it only from the path the report recorded; "
                     f"{NOTHING_DONE}")
    rec_summary = data.get("summary") if isinstance(data, dict) else None
    records = data.get("records") if isinstance(data, dict) else None
    if not isinstance(rec_summary, dict) or not isinstance(records, dict):
        raise PullError(f"the file this report names as its records file is not a records "
                        f"file (summary, records) - {NOTHING_DONE}")
    problems = run_problems(rec_summary)
    if problems:
        raise PullError(f"the records file does not describe a real production create run "
                        f"({', '.join(problems)}) - {NOTHING_DONE}")
    differ = [k for k in ("start_time", "target") if rec_summary[k] != summary[k]]
    if differ:
        raise PullError(f"the records file is from a different run than this report "
                        f"(differs: {', '.join(differ)}) - {NOTHING_DONE}")
    return records


def load_report(path, exclude=()):
    """(candidates, review, counts, excluded) from a real production import report.

    Before anything else - before any Airtable read - the report and, when it
    has created rows, its records file must each describe a real production
    create run with a valid ArchivesSpace target, agree with each other, and
    match creds.py's production entry; otherwise the whole report stops.

    candidates: [{catalog, parent, uri}] for rows the run created and read
    back. review: [(catalog, note)] for created rows that cannot be written
    back safely. counts: statuses of the rows left alone. excluded: the
    --exclude-catalog numbers, each of which must be a created row in the
    report - they are dropped before any Airtable planning.
    """
    report = read_json(path, path, " - use the import_report_<stamp>.json file")
    summary = report.get("summary") if isinstance(report, dict) else None
    results = report.get("results") if isinstance(report, dict) else None
    if not isinstance(summary, dict) or not isinstance(results, list):
        raise PullError(f"{path} is not an import report (no summary/results) - "
                        f"use import_report_<stamp>.json, not the CSV")
    if summary.get("dry_run") is True:
        raise PullError("this report is from a dry run (-n) - nothing was created; "
                        "use the report from the real run")
    environment = summary.get("environment")
    if environment != "production":
        named = (f"the {environment!r} environment" if isinstance(environment, str)
                 and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", environment)
                 else "an environment other than production")
        raise PullError(f"this report is from {named} - only production runs are written back")
    if summary.get("mode") == "update-only":
        raise PullError("this report is from an update-only run - only create runs "
                        "(--create-records) are written back")
    if "target" not in summary:
        raise PullError(f"this report does not record which ArchivesSpace server, repository "
                        f"and resource it was made against, so it cannot be checked against "
                        f"creds.py - {NOTHING_DONE}")
    problems = run_problems(summary)
    if problems:
        raise PullError(f"this report does not describe a real production create run "
                        f"({', '.join(problems)}) - {NOTHING_DONE}")
    target = summary["target"]
    try:  # creds.py's production entry, read only: nothing is selected or contacted
        production = aspace_client.configured_target("production")
    except ValueError as e:
        raise PullError(str(e))
    differ = [TARGET_LABELS[k] for k in TARGET_LABELS if target[k] != production[k]]
    if differ:
        raise PullError(f"this report's ArchivesSpace target does not match creds.py's "
                        f"production entry (differs: {', '.join(differ)}) - {NOTHING_DONE}. "
                        f"{CONSISTENCY}")

    created = [r for r in results if isinstance(r, dict) and r.get("status") == "created"]
    # Required whenever the run created rows - even if every one is excluded
    # below; a report with none needs no records file.
    records = load_records(summary) if created else {}
    uri_re = re.compile(rf"/repositories/{target['repo_id']}/archival_objects/[0-9]+")
    resource_uri = f"/repositories/{target['repo_id']}/resources/{target['resource_id']}"

    counts = {}
    for r in results:
        if isinstance(r, dict) and r.get("status") != "created":
            counts[r.get("status")] = counts.get(r.get("status"), 0) + 1

    created_numbers = {(r.get(col.CATALOG) or "").strip() for r in created}
    excluded = sorted(set(exclude))
    unknown = [c for c in excluded if c not in created_numbers]
    if unknown:
        # counted, never repeated: what was typed could be a password
        raise PullError(f"--exclude-catalog: {len(unknown)} of the values given "
                        f"{'is not a created row' if len(unknown) == 1 else 'are not created rows'} "
                        f"in this report - not shown, in case one is a password; check them "
                        f"(nothing written)")
    created = [r for r in created if (r.get(col.CATALOG) or "").strip() not in excluded]

    seen = {}
    for r in created:
        seen[r.get(col.CATALOG)] = seen.get(r.get(col.CATALOG), 0) + 1

    candidates, review = [], []
    for r in created:
        catalog = (r.get(col.CATALOG) or "").strip()
        parent = (r.get(col.PARENT_REFID) or "").strip()
        uri = (r.get("uri") or "").strip()
        snap = records.get(catalog)
        obj = snap.get("archival_object") if isinstance(snap, dict) else None
        resource = obj.get("resource") if isinstance(obj, dict) else None
        if not col.valid_catalog_number(catalog):
            review.append((catalog or f"row {r.get('row_number')}", "no valid catalog number"))
        elif seen[r.get(col.CATALOG)] > 1:
            review.append((catalog, "appears more than once in the report"))
        elif not REF_ID_RE.fullmatch(parent):
            review.append((catalog, f"no valid parent ref ID in the report ({parent!r})"))
        elif not uri_re.fullmatch(uri):
            review.append((catalog, f"record URI {uri!r} is not a production archival object"))
        elif not isinstance(obj, dict):
            review.append((catalog, "no read-back snapshot of the created record"))
        elif not (snap.get("uri") == uri and obj.get("uri") == uri
                  and obj.get("component_id") == catalog):
            review.append((catalog, "the read-back snapshot does not match the created record"))
        elif not (isinstance(resource, dict) and resource.get("ref") == resource_uri):
            review.append((catalog, "the read-back snapshot is not in the report's resource"))
        else:
            candidates.append({"catalog": catalog, "parent": parent, "uri": uri,
                               "title": (r.get(col.TITLE) or "").strip()})
    return candidates, review, counts, excluded

# ==============================
# AIRTABLE READS (read-only token)
# ==============================

def check_schema(token):
    """Field IDs for everything the write-back touches, after confirming each
    field has the type it must have. Raises PullError on any surprise."""
    url = f"{pull.API_URL}/meta/bases/{BASE_ID}/tables"
    tables = {t.get("id"): t for t in pull.airtable_request(url, token).get("tables", [])}

    def field(table_id, name, ftype):
        table = tables.get(table_id)
        if table is None:
            raise PullError(f"table {table_id} is not in base {BASE_ID}")
        matches = [f for f in table.get("fields", []) if f.get("name") == name]
        if len(matches) != 1:
            raise PullError(f"{table.get('name')} has no field named {name!r}")
        if matches[0].get("type") != ftype:   # the reply's type itself is never shown
            raise PullError(f"{table.get('name')}.{name} has another field type (not shown), "
                            f"expected {ftype} - nothing written")
        return matches[0]

    parent = field(IMPORT_TABLE_ID, PARENT_FIELD, "singleLineText")
    import_link = field(IMPORT_TABLE_ID, IMPORT_LINK_FIELD, "multipleRecordLinks")
    tracking_link = field(TRACKING_TABLE_ID, TRACKING_LINK_FIELD, "multipleRecordLinks")
    created = field(TRACKING_TABLE_ID, CREATED_FIELD, "singleSelect")
    choices = [c.get("name") for c in (created.get("options") or {}).get("choices", [])]
    if CREATED_VALUE not in choices:
        raise PullError(f"{CREATED_FIELD} has no {CREATED_VALUE!r} option (options: {choices})")
    source_id = (import_link.get("options") or {}).get("linkedTableId")
    if not source_id or source_id != (tracking_link.get("options") or {}).get("linkedTableId"):
        raise PullError(f"{IMPORT_LINK_FIELD} and {TRACKING_LINK_FIELD} do not link to the same table")
    source = tables.get(source_id) or {}
    # The hold is optional: a base without the field simply has no holds.
    import_fields = {f.get("name"): f for f in tables[IMPORT_TABLE_ID].get("fields", [])}
    misspelled = col.hold_name_problem(list(import_fields))
    if misspelled:
        raise PullError(misspelled + " - nothing written")
    hold = import_fields.get(col.HOLD)
    if hold is not None and hold.get("type") != "checkbox":
        raise PullError(f"{col.HOLD} has another field type (not shown), expected "
                        f"checkbox - nothing written")
    issue = import_fields.get(col.ISSUE)
    return {
        "hold": hold["id"] if hold else None,
        "issue": issue["id"] if issue else None,
        "parent": parent["id"], "import_link": import_link["id"],
        "tracking_link": tracking_link["id"], "created": created["id"],
        "source_table": source_id, "source_primary": source.get("primaryFieldId"),
        "source_name": source.get("name", source_id),
    }


def read_table(token, table_id, field_ids, label, as_text=False):
    """Every record of a table, only the given fields, keyed by field ID."""
    try:
        return _read_pages(token, table_id, field_ids, label, as_text)
    finally:
        close_progress()


def _read_pages(token, table_id, field_ids, label, as_text):
    params = [("returnFieldsByFieldId", "true"), ("pageSize", "100")]
    params += [("fields[]", fid) for fid in field_ids]
    if as_text:
        params += [("cellFormat", "string"), ("timeZone", pull.TIME_ZONE),
                   ("userLocale", pull.USER_LOCALE)]
    base_url = f"{pull.API_URL}/{BASE_ID}/{table_id}"
    records, offset = [], None
    while True:
        query = params + ([("offset", offset)] if offset else [])
        page = pull.airtable_request(f"{base_url}?{urlencode(query)}", token)
        if not isinstance(page, dict) or not isinstance(page.get("records"), list):
            raise PullError(f"Airtable sent a malformed page reading {label}")
        records.extend(page["records"])
        offset = page.get("offset")
        progress_count(f"Read {label}:", len(records), finished=not offset)
        if not offset:
            return records
        time.sleep(pull.PAGE_PAUSE)


def link_ids(value):
    """A link field's record IDs (JSON cell format: a list of rec IDs)."""
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def select_name(value):
    """A single select's option name (JSON cell format: the name, or absent)."""
    if isinstance(value, dict):
        return value.get("name") or ""
    return value if isinstance(value, str) else ""


def build_plan(token, candidates):
    """Re-read Airtable and decide, per candidate, what (if anything) to write.

    Each plan entry: catalog, parent, import_rec, tracking_rec, set_parent,
    set_created, note (non-empty = review, nothing written)."""
    ids = check_schema(token)
    print_status("info", "Reading Airtable - three tables, about a minute each...")
    sources = read_table(token, ids["source_table"], [ids["source_primary"]],
                         ids["source_name"], as_text=True)
    imports = read_table(token, IMPORT_TABLE_ID,
                         [f for f in (ids["import_link"], ids["parent"], ids["hold"],
                                      ids["issue"]) if f],
                         IMPORT_LABEL)
    trackings = read_table(token, TRACKING_TABLE_ID, [ids["tracking_link"], ids["created"]],
                           TRACKING_LABEL)

    by_catalog = {}
    for rec in sources:
        catalog = (rec.get("fields", {}).get(ids["source_primary"]) or "").strip()
        if col.valid_catalog_number(catalog):
            by_catalog.setdefault(catalog, []).append(rec["id"])
    import_by_source, tracking_by_source = {}, {}
    for rec in imports:
        for sid in link_ids(rec.get("fields", {}).get(ids["import_link"])):
            import_by_source.setdefault(sid, []).append(rec)
    for rec in trackings:
        for sid in link_ids(rec.get("fields", {}).get(ids["tracking_link"])):
            tracking_by_source.setdefault(sid, []).append(rec)

    def one(found, where):
        if len(found) == 1:
            return found[0], ""
        return None, f"{len(found) or 'no'} {where} row(s) link to it"

    plan = []
    for c in candidates:
        entry = {**c, "import_rec": None, "tracking_rec": None,
                 "set_parent": False, "set_created": False, "note": ""}
        plan.append(entry)
        source_ids = by_catalog.get(c["catalog"], [])
        if len(source_ids) != 1:
            entry["note"] = (f"{len(source_ids) or 'no'} {ids['source_name']} row(s) "
                             f"named {c['catalog']}")
            continue
        imp, note = one(import_by_source.get(source_ids[0], []), IMPORT_LABEL)
        trk, note2 = one(tracking_by_source.get(source_ids[0], []), TRACKING_LABEL)
        if note or note2:
            entry["note"] = "; ".join(n for n in (note, note2) if n)
            continue
        # a row linking this item AND others would change the others too
        shared = [f"{where} row links {len(links)} items"
                  for where, rec, fid in ((IMPORT_LABEL, imp, ids["import_link"]),
                                          (TRACKING_LABEL, trk, ids["tracking_link"]))
                  for links in [link_ids(rec.get("fields", {}).get(fid))]
                  if links != [source_ids[0]]]
        if shared:
            entry["note"] = "; ".join(shared) + " - left alone"
            continue
        if ids["hold"] and imp.get("fields", {}).get(ids["hold"]) is True:
            # held NOW in Airtable - even after it was created
            reason = (imp["fields"].get(ids["issue"]) or "").strip() if ids["issue"] else ""
            entry["note"] = f"on hold in Airtable{': ' + reason if reason else ''} - left alone"
            continue
        entry["import_rec"], entry["tracking_rec"] = imp["id"], trk["id"]
        entry["source_rec"] = source_ids[0]   # re-checked before each write
        current = (imp.get("fields", {}).get(ids["parent"]) or "").strip()
        if current and current != c["parent"]:
            entry["note"] = (f"Airtable already has parent {current}; the import used "
                             f"{c['parent']} - left alone")
            continue
        created_now = select_name(trk.get("fields", {}).get(ids["created"]))
        entry["current_parent"], entry["current_created"] = current, created_now
        entry["set_parent"] = not current
        entry["set_created"] = created_now != CREATED_VALUE
    return plan, ids


def read_records(token, table_id, record_ids, field_ids, as_text=False):
    """Only the given records of a table, read again by record ID - never the
    whole table: {record ID: fields}. A record that no longer exists is
    simply absent. Only record IDs of letters and digits go into the
    formula; an answer naming any other record is refused."""
    wanted = sorted(set(record_ids))
    if not all(isinstance(r, str) and AIRTABLE_ID_RE.fullmatch(r) for r in wanted):
        raise PullError("a planned Airtable record ID is not in Airtable's form - nothing more "
                        "was written")
    params = [("filterByFormula", "OR(" + ",".join(f"RECORD_ID()='{r}'" for r in wanted) + ")"),
              ("returnFieldsByFieldId", "true"), ("pageSize", "100")]
    params += [("fields[]", fid) for fid in field_ids]
    if as_text:
        params += [("cellFormat", "string"), ("timeZone", pull.TIME_ZONE),
                   ("userLocale", pull.USER_LOCALE)]
    page = pull.airtable_request(f"{pull.API_URL}/{BASE_ID}/{table_id}?{urlencode(params)}", token)
    records = page.get("records") if isinstance(page, dict) else None
    if (not isinstance(records, list) or page.get("offset")
            or any(not isinstance(r, dict) or r.get("id") not in wanted
                   or not isinstance(r.get("fields"), dict) for r in records)
            or len({r["id"] for r in records}) != len(records)):
        raise PullError("Airtable sent a malformed answer while the rows were re-checked - "
                        "nothing more was written")
    time.sleep(pull.PAGE_PAUSE)
    return {r["id"]: r["fields"] for r in records}


def _text(value):
    """A cell as stripped text: "" when empty, None when it is not text."""
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else None


def recheck(token, ids, rows, phase):
    """Read the rows of the next batch again, just before it is sent, and
    compare them with what the PLAN approved: -> (changed, satisfied).

    changed: {catalog: what changed} for rows the PLAN no longer authorizes -
    their source record, import or tracking row is gone or relinked, the
    item is on hold, or a field changed. The words are fixed; no cell value
    is quoted. satisfied: catalogs whose approved value is already there, so
    their write is skipped. Before a parent write ("parent") the cell may
    still be blank or already the approved parent; before Yes ("created") it
    must be the approved parent - a cleared or changed parent stops the Yes.
    A failed read raises PullError; nothing has been sent for these rows."""
    changed, ready = {}, []
    for e in rows:
        if all(AIRTABLE_ID_RE.fullmatch(str(e.get(k))) for k in
               ("source_rec", "import_rec", "tracking_rec")):
            ready.append(e)
        else:
            changed[e["catalog"]] = "its Airtable records cannot be re-checked"
    if not ready:
        return changed, set()
    sources = read_records(token, ids["source_table"], [e["source_rec"] for e in ready],
                           [ids["source_primary"]], as_text=True)
    imports = read_records(token, IMPORT_TABLE_ID, [e["import_rec"] for e in ready],
                           [f for f in (ids["import_link"], ids["parent"], ids["hold"]) if f])
    trackings = read_records(token, TRACKING_TABLE_ID, [e["tracking_rec"] for e in ready],
                             [ids["tracking_link"], ids["created"]])
    satisfied = set()
    for e in ready:
        facts = []
        src, imp, trk = (sources.get(e["source_rec"]), imports.get(e["import_rec"]),
                         trackings.get(e["tracking_rec"]))
        if src is None:
            facts.append("its source record is gone")
        elif _text(src.get(ids["source_primary"])) != e["catalog"]:
            facts.append("its source record was renamed")
        if imp is None:
            facts.append(f"its {IMPORT_LABEL} row is gone")
        else:
            if link_ids(imp.get(ids["import_link"])) != [e["source_rec"]]:
                facts.append(f"its {IMPORT_LABEL} row links other records")
            if ids["hold"] and imp.get(ids["hold"]) is True:
                facts.append("on hold in Airtable now")
            parent = _text(imp.get(ids["parent"]))
            allowed = ({e["current_parent"], e["parent"]} if phase == "parent"
                       else {e["parent"]})
            if parent not in allowed:
                facts.append(f"{PARENT_FIELD} changed")
        if trk is None:
            facts.append(f"its {TRACKING_LABEL} row is gone")
        else:
            if link_ids(trk.get(ids["tracking_link"])) != [e["source_rec"]]:
                facts.append(f"its {TRACKING_LABEL} row links other records")
            created = trk.get(ids["created"])
            if created is not None and not isinstance(created, (str, dict)):
                facts.append(f"{CREATED_FIELD} changed")
            elif select_name(created) not in (e["current_created"], CREATED_VALUE):
                facts.append(f"{CREATED_FIELD} changed")
        if facts:
            changed[e["catalog"]] = "; ".join(facts)
        elif phase == "parent" and _text(imp.get(ids["parent"])) == e["parent"]:
            satisfied.add(e["catalog"])
        elif phase == "created" and select_name(trk.get(ids["created"])) == CREATED_VALUE:
            satisfied.add(e["catalog"])
    return changed, satisfied

# ==============================
# AIRTABLE WRITES (write token)
# ==============================

def airtable_patch(table_id, records, token):
    """PATCH up to 10 records, once; returns the updated records keyed by ID.
    A 429 raises RateLimited (definitely not applied): the caller re-checks
    the rows before any retry, so no write goes out on an old check."""
    url = f"{pull.API_URL}/{BASE_ID}/{table_id}"
    body = {"records": records, "returnFieldsByFieldId": True}
    problem = creds_loader.token_problem(token)  # the token actually used
    if problem:  # refused before any request: definitely not sent
        raise PullError(creds_loader.token_refusal(*WRITE_TOKEN, problem)
                        + " - nothing was sent for this batch")
    headers = {"Authorization": f"Bearer {token}"}
    # Past this point a failure may follow a send: it stays uncertain.
    # An exception's own text can quote the Authorization header, so
    # only its kind is shown, and none is chained ("from None").
    try:
        resp = requests.patch(url, headers=headers, json=body, timeout=pull.TIMEOUT,
                              allow_redirects=False)
    except requests.Timeout:
        raise UncertainWrite(f"Airtable did not answer a write within {pull.TIMEOUT}s - it "
                             f"may or may not have been applied; rerun to re-check") from None
    except requests.ConnectionError:
        raise UncertainWrite("the connection to api.airtable.com failed during a write - "
                             "check the network; rerun to re-check") from None
    except requests.RequestException as e:
        raise UncertainWrite(f"write to Airtable failed ({type(e).__name__}) - it may or "
                             f"may not have been applied; rerun to re-check") from None
    except ValueError as e:  # refused inside the HTTP library while sending
        raise UncertainWrite(f"write to Airtable failed ({type(e).__name__}) - it may or "
                             f"may not have been applied; rerun to re-check") from None
    # A redirect is never followed (that would re-send the write and the
    # token elsewhere) and its Location is never shown. The write itself
    # may or may not have been applied: uncertain, never retried.
    if 300 <= resp.status_code < 400:
        raise UncertainWrite(f"Airtable answered a write with a redirect (HTTP "
                             f"{resp.status_code}), which is not followed - it may or "
                             f"may not have been applied; rerun to re-check")
    if resp.status_code == 429:
        raise RateLimited(f"Airtable rate limit - still refused after "
                          f"{pull.RATE_LIMIT_RETRIES} retries")
    if resp.status_code in (401, 403, 404):
        raise PullError(f"Airtable refused the write (HTTP {resp.status_code}: "
                        f"{pull._error_explanation(resp)}) - check airtable_pat_write's scopes "
                        f"(data.records:write), its access to base {BASE_ID}, and "
                        f"field permissions before changing anything")
    if resp.status_code >= 500:
        # Airtable can time out WHILE applying a write (503), so a 5xx
        # is not proof the write was refused
        raise UncertainWrite(f"Airtable had a server error during a write (HTTP "
                             f"{resp.status_code}: {pull._error_explanation(resp)}) - it may or "
                             f"may not have been applied; rerun to re-check")
    if resp.status_code >= 400:
        raise PullError(f"Airtable refused the write (HTTP {resp.status_code}): "
                        f"{pull._error_explanation(resp)}")
    try:
        data = resp.json()
    except ValueError:
        raise UncertainWrite("Airtable answered a write with something that is not JSON - "
                             "rerun to re-check")
    records = data.get("records") if isinstance(data, dict) else None
    if not isinstance(records, list):
        raise UncertainWrite("Airtable answered a write without a list of records - it "
                             "may or may not have been applied; rerun to re-check")
    # every record must be one we asked about, once, with a fields dict -
    # anything else is an answer we cannot read, not a result
    sent = [r["id"] for r in body["records"]]
    got = [r.get("id") if isinstance(r, dict) else None for r in records]
    if (sorted(map(str, got)) != sorted(sent)
            or any(not isinstance(r, dict) or not isinstance(r.get("id"), str)
                   or not isinstance(r.get("fields"), dict) for r in records)):
        raise UncertainWrite("Airtable answered a write with records that do not match "
                             "the request - it may or may not have been applied; rerun "
                             "to re-check")
    return {r["id"]: r for r in records}


INTERRUPTED = "interrupted (Ctrl-C) - rerun to re-check and finish"


def initial_outcome(e):
    """A row's outcome before anything is written for it."""
    return "review" if e["note"] else (
        "already done" if not (e["set_parent"] or e["set_created"]) else "not started")


def complete_partials(plan):
    """A row whose parent was just confirmed and whose Yes was already set
    is complete (never a row whose outcome is unknown)."""
    for e in plan:
        if e["outcome"] == "partial" and not e["set_created"]:
            e["outcome"] = "done"


CHANGED = "changed in Airtable after the PLAN"


def stop_if_output_lost():
    """Before any write is sent: once the screen output has failed, nothing
    more goes to Airtable (a definite stop - nothing is in flight). What a
    pipe still holds back is flushed first, so a failure hidden in its
    buffer - a warning just printed - counts before the send, not after."""
    if SCREEN is not None:
        SCREEN.flush()
    lost = output_lost()
    if lost:
        raise OutputStopped(f"the screen output failed ({lost}) - nothing more was sent "
                            f"to Airtable")


def execute(plan, ids, token, inflight=None, *, recheck):
    """Parents first (confirmed from the write's response), then Yes for rows
    whose parent is in place. Sets each entry's outcome; stops on the first
    refusal, lost response or Ctrl-C and returns its message (None when
    everything went through). A batch whose write may or may not have
    landed is marked "unknown" - a rerun re-reads Airtable and settles it.
    `inflight`, when given, is the list the batch being written is kept in,
    so the caller still knows it if a second Ctrl-C escapes this function.

    recheck(rows, phase) -> (changed, satisfied) reads a batch's rows again
    just before it is sent, and again after every rate-limit wait (see
    recheck()). A changed row is left alone - "changed", or "partial" with
    its note when this run already wrote its parent - and never replaced by
    another row or a new plan; a satisfied write is skipped. It runs while
    no batch is in flight, so its failure or a Ctrl-C during it makes no row
    unknown. So does a failure of the screen output, checked before each send."""
    for e in plan:
        e["outcome"] = initial_outcome(e)
        e["parent_ok"] = not e["note"] and not e["set_parent"]
        e["wrote"] = False            # did this run write anything to the row
    # the batch being written; its outcome is unknown if interrupted
    batch = inflight if inflight is not None else []

    def send(rows, phase, table_id, record, field, value):
        """Re-check `rows`, then PATCH the ones still authorized and not
        already in place - each row's `record` ID, `field` set to value(row);
        after a 429, wait, re-check and try again.
        -> (rows sent, the reply's records by ID)."""
        for attempt in range(pull.RATE_LIMIT_RETRIES + 1):
            stop_if_output_lost()
            changed, satisfied = recheck(rows, phase)
            for e in rows:
                if e["catalog"] in changed:
                    e["note"] = (f"{CHANGED} ({changed[e['catalog']]}) - "
                                 f"{'Yes not set' if e['wrote'] else 'left alone'}; run the "
                                 f"same command again to see the current plan")
                    e["outcome"] = "partial" if e["wrote"] else "changed"
                elif e["catalog"] in satisfied and phase == "parent":
                    e["parent_ok"] = True     # already the approved parent: not written
                elif e["catalog"] in satisfied:
                    e["outcome"] = "done" if e["wrote"] else "already done"
            rows = [e for e in rows if e["catalog"] not in changed
                    and e["catalog"] not in satisfied]
            if not rows:
                return [], {}
            stop_if_output_lost()
            batch[:] = rows
            try:
                back = airtable_patch(table_id, [{"id": e[record], "fields": {field: value(e)}}
                                                 for e in rows], token)
            except RateLimited:
                batch.clear()                 # refused: definitely not applied
                if attempt == pull.RATE_LIMIT_RETRIES:
                    raise
                print_status("warning", f"Airtable rate limit - waiting "
                                        f"{pull.RATE_LIMIT_WAIT}s, then re-checking these rows")
                time.sleep(pull.RATE_LIMIT_WAIT)
                continue
            return rows, back
        return [], {}

    try:
        todo = [e for e in plan if not e["note"] and e["set_parent"]]
        for i in range(0, len(todo), PATCH_BATCH):
            sent, back = send(todo[i:i + PATCH_BATCH], "parent", IMPORT_TABLE_ID,
                              "import_rec", ids["parent"], lambda e: e["parent"])
            for e in sent:
                got = (back.get(e["import_rec"], {}).get("fields", {}).get(ids["parent"]) or "")
                e["wrote"] = True
                e["parent_ok"] = got == e["parent"]
                e["outcome"] = "partial" if e["parent_ok"] else "parent not confirmed"
            batch.clear()
            time.sleep(pull.PAGE_PAUSE)
        for e in plan:                    # a parent found already in place, nothing else to do
            if (e["set_parent"] and not e["note"] and e["parent_ok"] and not e["wrote"]
                    and not e["set_created"]):
                e["outcome"] = "already done"
        todo = [e for e in plan if not e["note"] and e["parent_ok"] and e["set_created"]]
        for i in range(0, len(todo), PATCH_BATCH):
            sent, back = send(todo[i:i + PATCH_BATCH], "created", TRACKING_TABLE_ID,
                              "tracking_rec", ids["created"], lambda e: CREATED_VALUE)
            for e in sent:
                got = select_name(back.get(e["tracking_rec"], {}).get("fields", {}).get(ids["created"]))
                e["wrote"] = True
                e["outcome"] = "done" if got == CREATED_VALUE else "partial"
            batch.clear()
            time.sleep(pull.PAGE_PAUSE)
    except UncertainWrite as err:
        for e in batch:
            e["outcome"] = "unknown"
        return str(err)
    except KeyboardInterrupt:
        for e in batch:
            e["outcome"] = "unknown"
        return INTERRUPTED
    except PullError as err:  # a definite refusal: that batch was not applied
        batch.clear()
        return str(err)
    finally:
        complete_partials(plan)
    return None


def settle_escaped(plan, inflight):
    """After a Ctrl-C escaped execute (pressed again while it was stopping
    for the first): rows it never reached keep their starting outcome,
    confirmed rows keep theirs, and only the batch in flight is unknown."""
    for e in plan:
        e.setdefault("outcome", initial_outcome(e))
    for e in inflight:
        e["outcome"] = "unknown"
    complete_partials(plan)


SAVE_INTERRUPTED = "interrupted by Ctrl-C while saving"


def receipt_path(report):
    """This run's outcomes file, named before anything is written to Airtable:
    airtable_writeback_<stamp>_<pid>.csv beside the report, or ..._2.csv and
    so on when that name is taken - by anything, a dangling link included."""
    folder = Path(report).resolve().parent
    base = f"airtable_writeback_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    path, n = folder / f"{base}.csv", 1
    while os.path.lexists(path):
        n += 1
        path = folder / f"{base}_{n}.csv"
    return path


def outcomes_text(plan, review, excluded, provenance):
    """One row per created report row: its outcome and any note."""
    f = io.StringIO(newline="")
    f.write(f"# {provenance}\n")
    w = csv.writer(f)
    w.writerow([col.CATALOG, col.PARENT_REFID, "outcome", "note"])
    for catalog in excluded:
        w.writerow([catalog, "", "excluded", "--exclude-catalog"])
    for catalog, note in review:
        w.writerow([catalog, "", "review", note])
    for e in plan:
        w.writerow([e["catalog"], e["parent"], e["outcome"], e["note"]])
    return f.getvalue()


def write_outcomes(path, plan, review, excluded, provenance, owned=None):
    """Publish the receipt as `path` without replacing anything. The content
    goes to a new temporary file created exclusively (O_EXCL: never through
    an existing name or link), which is then hard-linked as `path` - the
    link fails if anything, even a dangling link, is already there. A
    filesystem without hard links fails the save rather than risk an
    overwrite. `owned` maps each temporary file this run created to its
    (device, inode), so only those are removed and only this run's own
    publication counts; the temporary name is removed here once published."""
    owned = {} if owned is None else owned
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                 0o666)
    try:
        st = os.fstat(fd)
        owned[tmp] = (st.st_dev, st.st_ino)
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            fd = None
            f.write(outcomes_text(plan, review, excluded, provenance))
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise FileExistsError(f"{path.name} already exists - not replaced") from None
        except OSError as e:
            raise OSError(f"cannot publish {path.name} here without risking an overwrite "
                          f"({e.strerror or type(e).__name__})") from None
    finally:
        if fd is not None:
            os.close(fd)
        if tmp in owned:
            remove_owned(tmp, owned[tmp])


def remove_owned(tmp, ident):
    """Remove `tmp` only while it is still the file this run created there."""
    try:
        st = os.lstat(tmp)
        if (st.st_dev, st.st_ino) == ident and not stat.S_ISLNK(st.st_mode):
            os.unlink(tmp)
    except OSError:
        pass


def publication_problem(folder):
    """Why this run's receipt could not be published in `folder`, or None -
    checked before any write with the save's own steps (an exclusive new
    temporary file, then a no-clobber hard link) on two uniquely named probe
    files that only this check creates and removes. Nothing existing is
    touched. Passing does not guarantee the later save: the folder can still
    change or fill up."""
    base = f".airtable_writeback_probe.{os.getpid()}.{secrets.token_hex(4)}"
    src, dst = folder / f"{base}.tmp", folder / f"{base}.lnk"
    owned = {}
    try:
        fd = os.open(src, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                     0o666)
        try:
            st = os.fstat(fd)
            owned[src] = owned[dst] = (st.st_dev, st.st_ino)   # dst only if it is ours
        finally:
            os.close(fd)
        os.link(src, dst)
        return None
    except OSError as e:
        return e.strerror or type(e).__name__
    finally:
        for path, ident in owned.items():
            remove_owned(path, ident)


def published(path, owned):
    """True when `path` is the file this run created and linked there - by
    identity (device and inode), never by content: another file that happens
    to match is not this run's receipt."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return not stat.S_ISLNK(st.st_mode) and (st.st_dev, st.st_ino) in set(owned.values())


def save_receipt(path, plan, review, excluded, provenance, tries, owned):
    """Save this run's receipt: -> (saved, problem, interrupted). At most two
    attempts in all (`tries` counts them across calls): one Ctrl-C while
    saving is retried, a second is not. Nothing is sent to Airtable. Saved
    means this run's own file was published at `path` (see published), not
    that a file is there; temporary files this run created are removed."""
    problem, interrupted = None, False
    try:
        while len(tries) < 2:
            tries.append(len(tries) + 1)
            try:
                write_outcomes(path, plan, review, excluded, provenance, owned)
                return True, None, interrupted
            except OSError as e:
                problem = str(e)
                break
            except KeyboardInterrupt:
                interrupted = True
                if published(path, owned):
                    return True, None, True      # published just before the Ctrl-C
        if published(path, owned):
            return True, None, interrupted
        return False, problem or SAVE_INTERRUPTED, interrupted
    finally:
        for tmp, ident in owned.items():
            remove_owned(tmp, ident)

# ==============================
# SCREEN OUTPUT
# ==============================

def _to_null(stream):
    """Point a failed stream's descriptor at the null device, so what is
    still buffered - and the interpreter's own flush at exit - cannot fail
    again (Python's documented broken-pipe pattern). A stream without a
    usable descriptor (an in-memory one) is left as it is."""
    try:
        fd = stream.fileno()
    except (OSError, ValueError, AttributeError):   # io.UnsupportedOperation included
        return
    try:
        null = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null, fd)
        finally:
            os.close(null)
    except OSError:
        pass


class Screen:
    """Standard output for one run of main(). The first write or flush that
    fails - a closed pipe or terminal - is recorded in `lost`; that and every
    later write are dropped, so nothing more goes to the failed sink, and
    the failure never escapes into the run. Only stream errors are caught:
    an interrupt passes, and so does a ValueError from write() on a stream
    that is still open (bad text, not a failed sink). A failed flush always
    counts as lost output, so it can never skip the receipt."""

    def __init__(self, stream):
        self.stream, self.lost, self.told = stream, None, False

    def _failed(self, error, flushing=False):
        if (isinstance(error, ValueError) and not flushing
                and not getattr(self.stream, "closed", False)):
            return False
        self.lost = getattr(error, "strerror", None) or type(error).__name__
        _to_null(self.stream)
        return True

    def write(self, text):
        if self.lost is None:
            try:
                return self.stream.write(text)
            except (OSError, ValueError) as e:
                if not self._failed(e):
                    raise
        return len(text)

    def flush(self):
        if self.lost is None:
            try:
                self.stream.flush()
            except (OSError, ValueError) as e:
                self._failed(e, flushing=True)

    def isatty(self):
        try:
            return self.lost is None and self.stream.isatty()
        except (OSError, ValueError):
            return False

    def __getattr__(self, name):
        return getattr(self.stream, name)


SCREEN = None   # this run's Screen while main() runs


def output_lost():
    """Why the screen output failed during this run, or None."""
    return SCREEN.lost if SCREEN is not None else None


def tell(lines):
    """After the screen output failed: a few plain lines on stderr, best
    effort. If stderr fails too they are dropped - the outcomes file is
    already saved and the exit status still says what happened."""
    if SCREEN is not None:
        SCREEN.told = True
    try:
        for line in lines:
            sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        _to_null(sys.stderr)


def tell_receipt(out_path, saved, save_problem, during_writes, unfinished):
    """The receipt and the stop, on stderr, once the screen output failed."""
    lines = [f"The screen output failed ({output_lost()})"
             + (" during the writes - nothing more was sent to Airtable." if during_writes
                else "; the outcomes file records what was written.")]
    if saved:
        lines.append(f"Saved write-back outcomes: {out_path}")
    else:
        lines.append(f"NOT saved write-back outcomes: {out_path} ({save_problem}) - Airtable "
                     f"was written as far as it got; run the same command again to re-check it")
    if unfinished:
        lines.append(f"{unfinished} row(s) unfinished - run the same command again to re-check "
                     f"Airtable and finish them")
    tell(lines)

# ==============================
# MAIN EXECUTION
# ==============================

def summarize(plan, review):
    ready = [e for e in plan if not e["note"]]
    counts = {
        "parent + Yes": sum(1 for e in ready if e["set_parent"] and e["set_created"]),
        "Yes only (parent already right)": sum(1 for e in ready if not e["set_parent"] and e["set_created"]),
        "parent only (Yes already set)": sum(1 for e in ready if e["set_parent"] and not e["set_created"]),
        "already done": sum(1 for e in ready if not (e["set_parent"] or e["set_created"])),
    }
    return counts, review + [(e["catalog"], e["note"]) for e in plan if e["note"]]


def print_changes(plan):
    """One line per row that will change, showing both transitions as they
    actually are - a parent written into a blank cell vs one already there,
    the flag changed to Yes vs already Yes - so the change can be checked
    row by row before anything is written."""
    pending = [e for e in plan if not e["note"] and (e["set_parent"] or e["set_created"])]
    if not pending:
        return
    print(f"\n  {Colors.BOLD}Changes, row by row{Colors.RESET}  "
          f"{Colors.DIM}({PARENT_FIELD} | {CREATED_FIELD} | title){Colors.RESET}")
    for e in pending:
        parent = (f"(blank) -> {e['parent']}" if e["set_parent"]
                  else f"{e['parent']} (already set)")
        created = (f"{e.get('current_created') or '(blank)'} -> {CREATED_VALUE}"
                   if e["set_created"] else f"already {CREATED_VALUE}")
        print(f"    {e['catalog']}  parent {parent}  |  created {created}  |  "
              f"{e.get('title') or '(no title)'}")


def confirm(report, plan, excluded, review_count):
    """Show what --run is about to write and ask for an explicit yes.
    Anything else - no, blank, closed input, Ctrl-C - writes nothing; so
    does a PLAN or prompt that could not be shown (the screen output
    failed), whatever is typed."""
    pending = [e for e in plan if not e["note"] and (e["set_parent"] or e["set_created"])]
    n_parent = sum(1 for e in pending if e["set_parent"])
    n_yes = sum(1 for e in pending if e["set_created"])
    print(f"\n  {Colors.BOLD}About to write to Airtable{Colors.RESET}")
    print(f"    Report:   {report} (production import)")
    print(f"    Rows:     {len(pending)} to write, {review_count} for review, "
          f"{len(excluded)} excluded")
    print(f"    Fields:   {PARENT_FIELD} in {IMPORT_LABEL} ({n_parent} row(s))")
    print(f"              {CREATED_FIELD} = {CREATED_VALUE} in {TRACKING_LABEL} "
          f"({n_yes} row(s))")
    sys.stdout.flush()              # the PLAN must have reached the screen
    if output_lost():
        return False
    try:
        answer = input(f"\n  Type yes to write, anything else to cancel: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer.strip().lower() == "yes" and not output_lost()


def build_parser():
    """The command-line parser (module-level so tests can check it against -h)."""
    parser = styled_parser(["REPORT.json [--run] [--exclude-catalog JPC_AV_xxxxx ...] [--no-color]"],
                           get_colored_help, [ARGUMENTS, OPTIONS],
                           hide_values=True)   # an argument error never repeats what was typed
    parser.add_argument('report')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--exclude-catalog', action='append', default=[], metavar='JPC_AV_xxxxx')
    parser.add_argument('--no-color', action='store_true')
    return parser


def run_suggestion(args, recorded):
    """The command that writes what this preview showed: the same report,
    every exclusion in order, --no-color if given, and --run. Started by
    jpc-writeback: as that command. Otherwise - or when a value cannot go to
    the launcher as it is (starting with "-") - the recorded command plus
    --run. `recorded` stays the run's own record (outcome-file provenance)."""
    values = [args.report] + list(args.exclude_catalog)
    if started_by("jpc-writeback") and not any(v.startswith("-") for v in values):
        parts = ["jpc-writeback", "--report", args.report]
        for number in args.exclude_catalog:
            parts += ["--exclude-catalog", number]
        if args.no_color:
            parts.append("--no-color")
        return shlex.join(parts + ["--run"])
    return f"{recorded} --run"


def main():
    """The run, with standard output guarded (Screen) and put back after.
    A detected output failure makes the exit status 1 - after the writes
    and a saved receipt too - except where a Ctrl-C's 130 applies; stderr
    says so when it can."""
    global SCREEN
    real = sys.stdout
    screen = SCREEN = Screen(real)
    sys.stdout = screen
    code = 0
    try:
        run()
    except SystemExit as e:
        code = e.code
    finally:
        screen.flush()      # what a pipe still holds: a failure counts now, not at exit
        SCREEN = None
        if sys.stdout is screen:
            sys.stdout = real
    if screen.lost:
        if not screen.told:
            tell([f"The screen output failed ({screen.lost}) - nothing was written to Airtable."])
        if code != 130:
            code = 1
    sys.exit(code)


def run():
    parser = build_parser()
    args = parser.parse_args()
    if args.no_color:
        Colors.disable()
    command = " ".join([os.path.basename(sys.executable)] + [shlex.quote(a) for a in sys.argv])

    print_run_header(TITLE, target=f"Airtable - base {BASE_ID} ({IMPORT_LABEL}, {TRACKING_LABEL})",
                     input=os.path.abspath(args.report),
                     mode=("apply - confirmation required" if args.run
                           else "preview - nothing is written to Airtable"))

    if not pull.AIRTABLE_PAT_READ_ONLY:
        print_status("error", creds_loader.problem()
                     or "No read token - add airtable_pat_read_only to creds.py")
        sys.exit(1)
    if args.run and not AIRTABLE_PAT_WRITE:
        print_status("error", creds_loader.problem()
                     or "No write token - add airtable_pat_write to creds.py "
                        "(data.records:write on this base)")
        sys.exit(1)
    # Before anything is read: the tokens this run will use (the write token
    # only with --run - a preview never uses it).
    for token, names in ((pull.AIRTABLE_PAT_READ_ONLY, pull.READ_TOKEN),
                         (AIRTABLE_PAT_WRITE if args.run else None, WRITE_TOKEN)):
        problem = token is not None and creds_loader.token_problem(token)
        if problem:
            print_status("error", creds_loader.token_refusal(*names, problem))
            sys.exit(1)

    try:  # Ctrl-C while reading: nothing has been written yet
        candidates, review, left_alone, excluded = load_report(
            args.report, [c.strip() for c in args.exclude_catalog])
        if not candidates:
            plan, ids = [], None
        else:
            plan, ids = build_plan(pull.AIRTABLE_PAT_READ_ONLY, candidates)
    except PullError as e:
        print_status("error", str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        print_status("warning", "Cancelled while reading - nothing written")
        sys.exit(1)

    counts, to_review = summarize(plan, review)
    print_result(
        [(label, n, "ok") for label, n in counts.items()]
        + [("For review", len(to_review), "attention"),
           ("Excluded", len(excluded), "neutral")]
        + [(f"Left alone ({status} in the import)", n, "neutral")
           for status, n in sorted(left_alone.items())],
        title="PLAN")
    if excluded:
        print(f"\n  Excluded: {', '.join(excluded)}")
    if to_review:
        print()
        print_status("warning", f"{len(to_review)} row(s) for review - nothing written for them:")
        for catalog, note in to_review:
            print_status("warning", f"{catalog}: {note}", indent=1)

    pending = [e for e in plan if not e["note"] and (e["set_parent"] or e["set_created"])]
    print_changes(plan)
    if not args.run:
        if pending:
            # the same report and exclusions, plus --run
            print_next_step([run_suggestion(args, command),
                             f"{Colors.DIM}(shows this plan again and asks before writing){Colors.RESET}"])
        sys.exit(2 if to_review else 0)

    if pending and not confirm(args.report, plan, excluded, len(to_review)):
        if output_lost():
            tell([f"Cancelled: the screen output failed ({output_lost()}) before the yes - "
                  f"nothing was written to Airtable."])
        print_status("warning", "Cancelled - nothing written")
        sys.exit(1)
    if pending:
        # Before any write: can the report's folder hold the receipt the way
        # the save publishes it? A pass does not guarantee the later save.
        try:
            problem = publication_problem(Path(args.report).resolve().parent)
        except KeyboardInterrupt:
            print()
            print_status("warning", "Cancelled before writing - nothing written to Airtable")
            sys.exit(1)
        if problem:
            print_status("error", f"Stopped before writing: the report's folder cannot hold the "
                                  f"outcomes file safely ({problem}) - nothing was written to "
                                  f"Airtable")
            sys.exit(1)
    # After the yes: one boundary to the end of the run. The receipt is named
    # before anything is written; a Ctrl-C anywhere below still settles the
    # outcomes, saves this run's receipt (at most two attempts) and says
    # whether it was saved. Nothing is sent to Airtable to recover it.
    out_path = receipt_path(args.report)
    inflight, tries, owned, stage = [], [], {}, "writing"
    error = provenance = saved = save_problem = None
    after_writes, unfinished = False, 0   # after_writes: a Ctrl-C after the writes
    lost_in_writes = False                # the screen output failed before the writes ended

    def check(rows, phase):               # each batch is read again just before it is sent
        return recheck(pull.AIRTABLE_PAT_READ_ONLY, ids, rows, phase)
    try:
        try:
            error = (execute(plan, ids, AIRTABLE_PAT_WRITE, inflight, recheck=check)
                     if pending else None)
        except KeyboardInterrupt:  # pressed again while the writes were stopping
            settle_escaped(plan, inflight)
            error = INTERRUPTED
        lost_in_writes = bool(pending) and output_lost() is not None
        if not pending:
            for e in plan:
                e["outcome"] = "review" if e["note"] else "already done"
        stage = "saving"
        provenance = f"{command} | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        saved, save_problem, after_writes = save_receipt(out_path, plan, review, excluded,
                                                         provenance, tries, owned)
        stage = "showing"
        unfinished = show_result(plan, to_review, error, out_path, saved, save_problem,
                                 after_writes)
    except KeyboardInterrupt:
        print()
        if stage == "writing":  # as the writes ended: nothing saved or shown yet
            settle_escaped(plan, inflight)
            error = error or INTERRUPTED
            lost_in_writes = bool(pending) and output_lost() is not None
        else:
            after_writes = True
        if saved is None:  # finish this run's save, within its two attempts
            if provenance is None:
                provenance = f"{command} | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            saved, save_problem, _ = save_receipt(out_path, plan, review, excluded,
                                                  provenance, tries, owned)
        if stage == "showing":  # RESULT was already on its way: the receipt, at least
            print_status("warning", "Interrupted (Ctrl-C) while showing the result - "
                                    "nothing more was sent to Airtable")
            announce_receipt(out_path, saved, save_problem)
            unfinished = count_unfinished(plan)
        else:
            unfinished = show_result(plan, to_review, error, out_path, saved, save_problem,
                                     after_writes)
    print()
    sys.stdout.flush()  # a pipe holds output back: a failure must show up here, not at exit
    if output_lost():   # the receipt is final: now the stop and the receipt, on stderr
        tell_receipt(out_path, saved, save_problem, lost_in_writes, count_unfinished(plan))
    if saved is False and save_problem != SAVE_INTERRUPTED:
        sys.exit(1)  # the outcomes file could not be saved
    sys.exit(130 if after_writes else
             1 if error or not saved else (2 if unfinished or to_review else 0))


def count_unfinished(plan):
    return sum(1 for e in plan if e["outcome"] in ("partial", "parent not confirmed",
                                                   "unknown", "not started", "changed"))


def announce_receipt(out_path, saved, save_problem):
    """Whether this run's outcomes file was saved, and where."""
    if saved:
        print_saved([("write-back outcomes", out_path)])
    else:
        print_saved([], failed=[("write-back outcomes", out_path)])
        print()
        print_status("error", f"Could not save the outcomes file ({save_problem}) - Airtable "
                              f"was written as shown above; rerun the same command to re-check it")


def show_result(plan, to_review, error, out_path, saved, save_problem, after_writes):
    """RESULT, any stop, unfinished rows and the receipt. Returns the number
    of unfinished rows."""
    tally = {}
    for e in plan:
        tally[e["outcome"]] = tally.get(e["outcome"], 0) + 1
    print_result([("Done", tally.get("done", 0), "ok"),
                  ("Already done", tally.get("already done", 0), "neutral"),
                  ("Partial (parent written, Yes not yet)", tally.get("partial", 0), "attention"),
                  ("Parent not confirmed", tally.get("parent not confirmed", 0), "attention"),
                  ("Outcome unknown", tally.get("unknown", 0), "unknown"),
                  ("Not started", tally.get("not started", 0), "attention"),
                  ("Changed since the PLAN (left alone)", tally.get("changed", 0), "attention"),
                  ("For review", len(to_review), "attention")])
    changed = [e for e in plan if e["note"].startswith(CHANGED)]
    if changed:
        print()
        print_status("warning", f"{len(changed)} row(s) {CHANGED} - nothing more written "
                                f"for them:")
        for e in changed:
            print_status("warning", f"{e['catalog']}: {e['note']}", indent=1)
    if error:
        print()
        print_status("error", f"Stopped: {error}")
    if after_writes:
        print_status("warning", "Interrupted (Ctrl-C) after the writes - nothing more was "
                                "sent to Airtable")
    unfinished = count_unfinished(plan)
    if unfinished:
        print_status("warning", f"{unfinished} row(s) unfinished - rerun the same command to "
                                f"re-check Airtable and finish them")
    announce_receipt(out_path, saved, save_problem)
    return unfinished

if __name__ == "__main__":
    main()
