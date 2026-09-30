#!/usr/bin/env python3
"""
Pull one Airtable view to a CSV, the same shape as Airtable's own
"Download CSV": the view's visible columns in the view's order, its
filters and sort applied, cells as the text Airtable shows.

Read-only toward Airtable. The CSV lands in __airtable_exports__/ as
<view>_<YYYYMMDD_HHMM>.csv, ready for --fill-parents or the importer.
"""

import argparse
import csv
import io
import os
import re
import shlex
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests

import sheet_rules as col  # single source of truth for CSV header names

# ==============================
# CONFIGURATION
# ==============================

# Every import batch comes from the <<< ASpace_import >>> table; only the
# view changes. IDs, not names, so renaming the base or table in Airtable
# does not break the pull.
BASE_ID = "appLc3BwqefNYUKoA"
TABLE_ID = "tblr44TB81eWVXmY1"

API_URL = "https://api.airtable.com/v0"
EXPORT_DIR = Path(__file__).resolve().parent / "__airtable_exports__"

# Required by cellFormat=string. Dates are ISO in Airtable, so neither
# changes a date; they only shape datetime and number fields.
TIME_ZONE = "America/New_York"
USER_LOCALE = "en-us"

TIMEOUT = 30          # seconds per request
PAGE_PAUSE = 0.25     # Airtable allows 5 requests/second per base
RATE_LIMIT_WAIT = 30  # Airtable asks for 30s after a 429
RATE_LIMIT_RETRIES = 3

# Token: airtable_pat_read_only in creds.py (repo root), else
# AIRTABLE_PAT_READ_ONLY in the shell.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from creds import airtable_pat_read_only
except ImportError:
    airtable_pat_read_only = ""
AIRTABLE_PAT_READ_ONLY = airtable_pat_read_only or os.environ.get("AIRTABLE_PAT_READ_ONLY", "")

RUN_COMMAND = " ".join([os.path.basename(sys.executable)]
                       + [shlex.quote(a) for a in sys.argv])

# ==============================
# TERMINAL COLORS
# ==============================

class Colors:
    """ANSI color codes for terminal output."""
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

    @classmethod
    def disable(cls):
        """Disable colors (for non-TTY output)."""
        cls.CYAN = cls.GREEN = cls.YELLOW = cls.RED = ''
        cls.BOLD = cls.DIM = cls.RESET = ''


if not sys.stdout.isatty():
    Colors.disable()


def print_status(status: str, message: str, indent: int = 0):
    """Print a colorized status message."""
    symbols = {
        "success": f"{Colors.GREEN}[OK]{Colors.RESET}",
        "error": f"{Colors.RED}[X]{Colors.RESET}",
        "warning": f"{Colors.YELLOW}[!]{Colors.RESET}",
        "info": f"{Colors.CYAN}[>]{Colors.RESET}",
    }
    print(f"{'  ' * indent}{symbols.get(status, '   ')} {message}")


def print_header(text: str):
    """Print a header line."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{text}{Colors.RESET}")
    print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}")

# ==============================
# HELP MENU
# ==============================

def get_colored_help():
    """Generate a colored and formatted help message for the command line."""
    C = Colors
    return f"""
{C.BOLD}{C.CYAN}===============================================================================
                    Read an Airtable view (read-only)
==============================================================================={C.RESET}

{C.BOLD}DESCRIPTION{C.RESET}
    Saves one view of the <<< ASpace_import >>> table as a CSV, the same as
    Airtable's Download CSV: the view's visible columns in its order, with its
    filters and sort. Read-only toward Airtable.

    The view must be a grid view, and the name must match exactly
    (capitals and spaces count). A wrong name lists the table's views.

{C.BOLD}USAGE{C.RESET}
    {C.GREEN}${C.RESET} python3 aspace_csv_import/airtable_pull.py VIEW

{C.BOLD}ARGUMENTS{C.RESET}
    {C.CYAN}VIEW{C.RESET}                      Airtable view name (quote it if it has spaces)

{C.BOLD}OPTIONS{C.RESET}
    {C.CYAN}--no-color{C.RESET}                Disable colored output

{C.BOLD}OUTPUT{C.RESET}
    {C.CYAN}{EXPORT_DIR}/{C.RESET}
    <view>_<YYYYMMDD_HHMM>.csv - never overwrites an earlier pull

{C.BOLD}TOKEN{C.RESET}
    airtable_pat_read_only in creds.py (or AIRTABLE_PAT_READ_ONLY in the shell).
    Read-only: scopes data.records:read and schema.bases:read, this base only.

{C.BOLD}EXAMPLES{C.RESET}
    {C.GREEN}${C.RESET} python3 aspace_csv_import/airtable_pull.py OpticalDisc-ASpace
    {C.GREEN}${C.RESET} python3 aspace_csv_import/airtable_pull.py "DVD batch 2"

{C.BOLD}NEXT STEP{C.RESET}
    {C.GREEN}${C.RESET} python3 aspace_csv_import/aspace_csv_export.py --fill-parents FILE --env production   # writes FILE_ready.csv + FILE_review.csv
