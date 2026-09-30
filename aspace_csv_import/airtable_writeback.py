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
import json
import os
import re
import shlex
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

try:
    from creds import airtable_pat_write
except ImportError:
    airtable_pat_write = ""
AIRTABLE_PAT_WRITE = airtable_pat_write or os.environ.get("AIRTABLE_PAT_WRITE", "")

REF_ID_RE = re.compile(r"[0-9a-f]{32}")

from console import (Colors, print_status, print_run_header,  # shared display  # noqa: E402
                     print_result, print_saved, print_next_step, render_options,
                     help_screen, styled_parser, progress_count, close_progress)
PullError = pull.PullError


class UncertainWrite(PullError):
    """A write whose outcome is unknown: it may or may not have been applied."""

# ==============================
# HELP MENU
# ==============================

TITLE = "Record import results in Airtable"
ARGUMENTS = [("REPORT.json", "", "import_report_<stamp>.json from a REAL (not -n) production create run")]
OPTIONS = [
    ("--run", "", 'Show the plan, ask for "yes", then write (without it: preview only)'),
    ("--exclude-catalog NUM", "", "Leave this created row out (repeatable) - e.g. a record"),
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

    Rows the run skipped, updated or refused are left alone. A row whose
    Airtable parent already differs, that matches no row or several, or that
    is on hold in Airtable now, is listed for review and not touched."""),
        ("USAGE", f"""    {C.GREEN}${C.RESET} python3 aspace_csv_import/airtable_writeback.py REPORT.json          {C.DIM}# preview{C.RESET}
    {C.GREEN}${C.RESET} python3 aspace_csv_import/airtable_writeback.py REPORT.json --run    {C.DIM}# shows the plan, asks, writes{C.RESET}"""),
        ("ARGUMENTS", render_options(ARGUMENTS)),
        ("OPTIONS", render_options(OPTIONS)),
        ("TOKENS", """    airtable_pat_read_only   read-only - schema and table reads (creds.py)
    airtable_pat_write       data.records:write on this base - the writes only"""),
        ("EXAMPLES", f"""    {C.GREEN}${C.RESET} python3 aspace_csv_import/airtable_writeback.py import_reports/import_report_<stamp>.json --run
    {C.GREEN}${C.RESET} python3 aspace_csv_import/airtable_writeback.py REPORT.json --exclude-catalog JPC_AV_13500 --run"""),
        ("OUTPUT", """    With --run: airtable_writeback_<stamp>.csv next to the report - each row's
    outcome (done / already done / partial / unknown / not started / review).
    "unknown" means a write may or may not have landed (lost response, server
    error, Ctrl-C); run the same command again to settle it."""),
        ("EXIT", f"""    {C.GREEN}0{C.RESET}  done (or, previewing, nothing for review)
    {C.YELLOW}2{C.RESET}  rows for review or unfinished rows (rerun to finish), or a bad argument
    {C.RED}1{C.RESET}  stopped: a report or token problem, a refused or unknown write,
       cancelled at the prompt, or the outcomes file could not be saved"""),
    ])


# ==============================
# IMPORT REPORT
# ==============================

