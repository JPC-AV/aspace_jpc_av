#!/usr/bin/env python3
"""Check which JPC AV items are live in MADS (the public DAMS delivery).

DAMS ingest auto-publishes to MADS, so an item's public URL is derived from
its catalog number. The viewer page returns HTTP 200 whether or not the item
exists - the real liveness test is the package descriptor behind it:

    GET https://api.jpc.si.edu/mads/view/JPC-<CATALOG_NUMBER>/info.json
    empty {}  -> not in MADS
    populated -> live (streaming package with src/poster)

Standalone usage (never touches ArchivesSpace - public MADS URLs only):

    python3 check_mads.py FILE [-o OUT.csv]

FILE is a plain text list of catalog numbers (one per line) or any CSV with
a CATALOG_NUMBER column (an export CSV works as-is). Writes a CSV of
CATALOG_NUMBER, MADS URL, MADS live (Yes/No/check failed), Checked.

Also imported by aspace_csv_export.py for its --mads-live flag.
"""

import argparse
import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import aspace_client  # noqa: F401  (friendly missing-package guard for requests)
import requests

from aspace_csv_import import Colors, print_status, print_header, RUN_COMMAND
import csv_columns as col

MADS_URL_PREFIX = "https://api.jpc.si.edu/mads/view/JPC-"
TIMEOUT = 10
WORKERS = 8

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


def mads_live(catalog_number, session=None):
    """One liveness check. Returns 'Yes', 'No', or 'check failed'.

    A network error or unexpected response is 'check failed', never 'No' -
    a false "not in DAMS" could send someone re-ingesting a file that is
    already there.
    """
    getter = session or requests
    try:
        resp = getter.get(f"{mads_url(catalog_number)}/info.json",
                          timeout=TIMEOUT, allow_redirects=False)
        if resp.status_code != 200:
            return "check failed"
        body = resp.json()
        if not isinstance(body, dict):
            return "check failed"
        return "Yes" if body else "No"
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
    live = sum(1 for s in results.values() if s == "Yes")
    not_live = sum(1 for s in results.values() if s == "No")
    failed = sum(1 for s in results.values() if s == "check failed")
    return live, not_live, failed


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

    print_header("MADS Liveness Check")
    print(f"  Source: {args.file} ({len(numbers)} catalog number(s))")
    results = check_many(numbers)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stamp = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    out_path = args.output or os.path.join(OUTPUT_DIR, f"mads_check_{stamp}.csv")
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
        print_status("warning", "'check failed' means the check itself errored "
                                "(network/odd response) - NOT that the item is "
                                "absent; re-run for those")
    print_status("success", f"Report: {out_path}")
    sys.exit(2 if failed else 0)


if __name__ == "__main__":
    main()