"""

# ==============================
# AIRTABLE API
# ==============================

class PullError(Exception):
    """A problem the operator can act on; the message says what."""


def airtable_request(url, token):
    """One Airtable call, returning the parsed JSON.

    Every failure becomes a PullError naming the likely cause. A 429 (rate
    limit) waits and retries; nothing else is retried, since the pull is
    cheap to run again.
    """
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        except requests.Timeout:
            raise PullError(f"Airtable did not respond within {TIMEOUT}s - check the network or VPN")
        except requests.ConnectionError:
            raise PullError("could not reach api.airtable.com - check the network or VPN")
        except requests.RequestException as e:
            raise PullError(f"request to Airtable failed: {e}")

        if resp.status_code == 429 and attempt < RATE_LIMIT_RETRIES:
            print_status("warning", f"Airtable rate limit - waiting {RATE_LIMIT_WAIT}s")
            time.sleep(RATE_LIMIT_WAIT)
            continue
        if resp.status_code == 401:
            raise PullError("Airtable refused the token (401) - check airtable_pat_read_only in creds.py")
        if resp.status_code in (403, 404):
            raise PullError(f"Airtable denied access (HTTP {resp.status_code}) - the token needs "
                            f"the scopes data.records:read and schema.bases:read and access "
                            f"to base {BASE_ID}; also check BASE_ID/TABLE_ID in this script")
        if resp.status_code >= 400:
            raise PullError(f"Airtable returned HTTP {resp.status_code}: {_error_text(resp)}")
        try:
            return resp.json()
        except ValueError:
            raise PullError("Airtable sent a response that is not JSON")
    raise PullError(f"Airtable rate limit - still refused after {RATE_LIMIT_RETRIES} retries")


def _error_text(resp):
    """Airtable's own error message when it sent one, else the raw text."""
    try:
        err = resp.json().get("error")
        if isinstance(err, dict):
            return err.get("message") or err.get("type") or str(err)
        return str(err or resp.text)[:200]
    except (ValueError, AttributeError):
        return str(resp.text)[:200]


def fetch_view_columns(token, view_name):
    """Resolve the view by exact name (or view ID) and return
    (view, [(field_id, field_name, field_type), ...]) in the view's column order."""
    url = f"{API_URL}/meta/bases/{BASE_ID}/tables?include[]=visibleFieldIds"
    schema = airtable_request(url, token)
    table = next((t for t in schema.get("tables", []) if t.get("id") == TABLE_ID), None)
    if table is None:
        raise PullError(f"table {TABLE_ID} is not in base {BASE_ID} - check TABLE_ID in this script")

    views = table.get("views", [])
    view = next((v for v in views if v.get("name") == view_name or v.get("id") == view_name), None)
    if view is None:
        names = "\n".join(f"      {v.get('name')}" + ("" if v.get("type") == "grid"
                                                      else f"  ({v.get('type')} - not pullable)")
                          for v in views)
        raise PullError(f"no view named '{view_name}' in {table.get('name')} "
                        f"(names must match exactly). Views:\n{names}")
    if view.get("type") != "grid":
        raise PullError(f"view '{view_name}' is a {view.get('type')} view - only grid views "
                        f"can be pulled (Airtable reports columns for grid views only)")

    visible = view.get("visibleFieldIds")
    if not visible:
        raise PullError(f"Airtable did not report the columns of view '{view_name}'")
    # The primary field is always shown in a grid view; make sure it leads.
    primary = table.get("primaryFieldId")
    if primary and primary not in visible:
        visible = [primary] + list(visible)

    fields = {f.get("id"): f for f in table.get("fields", [])}
    missing = [fid for fid in visible if fid not in fields]
    if missing:
        raise PullError(f"view lists field(s) the table schema does not: {', '.join(missing)}")
    # The hold columns travel with every pull, even when the view hides
    # them: whether an item is held must never depend on the view's layout.
    by_name = {f.get("name"): fid for fid, f in fields.items()}
    misspelled = col.hold_name_problem(list(by_name))
    if misspelled:
        raise PullError(misspelled + " - nothing written")
    for name in (col.HOLD, col.HOLD_REASON):
        fid = by_name.get(name)
        if fid and fid not in visible:
            visible = list(visible) + [fid]
    return view, [(fid, fields[fid].get("name"), fields[fid].get("type")) for fid in visible]


def fetch_records(token, view_id, field_ids):
    """Every record in the view, in view order, cells as display text.

    GET with everything in the query string - the form Airtable documents
    for timeZone/userLocale (its POST variant rejected them live). A view's
    field IDs stay far below Airtable's 16k URL limit.
    """
    params = [("view", view_id), ("cellFormat", "string"),
              ("timeZone", TIME_ZONE), ("userLocale", USER_LOCALE),
              ("returnFieldsByFieldId", "true"), ("pageSize", "100")]
    params += [("fields[]", fid) for fid in field_ids]
    base_url = f"{API_URL}/{BASE_ID}/{TABLE_ID}"
    records = []
    offset = None
    while True:
        query = params + ([("offset", offset)] if offset else [])
        page = airtable_request(f"{base_url}?{urlencode(query)}", token)
        # A page without a records list is malformed, not the last page -
        # accepting it would write the earlier pages as if they were all.
        if not isinstance(page, dict) or not isinstance(page.get("records"), list):
            raise PullError(f"Airtable sent a malformed page after {len(records)} record(s) "
                            f"- nothing written; run the pull again")
        records.extend(page["records"])
        offset = page.get("offset")
        if not offset:
            return records
        time.sleep(PAGE_PAUSE)


