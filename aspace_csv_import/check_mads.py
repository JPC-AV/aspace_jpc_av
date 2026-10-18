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
import shlex
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import aspace_client  # noqa: F401  (friendly missing-package guard for requests)
import requests

from console import (Colors, print_status, print_run_header,  # shared display helpers
                     print_result, print_saved, render_options, help_screen,
                     styled_parser, close_progress)
from console import progress as progress_line
import sheet_rules as col

# The command line as run, for the report's provenance line (this tool takes
# no password, so nothing needs hiding).
RUN_COMMAND = " ".join([os.path.basename(sys.executable)]
                       + [shlex.quote(a) for a in sys.argv])

MADS_URL_PREFIX = "https://api.jpc.si.edu/mads/view/JPC-"
MADS_HOST = "api.jpc.si.edu"
TIMEOUT = 10
WORKERS = 8
# Only well-formed catalog numbers are looked up: MADS answers HTTP 200 + {}
# for ANY identifier, so a typo would otherwise read as a definitive "No".
CATALOG_RE = col.CATALOG_NUMBER_RE  # the shared contract (sheet_rules)

# Reports directory: same convention as the other tools - a custom logs_dir
# gets a per-script subfolder.
import creds_loader  # noqa: E402
logs_dir = creds_loader.setting("logs_dir", "")
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
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for i, (cat, status) in enumerate(
                    zip(unique, pool.map(lambda c: mads_live(c, session), unique)), 1):
                results[cat] = status
                if progress:
                    progress_line("Checked MADS", i, len(unique))
    finally:
        close_progress()
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


# An item folder in a batch: the delivered name JPC_AV_<digits>, or that name
# plus _refid_<RefID> after the rename tool (a RefID is 32 lowercase hex
# characters - the rename tool's own rule). The JPC_AV_xxxxx is group 1.
ITEM_FOLDER_RE = re.compile(r"(JPC_AV_[0-9]+)(?:_refid_[0-9a-f]{32})?")


def read_batch_folders(batch):
    """The JPC_AV_xxxxx that a batch folder's item folders stand for, and
    what in it needs a person: (numbers, review, problem).

    Only BATCH's immediate entries are looked at, in name order, and all of
    them are read before anything is checked: an entry that cannot be
    examined stops the run instead of leaving a partial selection. An item
    folder is a real directory named like ITEM_FOLDER_RE. Other entries
    named JPC_AV_... are reported, never checked: symlinks (not followed,
    dangling ones too) and names or files that are not item folders. Every
    other entry is ignored. A JPC_AV_xxxxx found in several folders is
    checked once and reported - two folders for one item is a batch-layout
    problem, unlike a repeated line in a list.

    numbers: each eligible JPC_AV_xxxxx once, in folder-name order.
    review: {"duplicates": {JPC_AV_xxxxx: [folder, ...]}, "symlinks": [...],
    "unrecognized": [...]}. problem: why BATCH could not be read."""
    folders = {}
    symlinks, unrecognized = [], []
    try:
        with os.scandir(batch) as listing:
            entries = sorted(listing, key=lambda entry: entry.name)
        for entry in entries:
            if not entry.name.startswith("JPC_AV_"):
                continue
            if entry.is_symlink():               # before is_dir: never followed
                symlinks.append(entry.name)
                continue
            match = ITEM_FOLDER_RE.fullmatch(entry.name)
            if not match or not entry.is_dir(follow_symlinks=False):
                unrecognized.append(entry.name)
                continue
            folders.setdefault(match.group(1), []).append(entry.name)
    except OSError as e:
        return None, None, f"could not read the folder {batch}: {e}"
    review = {"duplicates": {number: names for number, names in folders.items()
                             if len(names) > 1},
              "symlinks": symlinks, "unrecognized": unrecognized}
    return list(folders), review, None


