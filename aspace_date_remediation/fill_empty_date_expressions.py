#!/usr/bin/env python3
"""Remediation script 1 of 2 — fill EMPTY date expressions.

Walks every archival object in the configured AV resource (resource_id in
creds.py), finds single-date subrecords that have a full ISO begin date but a
blank/missing `expression`, and reports them (ref_id, level, title). With
--apply it writes the expression in the format chosen by --style (iso keeps
1982-08-01; dacs writes "1982 August 1"), leaving the structured begin/end
untouched.

Default is REPORT ONLY. Nothing is written without --apply.

Scope: only date_type == "single" with a complete YYYY-MM-DD begin. Year-only,
year-month, ranges, and dates that already have an expression are skipped and
counted separately (sibling script 2 handles ISO-formatted expressions).

--style chooses what gets written into the expression field:
  iso  = the ISO 8601 begin value verbatim (e.g. 1982-08-01).
  dacs = the DACS single-date form (e.g. 1982 August 1).
Both styles fill ONLY from a complete YYYY-MM-DD begin. A non-full begin
(year-only, year-month) or invalid date is flagged and skipped, never written
as a partial value. --style is required (no default) so it's a conscious choice.

Usage:
  python3 fill_empty_date_expressions.py --style iso             # report (ISO)
  python3 fill_empty_date_expressions.py --style dacs            # report (DACS)
  python3 fill_empty_date_expressions.py --style iso --apply     # write ISO expressions
  python3 fill_empty_date_expressions.py --style dacs --verbose  # report + list skipped
"""

import argparse
import sys

from aspace_session import (ASpaceSession, enumerate_archival_object_uris,
                            update_archival_object, RESOURCE_URI, WalkError)
from dacs_dates import expression_for, is_blank, STYLES


def plan_fills(ao, style):
    """Return (fills, partials, missing) for one archival object, given the style.

    Considers only single dates whose expression is blank.
    fills    = list of (date_index, begin, proposed_expression) ready to write
    partials = begin values that ARE present but yield no expression in either
               style (year-only / year-month / invalid date) — flagged, not touched
    missing  = labels of dates that have a blank expression AND a blank begin —
               an anomaly (a date subrecord with nothing to go on)
    """
    fills, partials, missing = [], [], []
    for i, date in enumerate(ao.get("dates", [])):
        if date.get("date_type") != "single":
            continue
        if not is_blank(date.get("expression")):
            continue  # already has an expression (script 2's territory)
        begin = date.get("begin")
        if is_blank(begin):
            missing.append(date.get("label") or "(unlabeled)")
            continue
        proposed = expression_for(begin, style)
        if proposed:
            fills.append((i, begin, proposed))
        else:
            partials.append(begin)
    return fills, partials, missing


def main():
    parser = argparse.ArgumentParser(description="Fill empty date expressions in the AV resource")
    parser.add_argument("--style", choices=STYLES, required=True,
                        help="Expression format to write: 'iso' copies the ISO begin date "
                             "verbatim (e.g. 1982-08-01); 'dacs' writes the DACS form "
                             "(e.g. 1982 August 1). Both fill only complete YYYY-MM-DD "
                             "begins; non-full begins are flagged, not written. "
                             "Required — no default.")
    parser.add_argument("--apply", action="store_true",
                        help="Write the expressions (default: report only)")
    parser.add_argument("--verbose", action="store_true",
                        help="Also list records skipped because the date yields no expression")
    args = parser.parse_args()

    mode = "APPLY (writing changes)" if args.apply else "REPORT ONLY (no changes)"
    print(f"Resource: {RESOURCE_URI}")
    print(f"Style:    {args.style}")
    print(f"Mode:     {mode}\n")

    session = ASpaceSession()
    if not session.login():
        sys.exit(1)

    counts = {"scanned": 0, "records_to_fill": 0, "dates_to_fill": 0,
              "filled": 0, "partial": 0, "missing_begin": 0, "failed": 0}
    try:
        try:
            uris = enumerate_archival_object_uris(session)
        except WalkError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
        print(f"Found {len(uris)} archival object(s) in the resource.\n")

        for uri in uris:
            ao = session.get(uri)
            if not ao:
                counts["failed"] += 1
                continue
            counts["scanned"] += 1

            fills, partials, missing = plan_fills(ao, args.style)
            if partials:
                counts["partial"] += len(partials)
                if args.verbose:
                    print(f"  (skip) {ao.get('ref_id')} [{ao.get('level')}] "
                          f"{ao.get('title')} — non-full begin: {', '.join(partials)}")
            if missing:
                counts["missing_begin"] += len(missing)
                if args.verbose:
                    print(f"  (anomaly) {ao.get('ref_id')} [{ao.get('level')}] "
                          f"{ao.get('title')} — blank expression AND blank begin: "
                          f"{', '.join(missing)}")
            if not fills:
                continue

            # Report this record: ref_id, level, title
            counts["records_to_fill"] += 1
            counts["dates_to_fill"] += len(fills)
            print(f"{ao.get('ref_id')}  [{ao.get('level')}]  {ao.get('title')}")
            for _, begin, proposed in fills:
                print(f"    {begin}  ->  \"{proposed}\"")

            if args.apply:
                for idx, _, proposed in fills:
                    ao["dates"][idx]["expression"] = proposed
                if update_archival_object(session, uri, ao):
                    counts["filled"] += len(fills)
                    print("    written")
                else:
                    counts["failed"] += 1
                    print("    FAILED to write")
    finally:
        session.logout()

    print("\n--- Summary ---")
    print(f"  Scanned objects:        {counts['scanned']}")
    print(f"  Records w/ empty expr:  {counts['records_to_fill']}")
    print(f"  Date subrecords to fill:{counts['dates_to_fill']}")
    if args.apply:
        print(f"  Expressions written:    {counts['filled']}")
    print(f"  Skipped (non-full date):{counts['partial']}")
    print(f"  Anomaly (no begin date):{counts['missing_begin']}")
    print(f"  Failed:                 {counts['failed']}")
    if counts["partial"] or counts["missing_begin"]:
        print("  (re-run with --verbose to list skipped/anomaly records)")
    if not args.apply and counts["records_to_fill"]:
        print("\nReport only — re-run with --apply to write these expressions.")

    sys.exit(1 if counts["failed"] else 0)


if __name__ == "__main__":
    main()
