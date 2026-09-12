#!/usr/bin/env python3
"""Check which JPC AV items are live in MADS (the public DAMS delivery).

DAMS ingest auto-publishes to MADS, so an item's public URL is derived from
its catalog number. The viewer page returns HTTP 200 whether or not the item
exists - the real liveness test is the package descriptor behind it:

    GET https://api.jpc.si.edu/mads/view/JPC-<CATALOG_NUMBER>/info.json
    empty {}                                   -> not in MADS ("No")
    {"src": "https://api.jpc.si.edu/mads/id/JPC-<CATALOG_NUMBER>/...", ...}
                                               -> live ("Yes")
    anything else (an error object, someone else's descriptor, a non-https
    or foreign-host src)                       -> "check failed"

Standalone usage (never touches ArchivesSpace - public MADS URLs only):

    python3 check_mads.py FILE [-o OUT.csv]

FILE is a plain text list of catalog numbers (one per line) or any CSV with
a CATALOG_NUMBER column (an export CSV works as-is). Writes a CSV of
CATALOG_NUMBER, MADS URL, MADS live, Checked - where MADS live is one of
Yes / No / check failed / invalid catalog number (the last two are never
evidence of absence).

Also imported by aspace_csv_export.py for its --mads-live flag.
"""

import argparse
import csv
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import aspace_client  # noqa: F401  (friendly missing-package guard for requests)
import requests

from aspace_csv_import import Colors, print_status, print_header, RUN_COMMAND
import sheet_rules as col

MADS_URL_PREFIX = "https://api.jpc.si.edu/mads/view/JPC-"
MADS_HOST = "api.jpc.si.edu"
TIMEOUT = 10
WORKERS = 8
# Only well-formed catalog numbers are looked up: MADS answers HTTP 200 + {}
# for ANY identifier, so a typo would otherwise read as a definitive "No".
CATALOG_RE = col.CATALOG_NUMBER_RE  # the shared contract (sheet_rules)

# Reports directory: same convention as the other tools - a custom logs_dir
# gets a per-script subfolder.
try:
    from creds import logs_dir
except ImportError:
    logs_dir = ""
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/aspace_mads_reports")
OUTPUT_DIR = os.path.join(logs_dir, "mads_reports") if logs_dir else DEFAULT_OUTPUT_DIR


def mads_url(catalog_number):
    return MADS_URL_PREFIX + catalog_number


# A real descriptor path: /mads/id/JPC-<number>/<file> with plain path
# characters only - no '.', '..', '%'-encoding, or empty segments anywhere.
# A path that needs resolving (or decoding) to be understood is not
# evidence of anything; the client applies the same rule to record uris.
_DESCRIPTOR_PATH_RE = re.compile(r"/mads/id/JPC-(JPC_AV_[0-9]+)/[A-Za-z0-9_.-]+")


def descriptor_identifies(catalog_number, src):
    """True if a descriptor's stream url is a MADS url for THIS catalog
    number (https, host api.jpc.si.edu, canonical package path
    /mads/id/JPC-<number>/<file>) - a descriptor for another item, a
    non-url, or a path that only names this item after '..' or
    percent-decoding is not proof of liveness."""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(src)
    except (TypeError, ValueError):
        return False
    if parsed.scheme != "https" or parsed.netloc != MADS_HOST or parsed.params or parsed.query:
        return False
    match = _DESCRIPTOR_PATH_RE.fullmatch(parsed.path)
    if match is None or match.group(1) != catalog_number:
        return False
    # the file segment itself may carry dots (stream.m3u8) but not as a name
    filename = parsed.path.rsplit("/", 1)[-1]
    return filename not in (".", "..")