def print_folder_review(review):
    """What in the batch folder needs a person - listed, never merged away."""
    if review["duplicates"]:
        print_status("warning", "The same JPC_AV_xxxxx is in more than one folder - checked "
                                "once; check the batch layout:")
        for number, names in review["duplicates"].items():
            print_status("warning", f"{number}: {', '.join(names)}", indent=1)
    if review["symlinks"]:
        print_status("warning", f"Skipped (symlink, not followed): "
                                f"{', '.join(review['symlinks'])}")
    if review["unrecognized"]:
        print_status("warning", f"Not recognized (named JPC_AV_ but not an item folder - check "
                                f"the name): {', '.join(review['unrecognized'])}")


TITLE = "Check which items are live in MADS (read-only)"
ARGUMENTS = [("FILE", "", "A plain text list of catalog numbers, or any CSV with a CATALOG_NUMBER column")]
OPTIONS = [("--directory BATCH", "", "Instead of FILE: the item folders in BATCH (see DIRECTORY MODE)"),
           ("-o, --output PATH", "", f"Report path (default: timestamped file in the reports folder)"),
           ("--no-color", "", "Disable colored output")]


def get_colored_help():
    """The -h screen, in the shared layout."""
    C = Colors
    return help_screen(TITLE, [
        ("DESCRIPTION", """    Checks each catalog number's public MADS page (the Smithsonian DAMS
    delivery) and saves the answer as a CSV. The JPC_AV_xxxxx come from a
    list FILE, or from a batch folder's item folders (--directory). Public
    URLs only - ArchivesSpace is never contacted, so no --env is needed."""),
        ("USAGE", f"""    {C.GREEN}${C.RESET} python3 aspace_csv_import/check_mads.py FILE [-o PATH]
    {C.GREEN}${C.RESET} python3 aspace_csv_import/check_mads.py --directory BATCH [-o PATH]"""),
        ("ARGUMENTS", render_options(ARGUMENTS)),
        ("OPTIONS", render_options(OPTIONS)),
        ("DIRECTORY MODE", f"""    Only the folders directly inside BATCH count, named JPC_AV_<digits> or
    JPC_AV_<digits>_refid_<RefID> (renamed). Each JPC_AV_xxxxx is checked once:
    one found in several folders is checked once, and all its folders are
    listed for review. Symlinks (not followed) and JPC_AV_ names that are not
    item folders are listed for review and not checked. The whole folder is
    read before anything is checked.
    It checks the items these folders stand for - a folder being there does
    not prove the item was delivered to or ingested by DAMS."""),
        ("EXAMPLES", f"""    {C.GREEN}${C.RESET} python3 aspace_csv_import/check_mads.py delivered.txt
    {C.GREEN}${C.RESET} python3 aspace_csv_import/check_mads.py batch.csv -o batch_mads.csv
    {C.GREEN}${C.RESET} python3 aspace_csv_import/check_mads.py --directory /Volumes/AV_DRIVE/batch"""),
        ("OUTPUT", f"""    {C.CYAN}{OUTPUT_DIR}/{C.RESET}
    mads_check_<stamp>.csv: CATALOG_NUMBER, MADS URL, MADS live, Checked
    MADS live is Yes, No, check failed, or invalid catalog number - the last
    two are never evidence that an item is missing"""),
        ("EXIT", f"""    {C.GREEN}0{C.RESET}  every number got a definite Yes or No, and nothing needs review
    {C.YELLOW}2{C.RESET}  some checks failed or numbers were invalid (re-run for those); or folders
       are listed for review (--directory); or a bad argument
    {C.RED}1{C.RESET}  the input could not be read, no eligible item folders were found, or the
       report would overwrite the input - nothing checked; or the checks ran
       (RESULT shows them) but the report could not be saved"""),
    ])