def load_report(path, exclude=()):
    """(candidates, review, counts, excluded) from a real production import report.

    candidates: [{catalog, parent, uri}] for rows the run created and read
    back. review: [(catalog, note)] for created rows that cannot be written
    back safely. counts: statuses of the rows left alone. excluded: the
    --exclude-catalog numbers, each of which must be a created row in the
    report - they are dropped before any Airtable planning.
    """
    try:
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
    except (OSError, ValueError) as e:
        raise PullError(f"could not read {path} as a JSON import report: {e}")
    summary = report.get("summary") if isinstance(report, dict) else None
    results = report.get("results") if isinstance(report, dict) else None
    if not isinstance(summary, dict) or not isinstance(results, list):
        raise PullError(f"{path} is not an import report (no summary/results) - "
                        f"use import_report_<stamp>.json, not the CSV")
    if summary.get("dry_run") is not False:
        raise PullError("this report is from a dry run (-n) - nothing was created; "
                        "use the report from the real run")
    if summary.get("environment") != "production":
        raise PullError(f"this report is from the {summary.get('environment')!r} environment "
                        f"- only production runs are written back")

    repo_id = str((aspace_client.ENVIRONMENTS.get("production") or {}).get("repo_id") or "")
    if not repo_id:
        raise PullError("creds.py has no production environment - cannot check record URIs")
    uri_re = re.compile(rf"/repositories/{re.escape(repo_id)}/archival_objects/[0-9]+")

    records = {}
    records_file = summary.get("records_file")
    if records_file:
        try:
            with open(records_file, encoding="utf-8") as f:
                records = (json.load(f) or {}).get("records") or {}
        except (OSError, ValueError, AttributeError):
            records = {}  # every created row then goes to review below

    created = [r for r in results if isinstance(r, dict) and r.get("status") == "created"]
    counts = {}
    for r in results:
        if isinstance(r, dict) and r.get("status") != "created":
            counts[r.get("status")] = counts.get(r.get("status"), 0) + 1

    created_numbers = {(r.get(col.CATALOG) or "").strip() for r in created}
    excluded = sorted(set(exclude))
    unknown = [c for c in excluded if c not in created_numbers]
    if unknown:
        raise PullError(f"--exclude-catalog {', '.join(unknown)}: not a created row in this "
                        f"report - check the number (nothing written)")
    created = [r for r in created if (r.get(col.CATALOG) or "").strip() not in excluded]

    seen = {}
    for r in created:
        seen[r.get(col.CATALOG)] = seen.get(r.get(col.CATALOG), 0) + 1

    candidates, review = [], []
    for r in created:
        catalog = (r.get(col.CATALOG) or "").strip()
        parent = (r.get(col.PARENT_REFID) or "").strip()
        uri = (r.get("uri") or "").strip()
        snap = records.get(catalog) if isinstance(records, dict) else None
        obj = snap.get("archival_object") if isinstance(snap, dict) else None
        if not col.valid_catalog_number(catalog):
            review.append((catalog or f"row {r.get('row_number')}", "no valid catalog number"))
        elif seen[r.get(col.CATALOG)] > 1:
            review.append((catalog, "appears more than once in the report"))
        elif not REF_ID_RE.fullmatch(parent):
            review.append((catalog, f"no valid parent ref ID in the report ({parent!r})"))
        elif not uri_re.fullmatch(uri):
            review.append((catalog, f"record URI {uri!r} is not a production archival object"))
        elif not (isinstance(obj, dict) and snap.get("uri") == uri
                  and obj.get("component_id") == catalog):
            review.append((catalog, "no read-back snapshot of the created record"))
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
        if matches[0].get("type") != ftype:
            raise PullError(f"{table.get('name')}.{name} is a {matches[0].get('type')} field, "
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
        raise PullError(f"{col.HOLD} is a {hold.get('type')} field, expected checkbox "
                        f"- nothing written")
    reason = import_fields.get(col.HOLD_REASON)
    return {
        "hold": hold["id"] if hold else None,
        "hold_reason": reason["id"] if reason else None,
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
                                      ids["hold_reason"]) if f],
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
            reason = (imp["fields"].get(ids["hold_reason"]) or "").strip() if ids["hold_reason"] else ""
            entry["note"] = f"on hold in Airtable{': ' + reason if reason else ''} - left alone"
            continue
        entry["import_rec"], entry["tracking_rec"] = imp["id"], trk["id"]
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

# ==============================
# AIRTABLE WRITES (write token)
# ==============================