# Field types whose string form comes back CSV-quoted when a value holds a
# comma, quote or newline ('"Show #12, Color Stills"'), where Airtable's own
# Download CSV shows the bare text. Only types seen doing it live are listed.
CSV_QUOTED_TYPES = {"multipleLookupValues"}


def cell_text(value, field_type=None):
    """cellFormat=string sends text; anything else is flattened the way
    Airtable's CSV does (lists comma-joined, empty as blank). A lookup value
    that parses as exactly ONE CSV field is unquoted to match the Download
    CSV; anything else (several items, stray quotes) is kept as sent."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(cell_text(v) for v in value)
    text = str(value)
    if field_type in CSV_QUOTED_TYPES and text.startswith('"'):
        try:
            rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        except csv.Error:
            return text
        if len(rows) == 1 and len(rows[0]) == 1:
            return rows[0][0]
    return text

# ==============================
# OUTPUT
# ==============================

def output_path(view_name, now):
    """__airtable_exports__/<view>_<YYYYMMDD_HHMM>.csv, view name made
    filename-safe (spaces and slashes become underscores)."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", view_name).strip("_.") or "view"
    return EXPORT_DIR / f"{safe}_{now.strftime('%Y%m%d_%H%M')}.csv"


def write_csv(path, columns, records, provenance):
    """Provenance line, header, rows - written to a temp file and moved into
    place, so an interrupted pull never leaves a half file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        f.write(f"# {provenance}\n")
        writer = csv.writer(f)
        writer.writerow([name for _, name, _ in columns])
        for rec in records:
            fields = rec.get("fields", {})
            writer.writerow([cell_text(fields.get(fid), ftype) for fid, _, ftype in columns])
    os.replace(tmp_path, path)

# ==============================
# MAIN EXECUTION
# ==============================

def main():
    class CustomArgumentParser(argparse.ArgumentParser):
        def format_usage(self):
            return (f"\nusage: {self.prog} VIEW [--no-color]\n"
                    f"       {Colors.DIM}Use -h or --help for detailed information{Colors.RESET}\n")

        def format_help(self):
            return get_colored_help()

        def error(self, message):
            self.print_usage(sys.stderr)
            self.exit(2, f"\n{Colors.RED}error: {message}{Colors.RESET}\n")

    parser = CustomArgumentParser(add_help=False, usage=argparse.SUPPRESS)
    parser.add_argument('-h', '--help', action='help', default=argparse.SUPPRESS)
    parser.add_argument('view')
    parser.add_argument('--no-color', action='store_true')
    args = parser.parse_args()
    if args.no_color:
        Colors.disable()

    print_header("Read an Airtable view (read-only)")
    print(f"  Base/table: {BASE_ID} / {TABLE_ID}")
    print(f"  View: {args.view}")

    if not AIRTABLE_PAT_READ_ONLY:
        print_status("error", "No Airtable token - add airtable_pat_read_only = \"pat...\" to creds.py "
                              "(or export AIRTABLE_PAT_READ_ONLY)")
        sys.exit(1)

    now = datetime.now()
    out_path = output_path(args.view, now)
    if out_path.exists():
        print_status("error", f"{out_path.name} already exists (a pull of this view this "
                              f"minute) - wait a minute and run again")
        sys.exit(1)

    try:
        print_status("info", "Reading the view's columns...")
        view, columns = fetch_view_columns(AIRTABLE_PAT_READ_ONLY, args.view)
        print_status("info", f"Reading records ({len(columns)} columns)...")
        records = fetch_records(AIRTABLE_PAT_READ_ONLY, view["id"], [fid for fid, _, _ in columns])
    except PullError as e:
        print_status("error", str(e))
        sys.exit(1)

    if not records:
        print_status("warning", f"View '{args.view}' has no records (check its filters) - "
                                f"no file written")
        sys.exit(1)

    provenance = f"{RUN_COMMAND} | airtable view: {args.view} | {now.strftime('%Y-%m-%d %H:%M')}"
    write_csv(out_path, columns, records, provenance)
    print_status("success", f"Wrote {len(records)} row(s) to: {out_path}")

    shown = {name for _, name, _ in columns}
    missing = [c for c in col.REQUIRED_COLUMNS if c not in shown]
    if col.CATALOG not in shown:
        print_status("warning", f"The view has no {col.CATALOG} column - every import "
                                f"needs it; show it in the view and pull again")
    elif missing:
        print_status("warning", f"The view is missing import column(s): {', '.join(missing)} - "
                                f"fine for --update-only (it changes only the columns present); "
                                f"--create-records needs all of them")


if __name__ == "__main__":
    main()
