#!/usr/bin/env python3
"""Remediation script 2 of 2 — reformat ISO-style date EXPRESSIONS.

Walks every archival object in the configured AV resource (resource_id in
creds.py), finds single-date subrecords whose `expression` was left as a bare
ISO string (e.g. "1982-08-01" — what the scripted imports produced), and
rewrites it to the DACS form "1982 August 1". The structured begin/end fields
are untouched.

Default is REPORT ONLY. Nothing is written without --apply.

Source of truth here is the expression string itself (not begin): we reformat
exactly what is displayed. Scope: date_type == "single" with an expression that
is a complete ISO date. Empty expressions are script 1's job; year-only /
year-month / range expressions are left alone. An expression that looks ISO but
is not a real date (e.g. 2020-02-30) is flagged, not converted.

Usage:
  python3 reformat_iso_date_expressions.py            # report what would change
  python3 reformat_iso_date_expressions.py --apply    # rewrite the expressions
  python3 reformat_iso_date_expressions.py --verbose   # also list anomalies
"""

import argparse
import sys

from aspace_session import (ASpaceSession, enumerate_archival_object_uris,
                            update_archival_object, RESOURCE_URI, WalkError)
from dacs_dates import iso_to_dacs, is_iso_expression


def plan_reformats(ao):
    """Return (reformats, anomalies) for one archival object.

    reformats = list of (date_index, old_expression, new_expression)
    anomalies = list of expressions that look ISO but cannot be converted
                (invalid calendar date, or sitting on a non-single date_type)
    """
    reformats, anomalies = [], []
    for i, date in enumerate(ao.get("dates", [])):
        expr = date.get("expression")
        if not is_iso_expression(expr):
            continue
        new_expr = iso_to_dacs(expr)
        if date.get("date_type") == "single" and new_expr:
            reformats.append((i, expr.strip(), new_expr))
        else:
            # ISO-looking expression we will not silently rewrite: a non-single
            # date_type, or a string that is not a real calendar date.
            anomalies.append(expr.strip())
    return reformats, anomalies


def main():
    parser = argparse.ArgumentParser(description="Reformat ISO date expressions to DACS form in the AV resource")
    parser.add_argument("--apply", action="store_true",
                        help="Write the reformatted expressions (default: report only)")
    parser.add_argument("--verbose", action="store_true",
                        help="Also list ISO-looking expressions that were NOT converted")
    args = parser.parse_args()

    mode = "APPLY (writing changes)" if args.apply else "REPORT ONLY (no changes)"
    print(f"Resource: {RESOURCE_URI}")
    print(f"Mode:     {mode}\n")

    session = ASpaceSession()
    if not session.login():
        sys.exit(1)

    counts = {"scanned": 0, "records_to_reformat": 0, "dates_to_reformat": 0,
              "reformatted": 0, "anomalies": 0, "failed": 0}
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

            reformats, anomalies = plan_reformats(ao)
            if anomalies:
                counts["anomalies"] += len(anomalies)
                if args.verbose:
                    print(f"  (skip) {ao.get('ref_id')} [{ao.get('level')}] "
                          f"{ao.get('title')} — ISO-looking, not converted: {', '.join(anomalies)}")
            if not reformats:
                continue

            # Report this record: ref_id, level, title
            counts["records_to_reformat"] += 1
            counts["dates_to_reformat"] += len(reformats)
            print(f"{ao.get('ref_id')}  [{ao.get('level')}]  {ao.get('title')}")
            for _, old_expr, new_expr in reformats:
                print(f"    \"{old_expr}\"  ->  \"{new_expr}\"")

            if args.apply:
                for idx, _, new_expr in reformats:
                    ao["dates"][idx]["expression"] = new_expr
                if update_archival_object(session, uri, ao):
                    counts["reformatted"] += len(reformats)
                    print("    written")
                else:
                    counts["failed"] += 1
                    print("    FAILED to write")
    finally:
        session.logout()

    print("\n--- Summary ---")
    print(f"  Scanned objects:           {counts['scanned']}")
    print(f"  Records w/ ISO expression: {counts['records_to_reformat']}")
    print(f"  Date subrecords to change: {counts['dates_to_reformat']}")
    if args.apply:
        print(f"  Expressions rewritten:     {counts['reformatted']}")
    print(f"  Anomalies (not converted): {counts['anomalies']}")
    print(f"  Failed:                    {counts['failed']}")
    if not args.apply and counts["records_to_reformat"]:
        print("\nReport only — re-run with --apply to rewrite these expressions.")

    sys.exit(1 if counts["failed"] else 0)


if __name__ == "__main__":
    main()