def airtable_patch(table_id, records, token):
    """PATCH up to 10 records; returns the updated records keyed by ID.
    Setting the same values twice is harmless, so a 429 is retried."""
    url = f"{pull.API_URL}/{BASE_ID}/{table_id}"
    body = {"records": records, "returnFieldsByFieldId": True}
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(pull.RATE_LIMIT_RETRIES + 1):
        try:
            resp = requests.patch(url, headers=headers, json=body, timeout=pull.TIMEOUT)
        except requests.Timeout:
            raise UncertainWrite(f"Airtable did not answer a write within {pull.TIMEOUT}s - it "
                                 f"may or may not have been applied; rerun to re-check")
        except requests.ConnectionError:
            raise UncertainWrite("the connection to api.airtable.com failed during a write - "
                                 "check the network; rerun to re-check")
        except requests.RequestException as e:
            raise UncertainWrite(f"write to Airtable failed ({e}); rerun to re-check")
        if resp.status_code == 429 and attempt < pull.RATE_LIMIT_RETRIES:
            print_status("warning", f"Airtable rate limit - waiting {pull.RATE_LIMIT_WAIT}s")
            time.sleep(pull.RATE_LIMIT_WAIT)
            continue
        if resp.status_code in (401, 403, 404):
            raise PullError(f"Airtable refused the write (HTTP {resp.status_code}: "
                            f"{pull._error_text(resp)}) - check airtable_pat_write's scopes "
                            f"(data.records:write), its access to base {BASE_ID}, and "
                            f"field permissions before changing anything")
        if resp.status_code >= 500:
            # Airtable can time out WHILE applying a write (503), so a 5xx
            # is not proof the write was refused
            raise UncertainWrite(f"Airtable had a server error during a write (HTTP "
                                 f"{resp.status_code}: {pull._error_text(resp)}) - it may or "
                                 f"may not have been applied; rerun to re-check")
        if resp.status_code >= 400:
            raise PullError(f"Airtable refused the write (HTTP {resp.status_code}): "
                            f"{pull._error_text(resp)}")
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
    raise PullError(f"Airtable rate limit - still refused after {pull.RATE_LIMIT_RETRIES} retries")


def execute(plan, ids, token):
    """Parents first (confirmed from the write's response), then Yes for rows
    whose parent is in place. Sets each entry's outcome; stops on the first
    refusal, lost response or Ctrl-C and returns its message (None when
    everything went through). A batch whose write may or may not have
    landed is marked "unknown" - a rerun re-reads Airtable and settles it."""
    for e in plan:
        e["outcome"] = "review" if e["note"] else (
            "already done" if not (e["set_parent"] or e["set_created"]) else "not started")
        e["parent_ok"] = not e["note"] and not e["set_parent"]
    batch = []  # the batch being written; its outcome is unknown if interrupted
    try:
        todo = [e for e in plan if not e["note"] and e["set_parent"]]
        for i in range(0, len(todo), PATCH_BATCH):
            batch = todo[i:i + PATCH_BATCH]
            back = airtable_patch(IMPORT_TABLE_ID, [
                {"id": e["import_rec"], "fields": {ids["parent"]: e["parent"]}} for e in batch
            ], token)
            for e in batch:
                got = (back.get(e["import_rec"], {}).get("fields", {}).get(ids["parent"]) or "")
                e["parent_ok"] = got == e["parent"]
                e["outcome"] = "partial" if e["parent_ok"] else "parent not confirmed"
            batch = []
            time.sleep(pull.PAGE_PAUSE)
        todo = [e for e in plan if not e["note"] and e["parent_ok"] and e["set_created"]]
        for i in range(0, len(todo), PATCH_BATCH):
            batch = todo[i:i + PATCH_BATCH]
            back = airtable_patch(TRACKING_TABLE_ID, [
                {"id": e["tracking_rec"], "fields": {ids["created"]: CREATED_VALUE}} for e in batch
            ], token)
            for e in batch:
                got = select_name(back.get(e["tracking_rec"], {}).get("fields", {}).get(ids["created"]))
                e["outcome"] = "done" if got == CREATED_VALUE else "partial"
            batch = []
            time.sleep(pull.PAGE_PAUSE)
    except UncertainWrite as err:
        for e in batch:
            e["outcome"] = "unknown"
        return str(err)
    except KeyboardInterrupt:
        for e in batch:
            e["outcome"] = "unknown"
        return "interrupted (Ctrl-C) - rerun to re-check and finish"
    except PullError as err:  # a definite refusal: that batch was not applied
        return str(err)
    finally:
        for e in plan:  # parent just confirmed, and Yes was already set: complete
            if e["outcome"] == "partial" and not e["set_created"]:  # never "unknown"
                e["outcome"] = "done"
    return None