def build_parser():
    """The command-line parser (module-level so tests can check it against -h)."""
    parser = styled_parser(["FILE [-o PATH] [--no-color]",
                            "--directory BATCH [-o PATH] [--no-color]"], get_colored_help,
                           [ARGUMENTS, OPTIONS])
    parser.add_argument("file", metavar="FILE", nargs="?")
    parser.add_argument("--directory", metavar="BATCH")
    parser.add_argument("-o", "--output", metavar="PATH")
    parser.add_argument("--no-color", action="store_true")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.no_color:
        Colors.disable()
    if (args.file is None) == (args.directory is None):
        parser.error("give FILE or --directory BATCH, not both" if args.file is not None
                     else "needs FILE or --directory BATCH")
    if args.directory is not None and not args.directory.strip():
        # e.g. --directory "$BATCH" with BATCH unset: never fall back to FILE mode
        parser.error("--directory needs a folder path (it was empty)")
    # MADS needs no credentials; a broken creds.py only costs the logs_dir setting
    creds_problem = creds_loader.problem()
    if creds_problem:
        print_status("warning", f"{creds_problem} Using the default reports folder.")

    review = None
    if args.directory is not None:
        # the whole folder is read, and its problems collected, before any request
        numbers, review, problem = read_batch_folders(args.directory)
        if numbers is None:
            print_status("error", problem)
            sys.exit(1)
        if not numbers:
            print_folder_review(review)          # why nothing was eligible, first
            print_status("error", f"no JPC_AV_xxxxx item folders in {args.directory} - "
                                  f"nothing checked")
            sys.exit(1)
    else:
        numbers, problem = col.read_catalog_list(args.file)
        if numbers is None:
            print_status("error", problem)
            sys.exit(1)

    stamp = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    out_path = col.resolve_output_path(args.output, OUTPUT_DIR, f"mads_check_{stamp}.csv")
    problem = clobber_problem(args.file, out_path) if args.file is not None else None
    if problem:
        print_status("error", problem)
        sys.exit(1)

    if args.directory is not None:
        source = f"{args.directory} ({len(numbers)} JPC_AV_xxxxx from its item folders)"
        note = ("checks the items these folders stand for - a folder does not prove "
                "delivery or DAMS ingest")
    else:
        source, note = f"{args.file} ({len(numbers)} catalog number(s))", None
    print_run_header(TITLE, target="the public MADS site (read-only) - answers saved to a local CSV",
                     input=source, mode="check only - ArchivesSpace is never contacted",
                     extra=[("Note", note)])
    results = check_many(numbers)

    # Written to a staging file, then moved into place in one step, so a
    # half-written report never sits under the final name. A failure here
    # comes after the checks: their RESULT is still shown, and the report is
    # announced as NOT saved (exit 1).
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    tmp_path = out_path + ".tmp"
    save_error = None
    try:
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            f.write(f"# {RUN_COMMAND} | {checked_at}\n")
            writer = csv.writer(f)
            writer.writerow([col.CATALOG, "MADS URL", "MADS live", "Checked"])
            for cat in numbers:
                writer.writerow([cat, mads_url(cat), results.get(cat, ""), checked_at])
        os.replace(tmp_path, out_path)
    except OSError as e:
        save_error = e
        try:
            os.remove(tmp_path)        # a staging file is not a report
        except OSError:
            pass

    live, not_live, failed = summarize(results)
    invalid = [c for c, s in results.items() if s == "invalid catalog number"]
    review = review or {"duplicates": {}, "symlinks": [], "unrecognized": []}
    print_result([("Live in MADS", live, "ok", True),
                  ("Not in MADS", not_live, "neutral", True),
                  ("Check failed", failed - len(invalid), "unknown"),
                  ("Invalid catalog number", len(invalid), "bad"),
                  ("In more than one folder", len(review["duplicates"]), "attention"),
                  ("Skipped symlinks", len(review["symlinks"]), "attention"),
                  ("Not recognized", len(review["unrecognized"]), "attention")])
    if failed:
        print()
        if invalid:
            print_status("warning", f"Not of the form JPC_AV_<digits>, so not looked up: "
                                    f"{', '.join(invalid)}")
        if failed - len(invalid):
            print_status("warning", "'Check failed' means the check itself errored "
                                    "(network or an odd response) - NOT that the item is "
                                    "absent; re-run for those")
    folders_to_review = any(review.values())
    if folders_to_review:
        print()
        print_folder_review(review)
    if save_error is not None:
        print_saved([], failed=[("MADS report", out_path)])
        print_status("error", f"The checks completed (above), but the report could not be "
                              f"saved: {save_error}")
        print()
        sys.exit(1)
    print_saved([("MADS report", out_path)])
    print()
    sys.exit(2 if failed or folders_to_review else 0)


if __name__ == "__main__":
    main()