def mads_live(catalog_number, session=None):
    """One liveness check. Returns 'Yes', 'No', 'check failed', or
    'invalid catalog number'.

    A network error or unexpected response is 'check failed', never 'No' -
    a false "not in DAMS" could send someone re-ingesting a file that is
    already there. A malformed number is never even requested.
    """
    if not isinstance(catalog_number, str) or not CATALOG_RE.fullmatch(catalog_number):
        return "invalid catalog number"
    getter = session or requests
    try:
        resp = getter.get(f"{mads_url(catalog_number)}/info.json",
                          timeout=TIMEOUT, allow_redirects=False)
        if resp.status_code != 200:
            return "check failed"
        body = resp.json()
        if not isinstance(body, dict):
            return "check failed"
        if not body:
            return "No"                       # empty {} : not in MADS
        src = body.get("src")
        if isinstance(src, str) and descriptor_identifies(catalog_number, src):
            return "Yes"                      # a real streaming descriptor for THIS item
        return "check failed"                 # an error object, or someone else's descriptor
    except Exception:
        return "check failed"


def check_many(catalog_numbers, progress=True):
    """Check catalog numbers concurrently. Returns {catalog_number: status}."""
    unique = list(dict.fromkeys(n for n in catalog_numbers if n))
    results = {}
    session = requests.Session()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, (cat, status) in enumerate(
                zip(unique, pool.map(lambda c: mads_live(c, session), unique)), 1):
            results[cat] = status
            if progress and i % 50 == 0:
                print_status("info", f"Checked {i}/{len(unique)}...")
    return results


def summarize(results):
    """(live, not_live, failed) - `failed` counts both failed checks and
    invalid catalog numbers: neither is evidence of absence."""
    live = sum(1 for s in results.values() if s == "Yes")
    not_live = sum(1 for s in results.values() if s == "No")
    failed = sum(1 for s in results.values() if s in ("check failed", "invalid catalog number"))
    return live, not_live, failed


# File-safety helpers live in sheet_rules (shared by every tool); re-exported
# here so callers and tests can keep using check_mads.same_file / clobber_problem.
same_file = col.same_file
clobber_problem = col.clobber_problem


def main():
    parser = argparse.ArgumentParser(
        description="Check which catalog numbers are live in MADS (public "
                    "URLs only - ArchivesSpace is never contacted).")
    parser.add_argument("file", metavar="FILE",
                        help="Plain text list of catalog numbers, or any CSV "
                             "with a CATALOG_NUMBER column")
    parser.add_argument("-o", "--output", metavar="PATH",
                        help=f"Output CSV path (default: timestamped file in {OUTPUT_DIR})")
    args = parser.parse_args()

    from aspace_csv_export import read_catalog_list  # late import: avoids cycle
    numbers, problem = read_catalog_list(args.file)
    if numbers is None:
        print_status("error", problem)
        sys.exit(1)

    stamp = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    out_path = col.resolve_output_path(args.output, OUTPUT_DIR, f"mads_check_{stamp}.csv")
    problem = clobber_problem(args.file, out_path)
    if problem:
        print_status("error", problem)
        sys.exit(1)

    print_header("MADS Liveness Check")
    print(f"  Source: {args.file} ({len(numbers)} catalog number(s))")
    results = check_many(numbers)

    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        f.write(f"# {RUN_COMMAND} | {checked_at}\n")
        writer = csv.writer(f)
        writer.writerow([col.CATALOG, "MADS URL", "MADS live", "Checked"])
        for cat in numbers:
            writer.writerow([cat, mads_url(cat), results.get(cat, ""), checked_at])
    os.replace(tmp_path, out_path)

    live, not_live, failed = summarize(results)
    print_status("success", f"Checked {len(results)} number(s): "
                            f"{live} live, {not_live} not in MADS"
                            + (f", {failed} check failed" if failed else ""))
    if failed:
        invalid = [c for c, s in results.items() if s == "invalid catalog number"]
        if invalid:
            print_status("warning", f"{len(invalid)} catalog number(s) are not of the form "
                                    f"JPC_AV_<digits> and were not looked up: {', '.join(invalid)}")
        print_status("warning", "'check failed' means the check itself errored "
                                "(network/odd response) - NOT that the item is "
                                "absent; re-run for those")
    print_status("success", f"Report: {out_path}")
    sys.exit(2 if failed else 0)


if __name__ == "__main__":
    main()