def write_outcomes(path, plan, review, excluded, provenance):
    """One row per created report row: its outcome and any note."""
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        f.write(f"# {provenance}\n")
        w = csv.writer(f)
        w.writerow([col.CATALOG, col.PARENT_REFID, "outcome", "note"])
        for catalog in excluded:
            w.writerow([catalog, "", "excluded", "--exclude-catalog"])
        for catalog, note in review:
            w.writerow([catalog, "", "review", note])
        for e in plan:
            w.writerow([e["catalog"], e["parent"], e["outcome"], e["note"]])
    os.replace(tmp_path, path)

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
    Anything else - no, blank, closed input, Ctrl-C - writes nothing."""
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
    try:
        answer = input(f"\n  Type yes to write, anything else to cancel: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer.strip().lower() == "yes"


def build_parser():
    """The command-line parser (module-level so tests can check it against -h)."""
    parser = styled_parser(["REPORT.json [--run] [--exclude-catalog NUM ...] [--no-color]"],
                           get_colored_help, [ARGUMENTS, OPTIONS])
    parser.add_argument('report')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--exclude-catalog', action='append', default=[], metavar='NUM')
    parser.add_argument('--no-color', action='store_true')
    return parser


def main():
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
        print_status("error", "No read token - add airtable_pat_read_only to creds.py")
        sys.exit(1)
    if args.run and not AIRTABLE_PAT_WRITE:
        print_status("error", "No write token - add airtable_pat_write to creds.py "
                              "(data.records:write on this base)")
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
            # the exact command plus --run, so the exclusions carry over
            print_next_step([f"{command} --run",
                             f"{Colors.DIM}(shows this plan again and asks before writing){Colors.RESET}"])
        sys.exit(2 if to_review else 0)

    if pending and not confirm(args.report, plan, excluded, len(to_review)):
        print_status("warning", "Cancelled - nothing written")
        sys.exit(1)
    error = execute(plan, ids, AIRTABLE_PAT_WRITE) if pending else None
    if not pending:
        for e in plan:
            e["outcome"] = "review" if e["note"] else "already done"
    stamp = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    out_path = Path(args.report).resolve().parent / f"airtable_writeback_{stamp}.csv"
    provenance = f"{command} | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    try:
        write_outcomes(out_path, plan, review, excluded, provenance)
        saved = True
    except OSError as e:
        # Airtable is already written: still show what happened, and how
        # to settle it (a rerun re-reads Airtable).
        saved = False
        save_problem = str(e)

    tally = {}
    for e in plan:
        tally[e["outcome"]] = tally.get(e["outcome"], 0) + 1
    print_result([("Done", tally.get("done", 0), "ok"),
                  ("Already done", tally.get("already done", 0), "neutral"),
                  ("Partial (parent written, Yes not yet)", tally.get("partial", 0), "attention"),
                  ("Parent not confirmed", tally.get("parent not confirmed", 0), "attention"),
                  ("Outcome unknown", tally.get("unknown", 0), "unknown"),
                  ("Not started", tally.get("not started", 0), "attention"),
                  ("For review", len(to_review), "attention")])
    if error:
        print()
        print_status("error", f"Stopped: {error}")
    unfinished = sum(tally.get(o, 0) for o in ("partial", "parent not confirmed", "unknown",
                                               "not started"))
    if unfinished:
        print_status("warning", f"{unfinished} row(s) unfinished - rerun the same command to "
                                f"re-check Airtable and finish them")
    if saved:
        print_saved([("write-back outcomes", out_path)])
    else:
        print_saved([], failed=[("write-back outcomes", out_path)])
        print()
        print_status("error", f"Could not save the outcomes file ({save_problem}) - Airtable "
                              f"was written as shown above; rerun the same command to re-check it")
    print()
    sys.exit(1 if error or not saved else (2 if unfinished or to_review else 0))


if __name__ == "__main__":
    main()
